"""``aidw prompt`` — task prompt generation and review (design §8.1).

Stages:

1. ``task-prompt``      — agent ``task-author`` creates ``docs/task-prompts/<phase>-<task>-prompt.md``
                          on branch ``<phase>-<task>`` and commits it.
2. ``task-review-N``    — agent ``task-reviewer`` reviews the prompt (read-only); N starts at 1.
                          Rounds 2+ receive a delta brief (``extra=``): a per-finding
                          resolution instruction, the previous review verbatim, and a
                          real ``git diff`` of the prompt since that review (L2.3).
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

import os
import shutil
import sys
from pathlib import Path
from tempfile import mkdtemp

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

#: Instruction prepended to every review round after the first (L2.3, design §8.1). The
#: three verdict tokens are literal because the reviewer must emit one of them per prior
#: finding before it may raise a new one. This lives here as toolkit runtime text rather
#: than in ``prompts/task-review.md``: that prompt is bucket (i) generic and ships as-is
#: (EXTRACTION.md §4.2), so the round-specific priming is assembly, not prompt copy.
_DELTA_BRIEF_INSTRUCTION = """\
## Delta brief — resolve the previous review before raising new findings

This is a later review round, not the first. For **each** finding in the previous review
below, state a per-finding resolution verdict of exactly `resolved`, `not resolved`, or
`newly contradicted` before you raise any new finding. Judge `resolved` only from the
current prompt and the diff that follows. New findings must be genuinely new: never
re-litigate a finding you judged `resolved`."""

#: Note used when the prompt diff cannot be produced. The brief must never present a
#: silently empty diff section: the reviewer is told the evidence is missing instead (L2.3).
_DIFF_UNAVAILABLE = (
    "The prompt diff for this round is unavailable (`git diff` could not be produced); "
    "review the prompt file itself for its current state."
)

#: Note used when the two prompt snapshots are byte-identical, so the reviewer is not left
#: wondering whether a diff section went missing.
_DIFF_EMPTY = "The prompt is unchanged since the previous review."

#: Temp-directory prefix for the two stable-named diff snapshots. The directory is
#: removed in a ``finally`` on every path; it is never the run directory (L3.3 owns
#: ``stages/<stage>.prompt.md`` snapshots).
_DIFF_TMP_PREFIX = "aidw-prompt-diff-"


def _capture_prompt(path: Path) -> str | None:
    """The prompt's current content, or ``None`` when it cannot be read (L2.3).

    The baseline is captured in memory after a review's verdict and before that round's
    fix stages run. ``_commit_reviewed_prompt`` runs only once after the loop, so there
    are no per-round commits and a bare ``git diff -- <path>`` would be cumulative; a
    capture-then-diff makes round N's diff exactly the previous fix batch's net effect.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _no_index_diff(directory: Path, name: str) -> tuple[int, str, str]:
    """Run ``git diff --no-index`` from ``directory`` under stable relative names.

    Running from the temp directory keeps both path arguments deterministic, so the
    ``diff --git a/baseline/<name> b/current/<name>`` header is identical across rounds
    and runs — the brief must never carry a random ``/tmp/...`` path. ``git diff``
    reports differences as exit code 1, so callers must accept ``{0, 1}`` as success; the
    ``code == 0`` guards in :mod:`aidw.git` (``diff_stat``/``changed_files``) would drop
    exactly the diff this brief exists for. ``GIT_DIR``/``GIT_WORK_TREE`` are removed from
    the environment so a caller's repository context cannot redirect the comparison.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
    }
    return git._git_out(
        directory,
        ["diff", "--no-index", f"baseline/{name}", f"current/{name}"],
        env=environment,
    )


def _prompt_diff(baseline: str, current: str, *, name: str) -> str | None:
    """A real unified diff between two prompt snapshots, or ``None`` (L2.3).

    Never hand-builds a summary: both snapshots are written under stable names into a
    ``tempfile`` directory (not the run directory) and compared with ``git diff --no-index``.
    Exit 0 (identical) and exit 1 (differences) are both success; anything else is a failed
    invocation, which warns on stderr and returns ``None`` so the caller degrades the
    brief instead of failing the run. The temp directory is removed in a ``finally`` on
    every path, so a multi-round run leaves no residue.
    """
    directory = Path(mkdtemp(prefix=_DIFF_TMP_PREFIX))
    try:
        for sub, text in (("baseline", baseline), ("current", current)):
            (directory / sub).mkdir()
            (directory / sub / name).write_text(text, encoding="utf-8")
        code, out, err = _no_index_diff(directory, name)
        if code not in (0, 1):
            reason = next(
                (line.strip() for line in err.splitlines() if line.strip()),
                "git diff failed",
            )[:300]
            print(
                f"warning: could not render the prompt diff for this review round "
                f"({reason}); the delta brief names it unavailable.",
                file=sys.stderr,
            )
            return None
        if code == 0:
            return _DIFF_EMPTY
        return out.rstrip("\n")
    except OSError as exc:
        print(
            f"warning: could not stage the prompt diff for this review round "
            f"({exc}); the delta brief names it unavailable.",
            file=sys.stderr,
        )
        return None
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _render_delta_brief(
    *,
    index: int,
    previous_review: str,
    baseline: str | None,
    current: str | None,
    rel: str,
) -> str:
    """Assemble round ``index``'s ``extra=`` (instruction, prior review, diff) (L2.3).

    The previous review is passed verbatim: the roadmap says "pass them the previous
    review", and the finding blocks are already the reviewer's own format. When the
    baseline or the diff cannot be produced the instruction and the review still ship
    plus an explicit unavailable note — never a silently empty diff section.
    """
    if baseline is None or current is None:
        print(
            f"warning: could not read the reviewed prompt `{rel}` to baseline review "
            f"round {index}; the delta brief names the prompt diff unavailable.",
            file=sys.stderr,
        )
        diff_text = _DIFF_UNAVAILABLE
    else:
        diff_text = _prompt_diff(baseline, current, name=Path(rel).name)
        if diff_text is None:
            diff_text = _DIFF_UNAVAILABLE

    return "\n\n".join(
        [
            _DELTA_BRIEF_INSTRUCTION,
            "### Previous review\n\n" + previous_review,
            "### Prompt diff since that review\n\n" + diff_text,
        ]
    )


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

    ``git.probe_ref`` distinguishes "the branch is absent" (rev-parse exit 1) from
    "git could not answer" (any other non-zero exit — a missing git binary, a timeout,
    a fatal plumbing error), so a transient pre-author probe failure reads as
    unanswerable, never as "absent", and cannot yield a spurious "created branch"
    warning for a branch that legitimately pre-existed (review follow-up F1, PR #16).
    """
    try:
        return git.probe_ref(repo, f"refs/heads/{name}")
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
    # L2.3: ``previous_review_text`` and ``baseline_prompt`` are set only when the round is
    # followed by fixes. ``review_text`` is reassigned on the next iteration, so the prior
    # review is carried separately; the baseline is the in-memory snapshot (no per-round
    # commits exist) taken after this verdict and before the fix stages mutate the prompt.
    previous_review_text: str | None = None
    baseline_prompt: str | None = None
    review_index = 0
    revisions = 0
    assumed_ok = False
    while True:
        review_index += 1
        name = f"task-review-{review_index}"
        # Round 1 is deliberately unprimed (``extra == ""``): the independent first
        # sample is what keeps the loop from anchoring on the previous review. Rounds 2+ get
        # the delta brief, keyed off the stage counter rather than ``revisions`` (which is
        # incremented later in the same iteration).
        delta = ""
        if review_index >= 2 and previous_review_text is not None:
            delta = _render_delta_brief(
                index=review_index,
                previous_review=previous_review_text,
                baseline=baseline_prompt,
                current=_capture_prompt(prompt_path),
                rel=rel,
            )
        rec = run_stage(
            StageSpec(
                name,
                "task-reviewer",
                aidt.prompts_dir / "task-review.md",
                [rel],
                extra=delta,
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
        if verdict == VERDICT_BLOCKED:
            # A `Blocked` verdict means a material ambiguity only a human can settle, so
            # it short-circuits before any fix stage and before any ``approve_all`` path
            # can reach the gate or :func:`_commit_reviewed_prompt` — the prompt stays
            # uncommitted and the run fails closed (design §8.1/§8.3, L2.1). This runs
            # before ``revisions += 1`` so a Blocked review never spawns a fixer, with or
            # without parsed findings.
            logger.error("task review returned Blocked; failing closed.")
            state.status = BLOCKED
            save(directory, state)
            print(
                "task review returned Blocked; a human must settle it.",
                file=sys.stderr,
            )
            print(review_text, file=sys.stderr)
            return 3
        if revisions >= MAX_REVISIONS:
            # No round left to run (MAX_REVISIONS is zero): accept what is already reviewed.
            assumed_ok = verdict != VERDICT_BLOCKED
            break

        # Capture after the verdict and its Blocked/MAX_REVISIONS exits, before the fix
        # stages run, so the next round's diff is exactly this fix batch's net effect and
        # not a cumulative diff across rounds (there is no per-round commit to diff against).
        baseline_prompt = _capture_prompt(prompt_path)
        previous_review_text = review_text
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
