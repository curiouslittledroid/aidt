"""``aidw prompt`` — task prompt generation and review (design §8.1).

Stages:

1. ``task-prompt``      — agent ``task-author`` creates ``docs/task-prompts/<phase>-<task>-prompt.md``
                          on branch ``<phase>-<task>`` and commits it.
2. ``task-review-N``    — agent ``task-reviewer`` reviews the prompt (read-only); N starts at 1.
3. ``task-review-fixes`` — repeated (bounded) rework when the review requests changes. One
                          stage per blocking (must-fix/should-fix) finding, plus one combined
                          stage for the non-blocking could-fix findings; a single combined stage
                          carrying the whole review when it does not parse into findings. At most
                          ``MAX_REVISIONS`` rounds run, and the last round's fixes are not
                          followed by another review: the prompt is accepted as ready.
4. optional gate ``approve-task-prompt``.

A real run requires ``main`` and a clean working tree, because the ``task-prompt`` prompt
requires it. It then refuses (exit 4) when an earlier task in the same ``docs/tasks/*.md``
phase file is unticked, unless ``--allow-incomplete-prereqs`` is given, then fetches
``origin`` and refuses (exit 4) when the base branch is behind or diverged from
``origin/<base>``; ``--no-fetch`` skips both the fetch and the comparison.
A ``--dry-run`` plans the stages without those preconditions, reports the incomplete
predecessors, and never touches the network.
When the author's first output line is ``blocked: <reason>`` the run ends ``blocked``
(exit 3) with the reason in the run log and on stderr; the leftovers the run can see — an
uncommitted change under ``docs/task-prompts/`` and a ``{phase}-{task}`` branch it created
during the run — are reported, never repaired (design §13, L1.3).
The approval gate is off by default; pass ``--require-approval`` to pause for a human decision.
"""

from __future__ import annotations

import sys
from pathlib import Path

from aidw import git
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.findings import (
    ParsedFinding,
    findings_summary,
    finding_title,
    parse_review_findings,
    partition_findings,
    render_could_fix_block,
    render_finding_block,
)
from aidw.gates import GateOutcome, decide
from aidw.log import RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.report import print_stage
from aidw.roadmap import RoadmapTask, find_task, load_tasks
from aidw.runner import StageSpec, run_stage
from aidw.state import (
    BLOCKED,
    FAILED,
    SUCCEEDED,
    GateRecord,
    create_run,
    run_dir,
    save,
    utcnow_iso,
)
from aidw.verdict import APPROVE, BLOCKED as VERDICT_BLOCKED, parse_verdict

GATE = "approve-task-prompt"

#: Remote the base-branch preflight fetches (L1.1, design §8.1). Full ``git fetch origin``
#: keeps ``refs/remotes/origin/<base>`` current; a partial refspec would not.
REMOTE = "origin"

#: Exit code for a preflight/safety refusal (design §14).
EXIT_REFUSED = 4

#: Review rounds. Each round reviews the prompt and, unless it approves, one round of fixes
#: follows (one stage per blocking finding, one combined stage for the could-fix findings).
#: After the **last** round's fixes AIDW does not review again — the prompt is accepted as
#: ready, because a reviewer that keeps requesting changes would otherwise block forever.
#: A `Blocked` verdict is the exception and still fails closed, since it means a human must
#: settle a material ambiguity.
MAX_REVISIONS = 3


def _read_out(record) -> str | None:
    out = record.artifacts.get("out")
    if out and Path(out).is_file():
        return Path(out).read_text(encoding="utf-8")
    return None


def _resolve_prompt_path(
    repo: Path, record, default_rel: str
) -> Path | None:
    """Prefer the path the agent reported; fall back to the conventional location."""
    out = _read_out(record)
    if out:
        first = out.strip().splitlines()[0].strip().strip("`").strip()
        candidate = Path(first)
        if not candidate.is_absolute():
            candidate = repo / candidate
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            pass

    fallback = repo / default_rel
    return fallback if fallback.is_file() else None


#: Directory the author owns. A blocked run reports uncommitted changes here and never
#: commits or removes them (design §13, L1.3).
_PROMPTS_DIR = "docs/task-prompts"

#: First-line marker the author uses to report it cannot author the task (L1.3).
_BLOCKED_MARKER = "blocked:"


def _parse_blocked(out: str | None) -> str | None:
    """Reason when the author's first output line is ``blocked: <reason>`` (L1.3).

    Uses the same strip-then-first-line convention as :func:`_resolve_prompt_path`, so a
    backticked or fenced marker is recognised, and is case-insensitive. Returns ``None``
    when the output is absent/empty or does not start with the marker; an empty string
    means the author reported ``blocked:`` without a reason.
    """
    if not out or not out.strip():
        return None
    lines = out.strip().splitlines()
    first = lines[0].strip().strip("`").strip()
    if not first.lower().startswith(_BLOCKED_MARKER):
        return None
    remainder = [first[len(_BLOCKED_MARKER):].strip(), *lines[1:]]
    return "\n".join(part.strip() for part in remainder if part.strip()).strip()


def _probe_branch(repo: Path, name: str) -> tuple[bool, str | None]:
    """``(answered, sha)`` for ``refs/heads/<name>`` — advisory, never raises (L1.3).

    ``git.rev_parse`` collapses a missing ref and a git failure into ``None``, so the
    caller distinguishes "the probe could not answer" from "the branch exists" by the
    first element and never warns on a probe that failed.
    """
    try:
        return True, git.rev_parse(repo, f"refs/heads/{name}")
    except Exception:  # advisory probe: it must never stop the blocked report
        return False, None


def _uncommitted_prompt_paths(repo: Path) -> list[str]:
    """Repo-relative paths under ``docs/task-prompts/`` with uncommitted changes.

    Uncommitted changes are enumerated one file at a time. ``git status --porcelain``
    collapses a wholly-untracked directory to a single ``?? docs/task-prompts/`` line, so
    untracked paths come from :func:`aidw.git.untracked_paths` instead; a blocked run must
    name every file it did not commit, not the directory it sits in.
    """
    prefix = f"{_PROMPTS_DIR}/"
    paths: list[str] = []
    for line in git.status_short(repo, paths=[_PROMPTS_DIR]).splitlines():
        if len(line) < 4 or line[:2] == "??":
            continue
        entry = line[3:].strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip('"')
        if entry not in paths:
            paths.append(entry)
    for rel in git.untracked_paths(repo):
        if rel.startswith(prefix) and rel not in paths:
            paths.append(rel)
    return paths


def _report_blocked_leftovers(
    repo: Path, *, branch: str, branch_before: tuple[bool, str | None]
) -> None:
    """Report — never repair — what a blocked run can see it left behind (design §13).

    AIDT never deletes a branch and never discards work, so a blocked run leaves the tree
    as the author left it and names it instead. The branch is only reported when the
    pre-author probe saw it absent and the post-block probe sees it present, so a branch
    that legitimately pre-existed is never blamed on the run.
    """
    for rel in _uncommitted_prompt_paths(repo):
        print(
            f"warning: blocked run left an uncommitted change under `{_PROMPTS_DIR}/`: "
            f"{rel} (the run neither committed nor removed it).",
            file=sys.stderr,
        )
    answered_before, sha_before = branch_before
    answered_after, sha_after = _probe_branch(repo, branch)
    if (
        answered_before
        and answered_after
        and sha_before is None
        and sha_after is not None
    ):
        print(
            f"warning: blocked run created branch `{branch}`; the run does not delete "
            "it. Remove it manually if it is not wanted.",
            file=sys.stderr,
        )


def _commit_reviewed_prompt(repo: Path, rel: str, phase: str, task: str) -> bool:
    """Commit the reviewed prompt when the review-fix loop changed it."""
    if not git.status_short(repo, paths=[rel]):
        return True
    return git.commit_paths(
        repo, [rel], f"docs: revise task prompt for {phase}-{task} after review"
    )


def _verify_base_branch(repo: TargetRepo, *, no_fetch: bool) -> int | None:
    """Fetch and require the base branch to be current (L1.1, design §8.1).

    Returns :data:`EXIT_REFUSED` when the base branch is provably stale or diverged, else
    ``None``. The fetch outcome is reported as a warning but never decides the verdict on
    its own: the comparison against ``origin/<base>`` (last known refs after a failed
    fetch) is what refuses, so an offline run still catches a stale base. Every message is
    operator-facing on stderr and carries no credential (design §13).
    """
    base = repo.base_branch
    remote_ref = f"{REMOTE}/{base}"

    if no_fetch:
        print(
            f"warning: --no-fetch: base branch `{base}` was not verified against "
            f"`{remote_ref}`.",
            file=sys.stderr,
        )
        return None

    fetched, reason = git.fetch(repo.root, REMOTE)
    if not fetched:
        detail = f" ({reason})" if reason else ""
        print(
            f"warning: could not fetch `{REMOTE}`{detail}; comparing `{base}` against "
            f"the last known `{remote_ref}`.",
            file=sys.stderr,
        )

    local = git.rev_parse(repo.root, base)
    remote = git.rev_parse(repo.root, remote_ref)
    if local is None or remote is None:
        print(
            f"warning: cannot verify base branch `{base}` against `{remote_ref}` "
            f"(no such remote-tracking ref); continuing.",
            file=sys.stderr,
        )
        return None

    if local == remote:
        return None

    behind = git.is_ancestor(repo.root, local, remote)
    if behind is True:
        print(
            f"refusing: base branch `{base}` is behind `{remote_ref}`.\n"
            f"  local  {base}  {local}\n"
            f"  remote {remote_ref}  {remote}\n"
            "Run `git pull --ff-only` in the base worktree, then retry.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    ahead = git.is_ancestor(repo.root, remote, local)
    if ahead is True:
        print(
            f"warning: base branch `{base}` is ahead of `{remote_ref}` "
            f"(unpushed commits); continuing.",
            file=sys.stderr,
        )
        return None

    if behind is False and ahead is False:
        print(
            f"refusing: base branch `{base}` has diverged from `{remote_ref}`.\n"
            f"  local  {base}  {local}\n"
            f"  remote {remote_ref}  {remote}\n"
            "Reconcile the base branch with its remote before authoring.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    # ``is_ancestor`` answered ``None`` (git could not decide): warn, never pass as current.
    print(
        f"warning: could not verify whether base branch `{base}` is current with "
        f"`{remote_ref}`; continuing.",
        file=sys.stderr,
    )
    return None


def _incomplete_predecessors(
    entries: list[RoadmapTask], entry: RoadmapTask
) -> list[RoadmapTask]:
    """Earlier, unticked tasks in the target's own roadmap file (L1.2, design §11).

    Roadmap ordering is the line order within ``RoadmapTask.file``; an epic-id sort is
    not the authority. ``load_tasks`` returns every phase file, so the filter is on the
    file, not the phase id — otherwise an unticked backlog in phase 00 would block every
    other phase.
    """
    return [
        candidate
        for candidate in entries
        if candidate.file == entry.file
        and candidate.line < entry.line
        and not candidate.done
    ]


def _render_predecessors(predecessors: list[RoadmapTask]) -> str:
    """One ``id — title`` line per predecessor, in roadmap order (never a bare count)."""
    return "\n".join(f"  {p.task} — {p.title}" for p in predecessors)


def _refuse_incomplete_predecessors(
    entry: RoadmapTask, predecessors: list[RoadmapTask]
) -> None:
    """Exit-4 refusal naming the target, its phase file and every predecessor."""
    print(
        f"refusing: cannot author `{entry.task}` in phase file `{entry.file}`; "
        "earlier tasks in the same file are incomplete:",
        file=sys.stderr,
    )
    print(_render_predecessors(predecessors), file=sys.stderr)
    print(
        "Tick each predecessor once its work is merged (a merged task may still be "
        "unticked, so the roadmap cannot tell the difference), or re-run with "
        "`--allow-incomplete-prereqs` to author anyway.",
        file=sys.stderr,
    )


def _warn_incomplete_predecessors(
    entry: RoadmapTask, predecessors: list[RoadmapTask]
) -> None:
    print(
        f"warning: --allow-incomplete-prereqs: authoring `{entry.task}` anyway; "
        "skipping incomplete predecessor(s):",
        file=sys.stderr,
    )
    print(_render_predecessors(predecessors), file=sys.stderr)


def run(
    *,
    phase: str,
    epic: str,
    task: str,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    label: str | None = None,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    require_approval: bool = False,
    strict: bool = False,
    dry_run: bool = False,
    no_fetch: bool = False,
    allow_incomplete_prereqs: bool = False,
    stream: bool = False,
) -> int:
    skip = set(skip_gates or [])
    deny = set(deny_gates or [])
    # ``aidt`` locates the toolkit's assets (prompts, agent configs); run state lives
    # under the per-repo state root (EXTRACTION.md §3.10), resolved once by ``_roots``
    # and threaded in as ``workspace`` so no workflow re-resolves it.
    runs_root = workspace.state_root / "runs"

    entries = load_tasks(repo.root / "docs" / "tasks")
    entry = find_task(entries, phase, epic, task)
    if entry is None:
        print(
            f"roadmap task not found: phase={phase} epic={epic} task={task}",
            file=sys.stderr,
        )
        return 2

    # L1.2 (design §8.1, §11): computed once, before the ``dry_run`` split, so the
    # dry-run note and the real-run refusal cannot disagree. ``entries`` already holds
    # every parsed phase file; the filter is on the target's own file and a strictly
    # earlier line, never on epic-id order (a later-sorting epic can sit on an earlier
    # line) and never across files (phase 00's unticked backlog must not block phase 02).
    incomplete = _incomplete_predecessors(entries, entry)

    branch = git.current_branch(repo.root)
    if dry_run:
        if branch != "main":
            print(f"[dry-run] a real run requires `main` (currently `{branch}`).")
        if not git.is_clean(repo.root):
            print("[dry-run] a real run requires a clean working tree.")
        if incomplete:
            print(
                f"[dry-run] incomplete predecessors for `{entry.task}` in "
                f"`{entry.file}`:\n{_render_predecessors(incomplete)}"
            )
        else:
            print(f"[dry-run] no incomplete predecessors in `{entry.file}`.")
        print(
            "[dry-run] a real run will fetch and verify the base branch against "
            f"`{REMOTE}/{repo.base_branch}`."
        )
    else:
        if branch != "main":
            print(
                f"`aidw prompt` must run on `main`; currently on `{branch}`.",
                file=sys.stderr,
            )
            return 4
        if not git.is_clean(repo.root):
            print("working tree is dirty; commit or stash first.", file=sys.stderr)
            return 4
        # Refuse before ``load_all``/``create_run`` so a stale base leaves no run
        # directory, no ``{phase}-{task}`` branch and no prompt file behind. A refusal
        # on roadmap ordering is deliberately checked before the network fetch: it is a
        # purely local, in-memory condition, so an unreachable ``origin`` must not be
        # spent first.
        if incomplete:
            if not allow_incomplete_prereqs:
                _refuse_incomplete_predecessors(entry, incomplete)
                return EXIT_REFUSED
            _warn_incomplete_predecessors(entry, incomplete)
        refusal = _verify_base_branch(repo, no_fetch=no_fetch)
        if refusal is not None:
            return refusal

    agents, issues = load_all(aidt.root, repo.root)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    default_rel = f"docs/task-prompts/{phase}-{task}-prompt.md"
    state = create_run(
        runs_root,
        repo.root,
        "prompt",
        label=label or f"{phase}-{task}",
        task={"phase": phase, "epic": epic, "task": task, "title": entry.title},
        strict=strict,
        branch=branch,
    )
    directory = run_dir(runs_root, state.run_id)
    logger = RunLogger(directory, stream=stream)
    logger.info(f"prompt workflow {phase}/{epic}/{task}: {entry.title}")
    print(f"run:    {state.run_id}")
    print(f"task:   {entry.title}")

    author = StageSpec(
        "task-prompt",
        "task-author",
        aidt.prompts_dir / "task-prompt.md",
        [phase, epic, task],
    )

    # L1.3: probe for the author's branch before it runs, so a blocked run can tell a
    # branch the author created from one that legitimately pre-existed (the author reuses
    # one based on ``main``). ``--dry-run`` plans no branch and does no comparison.
    branch_before: tuple[bool, str | None] | None = None
    if not dry_run:
        branch_before = _probe_branch(repo.root, f"{phase}-{task}")

    rec1 = run_stage(
        author,
        repo_root=repo.root,
        toolkit_root=aidt.root,
        runs_root=runs_root,
        state=state,
        logger=logger,
        agents=agents,
        dry_run=dry_run,
    )
    print_stage(rec1, repo_root=repo.root)

    if dry_run:
        rec2 = run_stage(
            StageSpec(
                "task-review-1",
                "task-reviewer",
                aidt.prompts_dir / "task-review.md",
                [default_rel],
            ),
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
            dry_run=True,
        )
        print(f"stage:  {rec2.name} [{rec2.status}] (planned) model={rec2.model}")
        state.status = SUCCEEDED
        save(directory, state)
        print("dry-run complete; Pi not invoked")
        return 0

    if rec1.status != SUCCEEDED:
        print(f"task-prompt stage failed: {rec1.error}", file=sys.stderr)
        return 1

    # L1.3: detect the blocked report before ``_resolve_prompt_path`` tries the first
    # line as a path and falls back to the conventional location — otherwise a
    # ``blocked:`` line would be silently ignored whenever the author also left a file.
    # The author stage stays ``succeeded`` (it exited 0 with a valid report); the *run* is
    # what is blocked, and no commit, review or fix stage follows.
    blocked_reason = _parse_blocked(_read_out(rec1))
    if blocked_reason is not None:
        reason = blocked_reason or "no reason given"
        logger.error(f"task-prompt author reported blocked: {reason}")
        if branch_before is not None:
            _report_blocked_leftovers(
                repo.root, branch=f"{phase}-{task}", branch_before=branch_before
            )
        state.status = BLOCKED
        save(directory, state)
        print(f"blocked: {reason}", file=sys.stderr)
        return 3

    prompt_path = _resolve_prompt_path(repo.root, rec1, default_rel)
    if prompt_path is None:
        print(
            f"generated task prompt not found at {default_rel}",
            file=sys.stderr,
        )
        state.status = FAILED
        save(directory, state)
        return 1
    rel = prompt_path.relative_to(repo.root).as_posix()
    print(f"prompt: {rel}")
    state.git["branch"] = f"{phase}-{task}"
    save(directory, state)

    verdict: str | None = None
    review_text = ""
    review_index = 0
    revisions = 0
    assumed_ok = False
    while True:
        review_index += 1
        name = f"task-review-{review_index}"
        rec = run_stage(
            StageSpec(
                name,
                "task-reviewer",
                aidt.prompts_dir / "task-review.md",
                [rel],
            ),
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(rec, repo_root=repo.root)
        if rec.status != SUCCEEDED:
            state.status = FAILED
            save(directory, state)
            return 1

        review_text = _read_out(rec) or ""
        if not review_text.strip():
            logger.error(f"{rec.name} produced no final message")
            print(
                f"{rec.name} produced no final message; stopping.", file=sys.stderr
            )
            state.status = FAILED
            save(directory, state)
            return 1

        verdict = parse_verdict(review_text)
        findings, problems = parse_review_findings(review_text)
        if verdict == APPROVE:
            print(f"verdict: {verdict}")
        else:
            print(f"verdict: {verdict or 'ambiguous'} — {findings_summary(findings)}")

        if verdict == APPROVE:
            break
        if revisions >= MAX_REVISIONS:
            # No round left to run (MAX_REVISIONS is zero): accept what is already reviewed.
            assumed_ok = verdict != VERDICT_BLOCKED
            break

        revisions += 1
        if not findings or problems:
            if problems:
                print(
                    f"         {len(problems)} finding block(s) did not parse cleanly "
                    f"({problems[0]}); reworking with the whole review instead"
                )
            rec_fix = run_stage(
                StageSpec(
                    f"task-review-fixes-{revisions}",
                    "task-fixer",
                    aidt.prompts_dir / "task-review-fixes.md",
                    [rel],
                    extra=f"## Review findings to address\n\n{review_text}",
                ),
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
            )
            print_stage(rec_fix, repo_root=repo.root)
            if rec_fix.status != SUCCEEDED:
                state.status = FAILED
                save(directory, state)
                return 1
        else:
            # Blocking findings are fixed one at a time so progress is visible per change;
            # the non-blocking could-fix findings share a single stage, so they cost one
            # invocation instead of one each.
            blocking, could_fix = partition_findings(findings)
            steps: list[tuple[str, list[ParsedFinding]]] = [
                ("finding", [finding]) for finding in blocking
            ]
            if could_fix:
                steps.append(("combined", could_fix))
            total = len(steps)

            for index, (kind, group) in enumerate(steps, start=1):
                prefix = f"fix {revisions}.{index}/{total}:"
                if kind == "finding":
                    finding = group[0]
                    print(f"{prefix} {finding_title(finding)} [{finding.priority}]")
                    extra = render_finding_block(finding, index=index, total=total)
                else:
                    noun = "finding" if len(group) == 1 else "findings"
                    print(f"{prefix} {len(group)} could-fix {noun} combined")
                    extra = render_could_fix_block(group)

                rec_fix = run_stage(
                    StageSpec(
                        f"task-review-fixes-{revisions}-{index}",
                        "task-fixer",
                        aidt.prompts_dir / "task-review-fixes.md",
                        [rel],
                        extra=extra,
                    ),
                    repo_root=repo.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                )
                print_stage(rec_fix, repo_root=repo.root)
                if rec_fix.status != SUCCEEDED:
                    state.status = FAILED
                    save(directory, state)
                    return 1

        if revisions >= MAX_REVISIONS:
            # The final round's fixes are done. Do not review again: the reviewer has had
            # MAX_REVISIONS chances and the prompt is accepted as ready.
            assumed_ok = verdict != VERDICT_BLOCKED
            break

    if assumed_ok:
        print(
            f"revision budget spent ({revisions} round(s)); accepting the prompt "
            "without a further review"
        )

    if verdict != APPROVE and not assumed_ok and not approve_all:
        state.status = BLOCKED
        save(directory, state)
        print(
            "task review did not approve within the revision budget; failing closed.",
            file=sys.stderr,
        )
        print(review_text, file=sys.stderr)
        return 3

    verdict_line = f"Review verdict: {verdict or 'ambiguous'}"
    if assumed_ok:
        verdict_line += (
            f" ({revisions} revision round(s) applied; no further review — accepted)"
        )
    summary = "\n".join(
        [
            f"Task: {phase} {epic} {task} — {entry.title}",
            f"Prompt: {prompt_path.relative_to(repo.root)}",
            verdict_line,
        ]
    )
    if require_approval:
        outcome = decide(
            GATE,
            summary,
            approve_all=approve_all,
            skip=skip,
            deny=deny,
            gate_default=gate_default,
        )
    else:
        # The prompt is verified by the reviewer above; the human gate is optional and
        # off by default. Record the auto-decision so state still shows what happened.
        outcome = GateOutcome(GATE, True, "optional (default)")
    state.record_gate(
        GateRecord(
            name=GATE,
            decision=outcome.decision,
            mechanism=outcome.mechanism,
            at=utcnow_iso(),
            detail=f"verdict={verdict}; revisions={revisions}; assumed_ok={assumed_ok}",
        )
    )
    if not outcome.approved:
        state.status = BLOCKED
        save(directory, state)
        print(f"gate {GATE} denied ({outcome.mechanism}); stopping.", file=sys.stderr)
        return 3

    # The initial task-prompt stage commits the prompt, but the review-fix loop runs
    # afterwards. Commit the reviewed prompt so the branch is clean when the
    # implementation workflow starts. Only the owned prompt path is committed.
    if _commit_reviewed_prompt(repo.root, rel, phase, task):
        logger.info(f"reviewed prompt committed or unchanged: {rel}")
    else:
        logger.error(f"failed to commit reviewed prompt {rel}")
        print(
            f"warning: could not commit the reviewed prompt ({rel}); "
            "the branch is dirty",
            file=sys.stderr,
        )

    state.status = SUCCEEDED
    save(directory, state)
    print("prompt workflow complete")
    print(f"branch: {phase}-{task}")
    print(f"prompt: {rel}")
    return 0
