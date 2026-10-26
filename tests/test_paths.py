"""Tests for toolkit-root and target-repository path resolution (E0.4/E1.4).

The toolkit root resolves from the installed package location; the target repository
root resolves from git. The two are independent: the toolkit is installed outside any
product checkout (see ``docs/migration/EXTRACTION.md`` §3.1). Run state no longer lives
under the toolkit root (E1.4 / §3.10), so the old ``aidt_root``/``runs_dir`` aliases and
their names are gone.
"""

from __future__ import annotations

from pathlib import Path

from aidw import paths
from aidw.paths import repo_root, toolkit_root


def test_toolkit_root_holds_the_shipped_assets() -> None:
    root = toolkit_root()
    assert root.is_dir()
    assert (root / "aidw").is_dir()
    assert (root / "prompts").is_dir()
    assert (root / "agent-configs").is_dir()
    assert (root / "agents").is_dir()
    assert (root / "pyproject.toml").is_file()


def test_toolkit_root_is_the_package_parent() -> None:
    package_file = Path(paths.__file__).resolve()
    assert toolkit_root() == package_file.parent.parent


def test_toolkit_root_matches_repo_root_in_this_checkout() -> None:
    """The toolkit repo's own root *is* the toolkit root: no ``aidt/`` wrapper (§5.2)."""
    assert toolkit_root() == repo_root()
    assert not (repo_root() / "aidt").exists()


def test_toolkit_root_is_independent_of_cwd(monkeypatch, tmp_path: Path) -> None:
    expected = toolkit_root()
    monkeypatch.chdir(tmp_path)
    assert toolkit_root() == expected


def test_repo_root_from_explicit_start() -> None:
    assert repo_root(Path(__file__).parent) == repo_root()


def test_no_old_helper_names_survive_under_aidw() -> None:
    """The literal E1.4 gate: ``rg "aidt_root|runs_dir" aidw/`` matches nothing.

    Implemented in Python rather than shelling out to ``rg`` so it runs in any CI
    environment. It covers parameter/local names too, not just the deleted functions.
    """
    aidw_dir = toolkit_root() / "aidw"
    offenders: list[str] = []
    for path in sorted(aidw_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for banned in ("aidt_root", "runs_dir"):
            if banned in text:
                offenders.append(f"{path.relative_to(aidw_dir)}: {banned}")
    assert offenders == []
