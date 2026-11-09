"""``aidw review`` — independent code review and findings publication (design §8.3).

```
preflight (PR exists, targets main, the PR head's worktree is located)
  → … stages declared before R1  (repo-added; design §8.3 order, E4.5b)
  → R1 code-review                 agent code-reviewer  (fresh, read-only)
  if findings:
    → … stages declared between R1 and R2 (repo-added)
    → R2 review-findings-to-github agent review-publisher (fresh, ungated)
    → … stages declared after R2     (repo-added)
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

from aidw import __version__, findings as findings_mod
from aidw import git, github, lock, stage_registry
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.log import RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.report import empty_final_message_error, print_stage
from aidw.runner import (
    StageSpec,
    declared_stage_issues,
    plan_stages,
    run_stage,
)
from aidw.state import (
    BLOCKED,
    FAILED,
    SUCCEEDED,
    create_run,
    run_dir,
    save,
)
from aidw.target_config import (
    SOURCE_CONFIG,
    agent_configs_override,
    config_identity,
    resolve_workflow_config,
)
from aidw.verdict import APPROVE, BLOCKED as VERDICT_BLOCKED, parse_verdict
from aidw.workflows.implement import worktree_add_command

R1 = "code-review"
R2 = "review-findings-to-github"

#: The findings manifest the publisher stage is told to read (§8.3). It is the run-dir
#: relative path R1's findings are written to, and it is what the registry renders into
#: R2's ``extra`` — the plan builder takes it as an expansion field (E4.3), so the dry run
#: and the real run cannot disagree about it.
MANIFEST_REL = "artifacts/review-manifest.json"

#: ``state.pr`` key recording whether this review published follow-ups (decision I2).
#: Both successful exits write it — ``True`` after R2 published a parent issue, ``False``
#: for an approving review with nothing to publish — so ``aidw run`` can tell the two
#: apart by re-reading the state it just wrote instead of asking GitHub again. The chain
#: uses it to end gracefully instead of starting a fix loop for a PR that has no
#: review-follow-up parent issue; the failed and blocked exits never write it, because a
#: non-zero exit already stops the chain.
PR_FOLLOWUPS = "followups_published"


def _index_of(plan: list[StageSpec], stage_id: str) -> int:
    """The plan position of ``stage_id`` (E4.5b: by id, never by unpacking position).

    Both core stages are mandatory (D13), so a missing id is a programming error, not a
    config one; ``StopIteration`` is the loud failure.
    """
    return next(index for index, spec in enumerate(plan) if spec.id == stage_id)


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

    # Target config (E4.3, EXTRACTION.md §3.4/§3.11): the same two fail-closed refusals
    # `aidw prompt` performs (validation ERRORs and `check_compatibility`), stderr + exit
    # 2 before any run record or worktree and regardless of `--dry-run`. `validate_paths`
    # stays prompt-only: a review tree has no roadmap or build-results template to read.
    resolved_config, config_issues = resolve_workflow_config(
        repo.root, toolkit_version=__version__
    )
    if config_issues:
        print(format_issues(config_issues), file=sys.stderr)
        return 2

    # --- core vs repo-optional stages (E4.5a, D12/D13, EXTRACTION.md §3.5) ------ #
    # Only a *declared* `workflows.review.stages` list is validated: it replaces the
    # toolkit's list wholesale (§3.4), so a missing core id is a removal. Declared-ness
    # (`source == "config"`) is the test — an undeclared list is absent from the resolved
    # config and the registry defaults plan unchanged, while an explicit `stages: []`
    # must report every core stage removed. Runs immediately after the config refusal,
    # before `load_all`, any run record/worktree, and in `--dry-run`: stderr + exit 2, the
    # same contract as every other config refusal.
    stages_entry = resolved_config.get("workflows.review.stages")
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        stage_issues = stage_registry.validate_stage_list(
            "review", stages_entry.value or []
        )
        if stage_issues:
            print(format_issues(stage_issues), file=sys.stderr)
            return 2

    # E4.6: a declared `paths.agent_configs_dir` shadows the toolkit's agent configs by
    # id; unset passes `None` (toolkit defaults). Re-resolved against the PR-head
    # worktree below, the tree the review stages actually run in.
    agents, issues = load_all(
        aidt.root,
        repo.root,
        override_dir=agent_configs_override(resolved_config, repo.root),
    )
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if force_model:
        # --force-model explicitly accepts the author==judge independence warning.
        warnings = [w for w in warnings if "reviewer != author" not in w.message]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    # --- declared stage settings (E4.5b, EXTRACTION.md §3.5/§3.6) --------------- #
    # After `load_all`, because the agents dict is what a repo-added stage's `agent` is
    # checked against — the validator above runs before it. `validate_stage_list` stays
    # the first stage-list refusal; this one covers the two settings the plan needs and
    # turns them into config ERRORs (stderr + exit 2) before any run record or worktree, so
    # a missing declared prompt or an unknown repo-added agent never escapes `run()` as a
    # traceback. Control-root only: the worktree re-resolve below keeps its own `load_all`
    # refusal and, like `validate_stage_list`, is not re-run.
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        declaration_issues = declared_stage_issues(
            "review",
            stages_entry.value or [],
            toolkit_root=aidt.root,
            target_root=repo.root,
            agents=agents,
        )
        if declaration_issues:
            print(format_issues(declaration_issues), file=sys.stderr)
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
        agents, issues = load_all(
            aidt.root,
            repo.root,
            override_dir=agent_configs_override(resolved_config, repo.root),
        )
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
        # EXTRACTION.md §3.11 (E8.2): what produced this run. One helper so the
        # five workflows cannot record different values for one config.
        config_schema_version, config_hash = config_identity(resolved_config)
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
            toolkit_version=__version__,
            config_schema_version=config_schema_version,
            config_hash=config_hash,
            branch=branch,
        )
        directory = run_dir(runs_root, state.run_id)
        logger = RunLogger(directory, stream=stream)
        print(f"run:    {state.run_id}")
        print(f"pr:     #{pr}" + (f" {pr_info['url']}" if pr_info.get("url") else ""))

        # The plan comes from the registry (E4.3): `findings=True` plans both core stages
        # (the pair is "R2 only if R1 reports findings", and the dry run plans R2 as
        # well); the manifest path is the expansion field that renders R2's extra, so the
        # dry-run prompt already points at the manifest the real run writes. Since E4.5b a
        # declared list may also carry repo-added stages, so the two core stages are
        # located **by id** (never by unpacking position) and everything else runs in
        # declared order around them (§8.3's gating and stops are unchanged).
        #
        # The field is the manifest's **absolute** path: the publisher stage runs with the
        # target repo as its cwd, so a run-dir-relative value sent it looking for
        # `<repo>/artifacts/review-manifest.json`, finding nothing (E7.3's PR 110).
        manifest_path = directory / MANIFEST_REL
        plan = plan_stages(
            "review",
            config=resolved_config,
            toolkit_root=aidt.root,
            target_root=repo.root,
            pr=pr,
            manifest_path=str(manifest_path),
            findings=True,
        )
        r1_index = _index_of(plan, "R1")
        r2_index = _index_of(plan, "R2")
        r1, r2 = plan[r1_index], plan[r2_index]
        # R2's postcondition is workflow-side, not stage data (E4.3 req 5), exactly as the
        # approve stage's is: the registry knows the stage, only this workflow knows which
        # manifest to re-read. A publisher that publishes nothing must fail the stage here,
        # not be recorded as `followups_published` and break `aidw fix` one workflow later.
        r2 = replace(
            r2,
            verify=lambda: github.verify_published(
                aidt.root,
                repo.root,
                pr,
                manifest_path,
                config=resolved_config,
            ),
        )
        before_r1 = plan[:r1_index]
        between = plan[r1_index + 1 : r2_index]
        after_r2 = plan[r2_index + 1 :]

        def run_spec(spec: StageSpec) -> bool:
            """Run one planned stage; on failure mark the run failed and return ``False``.

            The repo-added stages share this, so their failure contract is the core
            stages': the stage's error on stderr, ``state.status = FAILED``, the same exit
            1. ``R1``/``R2`` keep their own handling below because their records are read.
            """
            record = run_stage(
                spec,
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=repo.root)
            if record.status != SUCCEEDED:
                print(f"stage {spec.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                save(directory, state)
                return False
            return True

        if dry_run:
            for spec in plan:
                record = run_stage(
                    spec,
                    repo_root=repo.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    dry_run=True,
                    config=resolved_config,
                )
                suffix = (
                    " (runs only when R1 reports findings)" if spec.name == R2 else ""
                )
                print(
                    f"{record.name} [{record.status}] (planned) "
                    f"agent={record.agent} model={record.model}{suffix}"
                )
            publisher = github.script_path(aidt.root, github.PUBLISH_SCRIPT)
            argv = github.build_publish_argv(publisher, pr, manifest_path, dry_run=True)
            print(f"manifest: {manifest_path}")
            print("publisher argv: " + " ".join(argv))
            state.status = SUCCEEDED
            save(directory, state)
            print("dry-run complete; Pi not invoked, no GitHub state written")
            return 0

        # Stages declared before R1 run first, before any verdict exists.
        for spec in before_r1:
            if not run_spec(spec):
                return 1

        rec1 = run_stage(
            r1,
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
            config=resolved_config,
        )
        print_stage(rec1, repo_root=repo.root)
        if rec1.status != SUCCEEDED:
            print(f"stage {R1} failed: {rec1.error}", file=sys.stderr)
            state.status = FAILED
            save(directory, state)
            return 1

        text = _read_out(rec1) or ""
        if not text.strip():
            print(f"{empty_final_message_error(rec1)}; stopping.", file=sys.stderr)
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

        manifest_path.write_text(
            json.dumps(findings_mod.to_manifest(parsed), indent=2) + "\n", encoding="utf-8"
        )
        print(f"findings: {len(parsed)} (manifest: {manifest_path})")

        # Stages declared between R1 and R2 run after the verdict/artifacts and before R2.
        for spec in between:
            if not run_spec(spec):
                return 1

        # R2's `extra` is the registry-rendered manifest pointer (E4.3): never rebuilt here.
        rec2 = run_stage(
            r2,
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
            config=resolved_config,
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

        # Stages declared after R2 run only on the findings path, after R2 published.
        for spec in after_r2:
            if not run_spec(spec):
                return 1

        parent = published["parent_issue"]
        print("review complete; follow-up issues published")
        if isinstance(parent, dict) and parent.get("url"):
            print(f"parent: {parent['url']}")
        print("human action: decide each open pending child on GitHub before `aidw fix`.")
        return 0
    finally:
        run_lock.release()
