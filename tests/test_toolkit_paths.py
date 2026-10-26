"""Contract tests for ``ToolkitPaths`` (E1.2, EXTRACTION.md §3.1/§3.3/§3.12).

The toolkit root resolves from the installed package location, never from git or the
working directory, so a workflow always finds the toolkit's default prompts, agent
configs, agents and bundled scripts regardless of where it is invoked. ``ToolkitPaths``
is deliberately a different type from ``TargetRepo`` so toolkit-relative and
target-relative paths can never be interchanged. The doctor check that reports this root
must survive the ``repo_root()`` refusal when AIDW runs from ``/tmp``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from aidw import doctor, paths
from aidw.paths import TargetRepo, ToolkitPaths, toolkit_root


def _named(checks: list[doctor.Check], name: str) -> doctor.Check:
    return next(check for check in checks if check.name == name)


@pytest.fixture(autouse=True)
def _stub_external_clis(fake_external_clis: None) -> None:  # noqa: ARG001
    """The checks asserted here are about paths, not the ``pi``/``gh`` probes."""


# ---------------------------------------------------------------------------
# Resolution: cwd- and git-independent (Requirements 2-3)
# ---------------------------------------------------------------------------


def test_resolve_is_cwd_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = ToolkitPaths.resolve()
    monkeypatch.chdir(tmp_path)

    resolved = ToolkitPaths.resolve()

    assert resolved.root == toolkit_root()
    assert resolved.root == expected.root
    for path in (
        resolved.root,
        resolved.prompts_dir,
        resolved.agent_configs_dir,
        resolved.agents_dir,
        resolved.scripts_dir,
    ):
        assert path.is_absolute()
        assert path == path.resolve()


@pytest.mark.parametrize("depth", [0, 1, 3, 6])
def test_resolution_is_invariant_to_cwd_depth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, depth: int
) -> None:
    """Metamorphic: nesting the cwd deeper must not change any resolved path."""
    expected = ToolkitPaths.resolve()
    nested = tmp_path.joinpath(*["d"] * depth)
    nested.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(nested)

    assert ToolkitPaths.resolve() == expected


def test_resolve_never_consults_git_or_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare ``tmp_path`` has no ``.git``; resolution must not reach for one."""
    monkeypatch.chdir(tmp_path)

    def _forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("ToolkitPaths.resolve() must not consult the target repo")

    class _NoSubprocess:
        @staticmethod
        def run(*args: object, **kwargs: object) -> object:
            raise AssertionError("ToolkitPaths.resolve() must not spawn a subprocess")

    monkeypatch.setattr(paths, "repo_root", _forbidden)
    monkeypatch.setattr(paths, "subprocess", _NoSubprocess)

    assert ToolkitPaths.resolve().root == toolkit_root()


# ---------------------------------------------------------------------------
# Dir derivation (Requirement 4)
# ---------------------------------------------------------------------------


def test_scripts_dir_is_under_prompts_dir() -> None:
    resolved = ToolkitPaths.resolve()
    assert resolved.scripts_dir == resolved.prompts_dir / "scripts"


def test_dirs_point_at_the_real_shipped_assets() -> None:
    resolved = ToolkitPaths.resolve()
    assert (resolved.prompts_dir / "task-prompt.md").is_file()
    assert list(resolved.agent_configs_dir.glob("*.yaml"))
    assert [child for child in resolved.agents_dir.iterdir() if child.is_dir()]
    assert (resolved.scripts_dir / "review-followup").is_dir()


def test_fields_are_exactly_the_five_contract_fields() -> None:
    names = [field.name for field in dataclasses.fields(ToolkitPaths)]
    assert names == ["root", "prompts_dir", "agent_configs_dir", "agents_dir", "scripts_dir"]


def test_resolve_is_pure_and_repeatable() -> None:
    first = ToolkitPaths.resolve()
    second = ToolkitPaths.resolve()
    assert first == second
    assert first is not second


def test_resolve_is_frozen_and_immutable() -> None:
    resolved = ToolkitPaths.resolve()
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolved.root = Path("/tmp")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Type distinctness (Requirement 1; §3.1 "use two distinct types")
# ---------------------------------------------------------------------------


def test_toolkitpaths_is_a_distinct_type_from_targetrepo() -> None:
    assert ToolkitPaths is not TargetRepo
    assert not issubclass(ToolkitPaths, TargetRepo)
    assert not issubclass(TargetRepo, ToolkitPaths)

    toolkit_fields = {field.name for field in dataclasses.fields(ToolkitPaths)}
    target_fields = {field.name for field in dataclasses.fields(TargetRepo)}
    assert toolkit_fields == {
        "root",
        "prompts_dir",
        "agent_configs_dir",
        "agents_dir",
        "scripts_dir",
    }
    # TargetRepo's shape is untouched by this task.
    assert target_fields == {"root", "git_dir", "common_dir", "base_branch"}
    assert toolkit_fields != target_fields


# ---------------------------------------------------------------------------
# Doctor reporting (Requirement 6)
# ---------------------------------------------------------------------------


def test_doctor_reports_toolkit_root_from_a_non_repo_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    checks = doctor.collect_checks()

    toolkit = _named(checks, "toolkit root")
    assert toolkit.status == doctor.OK
    assert str(ToolkitPaths.resolve().root) in toolkit.detail
    # The check survives the repo_root() refusal, and is ordered before it.
    assert _named(checks, "repo root").status == doctor.FAIL
    names = [check.name for check in checks]
    assert names.index("toolkit root") < names.index("repo root")


def test_doctor_toolkit_root_fails_when_workflow_assets_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root with none of the asset dirs is a FAIL, not a silent OK."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "toolkit_root", lambda: tmp_path)

    toolkit = _named(doctor.collect_checks(), "toolkit root")

    assert toolkit.status == doctor.FAIL
    assert str(tmp_path) in toolkit.detail
    assert "missing: prompts, scripts, agent-configs, agents" in toolkit.detail


def test_doctor_toolkit_root_fails_when_root_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "missing-toolkit"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "toolkit_root", lambda: root)

    toolkit = _named(doctor.collect_checks(), "toolkit root")

    assert toolkit.status == doctor.FAIL
    assert toolkit.detail == f"{root} (missing: root, prompts, scripts, agent-configs, agents)"


def test_doctor_toolkit_root_warns_when_only_advisory_dirs_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "toolkit"
    (root / "prompts" / "scripts").mkdir(parents=True)
    (root / "agent-configs").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "toolkit_root", lambda: root)

    toolkit = _named(doctor.collect_checks(), "toolkit root")

    assert toolkit.status == doctor.WARN
    assert toolkit.detail == f"{root} (missing: agents)"


def test_doctor_toolkit_root_warns_when_both_advisory_dirs_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "toolkit"
    (root / "prompts" / "scripts").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "toolkit_root", lambda: root)

    toolkit = _named(doctor.collect_checks(), "toolkit root")

    assert toolkit.status == doctor.WARN
    assert toolkit.detail == f"{root} (missing: agent-configs, agents)"


def test_doctor_toolkit_root_fails_when_prompts_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "toolkit"
    root.mkdir()
    (root / "agent-configs").mkdir()
    (root / "agents").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "toolkit_root", lambda: root)

    toolkit = _named(doctor.collect_checks(), "toolkit root")

    assert toolkit.status == doctor.FAIL
    assert toolkit.detail == f"{root} (missing: prompts, scripts)"


def test_doctor_toolkit_root_fails_when_scripts_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "toolkit"
    (root / "prompts").mkdir(parents=True)
    (root / "agent-configs").mkdir()
    (root / "agents").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "toolkit_root", lambda: root)

    toolkit = _named(doctor.collect_checks(), "toolkit root")

    assert toolkit.status == doctor.FAIL
    assert toolkit.detail == f"{root} (missing: scripts)"


def test_doctor_toolkit_root_fails_closed_when_resolution_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def unavailable_root() -> Path:
        raise RuntimeError("package location unavailable")

    monkeypatch.setattr(paths, "toolkit_root", unavailable_root)

    toolkit = _named(doctor.collect_checks(), "toolkit root")

    assert toolkit.status == doctor.FAIL
    assert toolkit.detail == "unresolved: package location unavailable"
