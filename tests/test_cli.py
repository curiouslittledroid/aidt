"""Phase 0 tests for the AIDW CLI surface, plus E1.4 run-location tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from aidw import __version__, github
from aidw import state as state_mod
from aidw.cli import EXIT_REFUSED, app
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
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _init_repo_with_task(path: Path) -> Path:
    """A tmp git repo carrying the roadmap task ``03 E4 E4.1``."""
    _init_repo(path)
    tasks = path / "docs" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "03 - Test Phase.md").write_text(ROADMAP_FIXTURE, encoding="utf-8")
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


def test_doctor_runs() -> None:
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

    listed = runner.invoke(app, ["--repo", str(tmp_path), "runs", "list"])
    assert listed.exit_code == 0
    assert created.run_id in listed.stdout
    assert not (toolkit_root() / "runs" / created.run_id).exists()

    shown = runner.invoke(app, ["--repo", str(tmp_path), "runs", "show", created.run_id])
    assert shown.exit_code == 0
    assert f"run:      {created.run_id}" in shown.stdout
    assert "workflow: implement" in shown.stdout


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
    prompt.parent.mkdir(parents=True)
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

    def spy_resolve(root: Path, value: str) -> Path:
        resolved.append(root)
        return real_resolve(root, value)

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
