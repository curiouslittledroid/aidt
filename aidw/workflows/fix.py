"""``aidw fix`` — fix approved review follow-ups (design §8.4).

```
preflight (PR exists, targets main, the PR head's worktree is located)
  → list open children; show GitHub state
  ◇  approve-followups              runs /approve-review-followups (agent review-approver)
  ⟳  one approved child at a time:
       → F1 fix-next-review-followup  (agent fixer, fresh)
       → F2 test                      (agent tester, fresh)
       → F3 code-review               (agent code-reviewer, fresh)
       if F3 has findings:
         → F4 review-findings-to-github (ungated)  then ◇ approve-followups
       else:
         ◇ approve-fix-pr
     repeat until no approved child remains
```

Selection is always re-derived from ``review_followup.py select`` (never by counting), so
the loop is driven by real GitHub state. ``--max-iterations`` bounds the number of fixes.

All GitHub writes are performed by AIDT's bundled prompts/scripts (the fixer and approver
agents). AIDT only reads: ``gh pr view`` and ``review_followup.py select``.

The run lock (``aidw.lock``, EXTRACTION.md §3.2/§3.10) is keyed on the **re-resolved
PR-head worktree**, acquired immediately before ``create_run`` and released on every exit
path; a live peer in that worktree is refused (exit 4) before any run state is written.
``_latest_fix_run`` stays branch-keyed and is *not* the lock: it is the `--resume` path
for a crashed run, which ``flock`` has already released.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from aidw import __version__, findings as findings_mod
from aidw import git, github, lock, stage_registry
from aidw.config import ERROR, WARNING, Issue, format_issues, load_all
from aidw.gates import decide
from aidw.log import RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.report import print_stage
from aidw.runner import StageSpec, plan_stages, run_stage
from aidw.state import (
    BLOCKED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    GateRecord,
    RunState,
    create_run,
    list_runs,
    run_dir,
    save,
    utcnow_iso,
)
from aidw.target_config import SOURCE_CONFIG, ResolvedConfig, resolve_workflow_config
from aidw.verdict import APPROVE, BLOCKED as VERDICT_BLOCKED, parse_verdict
from aidw.workflows.implement import worktree_add_command

GATE_FOLLOWUPS = "approve-followups"
GATE_FIX_PR = "approve-fix-pr"
DEFAULT_MAX_ITERATIONS = 10


def _planned_iteration(
    *,
    pr: int,
    round_index: int,
    iteration: int,
    config: ResolvedConfig,
    aidt: Path,
    repo: Path,
) -> dict[str, StageSpec]:
    """One fix iteration's stage specs from the registry, keyed by stage name (E4.3).

    The iteration count and the round index are external GitHub state, so the loop expands
    the iteration it is about to run rather than a pre-built list (EXTRACTION.md §3.5,
    design §8.4). ``manifest_rel`` is that iteration's real-run manifest path — the value
    the registry renders into F4's pointer — so the dry run and a real run plan the same
    ``extra``.
    """
    planned = plan_stages(
        "fix",
        config=config,
        toolkit_root=aidt,
        target_root=repo,
        pr=pr,
        round_index=round_index,
        iteration=iteration,
        manifest_rel=f"artifacts/iter{iteration}-review-manifest.json",
    )
    return {spec.name: spec for spec in planned}


def _read_out(record) -> str | None:
    out = record.artifacts.get("out")
    if out and Path(out).is_file():
        return Path(out).read_text(encoding="utf-8")
    return None


def _latest_fix_run(runs_root: Path, branch: str) -> RunState | None:
    matches = [
        state
        for state in list_runs(runs_root)
        if state.workflow == "fix" and state.git.get("branch") == branch
    ]
    return matches[-1] if matches else None


def _filter_force_model(warnings: list[Issue]) -> list[Issue]:
    """The warnings ``--force-model`` overrides (design §5 independence check).

    ``reviewer != author`` is emitted by ``check_independence`` from inside
    ``load_all`` and ``differs from the fixer`` by the reviewer-rotation preflight;
    ``--force-model`` accepts the model coincidence, so neither may fail a strict
    run. Both the control-root preflight and the reloaded PR-head worktree check
    must apply this: they load the same toolkit agent configs, so the warning is
    identical in both (issue #58).
    """
    return [
        w
        for w in warnings
        if "reviewer != author" not in w.message and "differs from the fixer" not in w.message
    ]


def _followup_summary(selection: github.ScriptResult, round_index: int) -> str:
    payload = github.parse_json_output(selection.stdout) or {}
    selected = payload.get("selected") or {}
    lines = [f"Review follow-ups for this PR (round {round_index})"]
    if selected:
        lines.append(
            f"  next approved child: #{selected.get('number')} "
            f"{selected.get('title')} ({selected.get('priority')})"
        )
    else:
        lines.append("  no available approved child yet")
    lines.append(
        f"  children inspected: {payload.get('childrenInspected', '?')} "
        f"of {payload.get('totalChildren', '?')}"
    )
    for skipped in list(payload.get("skipped", []))[:10]:
        lines.append(
            f"  skip #{skipped.get('number')} [{skipped.get('reason')}] "
            f"{skipped.get('title')}"
        )
    lines.append("")
    lines.append(
        "Approving runs /approve-review-followups, which applies the GitHub decisions "
        "to every open child (`approve-fix`, removes `decision-pending`)."
    )
    return "\n".join(lines)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _approval_round(
    round_index: int,
    *,
    pr: int,
    repo: Path,
    aidt: Path,
    agents: dict,
    state: RunState,
    logger: RunLogger,
    directory: Path,
    runs_root: Path,
    config: ResolvedConfig,
    approve_all: bool,
    skip: set[str],
    deny: set[str] | None = None,
    gate_default: str | None = None,
) -> int | None:
    """Gate ``approve-followups`` and, on approval, run the approver agent.

    The A1 stage itself comes from the registry through :func:`plan_stages` (E4.3): its
    name carries the round index, which is the only part that varies per approval round, so
    the plan is asked for ``iteration=1`` and only its A1 entry is used.
    """
    planned = _planned_iteration(
        pr=pr,
        round_index=round_index,
        iteration=1,
        config=config,
        aidt=aidt,
        repo=repo,
    )
    spec = planned[f"round{round_index}-approve-review-followups"]
    name = spec.name
    selection = github.select_followups(aidt, repo, pr)
    outcome = decide(
        GATE_FOLLOWUPS,
        _followup_summary(selection, round_index),
        approve_all=approve_all,
        skip=skip,
        deny=deny,
        gate_default=gate_default,
    )
    state.record_gate(
        GateRecord(
            name=GATE_FOLLOWUPS,
            decision=outcome.decision,
            mechanism=outcome.mechanism,
            at=utcnow_iso(),
            detail=f"round={round_index}",
        )
    )
    save(directory, state)
    print(f"gate:   {GATE_FOLLOWUPS} [{outcome.mechanism}]")
    if not outcome.approved:
        print(
            f"gate {GATE_FOLLOWUPS} denied ({outcome.mechanism}); stopping.",
            file=sys.stderr,
        )
        return 3

    record = run_stage(
        # The approval postcondition is workflow-side, not stage data (E4.3 req 5): the
        # registry knows the stage, only this workflow knows how to verify the approvals.
        replace(spec, verify=lambda: github.verify_approvals(aidt, repo, pr)),
        repo_root=repo,
        toolkit_root=aidt,
        runs_root=runs_root,
        state=state,
        logger=logger,
        agents=agents,
    )
    print_stage(record, repo_root=repo)
    if record.status != SUCCEEDED:
        print(f"stage {name} failed: {record.error}", file=sys.stderr)
        return 1
    return None


def run(
    *,
    pr: int,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    force_model: bool = False,
    stream: bool = False,
) -> int:
    skip = set(skip_gates or [])
    deny = set(deny_gates or [])
    runs_root = workspace.state_root / "runs"

    # Target config (E4.3, EXTRACTION.md §3.4/§3.11): `aidw prompt`'s two fail-closed
    # refusals — validation ERRORs and `check_compatibility` — stderr + exit 2 before any
    # run record or worktree, `--dry-run` included. `validate_paths` stays prompt-only.
    resolved_config, config_issues = resolve_workflow_config(
        repo.root, toolkit_version=__version__
    )
    if config_issues:
        print(format_issues(config_issues), file=sys.stderr)
        return 2

    # --- core vs repo-optional stages (E4.5a, D12/D13, EXTRACTION.md §3.5) ------ #
    # Only a *declared* `workflows.fix.stages` list is validated: it replaces the
    # toolkit's list wholesale (§3.4), so a missing core id is a removal. Declared-ness
    # (`source == "config"`) is the test — an undeclared list is absent from the resolved
    # config and the registry defaults plan unchanged, while an explicit `stages: []`
    # must report every core stage removed. Runs immediately after the config refusal,
    # before `load_all`, any run record/worktree, and in `--dry-run`: stderr + exit 2, the
    # same contract as every other config refusal.
    stages_entry = resolved_config.get("workflows.fix.stages")
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        stage_issues = stage_registry.validate_stage_list(
            "fix", stages_entry.value or []
        )
        if stage_issues:
            print(format_issues(stage_issues), file=sys.stderr)
            return 2

    agents, issues = load_all(aidt.root, repo.root)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if force_model:
        # The rotation warning below is appended *after* this filter: it reports the
        # workflow's own re-review pairing, not a configured reviewer/author pair,
        # so ``--force-model`` deliberately does not override it.
        warnings = _filter_force_model(warnings)

    # Reviewer rotation: the re-review must not run on the fixer's model.
    if all(aid in agents for aid in ("fixer", "tester", "code-reviewer")):
        fixer_model = agents["fixer"].qualified_model
        reviewers = {
            agents["tester"].qualified_model,
            agents["code-reviewer"].qualified_model,
        }
        if not (reviewers - {fixer_model}):
            warnings.append(
                Issue(
                    WARNING,
                    "fix",
                    f"no reviewer model differs from the fixer model "
                    f"({fixer_model}); the re-review would judge its own author",
                )
            )

    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    # --- preflight: gh, PR exists, targets main (design §8.4) ---------------- #
    # ``gh`` missing and a missing PR are read failures: the refusals stay real-run
    # only, but the ``pr_view`` read itself runs in dry-run too (E2.6 req 6), so the PR
    # head resolves in both modes and ``git.current_branch`` is gone entirely.
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

    if not dry_run:
        existing = _latest_fix_run(runs_root, branch) if branch else None
        if existing is not None and existing.status == RUNNING:
            print(
                f"another fix run for `{branch}` is still marked running: "
                f"{existing.run_id}.",
                file=sys.stderr,
            )
            return 4

    if max_iterations <= 0:
        print("--max-iterations must be positive.", file=sys.stderr)
        return 2

    # --- locate the PR-head worktree (E2.6 req 3) ---------------------------- #
    # The PR head is authoritative, not the control worktree's current branch. A
    # missing worktree is a preflight refusal (exit 4, design §14) in a real run; a
    # dry run prints the corrective command as planned output and plans the F-rounds
    # against ``repo.root`` (the branch is known, there is just no worktree to plan in).
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
        # stage, every ``github.*`` read of the tree, and ``create_run`` below, so
        # ``state.json``'s ``repo_root`` records the worktree (mirroring implement).
        resolved = TargetRepo.resolve(worktree)
        repo = replace(
            resolved,
            base_branch=repo.base_branch,
            branch_pattern=repo.branch_pattern,
        )
        agents, issues = load_all(aidt.root, repo.root)
        reloaded_errors = [i for i in issues if i.level == ERROR]
        reloaded_warnings = [i for i in issues if i.level == WARNING]
        if force_model:
            # Same override as the control-root preflight: the reloaded configs are
            # the toolkit's agent configs, so the same warning reappears here (issue #58).
            reloaded_warnings = _filter_force_model(reloaded_warnings)
        if reloaded_errors or (strict and reloaded_warnings):
            print(
                format_issues(reloaded_errors + (reloaded_warnings if strict else [])),
                file=sys.stderr,
            )
            return 2
        if dry_run:
            print(f"worktree (planned): {worktree}")
    else:
        # An unanswerable PR read (``gh`` missing, or the chain's placeholder PR 0):
        # plan against the control root and keep going (E2.6 req 6), mirroring the
        # existing ``child: unknown`` line rather than refusing.
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
            "fix",
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

        if dry_run:
            script = github.script_path(aidt.root, github.FOLLOWUP_SCRIPT)
            if github.gh_available():
                selection = github.select_followups(aidt.root, repo.root, pr)
                payload = github.parse_json_output(selection.stdout) or {}
                if selection.exit_code == github.EXIT_NONE_AVAILABLE:
                    print("child:  none available")
                elif selection.exit_code == github.EXIT_OK:
                    selected = payload.get("selected") or {}
                    print(
                        f"child:  #{selected.get('number')} {selected.get('title')} "
                        f"({selected.get('priority')})"
                    )
                    print(
                        f"children: {payload.get('childrenInspected')} inspected "
                        f"of {payload.get('totalChildren')}"
                    )
                else:
                    print(
                        f"select failed (exit {selection.exit_code}): "
                        f"{selection.stderr.strip()[:200]}",
                        file=sys.stderr,
                    )
            else:
                print("child:  unknown (`gh` not found)")
            print("select argv: " + " ".join(github.build_followup_argv(script, "select", pr)))

            # The planned iteration's real-run field values (E4.3 req 5): round 1's
            # approval plus iteration 1's F1–F4, with that iteration's manifest path so the
            # dry-run F4 prompt already carries the pointer a real run would render.
            planned = _planned_iteration(
                pr=pr,
                round_index=1,
                iteration=1,
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
            )
            for spec in planned.values():
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
                note = (
                    " (only when F3 reports findings)"
                    if spec.name.endswith("review-findings-to-github")
                    else ""
                )
                print(f"{record.name} [{record.status}] (planned) agent={record.agent}{note}")
            print("gates (planned): approve-followups, approve-fix-pr")
            print(f"loop: bounded by --max-iterations={max_iterations}")
            state.status = SUCCEEDED
            save(directory, state)
            print("dry-run complete; Pi not invoked, no GitHub state written")
            return 0

        # --- initial approval round --------------------------------------------- #
        code = _approval_round(
            1,
            pr=pr,
            repo=repo.root,
            aidt=aidt.root,
            agents=agents,
            state=state,
            logger=logger,
            directory=directory,
            runs_root=runs_root,
            config=resolved_config,
            approve_all=approve_all,
            skip=skip,
            deny=deny,
            gate_default=gate_default,
        )
        if code is not None:
            state.status = BLOCKED if code == 3 else FAILED
            save(directory, state)
            return code

        iterations = 0
        round_index = 1
        closed_issues: list[dict] = []
        latest_verdict: str | None = None

        while True:
            if iterations >= max_iterations:
                print(
                    f"reached --max-iterations ({max_iterations}); stopping.",
                    file=sys.stderr,
                )
                state.status = BLOCKED
                save(directory, state)
                return 3

            selection = github.select_followups(aidt.root, repo.root, pr)
            payload = github.parse_json_output(selection.stdout) or {}
            if selection.exit_code == github.EXIT_NONE_AVAILABLE:
                break
            if selection.exit_code != github.EXIT_OK:
                print(
                    f"select failed (exit {selection.exit_code}): "
                    f"{selection.stderr.strip()[:300]}",
                    file=sys.stderr,
                )
                state.status = FAILED
                save(directory, state)
                return 1

            selected = payload.get("selected") or {}
            iterations += 1
            prefix = f"iter{iterations}"
            print(
                f"fix:    #{selected.get('number')} {selected.get('title')} "
                f"({selected.get('priority')})"
            )

            # This iteration's F1–F4, expanded from the registry once per iteration
            # (E4.3): the stage names carry the iteration count and F2/F4 carry the
            # registry-rendered context and manifest pointer. The loop is re-derived from
            # GitHub state each iteration, so nothing here is pre-planned.
            planned = _planned_iteration(
                pr=pr,
                round_index=round_index,
                iteration=iterations,
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
            )

            # F1 — fix exactly one approved child.
            record = run_stage(
                planned[f"{prefix}-fix-next-review-followup"],
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
            )
            print_stage(record, repo_root=repo.root)
            if record.status != SUCCEEDED:
                print(f"stage {record.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                save(directory, state)
                return 1

            # F2 — independent re-test.
            record = run_stage(
                planned[f"{prefix}-test"],
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
            )
            print_stage(record, repo_root=repo.root)
            if record.status != SUCCEEDED:
                print(f"stage {record.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                save(directory, state)
                return 1

            # F3 — independent re-review.
            record = run_stage(
                planned[f"{prefix}-code-review"],
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
            )
            print_stage(record, repo_root=repo.root)
            if record.status != SUCCEEDED:
                print(f"stage {record.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                save(directory, state)
                return 1

            review_text = _read_out(record) or ""
            if not review_text.strip():
                print(f"{record.name} produced no final message; stopping.", file=sys.stderr)
                state.status = FAILED
                save(directory, state)
                return 1
            verdict = parse_verdict(review_text)
            latest_verdict = verdict
            parsed, problems = findings_mod.parse_review_findings(review_text)
            _write_json(
                directory / "artifacts" / f"{prefix}-findings.json",
                {
                    "pr": pr,
                    "iteration": iterations,
                    "verdict": verdict,
                    "findings": [
                        f.to_manifest_entry(i) for i, f in enumerate(parsed, start=1)
                    ],
                    "problems": problems,
                },
            )
            print(f"verdict: {verdict or 'ambiguous'}")

            if verdict is None:
                state.status = BLOCKED
                save(directory, state)
                print("re-review verdict is ambiguous; failing closed.", file=sys.stderr)
                return 3
            if verdict == VERDICT_BLOCKED:
                state.status = BLOCKED
                save(directory, state)
                print("re-review is Blocked; stopping.", file=sys.stderr)
                return 3
            if problems:
                state.status = BLOCKED
                save(directory, state)
                print(
                    "could not build a findings manifest for the re-review; failing closed.",
                    file=sys.stderr,
                )
                return 3

            if parsed:
                # F4 — publish the new findings (ungated), then a human decides on GitHub.
                manifest_rel = f"artifacts/{prefix}-review-manifest.json"
                _write_json(
                    directory / manifest_rel,
                    findings_mod.to_manifest(parsed),
                )
                record = run_stage(
                    planned[f"{prefix}-review-findings-to-github"],
                    repo_root=repo.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                )
                print_stage(record, repo_root=repo.root)
                if record.status != SUCCEEDED:
                    print(f"stage {record.name} failed: {record.error}", file=sys.stderr)
                    state.status = FAILED
                    save(directory, state)
                    return 1

                round_index += 1
                code = _approval_round(
                    round_index,
                    pr=pr,
                    repo=repo.root,
                    aidt=aidt.root,
                    agents=agents,
                    state=state,
                    logger=logger,
                    directory=directory,
                    runs_root=runs_root,
                    config=resolved_config,
                    approve_all=approve_all,
                    skip=skip,
                    deny=deny,
                    gate_default=gate_default,
                )
                if code is not None:
                    state.status = BLOCKED if code == 3 else FAILED
                    save(directory, state)
                    return code
                continue

            if verdict != APPROVE:
                state.status = BLOCKED
                save(directory, state)
                print(
                    "re-review requires changes but no findings could be extracted; "
                    "failing closed.",
                    file=sys.stderr,
                )
                return 3

            # Clean re-review: approve the fix PR.
            summary = "\n".join(
                [
                    f"Re-review approved for PR #{pr} (iteration {iterations})",
                    f"Fixed issue: #{selected.get('number')} {selected.get('title')}",
                    f"Verdict: {verdict}",
                ]
            )
            outcome = decide(
                GATE_FIX_PR,
                summary,
                approve_all=approve_all,
                skip=skip,
                deny=deny,
                gate_default=gate_default,
            )
            state.record_gate(
                GateRecord(
                    name=GATE_FIX_PR,
                    decision=outcome.decision,
                    mechanism=outcome.mechanism,
                    at=utcnow_iso(),
                    detail=f"iteration={iterations}",
                )
            )
            save(directory, state)
            print(f"gate:   {GATE_FIX_PR} [{outcome.mechanism}]")
            if not outcome.approved:
                state.status = BLOCKED
                save(directory, state)
                print(
                    f"gate {GATE_FIX_PR} denied ({outcome.mechanism}); stopping.",
                    file=sys.stderr,
                )
                return 3
            closed_issues.append(selected)

        _write_json(
            directory / "artifacts" / "fix.json",
            {
                "pr": pr,
                "iterations": iterations,
                "closed_issues": closed_issues,
                "latest_verdict": latest_verdict,
            },
        )
        state.pr.update(
            {
                "iterations": iterations,
                "closed_issues": closed_issues,
                "latest_verdict": latest_verdict,
            }
        )
        state.status = SUCCEEDED
        save(directory, state)
        print("fix workflow complete")
        if closed_issues:
            print(f"closed: {', '.join('#' + str(i.get('number')) for i in closed_issues)}")
        else:
            print("no approved children required a fix")
        return 0
    finally:
        run_lock.release()
