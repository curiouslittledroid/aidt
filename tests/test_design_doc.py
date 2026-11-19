"""Consistency checks pinning cross-references inside ``design.md``.

Implements the regression cover for review follow-up PR #40 finding F1 (issue #42):
§17 row H1 must not contradict the blocked-run semantics that §8.1 specifies and
``aidw/workflows/prompt.py::_report_blocked_leftovers`` implements (report, never
repair — design §13).
"""

from __future__ import annotations

import re

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


def _section_86_block(design: str) -> str:
    """The §8.6 ``aidw run`` block: its heading up to the §9 separator."""
    start = design.index("### 8.6 `aidw run <workflow>` (orchestrator)")
    end = design.index("\n---\n", start)
    return design[start:end]


def test_section_86_chain_ends_gracefully_when_review_published_nothing() -> None:
    """§8.6 and §17 I2 must state the graceful end, not only the auto-approval.

    The trigger: an ``Approve`` review published no follow-ups, yet ``prompt-to-fix`` ran
    ``fix``, whose entry stage failed closed on a missing review-follow-up parent issue —
    a red run for a review that had approved. Decision I2 ends the chain at exit 0; this
    pins the design wording (and the recorded marker it reads) to that behaviour.
    """
    design = _design_md()

    block = _section_86_block(design)
    assert "followups_published" in block
    assert "chain complete." in block
    assert "exit 0" in block

    rows = [line for line in design.splitlines() if line.startswith("| I2 |")]
    assert len(rows) == 1, f"expected exactly one §17 I2 row, found {len(rows)}"
    i2 = rows[0]
    assert "exit 0" in i2
    assert "followups_published" in i2
    assert "No review-follow-up parent issue found" in i2


def _section_84_block(design: str) -> str:
    """The §8.4 ``aidw fix`` block: its heading up to the §8.5 heading."""
    start = design.index("### 8.4 `aidw fix --pr <n>`")
    end = design.index("### 8.5 ", start)
    return design[start:end]


def test_section_84_fix_publishes_its_own_work() -> None:
    """05-P1.1: the "no stage of `fix` commits" claim is reversed, not left contradicting.

    The reversal is the whole point of the task: `F1` closes each issue as `Status: fixed`,
    so a `fix` run that never committed reported work done that never reached the PR. The
    design must name the new stage, its position and its four-case no-op boundary, and must
    no longer assert that no stage of `fix` commits.
    """
    design = _design_md()

    block = _section_84_block(design)
    assert "→ F5 commit-and-push" in block
    assert "`F5 commit-and-push`" in block
    # The reversed sentence, and the §13 claim it leaned on.
    assert "no stage of `fix` commits" not in block
    assert "The edit stays **uncommitted**" not in block
    # The contract the code implements: convergence-triggered, not green-gated; verified
    # remote head; skipped no-ops; fail-closed fourth case.
    assert "convergence" in block
    assert 'state.pr["head_sha"]' in block
    assert 'state.pr["commit_skip_reason"]' in block
    assert 'git.rev_parse(worktree, "origin/<branch>")' in block
    assert "[A1, I7, F5]" in block


def test_section_13_names_both_owners_of_the_documented_git_add_all() -> None:
    """05-P1.1: the broad `git add -A` has two owners — `I6 pr` and `F5` — both agent-run."""
    design = _design_md()
    section = _section(design, "## 13. Git and GitHub safety", "## 14. CLI reference")

    assert "git add -A" in section
    assert "`I6 pr`" in section
    assert "`F5 commit-and-push`" in section
    assert "`pr-publisher` agent" in section
    assert "not by Python" in section
    # The preserving-unrelated-work rule survives the widening.
    assert "preserves unrelated user changes" in section


def test_section_17_has_one_z9_row_recording_the_reversal() -> None:
    """05-P1.1: one row, not two — the reversal and P1.2's close-after-push ordering."""
    design = _design_md()
    section = _section(design, "## 17. Resolved decisions", "## 18. Risks")

    rows = [line for line in section.splitlines() if line.startswith("| Z9 |")]
    assert len(rows) == 1, f"expected exactly one §17 Z9 row, found {len(rows)}"
    z9 = rows[0]
    assert "F5" in z9 and "commit-and-push" in z9
    assert "reverses" in z9
    assert "P1.2" in z9
    # The prompt-fixed decisions travel with the row (Z2's precedent).
    assert "Prompt-fixed decisions" in z9
    for decision in ("(D1)", "(D2)", "(D3)", "(D4)", "(D5)", "(D6)", "(D7)", "(D8)", "(D9)", "(D10)"):
        assert decision in z9, decision


def test_section_17_z9_row_records_the_close_after_push_as_implemented() -> None:
    """05-P1.2: the close-after-push half is appended to the **same** Z9 row.

    The row exists because one reversal (no stage of `fix` committed) has one close:
    ordering the close behind the new push. A second row would split that decision, so the
    pin is that Z9 alone carries P1.2's prompt-fixed decisions — and that they are recorded
    as implemented, not as a plan.
    """
    section = _section(_design_md(), "## 17. Resolved decisions", "## 18. Risks")

    rows = [line for line in section.splitlines() if line.startswith("| Z9 |")]
    assert len(rows) == 1, f"expected exactly one §17 Z9 row, found {len(rows)}"
    z9 = rows[0]
    assert "P1.2's prompt-fixed decisions" in z9
    for decision in ("(P1.2a)", "(P1.2b)", "(P1.2c)", "(P1.2d)", "(P1.2e)", "(P1.2f)"):
        assert decision in z9, decision
    # The four facts the code implements, named in the row that records them.
    assert "review_followup.py close" in z9
    assert "{closing_body}" in z9
    assert "head_sha" in z9
    assert "no verified push" in z9
    assert "agents/fixer/AGENTS.md" in z9


def test_section_84_documents_the_deferred_close() -> None:
    """05-P1.2: §8.4 says when the close happens, and that F1 no longer does it.

    Without this the design would still read as "F1 closes the issue in-stage" — the exact
    sentence P1.2 removes — and case 4 of D3's table would keep claiming P1.2 fixes it
    "later".
    """
    block = _section_84_block(_design_md())

    assert "The deferred close" in block
    assert "review_followup.py close" in block
    assert "{closing_body}" in block
    # The ordering rule, and the flag that it is no longer a future change.
    assert "only **after** `F5` has pushed" in block
    assert "unrepresentable later" not in block
    # The fixer no longer posts the marker or closes in-stage.
    assert "`F1` no longer posts the marker and no longer closes in-stage" in block


def test_section_18_row_is_no_longer_contradictory() -> None:
    """05-P1.1: the risk row is resolved with the F5 boundary, not left asserting the old rule."""
    design = _design_md()
    risks = _section(design, "## 18. Risks", "## 19. Acceptance criteria")

    rows = [
        line
        for line in risks.splitlines()
        if line.startswith("| The fix-loop prompts leave their changes uncommitted")
    ]
    assert len(rows) == 1, f"expected exactly one §18 risk row, found {len(rows)}"
    row = rows[0]
    assert "Resolved" in row
    assert "F5" in row and "commit-and-push" in row
    # The old claim ("AIDT never commits") must be gone from the row's status/notes.
    assert "AIDT never commits" not in row
    assert "Not AIDT's to fix" not in row


def _section(design: str, heading: str, next_heading: str) -> str:
    """Return one design section, excluding the following section."""
    start = design.index(heading)
    end = design.index(next_heading, start)
    return design[start:end]


def test_header_does_not_couple_the_toolkit_to_a_product_repo() -> None:
    """Historical provenance is allowed; ownership/coupling claims are not."""
    design = _design_md()
    header = design[: design.index("## 1. Purpose and scope")]
    assert not re.search(
        r"(?:toolkit|AIDT).*?(?:lives inside|is part of|belongs to).*?repo",
        header,
        re.IGNORECASE | re.DOTALL,
    )


def test_section_1_names_the_two_roots_workspace_and_state_root() -> None:
    """§1 must make target selection and the four path concepts unambiguous."""
    design = _design_md()
    section = _section(design, "## 1. Purpose and scope", "## 2. Concepts")
    for phrase in (
        "Toolkit root",
        "Target repo root",
        "Workspace root",
        "State root",
        "--repo <path>",
        "$AIDW_REPO",
        "TargetRepo.resolve",
    ):
        assert phrase in section


def test_design_has_no_legacy_root_or_prompt_source_markers() -> None:
    """E9.1 stale-marker sweep: the design must describe the extracted toolkit."""
    design = _design_md()
    forbidden = (
        "Scope: ./aidt",
        "./aidt",
        "aidt/runs/",
        "aidt/prompts/",
        "aidt/tests/",
        "aidt/agent-configs",
        "aidt/aidt.toml",
        "aidt/.env",
        ".pi/prompts/",
        "03 E2 E2.9",
    )
    assert not [marker for marker in forbidden if marker in design]

    non_goals = _section(design, "### 1.3 Non-goals", "## 2. Concepts")
    assert not re.search(r"worktree", non_goals, re.IGNORECASE)


def test_implement_chain_documentation_is_rebased_to_i9() -> None:
    """X1.2: the current design must not advertise the pre-guide chain.

    The implementation contract adds a retained core stage, so the high-level workflow
    inventory, the stage-registry contract, and the acceptance section must all describe
    the same nine-stage chain. Historical task prompts are intentionally out of scope;
    these are the live sections operators use to understand the current toolkit.
    """
    design = _design_md()

    purpose = _section(design, "## 1. Purpose and scope", "### 1.1 Two roots")
    registry = _section(design, "### 12.2 Stage registry", "### 12.3 Prompt resolution")
    acceptance = design[design.index("## 19. Acceptance criteria") :]

    assert "I1–I9" in purpose
    assert "I1–I8" not in purpose
    assert "I1`–`I9" in registry
    assert "I1`–`I8" not in registry
    assert "I1–I9" in acceptance
    assert "I1–I8" not in acceptance


def test_section_3_uses_the_extracted_fixture_layout() -> None:
    """§3 must use the authoritative top-level fixture path from EXTRACTION §3.12."""
    design = _design_md()
    section = _section(design, "## 3. Repository layout", "### 3.1 Two distinct path types")

    for path in (
        "aidw/",
        "prompts/",
        "agent-configs/",
        "agents/",
        "docs/",
        "tests/",
        "fixtures/target-repo/",
        "design.md",
        "README.md",
        "pyproject.toml",
    ):
        assert path in section, f"missing layout entry: {path}"
    assert "tests/fixtures/target-repo/" not in section
    assert "ToolkitPaths" in section and "TargetRepo" in section
    assert "never interchangeable" in section
    assert "R8" in section and "Nothing generated" in section
    assert "inside the **toolkit** repo" in section
    assert "inside a **target** repo" in section


def test_section_91_matches_the_extraction_state_and_lock_layout() -> None:
    """§9.1 must preserve D18's run directory and branch lock contract."""
    design = _design_md()
    section = _section(design, "### 9.1 Layout", "### 9.2 `state.json` (schema)")

    assert "<state root>/<repo-slug>/runs/<run-id>/" in section
    assert "locks/<branch>.lock" in section
    assert "<worktree>-<digest>.lock" not in section
    assert "never in a working tree" in section


def test_section_91_tree_locks_child_is_branch_lock() -> None:
    """Regression (issue #130): the §9.1 tree child of `locks/` is `<branch>.lock`.

    The trigger: the tree rendered the lock as ``└── locks/<branch>.lock`` *under*
    ``└── locks/``, so a reader resolving the literal read
    ``<state root>/<repo-slug>/locks/locks/<branch>.lock`` — one `locks/` level deeper
    than the prose above the tree and EXTRACTION.md §3.10, and a path `aidw/lock.py`
    (`locks_dir()` + `lock_filename()`) never writes.
    """
    design = _design_md()
    section = _section(design, "### 9.1 Layout", "### 9.2 `state.json` (schema)")

    tree_start = section.index("```text\n") + len("```text\n")
    tree = section[tree_start : section.index("\n```", tree_start)]

    # `locks/` is a single level; its child is the lock file itself, not another `locks/`.
    assert "└── locks/\n    └── <branch>.lock" in tree
    assert "locks/<branch>.lock" not in tree


def test_section_92_records_config_identity_fields() -> None:
    """The state example must reconcile D10/P1 identity fields with the schema."""
    design = _design_md()
    section = _section(design, "### 9.2 `state.json` (schema)", "### 9.3 Stage reporting")
    for field in ("toolkit_version", "config_schema_version", "config_hash"):
        assert f'"{field}"' in section


def test_contract_links_are_existing_cross_references() -> None:
    """E9.1 links shipped contracts instead of creating a second schema copy."""
    root = toolkit_root()
    design = _design_md()
    linked = (
        "docs/target-repo-config.md",
        "docs/roadmap-format.md",
        "docs/releasing.md",
        "docs/schema/aidw-config.schema.json",
        "docs/migration/EXTRACTION.md",
    )
    for relative in linked:
        assert relative in design
        assert (root / relative).is_file(), relative

    section = _section(design, "### 12.1 The resolved target config", "### 12.2 Stage registry")
    assert "provenance" in section
    assert "docs/target-repo-config.md" in section
    assert "docs/schema/aidw-config.schema.json" in section
    assert "no loader exists yet" not in section.lower()


def test_section_12_describes_stage_and_prompt_contracts() -> None:
    """D12–D14 stay config-driven and preserve prompt precedence."""
    design = _design_md()
    stages = _section(design, "### 12.2 Stage registry", "### 12.3 Prompt resolution")
    prompts = _section(design, "### 12.3 Prompt resolution", "### 12.4 Environment")
    for phrase in ("Core stages", "Repo-optional stages", "Repo-added stages", "parallel_groups"):
        assert phrase in stages
    for phrase in (
        "explicit `prompt:`",
        "<target>/aidw/prompts/",
        "toolkit default",
        "explicit path does **not** fall through",
    ):
        assert phrase in prompts


def test_section_72_documents_the_frozen_contract_at_the_wrapper_boundary() -> None:
    """D5 must name config defaults, exact matching, and the E6.3 guard."""
    design = _design_md()
    section = _section(design, "### 7.2 Frozen GitHub contracts", "### 7.3 Prompt rendering")
    for phrase in (
        "github.markers",
        "github.labels",
        "defaults are today's literals",
        "exact string match",
        "strict `==`",
        "No whitespace",
        "normalisation",
        "case folding",
        "EXTRACTION.md §3.9",
        "tests/test_baseline_verbatim_golden.py",
        "aidw/github.py",
    ):
        assert phrase in section, f"missing frozen-contract evidence: {phrase}"


def test_section_125_documents_distribution_and_compatibility_boundary() -> None:
    """D9/D10 must point operators to installation, pins, and the release contract."""
    design = _design_md()
    section = _section(design, "### 12.5 Distribution", "## 13. Git and GitHub safety")
    for phrase in (
        "uv tool install",
        "uvx --from",
        "toolkit_version",
        "aidw.target_config.check_compatibility",
        "docs/releasing.md",
    ):
        assert phrase in section


def test_late_sections_are_post_extraction_and_use_current_test_paths() -> None:
    """§15–§19 must not reintroduce the removed self-contained subtree model."""
    design = _design_md()
    testing = _section(design, "## 15. Testing strategy", "## 16. Build state")
    build = _section(design, "## 16. Build state", "## 17. Resolved decisions")
    risks = _section(design, "## 18. Risks", "## 19. Acceptance criteria")
    acceptance = design[design.index("## 19. Acceptance criteria") :]

    assert 'testpaths = ["tests", "prompts/scripts/review-followup/tests"]' in testing
    assert "current state" in build
    assert "aidt/" not in risks and ".pi/prompts/" not in risks
    assert "03 E2 E2.9" not in acceptance
    assert "aidt/tests/" not in acceptance


def test_section_17_keeps_rewritten_extraction_decisions_traceable() -> None:
    """D1–D24 and R1–R18 must remain findable in the design-of-record section."""
    design = _design_md()
    section = _section(design, "## 17. Resolved decisions", "## 18. Risks")
    missing = [
        identifier
        for prefix, count in (("D", 24), ("R", 18))
        for identifier in (f"{prefix}{number}" for number in range(1, count + 1))
        if not re.search(rf"(?<![A-Za-z0-9]){identifier}(?![A-Za-z0-9])", section)
    ]
    assert not missing, f"missing extraction decision trail: {missing}"

    rows = {line.split("|", 2)[1].strip(): line for line in section.splitlines() if line.startswith("| ")}
    assert "target repo root" in rows["D4"]
    assert "D19" in rows["D4"]
    assert "D20" in rows["E4"]
    assert "D19" in rows["F6"]

    stale_rows = (
        "| D4 | Pi cwd = Mythical Forge root. |",
        "| E4 | Safety refusals enforced; no worktrees in v1. |",
        "| F3 | aidt/runs/<run-id>/ artifacts, gitignored. |",
        "| F5 | `pytest` locally; not part of the product's pnpm CI. |",
        "| F6 | Auto-detect repo root from any cwd; absolute paths internally. |",
    )
    assert not [row for row in stale_rows if row in section]
