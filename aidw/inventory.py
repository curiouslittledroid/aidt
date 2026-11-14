"""Prompt and helper-script inventory (design §7.2, EXTRACTION.md §3.6).

``<toolkit>/prompts/`` is **AIDT's own**: it is the source of truth for every workflow and
is edited freely. It is not mirrored from, synced to, or compared with any other directory.

The inventory has two independent halves (E7.5):

- :func:`check_defaults` — the toolkit's own tree. Every ``REQUIRED_PROMPTS`` and
  ``REQUIRED_SCRIPTS`` entry is present, nothing references ``.pi/prompts``
  (:data:`FOREIGN_PREFIX`), a script-invoking prompt locates the bundled script through
  ``AIDW_SCRIPTS_DIR``, and the legacy ``VENDOR.md`` manifest is warned about.
- :func:`check_resolved` — what a *target* repo actually runs. Each required prompt is
  resolved through :func:`aidw.runner.resolve_prompt` (never a second copy of §3.6's
  shadow/default order), its provenance is recorded, and the target's
  ``aidw/prompts/*.md`` overrides — which the defaults half never sees — get the same
  sentinel and ``AIDW_SCRIPTS_DIR`` sweeps.

Scripts stay toolkit-side (§3.6): ``REQUIRED_SCRIPTS`` belongs to the defaults half only,
because a target has no ``prompts/scripts/`` tree to shadow them with. A failure in one
half never suppresses the other (E7.5 requirement 6): the two functions share no state and
each reports the issues it owns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aidw.config import ERROR, WARNING, Issue
from aidw.paths import SCRIPTS_DIR_ENV_VAR
from aidw.runner import resolve_prompt

PROMPTS_SUBDIR = ("prompts",)

#: Where a target repo shadows toolkit prompts by filename (EXTRACTION.md §3.6, D14).
TARGET_PROMPTS_SUBDIR = ("aidw", "prompts")

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
    "summarize-implementation-results.md",
    "update-roadmap.md",
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

#: AIDT is self-contained: nothing under ``<toolkit>/prompts`` may reference the old tree.
FOREIGN_PREFIX = ".pi/prompts"

#: Prompts that invoke a bundled helper script, mapped to the script they need. The
#: invocation must locate the script through the runner-provided ``AIDW_SCRIPTS_DIR``
#: (an absolute toolkit path). A path relative to the working directory — the old
#: ``python3 prompts/scripts/...`` — resolves inside the *target* repository and
#: fails as soon as the toolkit is its own checkout (EXTRACTION.md §3.6).
PROMPT_INVOKED_SCRIPTS = {
    "review-findings-to-github.md": "scripts/review-followup/publish_review_followups.py",
    "approve-review-followups.md": "scripts/review-followup/review_followup.py",
    "fix-next-review-followup.md": "scripts/review-followup/review_followup.py",
}

#: Provenance labels for a resolved prompt (§3.6 precedence levels 2 and 3).
ORIGIN_TARGET = "target"
ORIGIN_TOOLKIT = "toolkit"

#: Human labels for the same two levels, used by ``prompts check``/``prompts list``.
ORIGIN_LABELS = {ORIGIN_TARGET: "repo override", ORIGIN_TOOLKIT: "toolkit default"}


@dataclass(frozen=True)
class ResolvedPrompt:
    """One required prompt as it resolves for a target repo, with its provenance.

    ``path`` is the resolved file :func:`aidw.runner.resolve_prompt` returns — the same
    file the stage runner hands to Pi, so the report cannot disagree with what runs.
    ``display`` is deliberately *relative to the root it came from*: a target shadow and
    the toolkit default share the basename ``code-review.md``, and printing two bare
    filenames would make "which is which" unreadable (E7.5 trap).
    """

    name: str
    path: Path
    origin: str

    @property
    def display(self) -> str:
        if self.origin == ORIGIN_TARGET:
            return f"{'/'.join(TARGET_PROMPTS_SUBDIR)}/{self.name}"
        return f"{'/'.join(PROMPTS_SUBDIR)}/{self.name}"

    @property
    def label(self) -> str:
        return ORIGIN_LABELS[self.origin]


@dataclass(frozen=True)
class ResolvedInventory:
    """The resolved half's two answers: provenance for every name, plus its issues."""

    prompts: tuple[ResolvedPrompt, ...]
    issues: tuple[Issue, ...]


def prompts_dir(toolkit_root: Path) -> Path:
    return toolkit_root.joinpath(*PROMPTS_SUBDIR)


def resolved_prompts_dir(target_root: Path) -> Path:
    """``<target>/aidw/prompts/`` — the §3.6 override tree (may not exist)."""
    return target_root.joinpath(*TARGET_PROMPTS_SUBDIR)


def list_files(toolkit_root: Path) -> list[str]:
    """Every prompt/script file AIDT owns, relative to ``<toolkit>/prompts/``."""
    root = prompts_dir(toolkit_root)
    if not root.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != LEGACY_MANIFEST
    )


def target_prompt_files(target_root: Path) -> list[Path]:
    """Every ``.md`` under ``<target>/aidw/prompts/``, sorted.

    The whole override tree is swept — not just the names that shadow a required prompt —
    because a repo-added or explicitly-declared prompt file lives there too, and a
    ``.pi/prompts`` reference in it fails exactly the same way at Pi invocation time.
    """
    root = resolved_prompts_dir(target_root)
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.rglob("*.md") if path.is_file()
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def check_defaults(toolkit_root: Path) -> list[Issue]:
    """Validate the toolkit's own prompts/scripts (design §7.2).

    Behaviour is unchanged from the pre-E7.5 ``check``: required files present, the
    ``.pi/prompts`` sentinel over every ``.md``/``.py``/``.json`` file, the legacy
    ``VENDOR.md`` warning, and ``AIDW_SCRIPTS_DIR`` in every script-invoking prompt.
    """
    issues: list[Issue] = []
    root = prompts_dir(toolkit_root)
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
                "legacy mirror manifest; prompts is independent now — delete it",
            )
        )

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == LEGACY_MANIFEST:
            continue
        if path.suffix not in (".md", ".py", ".json"):
            continue
        rel = path.relative_to(root).as_posix()
        text = _read_text(path)
        if text is None:
            continue
        if FOREIGN_PREFIX in text:
            issues.append(
                Issue(ERROR, rel, f"references `{FOREIGN_PREFIX}`, outside aidt/")
            )

    for prompt in PROMPT_INVOKED_SCRIPTS:
        path = root / prompt
        if not path.is_file():
            continue
        text = _read_text(path)
        if text is None:
            continue
        if SCRIPTS_DIR_ENV_VAR not in text:
            issues.append(
                Issue(
                    ERROR,
                    prompt,
                    f"must locate the bundled script via `{SCRIPTS_DIR_ENV_VAR}`, "
                    "not a path relative to the target repository",
                )
            )

    return issues


def check_resolved(toolkit_root: Path, target_root: Path) -> ResolvedInventory:
    """Resolve every required prompt for ``target_root`` and sweep its overrides.

    Per name in :data:`REQUIRED_PROMPTS`, the file is resolved by
    :func:`aidw.runner.resolve_prompt`, so this report names the same file the stage
    runner will run — a second implementation of §3.6's precedence would drift and let the
    check pass while a stage reads a different prompt (E7.5 trap).

    Target-side issues are labelled with the target-relative ``aidw/prompts/…`` path so
    they are never confused with the toolkit default of the same basename. A required
    prompt that resolves nowhere is one ERROR whose message names every location searched.

    Scripts are not part of this half (§3.6: they stay with the toolkit), and a prompt
    that resolved to the toolkit default is never re-swept here — :func:`check_defaults`
    already owns it, and re-reading it would double-count its issues.

    Performs no writes and no process spawns: :func:`resolve_prompt` is a leaf of
    ``Path`` existence checks, and everything else is a read.
    """
    issues: list[Issue] = []
    prompts: list[ResolvedPrompt] = []
    root = resolved_prompts_dir(target_root)

    for name in REQUIRED_PROMPTS:
        try:
            path = resolve_prompt(toolkit_root, target_root, name)
        except FileNotFoundError as exc:
            # The resolver's message lists both searched locations (§3.6's two levels).
            issues.append(Issue(ERROR, f"{'/'.join(TARGET_PROMPTS_SUBDIR)}/{name}", str(exc)))
            continue
        origin = ORIGIN_TARGET if path == (root / name).resolve() else ORIGIN_TOOLKIT
        prompts.append(ResolvedPrompt(name=name, path=path, origin=origin))

    for path in target_prompt_files(target_root):
        # The label is target-relative, mirroring the toolkit half's prompts-relative one.
        rel = f"{'/'.join(TARGET_PROMPTS_SUBDIR)}/{path.relative_to(root).as_posix()}"
        text = _read_text(path)
        if text is None:
            continue
        if FOREIGN_PREFIX in text:
            issues.append(
                Issue(
                    ERROR,
                    rel,
                    f"references `{FOREIGN_PREFIX}`, outside the target repo's "
                    "`aidw/prompts/` overrides",
                )
            )
        # Keyed off the basename: a shadowed script-invoking prompt runs the bundled
        # toolkit script, so it still needs the runner-provided absolute path.
        if (
            path.parent == root
            and path.name in PROMPT_INVOKED_SCRIPTS
            and SCRIPTS_DIR_ENV_VAR not in text
        ):
            issues.append(
                Issue(
                    ERROR,
                    rel,
                    f"must locate the bundled script via `{SCRIPTS_DIR_ENV_VAR}`, "
                    "not a path relative to the target repository",
                )
            )

    return ResolvedInventory(prompts=tuple(prompts), issues=tuple(issues))
