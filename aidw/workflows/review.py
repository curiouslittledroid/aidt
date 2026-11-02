"""``aidw review`` — independent code review and findings publication (design §8.3).

```
preflight (PR exists, targets main, current branch is the PR head)
  → R1 code-review                 agent code-reviewer  (fresh, read-only)
  if findings:
    → R2 review-findings-to-github agent review-publisher (fresh, ungated)
  else: report Approved and stop
```

Publishing is deliberately **ungated**: the human decision happens on GitHub before
``aidw fix`` runs (design §6, E2). A ``Blocked`` verdict, an ambiguous verdict, or a
finding that cannot be parsed into a manifest stops the workflow before publication.

The run lock (``aidw.lock``, EXTRACTION.md §3.2/§3.10) is keyed on ``repo.root``, acquired
immediately before ``create_run`` and released on every exit path. The preflight's
current-branch-equals-PR-head refusal is what makes ``repo.root`` reliably the task
worktree, so its key is the same key ``implement``/``fix`` use for that tree.
"""

from __future__ import annotations

import json
import sys
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

R1 = "code-review"
R2 = "review-findings-to-github"


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

    branch = git.current_branch(repo.root)
    pr_info: dict = {}

    if not dry_run:
        if not github.gh_available():
            print("`gh` was not found on PATH.", file=sys.stderr)
            return 4
        view = github.pr_view(repo.root, pr)
        if view is None:
            print(f"PR #{pr} was not found (or `gh` failed).", file=sys.stderr)
            return 2
        pr_info = view
        base = view.get("baseRefName")
        if base != "main":
            print(f"PR #{pr} targets `{base}`, not `main`.", file=sys.stderr)
            return 4
        head = view.get("headRefName")
        if branch != head:
            print(
                f"current branch `{branch}` is not the PR head `{head}`.",
                file=sys.stderr,
            )
            return 4

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
