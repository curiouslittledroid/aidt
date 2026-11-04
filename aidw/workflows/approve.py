"""``aidw approve-followups`` — record approval decisions for a PR's review follow-ups.

```
preflight (PR exists; `gh` available)
  ◇  approve-followups   show the open children and confirm
  →  approve-review-followups   agent review-approver
```

This extracts the approval step that ``aidw fix`` performs at its entry, so a human can
apply the GitHub decision without starting the whole fix loop. The prompt itself is
``aidt/prompts/approve-review-followups.md``; all GitHub writes are performed by the
bundled ``review_followup.py`` script the prompt invokes (design §13).

The run lock (``aidw.lock``, EXTRACTION.md §3.2/§3.10) is keyed on ``repo.root``. Unlike
``implement``/``fix`` this workflow resolves no worktree, so its key is the invocation
worktree by design: two concurrent approvals started in the same tree refuse (exit 4,
before any run state), while approvals started in different worktrees both proceed.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from aidw import __version__, git, github, lock, stage_registry
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.gates import decide
from aidw.log import RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.report import print_stage
from aidw.runner import plan_stages, run_stage
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
from aidw.target_config import SOURCE_CONFIG, resolve_workflow_config

GATE = "approve-followups"
STAGE = "approve-review-followups"
PROMPT = "approve-review-followups.md"
AGENT = "review-approver"


def _planned_stage(*, pr: int, config, aidt: Path, repo: Path):
    """The single A1 stage from the registry, with the approval postcondition (E4.3).

    The postcondition stays workflow-side: only this module knows how to verify that the
    approvals were actually applied, so it is attached to the planned spec rather than
    being stage data the registry would have to carry.
    """
    (spec,) = plan_stages(
        "approve",
        config=config,
        toolkit_root=aidt,
        target_root=repo,
        pr=pr,
    )
    return replace(spec, verify=lambda: github.verify_approvals(aidt, repo, pr))


def _selection_summary(selection: github.ScriptResult) -> str:
    payload = github.parse_json_output(selection.stdout) or {}
    selected = payload.get("selected") or {}
    lines = ["Review follow-ups for this PR"]
    if selected:
        lines.append(
            f"  next approved child: #{selected.get('number')} "
            f"{selected.get('title')} ({selected.get('priority')})"
        )
    else:
        lines.append("  no approved child available")
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
        "Approving runs /approve-review-followups, which applies `approve-fix` to every "
        "open child and removes `decision-pending`."
    )
    return "\n".join(lines)


def run(
    *,
    pr: int,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    stream: bool = False,
) -> int:
    skip = set(skip_gates or [])
    deny = set(deny_gates or [])
    runs_root = workspace.state_root / "runs"

    # Target config (E4.3, EXTRACTION.md §3.4/§3.11): `aidw prompt`'s two fail-closed
    # refusals — validation ERRORs and `check_compatibility` — stderr + exit 2 before any
    # run record and regardless of `--dry-run`. `validate_paths` stays prompt-only.
    resolved_config, config_issues = resolve_workflow_config(
        repo.root, toolkit_version=__version__
    )
    if config_issues:
        print(format_issues(config_issues), file=sys.stderr)
        return 2

    # --- core vs repo-optional stages (E4.5a, D12/D13, EXTRACTION.md §3.5) ------ #
    # Only a *declared* `workflows.approve.stages` list is validated: it replaces the
    # toolkit's list wholesale (§3.4), so a missing core id is a removal. Declared-ness
    # (`source == "config"`) is the test — an undeclared list is absent from the resolved
    # config and the registry defaults plan unchanged, while an explicit `stages: []`
    # must report every core stage removed. Runs immediately after the config refusal,
    # before `load_all`, any run record/worktree, and in `--dry-run`: stderr + exit 2, the
    # same contract as every other config refusal.
    stages_entry = resolved_config.get("workflows.approve.stages")
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        stage_issues = stage_registry.validate_stage_list(
            "approve", stages_entry.value or []
        )
        if stage_issues:
            print(format_issues(stage_issues), file=sys.stderr)
            return 2

    agents, issues = load_all(aidt.root, repo.root)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
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
            "approve",
            label=f"pr-{pr}",
            pr={
                "number": pr,
                **({"url": pr_info["url"]} if pr_info.get("url") else {}),
            },
            strict=strict,
            branch=branch,
        )
        directory = run_dir(runs_root, state.run_id)
        logger = RunLogger(directory, stream=stream)
        print(f"run:    {state.run_id}")
        print(f"pr:     #{pr}" + (f" {pr_info['url']}" if pr_info.get("url") else ""))

        if dry_run:
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
            record = run_stage(
                _planned_stage(
                    pr=pr,
                    config=resolved_config,
                    aidt=aidt.root,
                    repo=repo.root,
                ),
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                dry_run=True,
            )
            print(
                f"{record.name} [{record.status}] (planned) "
                f"agent={record.agent} model={record.model}"
            )
            print(f"gate (planned): {GATE}")
            state.status = SUCCEEDED
            save(directory, state)
            print("dry-run complete; Pi not invoked, no GitHub state written")
            return 0

        selection = github.select_followups(aidt.root, repo.root, pr)
        outcome = decide(
            GATE,
            _selection_summary(selection),
            approve_all=approve_all,
            skip=skip,
            deny=deny,
            gate_default=gate_default,
        )
        state.record_gate(
            GateRecord(
                name=GATE,
                decision=outcome.decision,
                mechanism=outcome.mechanism,
                at=utcnow_iso(),
            )
        )
        save(directory, state)
        print(f"gate:   {GATE} [{outcome.mechanism}]")
        if not outcome.approved:
            state.status = BLOCKED
            save(directory, state)
            print(
                f"gate {GATE} denied ({outcome.mechanism}); stopping.",
                file=sys.stderr,
            )
            return 3

        record = run_stage(
            _planned_stage(
                pr=pr,
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
            ),
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(record, repo_root=repo.root)
        if record.status != SUCCEEDED:
            state.status = FAILED
            save(directory, state)
            print(f"stage {STAGE} failed: {record.error}", file=sys.stderr)
            return 1

        state.status = SUCCEEDED
        save(directory, state)
        print("approve-followups complete")
        return 0
    finally:
        run_lock.release()
