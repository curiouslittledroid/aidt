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


def _section_82_block(design: str) -> str:
    """The §8.2 ``aidw implement`` block: its heading up to the §8.3 heading."""
    start = design.index("### 8.2 `aidw implement <task-prompt-path> [--pr <n>]`")
    end = design.index("### 8.3 ", start)
    return design[start:end]


def test_section_82_withholds_i6_on_an_in_scope_test_fail() -> None:
    """Q1.1: the I2 verdict gate is design, not an implementation detail.

    The gate's whole point is that a `Fail` lives in I2's *message* while the stage stays
    `SUCCEEDED`, so §8.2 must say so, name the tokens and the recorded state, and state the
    resume rule — otherwise the next reader "fixes" the block away as a dead end.
    """
    # Whitespace-flattened: the bullets are hard-wrapped, and the pinned sentences span lines.
    block = " ".join(_section_82_block(_design_md()).split())

    assert "**`I2`'s verdict withholds `I6`**" in block
    assert "Test verdict: Pass" in block
    assert "Test verdict: Fail" in block
    assert "Failing in-scope criteria:" in block
    assert "_parse_test_verdict" in block
    assert 'state.pr["test_verdict"] = "Fail"' in block
    assert 'state.pr["test_failing_criteria"]' in block
    assert "BLOCKED" in block and "exit 3" in block
    # The Resume rule sentence: repeat-stop is correct, `--from test` re-tests.
    assert "**Resume rule:**" in block
    assert "repeats the stop identically while the verdict is unchanged" in block
    assert "which is correct, not stuck" in block
    assert "`--from test`" in block
    assert "overrides §9.4's completed-stages-never-rerun rule" in block


def test_section_17_has_one_z10_row_recording_the_test_verdict_gate() -> None:
    """Q1.1: one §17 row records the gate, its fail-closed stop and its prompt-fixed choices."""
    design = _design_md()
    section = _section(design, "## 17. Resolved decisions", "## 18. Risks")

    rows = [line for line in section.splitlines() if line.startswith("| Z10 |")]
    assert len(rows) == 1, f"expected exactly one §17 Z10 row, found {len(rows)}"
    z10 = rows[0]
    # The behaviour the code implements: Fail → BLOCKED/exit 3, I6 withheld, criteria named.
    assert "Fail" in z10
    assert "BLOCKED" in z10 and "exit 3" in z10
    assert "I6" in z10 and "withholds" in z10
    assert "criteria" in z10
    assert "test_verdict" in z10
    # The prompt-fixed decisions travel with the row (Z2/Z9's precedent).
    assert "Prompt-fixed decisions" in z10
    for decision in ("(a)", "(b)", "(c)", "(d)"):
        assert decision in z10, decision


def test_section_82_documents_the_path_scoped_condition_on_i3() -> None:
    """S1.1: §8.2 states the token, the carry rule, the change set and the skip shape.

    Without the paragraph the next reader would find `I3` skipping with no design behind
    it — and would be free to "fix" the condition away, or to give the toolkit a default
    path set, which is exactly the product literal the decision forbids.
    """
    block = " ".join(_section_82_block(_design_md()).split())

    assert "**`when=WHEN_PATHS_CHANGED`**" in block
    assert "`when_paths`" in block
    assert "carried, never expanded away" in block
    assert "`_expand_static`" in block
    assert "`git.changed_paths`" in block and "`BASE_DEFAULT`" in block
    assert "`git.untracked_paths`" in block
    assert "`verification.normalise_ignore`" in block
    assert "`runner.record_skipped`" in block
    assert "`SKIP_REASON_KEY`" in block
    # The empty-default rule and the fail-closed direction are both stated.
    assert "absent or empty" in block and "**unconditional**" in block
    assert "Cannot prove" in block and "**runs** the stage" in block
    # The skip is a cost control, not a gate verdict.
    assert "cost-control skip, not a gate verdict" in block
    assert "no `state.status`/`state.resume` write" in block


def test_section_12_2_documents_the_token_and_the_stage_key() -> None:
    """S1.1: the registry/override section names both halves a repo has to know."""
    section = _section(
        _design_md(), "### 12.2 Stage registry", "### 12.3 Prompt resolution"
    )

    assert "`when=paths-changed`" in section
    assert "`when_paths`" in section
    assert "`verification.normalise_ignore`" in section
    assert "absent or empty" in section and "unconditional" in section
    # The token is one of the two the expander cannot resolve.
    assert "`evidence-green`" in section


def test_section_17_has_one_z11_row_recording_the_path_scoped_condition() -> None:
    """S1.1: one §17 row records the token, `I3`, its fail-closed edges and its choices."""
    design = _design_md()
    section = _section(design, "## 17. Resolved decisions", "## 18. Risks")

    rows = [line for line in section.splitlines() if line.startswith("| Z11 |")]
    assert len(rows) == 1, f"expected exactly one §17 Z11 row, found {len(rows)}"
    z11 = rows[0]
    assert "WHEN_PATHS_CHANGED" in z11 and "paths-changed" in z11
    assert "`I3`" in z11 and "`when_paths`" in z11
    # The principles it must not violate, and the follow-up task it must not do.
    assert "product literal" in z11
    assert "unconditional" in z11
    assert "S1.2" in z11
    assert "record_skipped" in z11
    assert "BASE_DEFAULT" in z11
    # The prompt-fixed decisions travel with the row (Z1/Z9's precedent).
    assert "Prompt-fixed decisions" in z11
    for decision in ("(a)", "(b)", "(c)", "(d)", "(e)"):
        assert decision in z11, decision
    # The touched set is named, so a later reader can find the contract tests.
    for path in (
        "aidw/stage_registry.py",
        "aidw/runner.py",
        "aidw/target_config.py",
        "aidw/workflows/implement.py",
        "docs/workflow-stages.md",
        "tests/test_implement_workflow.py",
    ):
        assert path in z11, path


def test_s1_2_design_sections_and_next_free_decision_row_are_recorded() -> None:
    """S1.2: design records I4's contract without hardcoding a future Z number."""
    design = _design_md()
    block = " ".join(_section_82_block(design).split())
    assert "I4" in block and "WHEN_PATHS_CHANGED" in block
    assert "docs/architecture" in block
    assert "doctor" in block

    section = _section(design, "### 12.2 Stage registry", "### 12.3 Prompt resolution")
    assert "I4" in section and "paths-changed" in section

    decisions = _section(design, "## 17. Resolved decisions", "## 18. Risks")
    rows = [
        line
        for line in decisions.splitlines()
        if re.match(r"^\| Z\d+ \|", line) and "S1.2" in line and "I4" in line
    ]
    assert len(rows) == 1, f"expected exactly one S1.2 decision row, found {len(rows)}"


def _section_73_block(design: str) -> str:
    """The §7.3 ``Prompt rendering`` block: its heading up to the §7.4 heading."""
    start = design.index("### 7.3 Prompt rendering")
    end = design.index("### 7.4 ", start)
    return design[start:end]


def test_c1_1_section_7_3_drops_the_agents_md_append_and_keeps_conventions() -> None:
    """C1.1: §7.3 step 4 states the new default and the marker that restores the old one.

    The design is what the next reader builds from: leaving step 4 saying the root
    ``AGENTS.md`` is appended would keep the duplication C1.1 removes, and omitting the
    marker would strand a repo whose agents set ``no_context_files: true`` (§5.5) with no
    ``AGENTS.md`` at all.
    """
    # Whitespace-flattened: the step is hard-wrapped, and the pinned sentences span lines.
    block = " ".join(_section_73_block(_design_md()).split())

    # The kept half: the source Pi does not provide, appended where a prompt takes it.
    assert "`aidw/conventions.md`" in block
    # The dropped half, with its reason (§5.5) and the opt-in that restores it.
    assert "The root `AGENTS.md` is **not** appended" in block
    assert "project context at `cwd` = target root (§5.5)" in block
    assert "`append_agents_md: true`" in block
    assert "`no_context_files: true`" in block
    assert "resolved prompt path" in block
    assert "YAML boolean `true`" in block
    # The read channel is explicitly left alone, because `_gate_block` depends on it.
    assert "read_conventions_sources" in block
    assert "`CONVENTIONS_SOURCES`" in block
    assert "`aidw/workflows/prompt.py:_gate_block`" in block
    # The pre-C1.1 claim that step 4 appends both sources is gone.
    assert "root `AGENTS.md` plus optional" not in block
    assert "`AGENTS.md` plus optional `<target>/aidw/conventions.md`" not in block


def test_c1_1_decision_row_records_the_agents_md_append_split() -> None:
    """C1.1: one §17 row records the split, its marker lever and its prompt-fixed choices.

    Matched by task id + wording, never by a hardcoded ``Z`` number: the roadmap's stale
    "recorded as Z12" collides with S1.2's row, and ``aidw/conventions.md`` forbids reusing
    or renumbering an id, so the row takes the next free id and this pin must not pin it.
    """
    design = _design_md()
    decisions = _section(design, "## 17. Resolved decisions", "## 18. Risks")

    rows = [
        line
        for line in decisions.splitlines()
        if re.match(r"^\| Z\d+ \|", line)
        and "C1.1" in line
        and "append_agents_md" in line
    ]
    assert len(rows) == 1, f"expected exactly one C1.1 decision row, found {len(rows)}"
    row = rows[0]
    # The behaviour the code implements: AGENTS.md dropped, conventions.md kept, marker opt-in.
    assert "AGENTS.md" in row and "`aidw/conventions.md`" in row
    assert "`append_agents_md: true`" in row
    assert "§7.3" in row and "§5.5" in row
    assert "appends_target_agents_md" in row
    assert "include_agents_md" in row
    # The read channel it must not move is named, so C1.2 cannot quietly lose its source.
    assert "read_conventions_sources" in row
    assert "CONVENTIONS_SOURCES" in row
    assert "_gate_block" in row
    # The prompt-fixed decisions travel with the row (Z2/Z9/Z11's precedent).
    assert "Prompt-fixed decisions" in row
    for decision in ("(a)", "(b)", "(c)", "(d)", "(e)"):
        assert decision in row, decision
    # No §17 id is reused: every Z id appears exactly once (``aidw/conventions.md``).
    ids = re.findall(r"^\| (Z\d+) \|", decisions, re.M)
    duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    assert duplicates == [], f"reused §17 decision ids: {duplicates}"
    # And C1.1 is not S1.2's Z12 row.
    assert not row.startswith("| Z12 |")
    # The touched set is named, so a later reader can find the contract tests.
    for path in (
        "aidw/prompts.py",
        "design.md",
        "tests/test_conventions_injection.py",
        "tests/test_design_doc.py",
    ):
        assert path in row, path


def _section_81_block(design: str) -> str:
    """The §8.1 ``aidw prompt`` block: its heading up to the §8.2 heading."""
    start = design.index("### 8.1 `aidw prompt <phase> <epic> <task>`")
    end = design.index("### 8.2 ", start)
    return design[start:end]


def test_c1_2_sections_and_decision_row_record_the_gate_heading_contract() -> None:
    """C1.2: §7.3, §8.1 and one §17 row state the two headings, the declaration and the WARN.

    The row is matched by task id + wording, never by a hardcoded ``Z`` number
    (``aidw/conventions.md`` forbids reusing or renumbering an id). C1.1's injection claims
    must survive: C1.2 changes only the read channel.
    """
    design = _design_md()

    block73 = " ".join(_section_73_block(design).split())
    assert "`## Gate commands`" in block73
    assert "`gates_heading`" in block73
    # The prefix rule, not exact equality, so the suffixed canonical heading still matches.
    assert "`startswith`" in block73
    assert "GATES_HEADINGS" in block73
    assert "is_gates_like_heading" in block73
    assert "is_recognised_gates_heading" in block73
    # C1.1's split is not undone by this task.
    assert "The root `AGENTS.md` is **not** appended" in block73
    assert "`append_agents_md: true`" in block73

    block81 = " ".join(_section_81_block(design).split())
    assert "`## Gate commands`" in block81
    assert "`gates_heading`" in block81
    assert "`gates heading`" in block81
    assert "WARN" in block81 and "never a FAIL" in block81

    decisions = _section(design, "## 17. Resolved decisions", "## 18. Risks")
    rows = [
        line
        for line in decisions.splitlines()
        if re.match(r"^\| Z\d+ \|", line)
        and "C1.2" in line
        and "gates_heading" in line
        and "is_recognised_gates_heading" in line
    ]
    assert len(rows) == 1, f"expected exactly one C1.2 decision row, found {len(rows)}"
    row = rows[0]
    assert "§7.3" in row and "§8.1" in row
    for decision in ("(a)", "(b)", "(c)"):
        assert decision in row, decision
    assert "Prompt-fixed decisions" in row
    # The touched set is named, so a later reader can find the contract tests.
    for path in (
        "aidw/prompts.py",
        "aidw/workflows/prompt.py",
        "aidw/doctor.py",
        "aidw/target_config.py",
        "docs/target-repo-config.md",
        "docs/schema/aidw-config.schema.json",
        "tests/test_prompt_workflow.py",
        "tests/test_doctor.py",
        "tests/test_target_config.py",
        "tests/test_design_doc.py",
    ):
        assert path in row, path
    assert not row.startswith("| Z15 |")


def test_c1_3_section_7_3_and_decision_row_record_the_gate_block_injection() -> None:
    """C1.3: §7.3 gets the injection step and one §17 row records the prompt-fixed choices.

    Matched by task id + wording, never by a ``Z`` number (``aidw/conventions.md`` forbids
    reusing or renumbering an id; the next free id was ``Z17``). C1.1's and C1.2's claims
    must survive: C1.3 adds a *consumer* of the resolved block, not a second resolution.
    """
    design = _design_md()

    # Whitespace-flattened: the steps are hard-wrapped, and the pinned sentences span lines.
    block73 = " ".join(_section_73_block(design).split())
    assert "resolved gate commands" in block73
    assert "`aidw/prompts.py:GATE_PROMPTS`" in block73
    assert "`## Resolved gate commands" in block73
    # The shared resolution and its single-consumer wrapper are both named.
    assert "`aidw/prompts.py:resolved_gate_block`" in block73
    assert "`aidw/workflows/prompt.py:_gate_block`" in block73
    # The five prompts are named so a reader can check the set without reading the code.
    for basename in (
        "`impliment-task.md`",
        "`test.md`",
        "`fix-next-review-followup.md`",
        "`record-implementation-results.md`",
        "`code-review.md`",
    ):
        assert basename in block73, basename
    # The two hard guarantees: the wrapper idiom stays, no-resolution is byte-identity.
    assert "`aidw gate run <key> $SCOPE -- <command>`" in block73
    assert "byte-identically" in block73
    assert "never injects an `unavailable` note" in block73
    # C1.1's split is not undone by this task.
    assert "The root `AGENTS.md` is **not** appended" in block73
    assert "`append_agents_md: true`" in block73

    decisions = _section(design, "## 17. Resolved decisions", "## 18. Risks")
    rows = [
        line
        for line in decisions.splitlines()
        if re.match(r"^\| Z\d+ \|", line)
        and "C1.3" in line
        and "GATE_PROMPTS" in line
        and "resolved_gate_block" in line
    ]
    assert len(rows) == 1, f"expected exactly one C1.3 decision row, found {len(rows)}"
    row = rows[0]
    assert "§§7.3, 8.2" in row
    assert "`inject_gate_block" in row
    assert "Prompt-fixed decisions" in row
    for decision in ("(a)", "(b)", "(c)", "(d)", "(e)", "(f)"):
        assert decision in row, decision
    # The duplication corner is decided, not left silent: the focused block is authoritative.
    assert "authoritative" in row
    # The code-review re-classification is named with its new class, not as a weaker guard.
    assert "byte-frozen" in row and "class (v)" in row
    # The touched set is named, so a later reader can find the contract tests.
    for path in (
        "aidw/prompts.py",
        "aidw/workflows/prompt.py",
        "aidw/runner.py",
        "prompts/code-review.md",
        "docs/migration/prompt-classification.md",
        "tests/test_conventions_injection.py",
        "tests/test_prompt_classification.py",
    ):
        assert path in row, path
    assert not row.startswith("| Z16 |")


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


def test_w12_dry_run_decision_and_acceptance_wording_are_recorded() -> None:
    """W1.2: the design records one uniform no-run rule and its acceptance wording."""
    design = _design_md()
    decisions = _section(design, "## 17. Resolved decisions", "## 18. Risks")
    rows = [
        line
        for line in decisions.splitlines()
        if line.startswith("|") and "05-W1.2" in line and "dry-run" in line
    ]
    assert len(rows) == 1
    assert "not resumable" in rows[0]
    assert "no run" in rows[0]

    acceptance = design[design.index("## 19. Acceptance criteria") :]
    criteria = acceptance.splitlines()
    starts = [
        index
        for index, line in enumerate(criteria)
        if re.match(r"^(?:8|9|10)\. ", line)
    ]
    assert len(starts) == 3
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(criteria)
        assert "no run state" in " ".join(criteria[start:end])


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


def test_g11_section_81_states_the_kind_contract_and_the_two_stops() -> None:
    """G1.1: §8.1 carries the `Kind:` contract, the re-read rule and both fail-closed stops.

    Without it the next reader would find a `spec-gap` blocking a run with no design behind
    it, and would be free to "fix" the loop back to handing spec gaps to the task-fixer.
    """
    block = " ".join(_section_81_block(_design_md()).split())

    assert "`Kind:`" in block
    assert "`spec-gap`" in block and "`prompt-gap`" in block
    assert "only the cited spec or roadmap can close" in block
    assert "fixable by editing the prompt" in block
    # Both stops: exit 3, surfaced findings, prompt uncommitted, and their mechanisms.
    assert "BLOCKED" in block and "exit 3" in block
    assert "mechanism `spec-gap`" in block
    assert "mechanism `unclassified`" in block
    assert "no fix stage or reconcile" in block
    assert "wins over an `Approve` or `Blocked` verdict" in block
    assert "never acted on even in part" in block
    # The parser/enforcement split and the unchanged manifest shape are both stated.
    assert "`to_manifest_entry`" in block
    assert "`_finding_text_block`" in block
    assert "§8.3's code-review findings carry none" in block
    # W1's resume rule is keyed on `review-loop`, so the new mechanisms must not be it.
    assert "**not** `review-loop`" in block
    assert "refuses the block instead of offering a fix cycle" in block
    # G1.1 req 7's re-read rule is design, not only prompt copy.
    assert "re-read the previously flagged material in full" in block
    assert "diff-only re-read" in block


def test_g11_decision_row_records_the_classification_contract() -> None:
    """G1.1: exactly one §17 row records the task, its files and its prompt-fixed choices.

    Matched by task id + wording, never by a ``Z`` number: the roadmap's "recorded as Z13"
    is stale (``Z13`` is 05-S1.2's roadmap-ownership row) and ``aidw/conventions.md`` forbids
    reusing or renumbering an id, so this pin must not pin the number.
    """
    decisions = _section(_design_md(), "## 17. Resolved decisions", "## 18. Risks")
    rows = [
        line
        for line in decisions.splitlines()
        if re.match(r"^\| Z\d+ \|", line)
        and "G1.1" in line
        and "unclassified" in line
        and "spec-gap" in line
    ]
    assert len(rows) == 1, f"expected exactly one G1.1 decision row, found {len(rows)}"
    row = rows[0]
    # The behaviour the code implements, on both sides of the parser/enforcement split.
    assert "`Kind:`" in row
    assert "`prompt-gap`" in row
    assert "`ParsedFinding.kind`" in row
    assert "`KIND_MAP`" in row
    assert "`_finding_text_block`" in row
    assert "`partition_findings`" in row
    assert "`STRING_FIELDS`" in row
    # The stale-id correction and the conventions rule travel with the row.
    assert "Z13" in row
    assert "`aidw/conventions.md`" in row
    assert "`Z18`" in row
    # The prompt-fixed decisions travel with the row (Z2/Z9/Z11's precedent).
    assert "Prompt-fixed decisions" in row
    for decision in ("(a)", "(b)", "(c)", "(d)"):
        assert decision in row, decision
    # The spec sections and the touched set are named, so the contract tests are findable.
    assert "§§8.1, 8.3" in row
    for path in (
        "prompts/task-review.md",
        "agents/task-reviewer/AGENTS.md",
        "aidw/findings.py",
        "aidw/workflows/prompt.py",
        "docs/migration/prompt-classification.md",
        "tests/test_findings.py",
        "tests/test_prompt_workflow.py",
        "tests/test_design_doc.py",
        "tests/test_prompt_classification.py",
    ):
        assert path in row, path
    # No §17 id is reused.
    ids = re.findall(r"^\| (Z\d+) \|", decisions, re.M)
    duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    assert duplicates == [], f"reused §17 decision ids: {duplicates}"
    assert not row.startswith("| Z13 |")


def test_g12_section_81_states_the_cited_spec_preflight() -> None:
    """G1.2: §8.1 documents the preflight's position, gap rule, exit code and backstop.

    The preflight is behaviour a later reader can only know from the design: without it,
    the exit-3 refusal would look like a bug beside §14's exit-4 preflight refusals, and
    the canonical (non-string) section comparison would be "simplified" back into a broken
    exact match.
    """
    block = " ".join(_section_81_block(_design_md()).split())

    # The stage diagram's `preflight (...)` line carries it, in execution order.
    assert "refuse on a cited spec section that is missing, unlocatable or empty" in block
    # The bullet: position, gap rule, cost, exit code and the author-side backstop.
    assert "cited spec section" in block
    assert "before `P1`" in block
    assert "exit 3" in block
    assert "non-empty" in block
    assert "semantic backstop" in block
    assert "spends no Pi invocation" in block
    assert "roadmap-format.md §8" in block
    assert "canonically" in block
    assert "leading zeros ignored" in block
    assert "L1.2" in block
    assert "--dry-run" in block and "never refuses" in block


def test_g12_decision_row_records_the_cited_spec_preflight() -> None:
    """G1.2: exactly one §17 row records the task, its files and its prompt-fixed choices.

    Matched by task id + wording, never by a ``Z`` number: ``aidw/conventions.md`` forbids
    reusing or renumbering an id, so this pin must not pin the number.
    """
    decisions = _section(_design_md(), "## 17. Resolved decisions", "## 18. Risks")
    rows = [
        line
        for line in decisions.splitlines()
        if re.match(r"^\| Z\d+ \|", line)
        and "G1.2" in line
        and "spec section" in line
        and "exit 3" in line
    ]
    assert len(rows) == 1, f"expected exactly one G1.2 decision row, found {len(rows)}"
    row = rows[0]
    # The behaviour the code implements, on both sides of the shared enumerator.
    assert "`_spec_feasibility_gaps`" in row
    assert "`_cited_specs`" in row
    assert "`_render_cited_specs`" in row
    assert "`D<nn>`" in row
    assert "empty" in row
    # The prompt-fixed decisions travel with the row (Z2/Z9/Z11's precedent).
    assert "Prompt-fixed decisions" in row
    for decision in ("(a)", "(b)", "(c)", "(d)"):
        assert decision in row, decision
    assert "not 2 or 4" in row
    assert "roadmap-format.md §10" in row
    assert "`not takeover`" in row
    assert "§17 Z14" in row
    # The spec sections and the touched set are named, so the contract tests are findable.
    assert "§§8.1, 14" in row
    for path in (
        "aidw/workflows/prompt.py",
        "tests/test_prompt_workflow.py",
        "tests/test_design_doc.py",
    ):
        assert path in row, path
    # The fixture re-baseline travels with the row (no citation was stripped).
    assert "`READ_PATH_FILES`" in row
    # No §17 id is reused, and the appended id is a fresh one.
    ids = re.findall(r"^\| (Z\d+) \|", decisions, re.M)
    duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    assert duplicates == [], f"reused §17 decision ids: {duplicates}"
