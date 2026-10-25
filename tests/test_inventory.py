"""Tests for the AIDT prompt/script inventory (design §7)."""

from __future__ import annotations

from pathlib import Path

from aidw import inventory
from aidw.config import ERROR, WARNING
from aidw.paths import aidt_root


def test_real_inventory_is_complete() -> None:
    issues = inventory.check(aidt_root())
    errors = [issue for issue in issues if issue.level == ERROR]
    assert errors == [], errors


def test_real_inventory_has_no_legacy_manifest() -> None:
    issues = inventory.check(aidt_root())
    assert not any(issue.source == inventory.LEGACY_MANIFEST for issue in issues)


def test_list_files_includes_known_prompts() -> None:
    files = inventory.list_files(aidt_root())
    assert "code-review.md" in files
    assert "scripts/review-followup/review_followup.py" in files


def test_missing_prompts_dir_is_error(tmp_path: Path) -> None:
    issues = inventory.check(tmp_path / "aidt")
    assert issues and issues[0].level == ERROR


def test_missing_required_prompt_is_error(tmp_path: Path) -> None:
    root = tmp_path / "aidt" / "prompts"
    root.mkdir(parents=True)
    (root / "task-prompt.md").write_text("ok\n", encoding="utf-8")
    issues = inventory.check(tmp_path / "aidt")
    assert any(
        issue.level == ERROR and issue.source == "code-review.md" for issue in issues
    )


def test_foreign_reference_is_error(tmp_path: Path) -> None:
    root = tmp_path / "aidt" / "prompts"
    root.mkdir(parents=True)
    (root / "notes.md").write_text("see .pi/prompts/x.md\n", encoding="utf-8")
    issues = inventory.check(tmp_path / "aidt")
    assert any(issue.level == ERROR and issue.source == "notes.md" for issue in issues)


def test_foreign_reference_in_python_is_error(tmp_path: Path) -> None:
    root = tmp_path / "aidt" / "prompts"
    root.mkdir(parents=True)
    (root / "helper.py").write_text("# see .pi/prompts/x.md\n", encoding="utf-8")
    issues = inventory.check(tmp_path / "aidt")
    assert any(issue.level == ERROR and issue.source == "helper.py" for issue in issues)


def test_legacy_manifest_is_warning(tmp_path: Path) -> None:
    root = tmp_path / "aidt" / "prompts"
    root.mkdir(parents=True)
    (root / inventory.LEGACY_MANIFEST).write_text("old\n", encoding="utf-8")
    issues = inventory.check(tmp_path / "aidt")
    assert any(
        issue.level == WARNING and issue.source == inventory.LEGACY_MANIFEST
        for issue in issues
    )


def test_prompt_invoking_a_script_must_use_the_env_var(tmp_path: Path) -> None:
    """A cwd-relative script path resolves inside the target repo, not the toolkit."""
    root = tmp_path / "aidt" / "prompts"
    root.mkdir(parents=True)
    (root / "approve-review-followups.md").write_text(
        'runner="python3 aidt/prompts/scripts/review-followup/review_followup.py"\n',
        encoding="utf-8",
    )

    issues = inventory.check(tmp_path / "aidt")

    assert any(
        issue.level == ERROR
        and issue.source == "approve-review-followups.md"
        and inventory.SCRIPTS_DIR_ENV_VAR in issue.message
        for issue in issues
    )
