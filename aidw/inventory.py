"""Prompt and helper-script inventory (design §7).

``aidt/prompts/`` is **AIDT's own**: it is the source of truth for every workflow and is
edited freely. It is not mirrored from, synced to, or compared with any other directory.

This module only asserts that the inventory the workflows depend on is present and
self-contained, so a deleted or renamed prompt fails loudly here instead of at Pi
invocation time.
"""

from __future__ import annotations

from pathlib import Path

from aidw.config import ERROR, WARNING, Issue

PROMPTS_SUBDIR = ("prompts",)

#: Left over from the old mirror model; AIDT no longer tracks a canonical source.
LEGACY_MANIFEST = "VENDOR.md"

#: Prompts the workflows invoke (design §8). Keep in step with the workflow modules.
REQUIRED_PROMPTS = (
    "task-prompt.md",
    "task-review.md",
    "task-review-fixes.md",
    "impliment-task.md",
    "test.md",
    "update-traceability.md",
    "update-architecture.md",
    "record-implementation-results.md",
    "pr.md",
    "code-review.md",
    "review-findings-to-github.md",
    "approve-review-followups.md",
    "fix-next-review-followup.md",
)

#: Helper scripts the review/fix prompts invoke.
REQUIRED_SCRIPTS = (
    "scripts/review-followup/review_followup.py",
    "scripts/review-followup/publish_review_followups.py",
    "scripts/review-followup/constants.py",
    "scripts/review-followup/proc.py",
    "scripts/review-followup/gh.py",
    "scripts/review-followup/logic.py",
)

#: AIDT is self-contained: nothing under ``aidt/prompts`` may reference the old tree.
FOREIGN_PREFIX = ".pi/prompts"


def prompts_dir(aidt_root: Path) -> Path:
    return aidt_root.joinpath(*PROMPTS_SUBDIR)


def list_files(aidt_root: Path) -> list[str]:
    """Every prompt/script file AIDT owns, relative to ``aidt/prompts/``."""
    root = prompts_dir(aidt_root)
    if not root.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != LEGACY_MANIFEST
    )


def check(aidt_root: Path) -> list[Issue]:
    """Validate that the required prompts/scripts exist and stay inside ``aidt/``."""
    issues: list[Issue] = []
    root = prompts_dir(aidt_root)
    if not root.is_dir():
        return [Issue(ERROR, str(root), "prompts directory not found")]

    for rel in (*REQUIRED_PROMPTS, *REQUIRED_SCRIPTS):
        if not (root / rel).is_file():
            issues.append(Issue(ERROR, rel, "required prompt/script missing"))

    if (root / LEGACY_MANIFEST).is_file():
        issues.append(
            Issue(
                WARNING,
                LEGACY_MANIFEST,
                "legacy mirror manifest; aidt/prompts is independent now — delete it",
            )
        )

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == LEGACY_MANIFEST:
            continue
        if path.suffix not in (".md", ".py", ".json"):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if FOREIGN_PREFIX in text:
            issues.append(
                Issue(ERROR, rel, f"references `{FOREIGN_PREFIX}`, outside aidt/")
            )

    return issues
