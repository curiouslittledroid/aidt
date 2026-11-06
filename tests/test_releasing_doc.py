"""Contract tests for the release and target-pin documentation (E8.5, D9/D10)."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
RELEASE_DOC = ROOT / "docs" / "releasing.md"
README = ROOT / "README.md"


def test_release_doc_records_the_version_tag_and_install_contract() -> None:
    """The release runbook keeps the operator-visible D9 contract copy-pasteable."""
    text = RELEASE_DOC.read_text(encoding="utf-8")

    assert 'pyproject.toml` → `[project].version' in text
    assert "`aidw/__init__.py` → `__version__`" in text
    assert "`tests/test_packaging.py` → `test_pyproject_identity_is_the_settled_name_version_and_script`" in text
    assert "MAJOR.MINOR.PATCH" in text
    assert "`aidw --version` and `aidw doctor` are **the release smoke checks**" in text

    assert "`v<X.Y.Z>`" in text
    assert 'git tag -a v0.1.0 -m "AIDT v0.1.0"' in text
    assert "git push origin v0.1.0" in text
    assert 'uv tool install "git+https://github.com/curiouslittledroid/aidt@v0.1.0"' in text
    assert 'uvx --from "git+https://github.com/curiouslittledroid/aidt@v0.1.0" aidw --version' in text
    assert "git+file:///path/to/scratch-clone@v0.1.0" in text
    assert "From a clean tool venv" in text


def test_release_doc_describes_the_pin_refusal_and_deliberate_upgrade() -> None:
    """The pin guidance distinguishes PEP 440 compatibility from schema compatibility."""
    text = RELEASE_DOC.read_text(encoding="utf-8")

    assert 'requires_toolkit: ">=0.1.0"' in text
    assert "PEP 440 specifier" in text
    assert "`packaging`" in text
    assert "aidw/target_config.py:check_compatibility" in text
    assert "refuses to run" in text
    assert 'requires_toolkit: ">=99.0.0"' in text
    assert "schema_version" in text
    assert "docs/target-repo-config.md" in text
    assert "Upgrade deliberately" in text
    assert "Only after they pass, bump" in text
    assert "`requires_toolkit` to the release you just verified" in text


def test_readme_install_points_to_the_first_release_without_erasing_the_verbatim_tag_caveat() -> None:
    """README Install exposes both D9 forms and links the release runbook."""
    text = README.read_text(encoding="utf-8")

    assert "no release tag exists yet" not in text
    assert "[`docs/releasing.md`](./docs/releasing.md)" in text
    assert 'aidt@v0.1.0"' in text
    assert "uvx --from" in text
    assert "`baseline-verbatim` tag marks the verbatim import, not a release." in text
    assert "@<tag>" not in text
