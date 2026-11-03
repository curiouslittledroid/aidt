"""Consistency checks pinning cross-references inside ``design.md``.

Implements the regression cover for review follow-up PR #40 finding F1 (issue #42):
§17 row H1 must not contradict the blocked-run semantics that §8.1 specifies and
``aidw/workflows/prompt.py::_report_blocked_leftovers`` implements (report, never
repair — design §13).
"""

from __future__ import annotations

from aidw.paths import toolkit_root


def _design_md() -> str:
    return (toolkit_root() / "design.md").read_text(encoding="utf-8")


def _section_17_h1_row(design: str) -> str:
    """Return the single §17 ``| H1 | ... |`` decision row."""
    rows = [line for line in design.splitlines() if line.startswith("| H1 |")]
    assert len(rows) == 1, f"expected exactly one §17 H1 row, found {len(rows)}"
    return rows[0]


def test_blocked_run_row_h1_matches_report_never_repair() -> None:
    """§17 H1 must agree with §8.1: a blocked run reports leftovers, never removes them.

    The trigger (issue #42): H1 claimed a blocked prompt run ends with "no branch left
    behind", contradicting §8.1's "reports, never repairs" paragraph and design §13's
    never-delete-a-branch / never-discard-work invariant — an implementer reading only
    §17 could build branch deletion on top of it.
    """
    design = _design_md()

    h1 = _section_17_h1_row(design)

    # The contradictory claim that a blocked run cleans up after itself.
    assert "no branch left behind" not in h1
    # H1 must instead state the §8.1/§13 semantics: leftovers are reported, not removed.
    assert "reported, never removed" in h1
    # The rest of the original row is untouched by the fix.
    assert "exit 3" in h1
    assert "the author stage itself stays `succeeded`" in h1


def test_section_81_blocked_run_reports_leftovers() -> None:
    """§8.1 keeps the authoritative blocked-run wording H1 must not contradict.

    Pins the §8.1 sentence the H1 rewording was aligned with, so a future edit to
    either side that reintroduces the contradiction fails loudly here.
    """
    design = _design_md()

    # §8.1's blocked-run paragraph, somewhere under the `aidw prompt` heading.
    assert "reports," in design and "never repairs" in design
    assert "an uncommitted change under" in design
    assert "branch that appeared during the run" in design


def _section_83_block(design: str) -> str:
    """The §8.3 ``aidw review`` block: its heading up to the §8.4 heading."""
    start = design.index("### 8.3 `aidw review --pr <n>`")
    end = design.index("### 8.4 ", start)
    return design[start:end]


def test_section_83_review_locates_the_pr_head_worktree() -> None:
    """§8.3 and §17 K1 must state the PR-head-worktree preflight, not the old cwd test.

    The trigger: the pre-E2.6 ``current branch is the PR head`` preflight shipped in
    ``review.py`` while ``implement``/``fix`` resolved worktrees, so ``aidw run
    prompt-to-fix`` exited 4 on the review stage of every worktree run. Decision K1
    replaces it; this pins the design wording to the behaviour so the cwd-driven claim
    cannot quietly return to one side only.
    """
    design = _design_md()

    block = _section_83_block(design)
    assert "the PR head's worktree is located" in block
    assert "current branch is the PR head" not in block
    assert "`git.worktree_for_branch`" in block

    rows = [line for line in design.splitlines() if line.startswith("| K1 |")]
    assert len(rows) == 1, f"expected exactly one §17 K1 row, found {len(rows)}"
    k1 = rows[0]
    assert "exit 4" in k1
    assert "prompt-to-fix" in k1
    assert "PR-head worktree" in k1
