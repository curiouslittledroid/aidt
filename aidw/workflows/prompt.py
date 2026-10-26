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
requires it. A ``--dry-run`` plans the stages without those preconditions. The approval gate
is off by default; pass ``--require-approval`` to pause for a human decision.
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
from aidw.paths import TargetRepo, WorkspacePaths
from aidw.report import print_stage
from aidw.roadmap import find_task, load_tasks
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


def _commit_reviewed_prompt(repo: Path, rel: str, phase: str, task: str) -> bool:
    """Commit the reviewed prompt when the review-fix loop changed it."""
    if not git.status_short(repo, paths=[rel]):
        return True
    return git.commit_paths(
        repo, [rel], f"docs: revise task prompt for {phase}-{task} after review"
    )


def run(
    *,
    phase: str,
    epic: str,
    task: str,
    repo: Path,
    aidt: Path,
    runs_root: Path | None = None,
    label: str | None = None,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    require_approval: bool = False,
    strict: bool = False,
    dry_run: bool = False,
    stream: bool = False,
) -> int:
    skip = set(skip_gates or [])
    deny = set(deny_gates or [])
    # ``aidt`` locates the toolkit's assets (prompts, agent configs); run state lives
    # under the per-repo state root (EXTRACTION.md §3.10). Tests may inject an isolated
    # ``runs_root``; otherwise it is resolved once from the target repository.
    if runs_root is None:
        runs_root = (
            WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root / "runs"
        )

    entries = load_tasks(repo / "docs" / "tasks")
    entry = find_task(entries, phase, epic, task)
    if entry is None:
        print(
            f"roadmap task not found: phase={phase} epic={epic} task={task}",
            file=sys.stderr,
        )
        return 2

    branch = git.current_branch(repo)
    if dry_run:
        if branch != "main":
            print(f"[dry-run] a real run requires `main` (currently `{branch}`).")
        if not git.is_clean(repo):
            print("[dry-run] a real run requires a clean working tree.")
    else:
        if branch != "main":
            print(
                f"`aidw prompt` must run on `main`; currently on `{branch}`.",
                file=sys.stderr,
            )
            return 4
        if not git.is_clean(repo):
            print("working tree is dirty; commit or stash first.", file=sys.stderr)
            return 4

    agents, issues = load_all(aidt, repo)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    default_rel = f"docs/task-prompts/{phase}-{task}-prompt.md"
    state = create_run(
        runs_root,
        repo,
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
        aidt / "prompts" / "task-prompt.md",
        [phase, epic, task],
    )

    rec1 = run_stage(
        author,
        repo_root=repo,
        toolkit_root=aidt,
        runs_root=runs_root,
        state=state,
        logger=logger,
        agents=agents,
        dry_run=dry_run,
    )
    print_stage(rec1, repo_root=repo)

    if dry_run:
        rec2 = run_stage(
            StageSpec(
                "task-review-1",
                "task-reviewer",
                aidt / "prompts" / "task-review.md",
                [default_rel],
            ),
            repo_root=repo,
            toolkit_root=aidt,
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

    prompt_path = _resolve_prompt_path(repo, rec1, default_rel)
    if prompt_path is None:
        print(
            f"generated task prompt not found at {default_rel}",
            file=sys.stderr,
        )
        state.status = FAILED
        save(directory, state)
        return 1
    rel = prompt_path.relative_to(repo).as_posix()
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
                aidt / "prompts" / "task-review.md",
                [rel],
            ),
            repo_root=repo,
            toolkit_root=aidt,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(rec, repo_root=repo)
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
                    aidt / "prompts" / "task-review-fixes.md",
                    [rel],
                    extra=f"## Review findings to address\n\n{review_text}",
                ),
                repo_root=repo,
                toolkit_root=aidt,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
            )
            print_stage(rec_fix, repo_root=repo)
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
                        aidt / "prompts" / "task-review-fixes.md",
                        [rel],
                        extra=extra,
                    ),
                    repo_root=repo,
                    toolkit_root=aidt,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                )
                print_stage(rec_fix, repo_root=repo)
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
            f"Prompt: {prompt_path.relative_to(repo)}",
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
    if _commit_reviewed_prompt(repo, rel, phase, task):
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
