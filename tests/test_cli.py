"""Phase 0 tests for the AIDW CLI surface, plus E1.4 run-location tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from typer.testing import CliRunner

from aidw import __version__, github, inventory
from aidw.config import ERROR, Issue
from aidw import state as state_mod
from aidw.cli import EXIT_REFUSED, EXIT_STAGE_FAILURE, EXIT_USAGE, app
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths, toolkit_root
from aidw.workflows import (
    approve as approve_workflow,
    fix as fix_workflow,
    implement as implement_workflow,
    prompt as prompt_workflow,
    review as review_workflow,
)

runner = CliRunner()

ROADMAP_FIXTURE = """# Phase 3: Test Phase

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** per Design 09..
  - Done when: applyTotalDefense returns the fixed effect.
"""


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _init_repo_with_task(path: Path) -> Path:
    """A tmp git repo carrying the roadmap task ``03 E4 E4.1`` and the read-paths.

    The four §3.4 read-paths ``aidw prompt``'s preflight validates (E3.7) must exist, or
    the dry-run scenario this fixture backs refuses at that preflight instead of planning
    stages: ``docs/tasks/`` (the roadmap), ``docs/task-prompts/``,
    ``docs/implementation-results/`` and its ``TEMPLATE.md``.
    """
    _init_repo(path)
    tasks = path / "docs" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "03 - Test Phase.md").write_text(ROADMAP_FIXTURE, encoding="utf-8")
    (path / "docs" / "task-prompts").mkdir(parents=True)
    results = path / "docs" / "implementation-results"
    results.mkdir(parents=True)
    (results / "TEMPLATE.md").write_text("# Build results template\n", encoding="utf-8")
    return path


def _runs_root(repo: Path) -> Path:
    """The per-repo state-root runs directory E1.4 writes to (never the toolkit)."""
    return WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root / "runs"


def _spy_run_stage(monkeypatch, module) -> list[tuple[Path, Path]]:
    """Wrap a workflow module's ``run_stage``, recording ``(repo_root, toolkit_root)``."""
    real = module.run_stage
    calls: list[tuple[Path, Path]] = []

    def spy(spec, **kwargs):
        calls.append((kwargs["repo_root"], kwargs["toolkit_root"]))
        return real(spec, **kwargs)

    monkeypatch.setattr(module, "run_stage", spy)
    return calls


def _assert_two_roots(calls: list[tuple[Path, Path]], target: Path) -> None:
    """Every planned stage reads the target working tree and the toolkit assets."""
    assert calls, "no stages were planned"
    assert toolkit_root().resolve() != target.resolve()
    for repo_root, toolkit in calls:
        assert repo_root == target.resolve()
        assert toolkit == toolkit_root()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"aidt {__version__}"


def test_version_flag_prints_the_toolkit_version() -> None:
    """E8.3: the eager top-level flag uses the `version` subcommand's text."""
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == f"aidt {__version__}"
    # Not click/typer's default `<prog>, version <v>` rendering.
    assert "version " not in result.stdout.replace(f"aidt {__version__}", "")


def test_version_flag_agrees_with_the_version_command() -> None:
    """One format and one source (`aidw.__version__`), asserted in one place."""
    flag = runner.invoke(app, ["--version"])
    command = runner.invoke(app, ["version"])

    assert (flag.exit_code, flag.stdout) == (command.exit_code, command.stdout)


def test_version_flag_needs_no_target_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The roadmap's "without a target repo" predicate: `/tmp`, no git repo at all.

    A `--version` routed through `_roots()` fails here with `RepoNotFoundError`
    (exit 4), which is the regression this pins.
    """
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".git").exists()

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == f"aidt {__version__}"
    assert "not a git repository" not in result.output
    assert "Traceback" not in result.output


def test_version_flag_resolves_no_target_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """E8.3: `--version` is eager and must not call the single target-resolution site.

    Patching `TargetRepo.resolve` (the only place a target is resolved from cwd) proves
    the flag exits before any target work rather than merely succeeding in a repo.
    """

    def _explode(*_args: object, **_kwargs: object) -> TargetRepo:
        raise AssertionError("--version must not resolve a target repo")

    monkeypatch.setattr(TargetRepo, "resolve", staticmethod(_explode))

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == f"aidt {__version__}"


def test_help_lists_workflow_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "prompt",
        "implement",
        "review",
        "fix",
        "approve-followups",
        "tasks",
        "agents",
    ):
        assert command in result.stdout


def test_run_chain_requires_arguments() -> None:
    result = runner.invoke(app, ["run", "task-to-pr"])
    assert result.exit_code == 2
    assert "requires" in result.stderr


def test_run_chain_prompt_to_fix_requires_arguments() -> None:
    result = runner.invoke(app, ["run", "prompt-to-fix"])
    assert result.exit_code == 2
    assert "prompt-to-fix requires" in result.stderr


def test_run_chain_rejects_unknown_name() -> None:
    result = runner.invoke(app, ["run", "unknown-chain"])
    assert result.exit_code == 2
    assert "prompt-to-fix" in result.stderr


def test_run_chain_accepts_allow_incomplete_prereqs() -> None:
    """H13: the ordering override L1.2's refusal names must exist on `aidw run` too.

    A chain runs `prompt` first, so its preflight's "re-run with
    `--allow-incomplete-prereqs`" advice is only actionable if the chain accepts it.
    """
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0, result.output
    assert "--allow-incomplete-prereqs" in result.stdout


def test_doctor_runs(fake_external_clis: None) -> None:  # noqa: ARG001
    result = runner.invoke(app, ["doctor"])
    # Unknown environment issues are warnings; doctor fails only on FAIL checks.
    assert result.exit_code in (0, 1)
    assert "AIDT doctor" in result.stdout


def test_runs_list_and_show_resolve_the_state_root(tmp_path: Path) -> None:
    """E1.4: ``runs`` reads the state root, not ``<toolkit>/runs``."""
    _init_repo(tmp_path)
    runs_root = _runs_root(tmp_path)
    created = state_mod.create_run(
        runs_root, tmp_path, "implement", label="03-E4.1", branch="03-E4.1"
    )
    created.record_stage(
        state_mod.StageRecord(
            name="impliment-task",
            agent="implementer",
            model="openrouter/z-ai/glm-5.3",
            status="succeeded",
            duration_seconds=10.0,
            generation_seconds=4.0,
            tool_seconds=6.0,
            output_tokens_per_second=42.5,
        )
    )
    state_mod.save(runs_root / created.run_id, created)

    listed = runner.invoke(app, ["--repo", str(tmp_path), "runs", "list"])
    assert listed.exit_code == 0
    assert created.run_id in listed.stdout
    assert not (toolkit_root() / "runs" / created.run_id).exists()

    shown = runner.invoke(app, ["--repo", str(tmp_path), "runs", "show", created.run_id])
    assert shown.exit_code == 0
    assert f"run:      {created.run_id}" in shown.stdout
    assert "workflow: implement" in shown.stdout
    assert "42.5 out-tok/s" in shown.stdout
    assert "timing: ai=4s tools=6s" in shown.stdout


def test_runs_show_recovers_tool_time_from_an_old_stage_log(tmp_path: Path) -> None:
    """A record written before ``tool_seconds`` existed still shows a tools figure."""
    _init_repo(tmp_path)
    runs_root = _runs_root(tmp_path)
    created = state_mod.create_run(
        runs_root, tmp_path, "implement", label="03-E4.2", branch="03-E4.2"
    )
    created.record_stage(
        state_mod.StageRecord(
            name="test",
            agent="tester",
            model="openrouter/openai/gpt-5.6-luna",
            status="succeeded",
            duration_seconds=100.0,
            generation_seconds=10.0,
            log="stages/test.jsonl",
        )
    )
    state_mod.save(runs_root / created.run_id, created)
    stages = runs_root / created.run_id / "stages"
    stages.mkdir(parents=True)
    (stages / "test.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "tool_execution_end",
                        "toolCallId": "a",
                        "toolName": "read",
                        "durationMs": 42000,
                    }
                ),
                json.dumps(
                    {
                        "type": "tool_execution_end",
                        "toolCallId": "b",
                        "toolName": "bash",
                        "durationMs": 8000,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    shown = runner.invoke(app, ["--repo", str(tmp_path), "runs", "show", created.run_id])
    assert shown.exit_code == 0
    assert "timing: ai=50s tools=50s" in shown.stdout
    assert "tools:  read=42s bash=8s" in shown.stdout


def test_exec_dry_run_writes_one_run_under_the_state_root(tmp_path: Path) -> None:
    """E1.4 ``_run_dir`` move: state.json, run.log and rendered prompt are siblings.

    The literal ``rg`` gate cannot catch a split here (a stray ``toolkit_root() /
    "runs"`` matches neither banned name), so this test proves the run is whole.
    """
    _init_repo(tmp_path)
    result = runner.invoke(
        app,
        [
            "--repo",
            str(tmp_path),
            "exec",
            "--agent",
            "code-reviewer",
            "--prompt",
            "code-review",
            "--workflow",
            "stage",
            "--label",
            "cli-test",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "aidt/runs" not in result.stdout
    assert "rendered: runs/" in result.stdout

    run_dirs = list(_runs_root(tmp_path).iterdir())
    assert len(run_dirs) == 1
    directory = run_dirs[0]
    assert (directory / "state.json").is_file()
    assert (directory / "run.log").is_file()
    assert (directory / "prompts" / "code-review.rendered.md").is_file()
    exec_state = state_mod.load(directory)
    assert exec_state.toolkit_version == __version__
    assert exec_state.config_schema_version is None
    assert exec_state.config_hash is None
    assert not (toolkit_root() / "runs" / directory.name).exists()


# --------------------------------------------------------------------------- #
# Target selection: --repo > $AIDW_REPO > cwd (EXTRACTION.md §3.3/D19)
# --------------------------------------------------------------------------- #


def test_aidw_repo_selects_the_target(tmp_path: Path, monkeypatch) -> None:
    target = _init_repo_with_task(tmp_path / "target")
    created = state_mod.create_run(
        _runs_root(target), target, "implement", label="03-E4.1", branch="03-E4.1"
    )
    monkeypatch.setenv("AIDW_REPO", str(target))

    result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0, result.output
    assert created.run_id in result.stdout
    assert not (toolkit_root() / "runs" / created.run_id).exists()


def test_repo_flag_beats_aidw_repo(tmp_path: Path, monkeypatch) -> None:
    flag_repo = _init_repo_with_task(tmp_path / "flag")
    env_repo = _init_repo_with_task(tmp_path / "env")
    in_flag = state_mod.create_run(
        _runs_root(flag_repo), flag_repo, "implement", label="flag", branch="flag"
    )
    in_env = state_mod.create_run(
        _runs_root(env_repo), env_repo, "implement", label="env", branch="env"
    )
    monkeypatch.setenv("AIDW_REPO", str(env_repo))

    result = runner.invoke(app, ["--repo", str(flag_repo), "runs", "list"])

    assert result.exit_code == 0, result.output
    assert in_flag.run_id in result.stdout
    assert in_env.run_id not in result.stdout


def test_bad_aidw_repo_refuses_without_touching_cwd(tmp_path: Path, monkeypatch) -> None:
    cwd_repo = _init_repo_with_task(tmp_path / "cwd")
    bad = tmp_path / "not-a-repo"
    bad.mkdir()
    monkeypatch.chdir(cwd_repo)
    monkeypatch.setenv("AIDW_REPO", str(bad))

    result = runner.invoke(
        app, ["exec", "--agent", "code-reviewer", "--prompt", "code-review", "--dry-run"]
    )

    assert result.exit_code == EXIT_REFUSED
    assert str(bad.resolve()) in result.stderr
    assert "Traceback" not in result.output
    assert not _runs_root(cwd_repo).exists()
    assert not (cwd_repo / ".aidw" / "state").exists()


def test_bare_aidw_repo_refuses_with_bare_message(tmp_path: Path, monkeypatch) -> None:
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    monkeypatch.setenv("AIDW_REPO", str(bare))

    result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == EXIT_REFUSED
    assert "bare repository" in result.stderr
    assert str(bare.resolve()) in result.stderr
    assert "Traceback" not in result.output


def test_non_repo_flag_refuses(tmp_path: Path) -> None:
    bad = tmp_path / "not-a-repo"
    bad.mkdir()

    result = runner.invoke(app, ["--repo", str(bad), "runs", "list"])

    assert result.exit_code == EXIT_REFUSED
    assert str(bad.resolve()) in result.stderr
    assert "Traceback" not in result.output


def test_bare_repo_flag_refuses(tmp_path: Path) -> None:
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    result = runner.invoke(app, ["--repo", str(bare), "runs", "list"])

    assert result.exit_code == EXIT_REFUSED
    assert "bare repository" in result.stderr
    assert str(bare.resolve()) in result.stderr
    assert "Traceback" not in result.output


def test_whitespace_only_aidw_repo_is_unset(tmp_path: Path, monkeypatch) -> None:
    """An empty/whitespace ``AIDW_REPO`` must fall through, never become ``Path("")``."""
    cwd_repo = _init_repo_with_task(tmp_path / "cwd")
    flag_repo = _init_repo_with_task(tmp_path / "flag")
    in_cwd = state_mod.create_run(
        _runs_root(cwd_repo), cwd_repo, "implement", label="cwd", branch="cwd"
    )
    in_flag = state_mod.create_run(
        _runs_root(flag_repo), flag_repo, "implement", label="flag", branch="flag"
    )
    monkeypatch.chdir(cwd_repo)
    monkeypatch.setenv("AIDW_REPO", "   ")

    # With --repo: the flag wins over the unset env value.
    flagged = runner.invoke(app, ["--repo", str(flag_repo), "runs", "list"])
    assert flagged.exit_code == 0, flagged.output
    assert in_flag.run_id in flagged.stdout
    assert in_cwd.run_id not in flagged.stdout

    # Without --repo: the unset env value falls through to cwd.
    monkeypatch.setenv("AIDW_REPO", "")
    from_cwd = runner.invoke(app, ["runs", "list"])
    assert from_cwd.exit_code == 0, from_cwd.output
    assert in_cwd.run_id in from_cwd.stdout


def test_roots_resolves_to_typed_roots(tmp_path: Path, monkeypatch) -> None:
    target_dir = _init_repo_with_task(tmp_path / "target")
    monkeypatch.chdir(target_dir)
    from aidw import cli

    monkeypatch.setattr(cli, "_state", {"repo": None, "verbose": False})
    target, aidt, workspace = cli._roots()

    assert isinstance(target, TargetRepo)
    assert isinstance(aidt, ToolkitPaths)
    assert isinstance(workspace, WorkspacePaths)
    assert target == TargetRepo.resolve(target_dir)
    assert aidt == ToolkitPaths.resolve()
    assert workspace == WorkspacePaths.resolve(target)


def test_roots_resolves_target_and_workspace_once(tmp_path: Path, monkeypatch) -> None:
    target_dir = _init_repo_with_task(tmp_path / "target")
    monkeypatch.chdir(target_dir)
    monkeypatch.delenv("AIDW_REPO", raising=False)
    from aidw import cli

    target_resolve = cli.TargetRepo.resolve
    workspace_resolve = cli.WorkspacePaths.resolve
    target_calls: list[tuple[tuple, dict]] = []
    workspace_calls: list[tuple[tuple, dict]] = []

    def spy_target(cls, *args, **kwargs):
        target_calls.append((args, kwargs))
        return target_resolve(*args, **kwargs)

    def spy_workspace(cls, *args, **kwargs):
        workspace_calls.append((args, kwargs))
        return workspace_resolve(*args, **kwargs)

    monkeypatch.setattr(cli.TargetRepo, "resolve", classmethod(spy_target))
    monkeypatch.setattr(cli.WorkspacePaths, "resolve", classmethod(spy_workspace))
    monkeypatch.setattr(cli, "_state", {"repo": None, "verbose": False})

    target, _aidt, workspace = cli._roots()

    assert len(target_calls) == 1
    assert len(workspace_calls) == 1
    assert target_calls[0][1] == {"explicit": None}
    assert workspace_calls[0][0] == (target,)
    expected_workspace = workspace_resolve(target)
    assert workspace.workspace_root == expected_workspace.workspace_root
    assert workspace.state_root == expected_workspace.state_root


# --------------------------------------------------------------------------- #
# Two roots: target-side state, toolkit-side prompts (target != toolkit root)
# --------------------------------------------------------------------------- #


def test_prompt_dry_run_reads_target_and_uses_toolkit_prompts(
    tmp_path: Path, monkeypatch
) -> None:
    target = _init_repo_with_task(tmp_path / "target")
    calls = _spy_run_stage(monkeypatch, prompt_workflow)

    result = runner.invoke(
        app, ["--repo", str(target), "prompt", "03", "E4", "E4.1", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    _assert_two_roots(calls, target)
    runs = list(_runs_root(target).iterdir())
    assert len(runs) == 1
    assert not (toolkit_root() / "runs" / runs[0].name).exists()


def test_implement_dry_run_reads_target_and_uses_toolkit_prompts(
    tmp_path: Path, monkeypatch
) -> None:
    target = _init_repo_with_task(tmp_path / "target")
    prompt = target / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    # ``_init_repo_with_task`` already creates the directory (E3.7's read-path), so this
    # must not be an exclusive ``mkdir``.
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("# Implement E4.1\n", encoding="utf-8")
    calls = _spy_run_stage(monkeypatch, implement_workflow)

    result = runner.invoke(
        app, ["--repo", str(target), "implement", str(prompt), "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    _assert_two_roots(calls, target)
    runs = list(_runs_root(target).iterdir())
    assert len(runs) == 1
    assert not (toolkit_root() / "runs" / runs[0].name).exists()


def test_review_dry_run_reads_target_and_uses_toolkit_prompts(
    tmp_path: Path, monkeypatch
) -> None:
    target = _init_repo_with_task(tmp_path / "target")
    # `review` reads the PR head in dry-run too (K1), so keep the plan off the network.
    monkeypatch.setattr(github, "gh_available", lambda: False)
    calls = _spy_run_stage(monkeypatch, review_workflow)

    result = runner.invoke(app, ["--repo", str(target), "review", "--pr", "7", "--dry-run"])

    assert result.exit_code == 0, result.output
    _assert_two_roots(calls, target)
    assert list(_runs_root(target).iterdir())


def test_fix_dry_run_reads_target_and_uses_toolkit_prompts(
    tmp_path: Path, monkeypatch
) -> None:
    target = _init_repo_with_task(tmp_path / "target")
    monkeypatch.setattr(github, "gh_available", lambda: False)
    calls = _spy_run_stage(monkeypatch, fix_workflow)

    result = runner.invoke(app, ["--repo", str(target), "fix", "--pr", "7", "--dry-run"])

    assert result.exit_code == 0, result.output
    _assert_two_roots(calls, target)
    assert list(_runs_root(target).iterdir())


def test_approve_dry_run_reads_target_and_uses_toolkit_prompts(
    tmp_path: Path, monkeypatch
) -> None:
    target = _init_repo_with_task(tmp_path / "target")
    monkeypatch.setattr(github, "gh_available", lambda: False)
    calls = _spy_run_stage(monkeypatch, approve_workflow)

    result = runner.invoke(
        app, ["--repo", str(target), "approve-followups", "--pr", "7", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    _assert_two_roots(calls, target)
    assert list(_runs_root(target).iterdir())


def test_exec_resolves_prompts_from_toolkit_and_state_from_target(
    tmp_path: Path, monkeypatch
) -> None:
    target = _init_repo_with_task(tmp_path / "target")
    from aidw import cli

    real_resolve = cli.resolve_prompt
    resolved: list[Path] = []

    # E4.2: the resolver's contract is (toolkit_root, target_root, name, explicit_path).
    def spy_resolve(
        root: Path, target: Path, name: str, explicit_path: str | None = None
    ) -> Path:
        resolved.append(root)
        return real_resolve(root, target, name, explicit_path)

    monkeypatch.setattr(cli, "resolve_prompt", spy_resolve)
    calls = _spy_run_stage(monkeypatch, cli)

    result = runner.invoke(
        app,
        [
            "--repo",
            str(target),
            "exec",
            "--agent",
            "code-reviewer",
            "--prompt",
            "code-review",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert resolved == [toolkit_root()]
    _assert_two_roots(calls, target)
    assert len(list(_runs_root(target).iterdir())) == 1


# --------------------------------------------------------------------------- #
# `config show` — six values with provenance (EXTRACTION.md §3.3/§3.4)
# --------------------------------------------------------------------------- #

CONFIG_KEYS = {
    "toolkit_root",
    "version",
    "target_root",
    "workspace_root",
    "state_root",
    "config_file",
    # E3.2: the resolved §3.4 config, one flat dotted-path mapping of ``{value, source}``.
    "config",
}

#: The six E1.6 root entries, kept intact by E3.2.
CONFIG_ROOT_KEYS = CONFIG_KEYS - {"config"}

#: The six ``github.labels`` names in the resolver's walk order: ``resolve_config`` visits
#: an open map in sorted name order, and ``config show`` prints the leaves in resolution
#: order, so the leaf tuple below is the real output order (asserted line-by-line).
CONFIG_LABEL_NAMES = (
    "approve-fix",
    "could-fix",
    "decision-pending",
    "must-fix",
    "review-follow-up",
    "should-fix",
)

#: Every §3.4 leaf resolved by ``resolve_config`` for a repo with no config file:
#: ``max_revisions`` (E3.2), the eight ``repo:``/``paths:`` values (E3.4), E4.6's unset
#: override directory, and E6.1's frozen ``github.markers``/``github.labels`` values. Only
#: the declared-only leaves are *unset* now.
CONFIG_LEAF_PATHS = (
    "schema_version",
    "requires_toolkit",
    "max_revisions",
    "repo.base_branch",
    "repo.branch_pattern",
    "paths.roadmap_dir",
    "paths.roadmap_glob",
    "paths.task_prompts_dir",
    "paths.implementation_results_dir",
    "paths.build_results_template",
    "paths.architecture_dir",
    "paths.agent_configs_dir",
    "github.markers.parent",
    "github.markers.child",
    "github.markers.summary",
    *(
        f"github.labels.{name}.{key}"
        for name in CONFIG_LABEL_NAMES
        for key in ("color", "description")
    ),
)

#: E3.4's eight §3.4 defaults (D17/R7) and E6.1's frozen D5 GitHub literals, spelled out
#: literally (never read from the module) so a changed default fails here, at the operator's
#: debug surface, and not only in the resolver's own tests.
CONFIG_DEFAULT_LEAVES = {
    "repo.base_branch": "main",
    "repo.branch_pattern": "{phase}-{task}",
    "paths.roadmap_dir": "docs/tasks",
    "paths.roadmap_glob": "[0-9]* - *.md",
    "paths.task_prompts_dir": "docs/task-prompts",
    "paths.implementation_results_dir": "docs/implementation-results",
    "paths.build_results_template": "docs/implementation-results/TEMPLATE.md",
    "paths.architecture_dir": "docs/architecture",
    "github.markers.parent": "<!-- mythical-forge-review-followups: pr={pr_url} -->",
    "github.markers.child": (
        "<!-- mythical-forge-review-follow-up: pr={pr_url} finding={finding_id} -->"
    ),
    "github.markers.summary": (
        "<!-- mythical-forge-review-followups-summary: pr={pr_url} -->"
    ),
    "github.labels.approve-fix.color": "B8D64A",
    "github.labels.approve-fix.description": "Human-approved review follow-up fix",
    "github.labels.could-fix.color": "FBCA04",
    "github.labels.could-fix.description": (
        "Limited review improvement or simplification"
    ),
    "github.labels.decision-pending.color": "EDEDED",
    "github.labels.decision-pending.description": (
        "Human decision required before implementation"
    ),
    "github.labels.must-fix.color": "B60205",
    "github.labels.must-fix.description": "Blocking review finding",
    "github.labels.review-follow-up.color": "5319E7",
    "github.labels.review-follow-up.description": (
        "Review-generated task or parent issue"
    ),
    "github.labels.should-fix.color": "D93F0B",
    "github.labels.should-fix.description": (
        "Non-blocking but recommended finding"
    ),
}

#: The leaves with **no** toolkit default: ``schema_version``/``requires_toolkit`` are
#: declared-only (E3.1/E3.3) and E4.6's override directory has none on purpose. In a
#: no-config repo they are the only leaves ``config show`` prints as ``unset``.
CONFIG_UNSET_LEAVES = (
    "schema_version",
    "requires_toolkit",
    # E4.6: the global agent-config override dir is unset, not defaulted.
    "paths.agent_configs_dir",
)


def _config_lines(stdout: str) -> list[str]:
    """The non-empty human-mode lines, each ``label: value (source)``."""
    return [line for line in stdout.splitlines() if line.strip()]


def _line_source(line: str) -> str:
    """Extract the trailing ``(source)`` from a human-mode line."""
    _head, sep, tail = line.rpartition(" (")
    assert sep, f"line has no source suffix: {line!r}"
    assert tail.endswith(")"), line
    return tail[:-1]


def _expected_state(repo: Path) -> Path:
    return WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root


def _config_show_json(*args: str):
    return runner.invoke(app, [*args, "config", "show", "--json"])


def test_config_show_resolves_target_and_workspace_once(
    tmp_path: Path, monkeypatch
) -> None:
    """The command consumes the three roots threaded by ``_roots``."""
    from aidw import cli

    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)

    real_target_resolve = cli.TargetRepo.resolve
    real_workspace_resolve = cli.WorkspacePaths.resolve
    target_calls = 0
    workspace_calls = 0

    def target_resolve(cls, *args, **kwargs):
        nonlocal target_calls
        target_calls += 1
        return real_target_resolve(*args, **kwargs)

    def workspace_resolve(cls, *args, **kwargs):
        nonlocal workspace_calls
        workspace_calls += 1
        return real_workspace_resolve(*args, **kwargs)

    monkeypatch.setattr(cli.TargetRepo, "resolve", classmethod(target_resolve))
    monkeypatch.setattr(cli.WorkspacePaths, "resolve", classmethod(workspace_resolve))

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    assert target_calls == 1
    assert workspace_calls == 1


def test_config_show_human_single_checkout(tmp_path: Path, monkeypatch) -> None:
    """The six root lines, then one line per resolved leaf (dotted path, source)."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0, result.output
    lines = _config_lines(result.stdout)
    # Six root entries + one line per §3.4 leaf; no YAML nesting, no per-stage entries.
    assert len(lines) == 6 + len(CONFIG_LEAF_PATHS)
    root_lines, leaf_lines = lines[:6], lines[6:]
    # Exactly the six pinned root source strings, no display-label wording pinned.
    assert sorted(_line_source(line) for line in root_lines) == [
        "cwd",
        "defaults",
        "package",
        "package",
        "workspace",
        "workspace",
    ]
    assert f"{ToolkitPaths.resolve().root} (package)" in result.stdout
    assert f"{__version__} (package)" in result.stdout
    assert f"{tmp_path.resolve()} (cwd)" in result.stdout
    assert f"{tmp_path.resolve()} (workspace)" in result.stdout
    assert f"{_expected_state(tmp_path)} (workspace)" in result.stdout

    defaults_line = [
        line for line in root_lines if _line_source(line) == "defaults"
    ]
    assert len(defaults_line) == 1
    assert "none" in defaults_line[0]

    # The leaf section is the same order and the same set as the JSON section.
    assert [line.split(":", 1)[0] for line in leaf_lines] == list(CONFIG_LEAF_PATHS)
    by_path = {line.split(":", 1)[0]: line for line in leaf_lines}
    assert by_path["max_revisions"] == "max_revisions: 3 (default)"
    # E3.4: a no-config repo reports the Mythical Forge layout as ``default``.
    for path, value in CONFIG_DEFAULT_LEAVES.items():
        assert by_path[path] == f"{path}: {value} (default)", path
    # Only the declared-only leaves print ``unset`` with no source.
    for path in CONFIG_UNSET_LEAVES:
        assert by_path[path] == f"{path}: unset", path
    assert set(CONFIG_DEFAULT_LEAVES) | set(CONFIG_UNSET_LEAVES) | {
        "max_revisions"
    } == set(CONFIG_LEAF_PATHS)


def test_config_show_json_single_checkout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == CONFIG_KEYS
    for key in CONFIG_ROOT_KEYS:
        assert set(payload[key]) == {"value", "source"}
    # The ``config`` section is the flat dotted-path dump, not a nested §3.4 shape.
    assert list(payload["config"]) == list(CONFIG_LEAF_PATHS)
    assert payload["config"]["max_revisions"] == {"value": 3, "source": "default"}
    # E3.4: the eight §3.4 leaves resolve as ``default`` with the Mythical Forge values.
    for path, value in CONFIG_DEFAULT_LEAVES.items():
        assert payload["config"][path] == {"value": value, "source": "default"}, path
    for path in CONFIG_UNSET_LEAVES:
        # Unset: value null and *no* ``source`` key at all.
        assert payload["config"][path] == {"value": None}, path

    assert payload["toolkit_root"] == {
        "value": str(ToolkitPaths.resolve().root),
        "source": "package",
    }
    assert payload["version"] == {"value": __version__, "source": "package"}
    assert payload["target_root"] == {
        "value": str(tmp_path.resolve()),
        "source": "cwd",
    }
    assert payload["workspace_root"] == {
        "value": str(tmp_path.resolve()),
        "source": "workspace",
    }
    assert payload["state_root"] == {
        "value": str(_expected_state(tmp_path)),
        "source": "workspace",
    }
    assert payload["config_file"] == {"value": None, "source": "defaults"}


def test_config_show_detects_the_target_config_file(tmp_path: Path, monkeypatch) -> None:
    """A regular ``<target>/aidw/config.yaml`` becomes a resolved path, not parsed."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    config_path = tmp_path / "aidw" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text("schema_version: 1\n", encoding="utf-8")

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["config_file"] == {
        "value": str(config_path.resolve()),
        "source": "target repo",
    }


def test_config_show_dumps_a_declared_config_by_dotted_path(
    tmp_path: Path, monkeypatch
) -> None:
    """The ``config`` section is one flat mapping: ``config`` provenance per declared leaf,
    a whole-list entry at ``workflows.<name>.stages``, and ``unset`` elsewhere."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    config_path = tmp_path / "aidw" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        "schema_version: 1\n"
        "repo:\n"
        "  base_branch: trunk\n"
        "workflows:\n"
        "  prompt:\n"
        "    stages:\n"
        "      - id: author\n"
        "      - id: review\n"
        "github:\n"
        "  labels:\n"
        "    must-fix: {color: \"B60205\", description: Blocking}\n",
        encoding="utf-8",
    )

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["config_file"] == {
        "value": str(config_path.resolve()),
        "source": "target repo",
    }
    config = payload["config"]
    assert config["schema_version"] == {"value": 1, "source": "config"}
    assert config["repo.base_branch"] == {"value": "trunk", "source": "config"}
    # A list carries provenance only at its own path: no ``stages[0]``-style entries.
    assert config["workflows.prompt.stages"] == {
        "value": [{"id": "author"}, {"id": "review"}],
        "source": "config",
    }
    assert not any(path.startswith("workflows.prompt.stages[") for path in config)
    assert "workflows.prompt.parallel_groups" not in config
    assert config["github.labels.must-fix.color"] == {
        "value": "B60205",
        "source": "config",
    }
    # E3.4: an undeclared sibling resolves its own §3.4 default, independently.
    assert config["paths.roadmap_dir"] == {"value": "docs/tasks", "source": "default"}
    assert config["repo.branch_pattern"] == {
        "value": "{phase}-{task}",
        "source": "default",
    }
    # ...and the E3.2 budget still resolves as ``default``, E6.1's markers resolve their
    # frozen defaults, while the declared-only pin stays unset.
    assert config["max_revisions"] == {"value": 3, "source": "default"}
    assert config["requires_toolkit"] == {"value": None}
    assert config["github.markers.parent"] == {
        "value": "<!-- mythical-forge-review-followups: pr={pr_url} -->",
        "source": "default",
    }
    # The declared label's fields are ``config``; every other label (and the three markers)
    # resolve the seeded defaults, per leaf.
    assert config["github.labels.must-fix.description"] == {
        "value": "Blocking",
        "source": "config",
    }
    assert config["github.labels.should-fix.color"] == {
        "value": "D93F0B",
        "source": "default",
    }


def test_config_show_human_renders_declared_and_unset_leaves(
    tmp_path: Path, monkeypatch
) -> None:
    """Human mode appends ``dotted-path: value (source)`` lines, with list values as JSON."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    config_path = tmp_path / "aidw" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        "schema_version: 1\n"
        "repo:\n"
        "  base_branch: trunk\n"
        "workflows:\n"
        "  prompt:\n"
        "    stages:\n"
        "      - id: author\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0, result.output
    lines = _config_lines(result.stdout)
    assert "repo.base_branch: trunk (config)" in lines
    assert 'workflows.prompt.stages: [{"id": "author"}] (config)' in lines
    assert "max_revisions: 3 (default)" in lines
    # E3.4: the undeclared base-branch sibling and the ``paths:`` block are defaults.
    assert "repo.branch_pattern: {phase}-{task} (default)" in lines
    assert "paths.roadmap_dir: docs/tasks (default)" in lines
    assert (
        "paths.build_results_template: "
        "docs/implementation-results/TEMPLATE.md (default)" in lines
    )
    # The still-unseeded leaves (E3.3's optional pin, E4.6's override dir) print ``unset``.
    assert "requires_toolkit: unset" in lines
    assert "paths.agent_configs_dir: unset" in lines
    # E6.1: the frozen D5 markers/labels now resolve ``default`` and render inline.
    assert (
        "github.markers.parent: <!-- mythical-forge-review-followups: pr={pr_url} --> "
        "(default)" in lines
    )
    assert "github.labels.must-fix.color: B60205 (default)" in lines
    assert (
        "github.labels.approve-fix.description: Human-approved review follow-up fix "
        "(default)" in lines
    )
    assert f"config file: {config_path.resolve()} (target repo)" in lines


def test_config_show_override_provenance_is_not_reachable_here(
    tmp_path: Path, monkeypatch
) -> None:
    """``config show`` takes no override flag (§3.3): no leaf reports ``override``."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    sources = {
        entry.get("source") for entry in json.loads(result.stdout)["config"].values()
    }
    assert sources == {"default", None}


def test_config_show_does_not_refuse_an_incompatible_config(
    tmp_path: Path, monkeypatch
) -> None:
    """Requirement 5 / E3.3: ``config show`` stays display-only, even when incompatible.

    The refusal belongs to the workflow preflight (§3.11 "refuses to run"); this command
    is the inspection aid that shows *why* a workflow refuses, so it exits 0 and reports
    the resolved ``schema_version``/``requires_toolkit`` with ``config`` provenance. A
    compatibility check wrongly added here fails this test.
    """
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    config_path = tmp_path / "aidw" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        'schema_version: 2\nrequires_toolkit: ">=99.0.0"\n', encoding="utf-8"
    )

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    # The single-checkout state-root warning is unrelated; no compatibility refusal.
    assert "error: config.yaml:" not in result.stderr
    config = json.loads(result.stdout)["config"]
    assert config["schema_version"] == {"value": 2, "source": "config"}
    assert config["requires_toolkit"] == {"value": ">=99.0.0", "source": "config"}


def test_config_show_config_file_directory_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """E3.2 flips E1.6's ``none``: a directory passes ``exists()`` but cannot be read.

    The loader's ``read_text`` raises ``OSError``, which is an ERROR issue — a broken
    config is refused, never silently resolved to defaults.
    """
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    (tmp_path / "aidw" / "config.yaml").mkdir(parents=True)

    result = _config_show_json()

    assert result.exit_code == EXIT_STAGE_FAILURE
    assert result.stdout == ""  # all-or-nothing: no resolved output at all
    assert "cannot read/parse config" in result.stderr


def test_config_show_unparseable_yaml_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """E3.2 flips E1.6's "detect but never parse": a broken YAML file refuses."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    config_path = tmp_path / "aidw" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text("{{ not yaml: [", encoding="utf-8")

    result = _config_show_json()

    assert result.exit_code == EXIT_STAGE_FAILURE
    assert result.stdout == ""
    assert "cannot read/parse config" in result.stderr


def test_config_show_unknown_key_fails_closed_human_keeps_root_lines(
    tmp_path: Path, monkeypatch
) -> None:
    """A validated-but-invalid config refuses; human mode keeps the two E1.6 lines."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    config_path = tmp_path / "aidw" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text("schema_version: 1\nreop:\n  base_branch: main\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == EXIT_STAGE_FAILURE
    assert "unknown key `reop`" in result.stderr
    # The two no-repo root lines precede the refusal; nothing else is printed.
    assert result.stdout.splitlines() == [
        f"toolkit root: {ToolkitPaths.resolve().root} (package)",
        f"version: {__version__} (package)",
    ]


def test_config_show_broken_config_symlink_uses_defaults(
    tmp_path: Path, monkeypatch
) -> None:
    """A broken config symlink is invisible to the loader's ``exists()``: absent.

    Same outcome E1.6's ``is_file()`` detection gave (``null``/``defaults``, exit 0); only
    the mechanism changed, so no fail-closed refusal applies here.
    """
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    config_path = tmp_path / "aidw" / "config.yaml"
    config_path.parent.mkdir()
    config_path.symlink_to(tmp_path / "missing-config.yaml")

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["config_file"] == {
        "value": None,
        "source": "defaults",
    }


def test_config_show_target_provenance(tmp_path: Path, monkeypatch) -> None:
    """``--repo`` > ``$AIDW_REPO`` > cwd, labelled with the actual winner."""
    flag_repo = tmp_path / "flag"
    env_repo = tmp_path / "env"
    cwd_repo = tmp_path / "cwd"
    _init_repo(flag_repo)
    _init_repo(env_repo)
    _init_repo(cwd_repo)
    monkeypatch.chdir(cwd_repo)
    monkeypatch.setenv("AIDW_REPO", str(env_repo))

    flagged = _config_show_json("--repo", str(flag_repo))
    assert flagged.exit_code == 0, flagged.output
    assert json.loads(flagged.stdout)["target_root"] == {
        "value": str(flag_repo.resolve()),
        "source": "--repo",
    }

    env_only = _config_show_json()
    assert env_only.exit_code == 0, env_only.output
    assert json.loads(env_only.stdout)["target_root"] == {
        "value": str(env_repo.resolve()),
        "source": "AIDW_REPO",
    }

    monkeypatch.delenv("AIDW_REPO")
    from_cwd = _config_show_json()
    assert from_cwd.exit_code == 0, from_cwd.output
    assert json.loads(from_cwd.stdout)["target_root"] == {
        "value": str(cwd_repo.resolve()),
        "source": "cwd",
    }


def test_config_show_whitespace_aidw_repo_falls_to_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    """A blank ``AIDW_REPO`` is normalised to unset by the shared helper."""
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    monkeypatch.setenv("AIDW_REPO", "   ")

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["target_root"] == {
        "value": str(tmp_path.resolve()),
        "source": "cwd",
    }


def test_config_show_state_provenance_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    env_dir = tmp_path / "env-state"
    monkeypatch.setenv("AIDW_STATE_DIR", str(env_dir))

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["state_root"] == {
        "value": str(_expected_state(tmp_path)),
        "source": "AIDW_STATE_DIR",
    }


def test_config_show_state_provenance_whitespace_env(
    tmp_path: Path, monkeypatch
) -> None:
    """Unlike ``AIDW_REPO``, a whitespace ``AIDW_STATE_DIR`` is *set* (§3.10 bare truthiness)."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    monkeypatch.setenv("AIDW_STATE_DIR", "   ")

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["state_root"]["source"] == "AIDW_STATE_DIR"
    assert Path(payload["state_root"]["value"]).parent == Path("   ").resolve()


def test_config_show_state_provenance_home(tmp_path: Path, monkeypatch) -> None:
    """An unwritable workspace root falls through to the ``home`` tier label."""
    workspace = tmp_path / "ws"
    _init_repo(workspace)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(workspace)

    original_mode = workspace.stat().st_mode
    try:
        workspace.chmod(0o500)
        result = _config_show_json()
    finally:
        workspace.chmod(original_mode)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["state_root"] == {
        "value": str(home.resolve() / ".aidw" / "state" / workspace.name),
        "source": "home",
    }


def test_config_show_wrong_target_refuses_human(tmp_path: Path, monkeypatch) -> None:
    """Human mode prints toolkit + version first, then refuses with the path."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    bad = tmp_path / "not-a-repo"
    bad.mkdir()

    result = runner.invoke(app, ["--repo", str(bad), "config", "show"])

    assert result.exit_code == EXIT_REFUSED
    assert str(bad.resolve()) in result.stderr
    assert "Traceback" not in result.output
    assert f"{ToolkitPaths.resolve().root} (package)" in result.stdout
    assert f"{__version__} (package)" in result.stdout


def test_config_show_bare_target_refuses(tmp_path: Path) -> None:
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    result = runner.invoke(app, ["--repo", str(bare), "config", "show"])

    assert result.exit_code == EXIT_REFUSED
    assert "bare repository" in result.stderr
    assert str(bare.resolve()) in result.stderr


def test_config_show_wrong_target_json_leaves_stdout_empty(tmp_path: Path) -> None:
    """``--json`` is all-or-nothing: no partial JSON, no human lines."""
    bad = tmp_path / "not-a-repo"
    bad.mkdir()

    result = runner.invoke(app, ["--repo", str(bad), "config", "show", "--json"])

    assert result.exit_code == EXIT_REFUSED
    assert result.stdout == ""
    assert str(bad.resolve()) in result.stderr


def test_config_unknown_action_beats_a_bad_target(tmp_path: Path) -> None:
    """Action validation runs before ``_roots()``: usage error wins over refusal."""
    bad = tmp_path / "not-a-repo"
    bad.mkdir()

    result = runner.invoke(app, ["--repo", str(bad), "config", "bogus"])

    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert "unknown action" in result.stderr
    assert str(bad.resolve()) not in result.stderr


def test_config_show_writes_no_state_dir(tmp_path: Path, monkeypatch) -> None:
    """Resolution is read-only: it must not create the state root (R8)."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)

    result = _config_show_json()

    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".aidw").exists()


# --------------------------------------------------------------------------- #
# E5.2: `aidw tasks` reads the configured roadmap location (D15/D17)
# --------------------------------------------------------------------------- #
#
# The roadmap's directory and filename pattern are target-repo configuration, so `tasks`
# must list whatever `paths.roadmap_dir` + `paths.roadmap_glob` resolve to — with no
# parser change and no `docs/tasks` present — and must fail closed on a broken config
# (E3.2/E3.3: a broken config is never silently resolved to defaults).


def _write_roadmap(path: Path, names: dict[str, str]) -> Path:
    """Write ``{filename: body}`` into ``path`` (created) and return it."""
    path.mkdir(parents=True, exist_ok=True)
    for name, body in names.items():
        (path / name).write_text(body, encoding="utf-8")
    return path


def _write_target_config(repo: Path, text: str) -> Path:
    config_path = repo / "aidw" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding="utf-8")
    return config_path


def _target_cwd(tmp_path: Path, monkeypatch) -> None:
    """Make ``tmp_path`` the resolved target with no leftover env override."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)


def test_tasks_reads_the_configured_roadmap_dir_and_glob(
    tmp_path: Path, monkeypatch
) -> None:
    """A non-default ``roadmap_dir`` + ``roadmap_glob`` drive the listing, config only.

    The repo has no ``docs/tasks`` at all, and the configured glob excludes the second
    phase file, so neither a hardcoded directory nor an ignored glob can pass.
    """
    _target_cwd(tmp_path, monkeypatch)
    _init_repo(tmp_path)
    _write_roadmap(
        tmp_path / "plans",
        {
            "03 - Test Phase.md": ROADMAP_FIXTURE,
            "10 - Later Phase.md": (
                "# Phase 10: Later Phase\n\n## Epic E4: Later\n\n"
                "- [ ] **E4.9. Later task** text.\n  - Done when: later.\n"
            ),
        },
    )
    _write_target_config(
        tmp_path,
        "schema_version: 1\n"
        "paths:\n"
        "  roadmap_dir: plans\n"
        '  roadmap_glob: "0[0-9] - *.md"\n',
    )

    result = runner.invoke(app, ["tasks"])

    assert result.exit_code == 0, result.output
    assert "E4.1" in result.stdout
    assert "Implement Total Defense" in result.stdout
    # `0[0-9] - *.md` selects the `03` file only: the glob, not just the directory, is read.
    assert "10 - Later Phase.md" not in result.stdout
    assert "E4.9" not in result.stdout
    assert not (tmp_path / "docs" / "tasks").exists()


def test_tasks_absolute_roadmap_dir_wins(tmp_path: Path, monkeypatch) -> None:
    """``repo.root / value``: an absolute ``roadmap_dir`` wins (pathlib, §3.4's rule)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _target_cwd(repo, monkeypatch)
    elsewhere = _write_roadmap(
        tmp_path / "elsewhere", {"07 - Absolute.md": ROADMAP_FIXTURE}
    )
    _write_target_config(
        repo,
        "schema_version: 1\n"
        "paths:\n"
        f"  roadmap_dir: {json.dumps(str(elsewhere))}\n",
    )

    result = runner.invoke(app, ["tasks"])

    assert result.exit_code == 0, result.output
    # The phase comes from the filename in the absolute directory, not from the heading.
    assert "07" in result.stdout
    assert "E4.1" in result.stdout
    # Nothing was read from the repo itself: the absolute dir is the roadmap.
    assert not (repo / "elsewhere").exists()
    assert not (repo / "docs" / "tasks").exists()


def test_tasks_default_roadmap_dir_still_lists_with_no_config(
    tmp_path: Path, monkeypatch
) -> None:
    """The D17 default (``docs/tasks`` + ``[0-9]* - *.md``) needs no config file."""
    _target_cwd(tmp_path, monkeypatch)
    _init_repo(tmp_path)
    _write_roadmap(tmp_path / "docs" / "tasks", {"03 - Test Phase.md": ROADMAP_FIXTURE})

    result = runner.invoke(app, ["tasks"])

    assert result.exit_code == 0, result.output
    assert "Implement Total Defense" in result.stdout
    assert not (tmp_path / "aidw").exists()


def test_tasks_malformed_config_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """A broken config refuses (stderr + EXIT_STAGE_FAILURE) instead of listing anything.

    The roadmap itself is present and parseable, so a command that resolved the config
    leniently would print a listing here; it must not.
    """
    _target_cwd(tmp_path, monkeypatch)
    _init_repo(tmp_path)
    _write_roadmap(tmp_path / "docs" / "tasks", {"03 - Test Phase.md": ROADMAP_FIXTURE})
    _write_target_config(tmp_path, "{{ not yaml: [")

    result = runner.invoke(app, ["tasks"])

    assert result.exit_code == EXIT_STAGE_FAILURE
    assert result.stdout == ""
    assert "cannot read/parse config" in result.stderr
    assert "Implement Total Defense" not in result.stderr


@pytest.mark.parametrize(
    ("glob", "expected"),
    [
        pytest.param("", "must be a non-empty glob pattern", id="empty"),
        pytest.param("/etc/*.md", "must be a relative glob pattern", id="absolute"),
    ],
)
def test_tasks_degenerate_roadmap_glob_fails_closed(
    tmp_path: Path, monkeypatch, glob: str, expected: str
) -> None:
    """A degenerate ``paths.roadmap_glob`` refuses like any broken config (PR #97 F1).

    Pre-fix the value reached ``tasks_dir.glob`` unguarded, so the command
    traceback'd (``ValueError``/``NotImplementedError`` on Python 3.13+) instead of
    the documented stderr + ``EXIT_STAGE_FAILURE`` refusal (E3.2/E3.3).
    """
    _target_cwd(tmp_path, monkeypatch)
    _init_repo(tmp_path)
    _write_roadmap(tmp_path / "docs" / "tasks", {"03 - Test Phase.md": ROADMAP_FIXTURE})
    _write_target_config(
        tmp_path,
        "schema_version: 1\npaths:\n  roadmap_dir: docs/tasks\n"
        f"  roadmap_glob: {json.dumps(glob)}\n",
    )

    result = runner.invoke(app, ["tasks"])

    assert result.exit_code == EXIT_STAGE_FAILURE
    # A clean refusal, never the pre-fix crash out of `load_tasks`.
    assert not isinstance(result.exception, (ValueError, NotImplementedError)), (
        result.exception
    )
    assert result.stdout == ""
    assert "paths.roadmap_glob" in result.stderr
    assert expected in result.stderr
    assert "Implement Total Defense" not in result.stderr


def test_tasks_does_not_validate_the_other_read_paths(
    tmp_path: Path, monkeypatch
) -> None:
    """`tasks` needs only the roadmap: it must not run the E3.7 read-path preflight.

    A roadmap-only repo (no task-prompts/results/template) is exactly what an inspection
    command must still be able to list; `validate_paths` here would refuse it.
    """
    _target_cwd(tmp_path, monkeypatch)
    _init_repo(tmp_path)
    _write_roadmap(tmp_path / "docs" / "tasks", {"03 - Test Phase.md": ROADMAP_FIXTURE})

    result = runner.invoke(app, ["tasks"])

    assert result.exit_code == 0, result.output
    assert "E4.1" in result.stdout
    assert not (tmp_path / "docs" / "task-prompts").exists()
    assert not (tmp_path / "docs" / "implementation-results").exists()


# --------------------------------------------------------------------------- #
# E5.3: `aidw tasks --validate` reports malformed entries (roadmap-format.md §10)
# --------------------------------------------------------------------------- #
#
# One malformed entry per rule, with hand-counted lines: `E4.1` (line 3) is before the
# first `## Epic`, `E4.2` is defined twice (lines 8 and 11, so the later one is the issue),
# and `E4.3` (line 14) has no `Done when`. `E4.4` is the clean control under the epic.
MALFORMED_ROADMAP = """# Phase 3: Test Phase

- [ ] **E4.1. Entry outside an epic** text.
  - Done when: outside an epic is reported.

## Epic E4: Defensive Combat

- [ ] **E4.2. Duplicate definition** text.
  - Done when: the duplicate is reported.

- [ ] **E4.2. Duplicate again** text.
  - Done when: the duplicate is reported.

- [ ] **E4.3. No Done when** text.
- [ ] **E4.4. Clean control** text.
  - Done when: the clean entry is quiet.
"""


#: Same task id (`E4.1`) in another phase file — legal, so `--validate` must stay silent.
OTHER_PHASE_ISSUE = """# Phase 7: Zero Phase

## Epic E7: Zero

- [ ] **E7.1. Missing acceptance** text.
  - Notes: no Done when here.
"""


def _init_repo_with_roadmap(path: Path, body: str) -> Path:
    """A temp git repo carrying ``body`` as its only roadmap file (``03 - Test Phase.md``)."""
    _init_repo_with_task(path)
    (path / "docs" / "tasks" / "03 - Test Phase.md").write_text(body, encoding="utf-8")
    return path


def _init_repo_without_roadmap(path: Path) -> Path:
    """A temp git repo with the read-paths but no roadmap directory at all."""
    _init_repo_with_task(path)
    shutil.rmtree(path / "docs" / "tasks")
    return path


def test_tasks_validate_reports_every_issue_on_stdout(
    tmp_path: Path, monkeypatch
) -> None:
    """Every malformation is printed as ``{file}:{line}: {rule} — {message}``, exit 2.

    The report goes to stdout (the `agents validate`/`prompts check` convention) and
    stderr stays empty; an early return after the first issue would fail this vector.
    ``AIDW_STATE_DIR`` is moved out of the tree so the §3.10 layout warning (which every
    in-tree state root gets) does not stand in for validation output on stderr.
    """
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_repo_with_roadmap(tmp_path / "target", MALFORMED_ROADMAP)

    result = runner.invoke(app, ["--repo", str(repo), "tasks", "--validate"])

    assert result.exit_code == EXIT_USAGE, result.output
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert len(lines) == 3, result.stdout
    assert lines[0].startswith("03 - Test Phase.md:3: entry outside an epic — "), lines[0]
    assert lines[1].startswith("03 - Test Phase.md:11: duplicate id — "), lines[1]
    # The duplicate names the earlier definition so the reader can go and fix it.
    assert "03 - Test Phase.md:8" in lines[1]
    assert lines[2].startswith("03 - Test Phase.md:14: missing Done when — "), lines[2]
    # The clean control entry (line 15) is not reported.
    assert ":15:" not in result.stdout


def test_tasks_validate_is_silent_and_zero_on_a_clean_roadmap(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_repo_with_roadmap(tmp_path / "target", ROADMAP_FIXTURE)

    result = runner.invoke(app, ["--repo", str(repo), "tasks", "--validate"])

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert result.stderr == ""


def test_tasks_validate_keeps_the_zero_entry_guard(tmp_path: Path) -> None:
    """No roadmap directory is not a clean pass: the existing stderr guard still refuses."""
    repo = _init_repo_without_roadmap(tmp_path / "target")

    result = runner.invoke(app, ["--repo", str(repo), "tasks", "--validate"])

    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert "no roadmap tasks found" in result.stderr


def test_tasks_validate_glob_selecting_nothing_keeps_the_zero_entry_guard(
    tmp_path: Path,
) -> None:
    """A glob with no matches is also zero entries — refused, never a silent clean pass."""
    repo = _init_repo_with_roadmap(tmp_path / "target", MALFORMED_ROADMAP)
    _write_target_config(
        repo, "schema_version: 1\npaths:\n  roadmap_glob: \"no-such-*.md\"\n"
    )

    result = runner.invoke(app, ["--repo", str(repo), "tasks", "--validate"])

    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert "no roadmap tasks found" in result.stderr


def test_tasks_validate_ignores_filters(tmp_path: Path, monkeypatch) -> None:
    """``--phase`` cannot narrow the report: an issue in another phase is still reported.

    The malformed entry is in the ``00`` file while the filter selects ``03``; a filtered
    validation would print nothing and exit 0, silently missing the issue.
    """
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_repo_with_task(tmp_path / "target")
    _write_roadmap(
        repo / "docs" / "tasks",
        {
            "00 - Zero Phase.md": OTHER_PHASE_ISSUE,
            "03 - Test Phase.md": ROADMAP_FIXTURE,
        },
    )

    result = runner.invoke(
        app, ["--repo", str(repo), "tasks", "--validate", "--phase", "03"]
    )

    assert result.exit_code == EXIT_USAGE, result.output
    assert result.stderr == ""
    assert result.stdout.startswith("00 - Zero Phase.md:5: missing Done when — ")
    assert "03 - Test Phase.md" not in result.stdout


def test_tasks_without_validate_still_lists_a_malformed_roadmap(tmp_path: Path) -> None:
    """``--validate`` is additive: the existing listing path is unchanged (and exit 0)."""
    repo = _init_repo_with_roadmap(tmp_path / "target", MALFORMED_ROADMAP)

    result = runner.invoke(app, ["--repo", str(repo), "tasks"])

    assert result.exit_code == 0, result.output
    assert "E4.1" in result.stdout
    assert "E4.4" in result.stdout
    assert "missing Done when" not in result.stdout


def test_tasks_validate_fails_closed_on_a_broken_config(
    tmp_path: Path, monkeypatch
) -> None:
    """Validation uses the tasks command's config refusal, not silent defaults."""
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_repo_with_roadmap(tmp_path / "target", ROADMAP_FIXTURE)
    _write_target_config(repo, "{{ not yaml: [")

    result = runner.invoke(app, ["--repo", str(repo), "tasks", "--validate"])

    assert result.exit_code == EXIT_STAGE_FAILURE
    assert result.stdout == ""
    assert "cannot read/parse config" in result.stderr
    assert "no roadmap tasks found" not in result.stderr


# --------------------------------------------------------------------------- #
# `prompts check`/`list`: toolkit defaults vs resolved repo prompts (E7.5, §3.6)
# --------------------------------------------------------------------------- #


def _init_prompt_target(path: Path, overrides: dict[str, str] | None = None) -> Path:
    """A temp git repo, optionally carrying ``<path>/aidw/prompts/<rel>`` overrides."""
    _init_repo(path)
    for rel, text in (overrides or {}).items():
        target = path / "aidw" / "prompts" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return path


def test_prompts_check_is_self_hosted_green_and_reports_both_groups(
    tmp_path: Path, monkeypatch
) -> None:
    """From a repo with no ``aidw/prompts/``, every prompt is a toolkit default (§3.6).

    ``prompts check`` shares the ``agents validate``/``prompts check`` stdout report
    convention, so the two group headings and one provenance line per required prompt are
    the contract — plus exit 0, which is what the AGENTS.md gate invokes.
    """
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_prompt_target(tmp_path / "target")

    result = runner.invoke(app, ["--repo", str(repo), "prompts", "check"])

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert result.stdout.startswith("prompts check — toolkit defaults (")
    assert "prompts check — resolved repo prompts (target: " in result.stdout
    assert str(repo.resolve()) in result.stdout
    for name in inventory.REQUIRED_PROMPTS:
        assert f"  {name} -> prompts/{name} (toolkit default)" in result.stdout
    assert "toolkit defaults: 0 error(s), 0 warning(s)" in result.stdout
    assert "resolved repo prompts: 0 error(s), 0 warning(s)" in result.stdout


def test_prompts_check_reports_a_target_shadow_as_a_resolved_repo_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_prompt_target(
        tmp_path / "target", {"code-review.md": "# repo review\n"}
    )

    result = runner.invoke(app, ["--repo", str(repo), "prompts", "check"])

    assert result.exit_code == 0, result.output
    assert (
        "  code-review.md -> aidw/prompts/code-review.md (repo override)"
        in result.stdout
    )
    # The shadow does not affect the other names' provenance.
    assert "  test.md -> prompts/test.md (toolkit default)" in result.stdout


def test_prompts_check_surfaces_a_foreign_reference_in_a_target_override(
    tmp_path: Path, monkeypatch
) -> None:
    """A target-side sentinel is a target-labelled ERROR and a non-zero exit."""
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_prompt_target(
        tmp_path / "target", {"notes.md": "see .pi/prompts/notes.md\n"}
    )

    result = runner.invoke(app, ["--repo", str(repo), "prompts", "check"])

    assert result.exit_code == EXIT_STAGE_FAILURE, result.output
    assert result.stderr == ""
    assert "aidw/prompts/notes.md" in result.stdout
    assert "target repo" in result.stdout
    # The group counts stay per-group: the defaults half is still clean.
    assert "toolkit defaults: 0 error(s), 0 warning(s)" in result.stdout
    assert "resolved repo prompts: 1 error(s), 0 warning(s)" in result.stdout


def test_prompts_check_reports_both_groups_when_the_target_halves_differ(
    tmp_path: Path, monkeypatch
) -> None:
    """A target-side error does not suppress the resolved provenance report."""
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_prompt_target(
        tmp_path / "target", {"code-review.md": "see .pi/prompts/x.md\n"}
    )

    result = runner.invoke(app, ["--repo", str(repo), "prompts", "check"])

    assert result.exit_code == EXIT_STAGE_FAILURE
    assert "resolved repo prompts" in result.stdout
    for name in inventory.REQUIRED_PROMPTS:
        assert f"  {name} -> " in result.stdout


def test_prompts_check_keeps_a_missing_default_and_target_error_in_separate_groups(
    tmp_path: Path, monkeypatch
) -> None:
    """A missing toolkit default and a target sentinel must both reach stdout."""
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_prompt_target(
        tmp_path / "target", {"code-review.md": "see .pi/prompts/notes.md\n"}
    )

    fake_toolkit = tmp_path / "toolkit"
    shutil.copytree(toolkit_root() / "prompts", fake_toolkit / "prompts")
    (fake_toolkit / "prompts" / "code-review.md").unlink()
    fake_paths = ToolkitPaths(
        root=fake_toolkit,
        prompts_dir=fake_toolkit / "prompts",
        agent_configs_dir=fake_toolkit / "agent-configs",
        agents_dir=fake_toolkit / "agents",
        scripts_dir=fake_toolkit / "prompts" / "scripts",
    )
    monkeypatch.setattr(
        ToolkitPaths, "resolve", classmethod(lambda cls: fake_paths)
    )

    result = runner.invoke(app, ["--repo", str(repo), "prompts", "check"])

    assert result.exit_code == EXIT_STAGE_FAILURE, result.output
    assert "toolkit defaults: 1 error(s), 0 warning(s)" in result.stdout
    assert "error: code-review.md: required prompt/script missing" in result.stdout
    assert "resolved repo prompts: 1 error(s), 0 warning(s)" in result.stdout
    assert "error: aidw/prompts/code-review.md:" in result.stdout


def test_prompts_list_prints_the_toolkit_and_the_target_override_trees(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_prompt_target(
        tmp_path / "target",
        {"code-review.md": "# repo review\n", "repo-only.md": "# repo extra\n"},
    )

    result = runner.invoke(app, ["--repo", str(repo), "prompts", "list"])

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert "toolkit defaults (" in result.stdout
    assert "  scripts/review-followup/review_followup.py" in result.stdout
    assert f"resolved repo prompts (target: {repo.resolve()}):" in result.stdout
    assert "  code-review.md -> aidw/prompts/code-review.md (repo override)" in result.stdout
    assert "  test.md -> prompts/test.md (toolkit default)" in result.stdout
    assert "repo overrides (" in result.stdout
    assert "  aidw/prompts/code-review.md (shadows a required prompt)" in result.stdout
    # A repo-added prompt file is listed too, marked as not shadowing anything.
    assert "  aidw/prompts/repo-only.md\n" in result.stdout


def test_prompts_list_marks_only_the_direct_shadow_child(
    tmp_path: Path, monkeypatch
) -> None:
    """A nested same-basename file never carries the shadow marker.

    `resolve_prompt` searches only the direct child ``<target>/aidw/prompts/<name>``
    (§3.6), so a nested ``extra/code-review.md`` is an ordinary repo-added file —
    printing the marker on it would disagree with what the stage runner runs
    (review follow-up #120).
    """
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_prompt_target(
        tmp_path / "target",
        {
            "code-review.md": "# direct shadow\n",
            "extra/code-review.md": "# nested same-basename file\n",
        },
    )

    result = runner.invoke(app, ["--repo", str(repo), "prompts", "list"])

    assert result.exit_code == 0, result.output
    # The direct child shadows and is marked; the nested same-basename file is not.
    assert "  aidw/prompts/code-review.md (shadows a required prompt)\n" in result.stdout
    assert "  aidw/prompts/extra/code-review.md\n" in result.stdout
    assert "(shadows a required prompt)" not in result.stdout.split(
        "aidw/prompts/extra/code-review.md", 1
    )[1].splitlines()[0]


def test_prompts_list_without_target_overrides_says_so(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AIDW_STATE_DIR", str(tmp_path / "state"))
    repo = _init_prompt_target(tmp_path / "target")

    result = runner.invoke(app, ["--repo", str(repo), "prompts", "list"])

    assert result.exit_code == 0, result.output
    assert "repo overrides (" in result.stdout
    assert "  none" in result.stdout


def test_prompts_rejects_an_unknown_action_before_resolving_a_target() -> None:
    result = runner.invoke(app, ["prompts", "nonsense"])

    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert "unknown action: nonsense" in result.stderr
