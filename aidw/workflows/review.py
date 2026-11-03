"""``aidw review`` — independent code review and findings publication (design §8.3).

```
preflight (PR exists, targets main, the PR head's worktree is located)
  → R1 code-review                 agent code-reviewer  (fresh, read-only)
  if findings:
    → R2 review-findings-to-github agent review-publisher (fresh, ungated)
  else: report Approved and stop
```

Publishing is deliberately **ungated**: the human decision happens on GitHub before
``aidw fix`` runs (design §6, E2). A ``Blocked`` verdict, an ambiguous verdict, or a
finding that cannot be parsed into a manifest stops the workflow before publication.

The run state records ``pr.followups_published`` on both successful exits (decision I2),
so ``aidw run prompt-to-fix`` can end the chain after an approving review that published
nothing — there is no review-follow-up parent issue for the fix loop to work on.

The run lock (``aidw.lock``, EXTRACTION.md §3.2/§3.10) is keyed on ``repo.root``, acquired
immediately before ``create_run`` and released on every exit path. The preflight's
current-branch-equals-PR-head refusal is what makes ``repo.root`` reliably the task
worktree, so its key is the same key ``implement``/``fix`` use for that tree.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from aidw import findings as findings_mod
from aidw import git, github, lock
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.log import RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.report import print_stage
from aidw.runner import StageSpec, run_stage
from aidw.state import (
    BLOCKED,
    FAILED,
    SUCCEEDED,
    create_run,
    run_dir,
    save,
)
from aidw.verdict import APPROVE, BLOCKED as VERDICT_BLOCKED, parse_verdict
from aidw.workflows.implement import worktree_add_command

R1 = "code-review"
R2 = "review-findings-to-github"

#: ``state.pr`` key recording whether this review published follow-ups (decision I2).
#: Both successful exits write it — ``True`` after R2 published a parent issue, ``False``
#: for an approving review with nothing to publish — so ``aidw run`` can tell the two
#: apart by re-reading the state it just wrote instead of asking GitHub again. The chain
#: uses it to end gracefully instead of starting a fix loop for a PR that has no
#: review-follow-up parent issue; the failed and blocked exits never write it, because a
#: non-zero exit already stops the chain.
PR_FOLLOWUPS = "followups_published"


def _read_out(record) -> str | None:
    out = record.artifacts.get("out")
    if out and Path(out).is_file():
        return Path(out).read_text(encoding="utf-8")
    return None


def _write_artifacts(
    directory: Path,
    *,
    pr: int,
    verdict: str | None,
    parsed: list[findings_mod.ParsedFinding],
    problems: list[str],
) -> None:
    artifacts = directory / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    record = {
        "pr": pr,
        "verdict": verdict,
        "findings": [f.to_manifest_entry(i) for i, f in enumerate(parsed, start=1)],
        "problems": problems,
    }
    (artifacts / "findings.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )


def run(
    *,
    pr: int,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    approve_all: bool = False,
    strict: bool = False,
    dry_run: bool = False,
    force_model: bool = False,
    stream: bool = False,
) -> int:
    runs_root = workspace.state_root / "runs"

    agents, issues = load_all(aidt.root, repo.root)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if force_model:
        # --force-model explicitly accepts the author==judge independence warning.
        warnings = [w for w in warnings if "reviewer != author" not in w.message]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    # --- preflight: gh, PR exists, targets main (design §8.3) ---------------- #
    # The PR head is authoritative, not this process's current branch (K1). Since E2.6
    # the task branch lives in its own worktree, so the control root a chain invokes us
    # from is on `main` while the PR head is checked out in a sibling directory: a
    # ``git.current_branch(repo.root) == headRefName`` test could therefore never pass
    # for ``aidw run prompt-to-fix`` right after its ``implement`` stage, which exits 4
    # on the review stage of every worktree run. ``pr_view`` runs in dry-run too, so the
    # head resolves in both modes (E2.6 req 6, mirroring ``fix``).
    pr_info: dict = {}
    branch: str | None = None
    worktree: Path | None = None

    if not dry_run and not github.gh_available():
        print("`gh` was not found on PATH.", file=sys.stderr)
        return 4

    view = github.pr_view(repo.root, pr) if github.gh_available() else None

    if not dry_run:
        if view is None:
            print(f"PR #{pr} was not found (or `gh` failed).", file=sys.stderr)
            return 2
        if view.get("baseRefName") != "main":
            print(f"PR #{pr} targets `{view.get('baseRefName')}`, not `main`.", file=sys.stderr)
            return 4

    pr_info = view or {}
    branch = pr_info.get("headRefName")

    # --- locate the PR-head worktree (K1) ------------------------------------ #
    # A missing worktree is a preflight refusal (exit 4, design §14) in a real run, with
    # the same copy-pasteable command ``implement``/``fix`` print; a dry run prints it as
    # planned output and keeps planning against ``repo.root`` (the branch is known, there
    # is just no worktree to plan in).
    if branch:
        worktree = git.worktree_for_branch(repo.root, branch)
    if branch and worktree is None:
        command = worktree_add_command(workspace, branch, repo.base_branch)
        if dry_run:
            print(f"worktree (planned): {(workspace.workspace_root / branch).resolve()}")
            print(f"branch-setup (planned): {command}")
        else:
            print(
                f"branch-setup refused: no worktree for `{branch}`. "
                f"Create it first:\n  {command}",
                file=sys.stderr,
            )
            return 4
    elif worktree is not None:
        # Re-resolve the target and agents against the worktree, and use it for every
        # stage, every ``github.*`` read of the tree, the run lock and ``create_run``
        # below, so ``state.json``'s ``repo_root`` records the worktree (mirroring
        # implement/fix). ``agent.cwd`` was resolved against the control root and would
        # silently review the wrong tree.
        resolved = TargetRepo.resolve(worktree)
        repo = replace(
            resolved,
            base_branch=repo.base_branch,
            branch_pattern=repo.branch_pattern,
        )
        agents, issues = load_all(aidt.root, repo.root)
        errors = [i for i in issues if i.level == ERROR]
        warnings = [i for i in issues if i.level == WARNING]
        if force_model:
            warnings = [w for w in warnings if "reviewer != author" not in w.message]
        if errors or (strict and warnings):
            print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
            return 2
        if dry_run:
            print(f"worktree (planned): {worktree}")
    else:
        # An unanswerable PR read (``gh`` missing, or the chain's placeholder PR 0):
        # plan against the control root and keep going (E2.6 req 6).
        reason = "`gh` not found" if not github.gh_available() else "PR head unknown"
        print(f"branch: unknown ({reason})")

    if branch:
        print(f"branch: {branch}")

    # --- one run per worktree (EXTRACTION.md §3.2/§3.10, E2.7) ---------------- #
    # The key is the *resolved* worktree path -- ``repo.root``, the same value
    # ``create_run`` records as ``repo_root`` -- never the branch: a detached-HEAD
    # worktree has no branch, and §3.2 says "keyed by worktree path". Acquired
    # immediately before ``create_run`` (the point where the key is final) and released
    # on every exit path below, refusals and failures included, so the worktree cannot
    # stay locked until process exit. It lives in the state root, never in a target
    # repo or worktree (§3.1), and it is neither ``_STATE_LOCK`` (in-process, per
    # ``state.json`` write) nor ``--parallel`` (concurrent stages inside one run).
    # A dry run reaches ``create_run`` too, so it holds and releases the same lock.
    try:
        run_lock = lock.acquire(workspace.state_root, repo.root)
    except lock.LockHeldError as exc:
        print(str(exc), file=sys.stderr)
        return 4

    try:
        state = create_run(
            runs_root,
            repo.root,
            "review",
            label=f"pr-{pr}",
            pr={
                "number": pr,
                **({"url": pr_info["url"]} if pr_info.get("url") else {}),
                **({"force_model": True} if force_model else {}),
            },
            strict=strict,
            branch=branch,
        )
        directory = run_dir(runs_root, state.run_id)
        logger = RunLogger(directory, stream=stream)
        print(f"run:    {state.run_id}")
        print(f"pr:     #{pr}" + (f" {pr_info['url']}" if pr_info.get("url") else ""))

        r1 = StageSpec(R1, "code-reviewer", aidt.prompts_dir / "code-review.md", [])
        r2 = StageSpec(
            R2,
            "review-publisher",
            aidt.prompts_dir / "review-findings-to-github.md",
            [str(pr)],
        )

        if dry_run:
            for spec in (r1, r2):
                record = run_stage(
                    spec,
                    repo_root=repo.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    dry_run=True,
                )
                suffix = (
                    " (runs only when R1 reports findings)" if spec.name == R2 else ""
                )
                print(
                    f"{record.name} [{record.status}] (planned) "
                    f"agent={record.agent} model={record.model}{suffix}"
                )
            manifest_path = directory / "artifacts" / "review-manifest.json"
            publisher = github.script_path(aidt.root, github.PUBLISH_SCRIPT)
            argv = github.build_publish_argv(publisher, pr, manifest_path, dry_run=True)
            try:
                manifest_display = manifest_path.relative_to(repo.root)
            except ValueError:
                manifest_display = manifest_path
            print(f"manifest: {manifest_display}")
            print("publisher argv: " + " ".join(argv))
            state.status = SUCCEEDED
            save(directory, state)
            print("dry-run complete; Pi not invoked, no GitHub state written")
            return 0

        rec1 = run_stage(
            r1,
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(rec1, repo_root=repo.root)
        if rec1.status != SUCCEEDED:
            print(f"stage {R1} failed: {rec1.error}", file=sys.stderr)
            state.status = FAILED
            save(directory, state)
            return 1

        text = _read_out(rec1) or ""
        if not text.strip():
            print(f"{R1} produced no final message; stopping.", file=sys.stderr)
            state.status = FAILED
            save(directory, state)
            return 1

        verdict = parse_verdict(text)
        print(f"verdict: {verdict or 'ambiguous'}")
        parsed, problems = findings_mod.parse_review_findings(text)
        _write_artifacts(
            directory,
            pr=pr,
            verdict=verdict,
            parsed=parsed,
            problems=problems,
        )

        if verdict is None:
            state.status = BLOCKED
            save(directory, state)
            print(
                "review verdict is ambiguous; failing closed without publishing.",
                file=sys.stderr,
            )
            return 3

        if verdict == VERDICT_BLOCKED:
            state.status = BLOCKED
            save(directory, state)
            print("review is Blocked; findings recorded but not published.", file=sys.stderr)
            return 3

        if not parsed:
            if verdict != APPROVE:
                state.status = BLOCKED
                save(directory, state)
                print(
                    "verdict requires changes but no findings could be extracted; "
                    "failing closed without publishing.",
                    file=sys.stderr,
                )
                return 3
            state.status = SUCCEEDED
            state.pr["verdict"] = verdict
            state.pr[PR_FOLLOWUPS] = False
            save(directory, state)
            print("review approved with no findings; nothing to publish")
            return 0

        if problems:
            state.status = BLOCKED
            save(directory, state)
            print(
                "could not build a findings manifest (failing closed without publishing):",
                file=sys.stderr,
            )
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 3

        manifest_rel = "artifacts/review-manifest.json"
        manifest_path = directory / "artifacts" / "review-manifest.json"
        manifest_path.write_text(
            json.dumps(findings_mod.to_manifest(parsed), indent=2) + "\n", encoding="utf-8"
        )
        print(f"findings: {len(parsed)} (manifest: {manifest_rel})")

        extra = findings_mod.MANIFEST_EXTRA.format(manifest_rel=manifest_rel)
        rec2 = run_stage(
            StageSpec(
                R2,
                "review-publisher",
                aidt.prompts_dir / "review-findings-to-github.md",
                [str(pr)],
                extra=extra,
            ),
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(rec2, repo_root=repo.root)
        if rec2.status != SUCCEEDED:
            print(f"stage {R2} failed: {rec2.error}", file=sys.stderr)
            state.status = FAILED
            save(directory, state)
            return 1

        published = github.parse_publish_output(_read_out(rec2) or "")
        state.pr.update(
            {
                "verdict": verdict,
                PR_FOLLOWUPS: True,
                "parent_issue": published["parent_issue"],
                "child_issues": published["child_issues"],
                "summary_comment": published["summary_comment"],
            }
        )
        state.status = SUCCEEDED
        save(directory, state)
        (directory / "artifacts" / "review.json").write_text(
            json.dumps(
                {
                    "pr": pr,
                    "verdict": verdict,
                    "parent_issue": published["parent_issue"],
                    "child_issues": published["child_issues"],
                    "summary_comment": published["summary_comment"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        parent = published["parent_issue"]
        print("review complete; follow-up issues published")
        if isinstance(parent, dict) and parent.get("url"):
            print(f"parent: {parent['url']}")
        print("human action: decide each open pending child on GitHub before `aidw fix`.")
        return 0
    finally:
        run_lock.release()
