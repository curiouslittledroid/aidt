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
"""

from __future__ import annotations

import sys
from pathlib import Path

from aidw import git, github
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.gates import decide
from aidw.log import RunLogger
from aidw.paths import TargetRepo, WorkspacePaths
from aidw.report import print_stage
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

GATE = "approve-followups"
STAGE = "approve-review-followups"
PROMPT = "approve-review-followups.md"
AGENT = "review-approver"


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
    repo: Path,
    aidt: Path,
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
    runs_root = WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root / "runs"

    agents, issues = load_all(aidt, repo)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    branch = git.current_branch(repo)
    pr_info: dict = {}

    if not dry_run:
        if not github.gh_available():
            print("`gh` was not found on PATH.", file=sys.stderr)
            return 4
        view = github.pr_view(repo, pr)
        if view is None:
            print(f"PR #{pr} was not found (or `gh` failed).", file=sys.stderr)
            return 2
        pr_info = view

    state = create_run(
        runs_root,
        repo,
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
            selection = github.select_followups(aidt, repo, pr)
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
            StageSpec(
                STAGE,
                AGENT,
                aidt / "prompts" / PROMPT,
                [str(pr)],
                verify=lambda: github.verify_approvals(aidt, repo, pr),
            ),
            repo_root=repo,
            toolkit_root=aidt,
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

    selection = github.select_followups(aidt, repo, pr)
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
        StageSpec(
            STAGE,
            AGENT,
            aidt / "prompts" / PROMPT,
            [str(pr)],
            verify=lambda: github.verify_approvals(aidt, repo, pr),
        ),
        repo_root=repo,
        toolkit_root=aidt,
        runs_root=runs_root,
        state=state,
        logger=logger,
        agents=agents,
    )
    print_stage(record, repo_root=repo)
    if record.status != SUCCEEDED:
        state.status = FAILED
        save(directory, state)
        print(f"stage {STAGE} failed: {record.error}", file=sys.stderr)
        return 1

    state.status = SUCCEEDED
    save(directory, state)
    print("approve-followups complete")
    return 0
