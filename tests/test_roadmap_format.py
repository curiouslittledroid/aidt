"""Contract tests for ``docs/roadmap-format.md`` (E5.1, EXTRACTION.md §3.7, D6/D15).

The document is the format contract and the fenced worked example in it is the executable
half of that contract — and, since E5.4, the **only** copy of it (``tests/test_roadmap.py"
parses the same extraction). These tests write the example to the filename the doc names
and assert the shipped parser produces exactly what the doc's field tables promise. The
extraction itself, including its "exactly one complete worked example" guard, lives once in
``tests/conftest.py`` (``roadmap_example``, E5.4) so a second example cannot satisfy one
copy of the selector while the other still finds "one" (EXTRACTION.md §3.7).

Since E9.2 the doc's status table and §10 also state the **shipped** validation split — the
parser stays silent while ``aidw/roadmap.py:validate_tasks`` reports exactly three rules,
surfaced by ``aidw tasks --validate`` — so the pre-shipped "not done"/"No validation" wording
fails here instead of misleading a reader.

Nothing here re-implements a rule: every assertion compares the doc's claims against
``aidw/roadmap.py`` (the four entry patterns, ``_FILENAME_RE``, ``CITATION_RE``,
``derive_epic``) and against ``aidw/workflows/prompt.py`` (``_done_when_block`` and
``_render_cited_specs``, the two consumers whose rules the doc documents separately). A doc
edit that contradicts the code therefore fails here instead of at the next roadmap parse.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aidw.paths import TargetRepo
from aidw.roadmap import (
    CITATION_RE,
    DONE_RE,
    EPIC_RE,
    PHASE_RE,
    RULE_DUPLICATE_ID,
    RULE_MISSING_DONE_WHEN,
    RULE_OUTSIDE_EPIC,
    TASK_RE,
    _FILENAME_RE,
    derive_epic,
    filter_tasks,
    find_task,
    load_tasks,
    next_todo,
    parse_file,
)
from aidw.workflows import prompt as prompt_workflow

if TYPE_CHECKING:  # pragma: no cover - type-only
    # A runtime ``from conftest import …`` binds whichever of the two collected
    # ``conftest`` modules was imported last and breaks the full-suite run; the fixture's
    # name is all these annotations need (``from __future__ import annotations``).
    from conftest import RoadmapExample

#: The toolkit's default ``paths.roadmap_glob`` (``TOOLKIT_DEFAULTS.paths``, D17). Passed
#: explicitly because :func:`aidw.roadmap.load_tasks` carries no pattern of its own.
DEFAULT_GLOB = "[0-9]* - *.md"

#: The stale claims E9.2 reconciled away (the Done-when rg gate's alternatives). E5.3 and E5.4
#: both shipped, and §10 now describes the separate ``validate_tasks`` pass instead of absent
#: validation, so any of these in the doc is drift back to the pre-shipped wording.
STALE_VALIDATION_CLAIMS = ("not done", "No validation", "No duplicate-id detection")

#: §10's heading, number preserved: ``aidw/roadmap.py`` and ``tests/test_roadmap_validate.py``
#: both cite "roadmap-format.md §10".
SECTION_10_HEADING = "## 10. What the parser does not do (v1)"


def _section(text: str, prefix: str, *, level: int = 2) -> str:
    """The block headed by ``prefix``, up to the next heading of ``level`` or shallower.

    Mirrors ``tests/test_target_repo_config_doc.py:_section``: a renamed or deleted section
    raises instead of silently producing an empty string that every assertion then passes.
    """
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith(prefix)), None)
    assert start is not None, f"missing heading {prefix!r} in the roadmap format doc"
    stop = re.compile(rf"^#{{1,{level}}} ")
    for index in range(start + 1, len(lines)):
        if stop.match(lines[index]):
            return "\n".join(lines[start:index])
    return "\n".join(lines[start:])


def _status_rows(text: str) -> list[str]:
    """The activity/owner table rows at the top of the doc (header and rules dropped)."""
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.startswith("| Activity | Owner |")),
        None,
    )
    assert start is not None, "missing the status table"
    rows = []
    for line in lines[start + 1 :]:
        if not line.startswith("|"):
            break
        if set(line) <= set("|-: "):
            continue
        rows.append(line)
    assert len(rows) >= 4, f"status table lost its rows: {rows}"
    return rows


def _assert_status_table_is_reconciled(text: str) -> None:
    """E5.3/E5.4 are marked done and point at the shipped artefact by symbol (E9.2)."""
    rows = _status_rows(text)
    validation = next(row for row in rows if "Format *validation*" in row)
    example = next(row for row in rows if "single source" in row)
    for row in (validation, example):
        for stale in STALE_VALIDATION_CLAIMS:
            assert stale not in row, f"stale claim {stale!r} in {row!r}"
        assert "done" in row, row
    assert "`aidw/roadmap.py:validate_tasks`" in validation
    assert "aidw tasks --validate" in validation
    assert "§10" in validation
    assert "`tests/conftest.py:roadmap_example`" in example
    assert "§9" in example


def _assert_section_10_is_reconciled(text: str) -> None:
    """§10 states the shipped split: silent parser, separate pure validator, three rules."""
    section = _section(text, SECTION_10_HEADING)
    for stale in STALE_VALIDATION_CLAIMS:
        assert stale not in section, f"stale claim {stale!r} in §10"

    # The parser stays silent; validation is the separate, pure pass.
    assert "`parse_file`" in section and "`load_tasks`" in section
    assert "silent" in section
    assert "`aidw/roadmap.py:validate_tasks`" in section
    assert "pure" in section

    # Exactly the three rules, under the module's own tokens (never a paraphrase).
    for rule in (RULE_MISSING_DONE_WHEN, RULE_DUPLICATE_ID, RULE_OUTSIDE_EPIC):
        assert f"`{rule}`" in section, f"rule token {rule!r} missing from §10"

    # The CLI surface and its exact line format.
    assert "aidw tasks --validate" in section
    assert "{file}:{line}: {rule} — {message}" in section

    # The two traps, stated precisely: pair keying, and `epic_title` rather than `epic`.
    assert "(phase, task)" in section
    assert "epic_title is None" in section
    assert "**not** `epic`" in section


def _snapshot(tasks: list) -> list[tuple]:
    """The fields the doc's §11 table promises, so two parses can be compared."""
    return [
        (
            task.phase,
            task.epic,
            task.task,
            task.title,
            task.done,
            task.done_when,
            tuple(task.citations),
            task.epic_title,
            task.phase_title,
            task.file,
            task.line,
        )
        for task in tasks
    ]


# --------------------------------------------------------------------------- #
# The document itself
# --------------------------------------------------------------------------- #


def test_doc_is_no_longer_a_placeholder(roadmap_example: RoadmapExample) -> None:
    text = roadmap_example.doc.read_text(encoding="utf-8")
    assert "Placeholder" not in text
    assert "# The AIDT roadmap format" in text
    # The contract's load-bearing pieces, named as the task requires.
    for required in ("Done when", "derive_epic", "Design", "_FILENAME_RE"):
        assert required in text


def test_doc_quotes_the_shipped_patterns_verbatim(roadmap_example: RoadmapExample) -> None:
    """A pattern edited in code but not in the doc (or vice versa) fails here."""
    text = roadmap_example.doc.read_text(encoding="utf-8")
    for pattern in (TASK_RE, EPIC_RE, PHASE_RE, DONE_RE, _FILENAME_RE, CITATION_RE):
        assert pattern.pattern in text, f"{pattern.pattern!r} is missing from {roadmap_example.doc}"
    assert prompt_workflow._FIELD_BULLET_RE.pattern in text


def test_doc_states_one_format_and_the_directory_plus_glob_surface(
    roadmap_example: RoadmapExample,
) -> None:
    """D6/D15: one AIDT-owned format; the repo supplies only a directory and a pattern."""
    text = roadmap_example.doc.read_text(encoding="utf-8")
    assert "D15" in text and "D6" in text
    assert "paths.roadmap_dir" in text
    assert "paths.roadmap_glob" in text
    assert "docs/tasks" in text
    assert "[0-9]* - *.md" in text
    # No configurable parser/dialect is described, only the two path keys.
    assert "per-repo dialect" in text


def test_doc_states_the_default_globs_spacing_is_convention_not_strictness(
    roadmap_example: RoadmapExample,
) -> None:
    """The §1 glob trap: `*` matches spaces, so the spacing is convention, not strictness.

    `roadmap_glob` is an `fnmatch` glob, and `*` absorbs spaces: the spaceless
    `[0-9]*-*.md` matches `00 - Extraction.md` too, so §1 must state the spaced default as
    the canonical convention (and a real non-matching shape), never as a strictness
    guarantee — the false blanket claim that the spaceless glob "would match nothing"
    invites a wrong strictness assumption in E5.2's file selection (issue #96).
    """
    text = roadmap_example.doc.read_text(encoding="utf-8")

    # The trigger, reproduced: `*` matches spaces, so both spellings select the same names.
    assert fnmatch("00 - Extraction.md", "[0-9]* - *.md")
    assert fnmatch("00 - Extraction.md", "[0-9]*-*.md")
    assert fnmatch("07 - Example Roadmap.md", "[0-9]* - *.md")
    assert fnmatch("07 - Example Roadmap.md", "[0-9]*-*.md")

    # The real strictness boundary is the pattern's scope, not its spacing.
    assert not fnmatch("example-roadmap.md", "[0-9]* - *.md")  # no two-digit prefix
    assert not fnmatch("00 - Extraction.txt", "[0-9]* - *.md")  # not `.md`

    # §1 states the convention and the scope, not the false glob-theory claim.
    assert "[0-9]*-*.md` would match" not in text  # the spaceless glob *does* match
    assert "not a strictness guarantee" in text
    assert "canonical convention" in text
    assert "no two-digit prefix" in text
    assert "not `.md`" in text


# --------------------------------------------------------------------------- #
# E9.2: the reconciliation, pinned so it cannot silently revert
# --------------------------------------------------------------------------- #


def test_status_table_marks_the_validation_tasks_shipped(
    roadmap_example: RoadmapExample,
) -> None:
    """E5.3/E5.4 shipped: the status table says so and names the shipped artefact."""
    _assert_status_table_is_reconciled(roadmap_example.doc.read_text(encoding="utf-8"))


def test_section_10_states_the_shipped_validation_contract(
    roadmap_example: RoadmapExample,
) -> None:
    """`parse_file`/`load_tasks` silent; `validate_tasks` reports the three rules (§10)."""
    _assert_section_10_is_reconciled(roadmap_example.doc.read_text(encoding="utf-8"))


def test_the_three_surfaces_name_the_shipped_validation(
    roadmap_example: RoadmapExample,
) -> None:
    """The Done-when's rg hits: the status table, §6 and §10 all name the shipped pass."""
    text = roadmap_example.doc.read_text(encoding="utf-8")

    assert any("validate_tasks" in row for row in _status_rows(text))
    assert "validate_tasks" in _section(text, "## 6. ")
    assert "validate_tasks" in _section(text, SECTION_10_HEADING)
    assert "aidw tasks --validate" in _section(text, SECTION_10_HEADING)


def test_section_1_lists_validate_in_the_tasks_surface(
    roadmap_example: RoadmapExample,
) -> None:
    """`--validate` is part of the documented `aidw tasks` surface (§1)."""
    section = _section(
        roadmap_example.doc.read_text(encoding="utf-8"), "## 1. One format, one owner"
    )
    tasks_line = next(
        line for line in section.splitlines() if line.strip().startswith("- `aidw tasks`")
    )
    assert "--validate" in tasks_line


def test_section_10_uses_the_modules_rule_tokens_verbatim(
    roadmap_example: RoadmapExample,
) -> None:
    """The doc's rule list is the module's `RULE_*` set — re-typing it would let it drift."""
    section = _section(roadmap_example.doc.read_text(encoding="utf-8"), SECTION_10_HEADING)
    tokens = (RULE_MISSING_DONE_WHEN, RULE_DUPLICATE_ID, RULE_OUTSIDE_EPIC)

    assert len(set(tokens)) == 3
    assert [token for token in tokens if f"`{token}`" in section] == list(tokens)


def test_the_reconciliation_pins_are_not_vacuous(roadmap_example: RoadmapExample) -> None:
    """Doctoring the doc back to the stale wording fails the pins (they are not vacuous).

    Metamorphic and deterministic: the doc's current bytes are edited in memory only — the
    real document is never written to — and each re-introduced stale claim must flip the
    reconciler from passing to `AssertionError`. This is the same drift-proof shape as
    `tests/test_roadmap.py::test_a_broken_done_when_line_in_the_doc_example_changes_done_when`.
    """
    text = roadmap_example.doc.read_text(encoding="utf-8")
    _assert_status_table_is_reconciled(text)
    _assert_section_10_is_reconciled(text)

    header = SECTION_10_HEADING + "\n"
    assert header in text
    for stale in STALE_VALIDATION_CLAIMS:
        doctored = text.replace(header, f"{header}\n- **{stale}.**\n", 1)
        assert doctored != text, f"could not re-introduce {stale!r}"
        with pytest.raises(AssertionError):
            _assert_section_10_is_reconciled(doctored)

    # A status row marked "not done" again is caught by the same pin.
    validation_row = next(row for row in _status_rows(text) if "Format *validation*" in row)
    regressed = text.replace(
        validation_row, validation_row.replace("(done —", "(not done —"), 1
    )
    assert regressed != text
    with pytest.raises(AssertionError):
        _assert_status_table_is_reconciled(regressed)


# --------------------------------------------------------------------------- #
# The shared selector (tests/conftest.py, E5.4)
# --------------------------------------------------------------------------- #


def test_the_shared_selector_rejects_a_second_complete_example(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """One guard, one home (E5.4): a second complete example fails loudly, not silently.

    This is the property that makes a single source meaningful. With the selector copied
    into each test file, a second worked example could satisfy one copy (which happens to
    find its own) while the other kept parsing the first — exactly the doc/parser drift the
    guard exists to prevent.
    """
    example = roadmap_example.text()
    doc = tmp_path / "two-examples.md"
    doc.write_text(
        "# Roadmap format\n\n"
        f"```markdown\n{example}```\n\n"
        f"```markdown\n{example}```\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="exactly one complete worked example"):
        roadmap_example.text(doc=doc)


def test_reading_the_example_writes_nothing_outside_tmp_path(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """No cached copy and no stray I/O: the doc is only read; ``tmp_path`` gets one file."""
    doc_before = roadmap_example.doc.read_bytes()

    first = roadmap_example.text()
    second = roadmap_example.text()
    path = roadmap_example.write(tmp_path)

    assert first == second == path.read_text(encoding="utf-8")
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [roadmap_example.name]
    assert roadmap_example.doc.read_bytes() == doc_before


# --------------------------------------------------------------------------- #
# The worked example, through the shipped parser
# --------------------------------------------------------------------------- #


def test_example_parses_to_the_documented_fields(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    path = roadmap_example.write(tmp_path)
    tasks = parse_file(path, roadmap_example.phase)

    assert [task.task for task in tasks] == ["E5.1", "E5.2", "E6.1"]
    assert [task.title for task in tasks] == [
        "Write the format contract",
        "Generalise the parser",
        "Move markers into resolved config",
    ]
    assert [task.done for task in tasks] == [True, False, False]

    # `epic` is derived from the id, and matches the `## Epic` heading only by convention.
    assert [task.epic for task in tasks] == ["E5", "E5", "E6"]
    assert [task.epic for task in tasks] == [derive_epic(task.task) for task in tasks]
    assert [task.epic_title for task in tasks] == [
        "Roadmap contracts",
        "Roadmap contracts",
        "Frozen GitHub contracts",
    ]

    # The phase comes from the filename; the matching `# Phase 07:` heading supplies the title.
    assert {task.phase for task in tasks} == {roadmap_example.phase}
    assert [task.phase_title for task in tasks] == ["Example phase"] * 3

    # `done_when` is the first physical line only — the doc says the block is `_done_when_block`'s.
    assert [task.done_when for task in tasks] == [
        "the format doc states the five-regex contract and the worked example in it",
        "the fixture repo's roadmap parses without any code change.",
        "the bundled scripts still run standalone with no config present.",
    ]

    # CITATION_RE captures `Design N` only; the `EXTRACTION.md` ref is the other channel (§8).
    assert [task.citations for task in tasks] == [["Design 11"], ["Design 11.1"], []]

    assert tasks[0].file == roadmap_example.name
    assert tasks[0].line < tasks[1].line < tasks[2].line
    assert [task.key for task in tasks] == ["07-E5.1", "07-E5.2", "07-E6.1"]
    assert [task.branch for task in tasks] == ["07-E5.1", "07-E5.2", "07-E6.1"]


def test_example_has_no_collapsed_id(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """The E0.7 rule-1 guard: every parsed id kept its period (§5)."""
    tasks = parse_file(roadmap_example.write(tmp_path), roadmap_example.phase)
    assert tasks, "no tasks parsed from the doc's worked example"
    bad = [task.task for task in tasks if "." not in task.task]
    assert not bad, f"MISPARSE: the doc's example has collapsed ids {bad}"


def test_example_parses_through_load_tasks(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    roadmap_example.write(tmp_path)
    # A non-matching filename in the same directory must be ignored (§3).
    (tmp_path / "notes.md").write_text("# Notes\n\n## Epic A: Alpha\n", encoding="utf-8")

    tasks = load_tasks(tmp_path, DEFAULT_GLOB)

    assert [task.task for task in tasks] == ["E5.1", "E5.2", "E6.1"]
    assert all("." in task.task for task in tasks)
    assert find_task(tasks, roadmap_example.phase, "E5", "E5.2") is not None
    assert find_task(tasks, "7", "E5", "E5.2") is None  # phase must be the filename's `07`
    assert next_todo(tasks).task == "E5.2"
    assert [task.task for task in filter_tasks(tasks, todo=True)] == ["E5.2", "E6.1"]
    assert [task.task for task in filter_tasks(tasks, epic="E6")] == ["E6.1"]
    assert [task.task for task in filter_tasks(tasks, phase="99")] == []
    assert next_todo(tasks, phase="99") is None


def test_example_parsing_is_deterministic_and_read_only(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """No input mutation and no undeclared I/O: the file is only ever read."""
    path = roadmap_example.write(tmp_path)
    before = path.read_bytes()

    first = _snapshot(parse_file(path, roadmap_example.phase))
    second = _snapshot(parse_file(path, roadmap_example.phase))

    assert first == second
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- #
# The Done-when block: both readers
# --------------------------------------------------------------------------- #


def test_example_done_when_block_survives_the_prompt_reread(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    path = roadmap_example.write(tmp_path)
    tasks = parse_file(path, roadmap_example.phase)
    lines = path.read_text(encoding="utf-8").splitlines()

    multi = tasks[0]
    block = prompt_workflow._done_when_block(lines, multi.line - 1)

    # Both continuation lines survive...
    assert block.startswith("  - Done when:")
    assert "the format doc states the five-regex contract and the worked example in it" in block
    assert "parses with the shipped parser, and the full pytest suite is green." in block
    # ...the one-line `done_when` is a prefix of the full block...
    assert multi.done_when in block
    # ...and the block stops at the `Tests:` field bullet rather than swallowing it.
    assert "Tests:" not in block
    assert "Deliverable:" not in block
    assert len(block.splitlines()) == 2

    # The bare form (E5.2) is one line; `Notes:` likewise bounds E6.1's block.
    single = prompt_workflow._done_when_block(lines, tasks[1].line - 1)
    assert single.strip() == "Done when: the fixture repo's roadmap parses without any code change."
    notes_bounded = prompt_workflow._done_when_block(lines, tasks[2].line - 1)
    assert "Notes:" not in notes_bounded
    assert tasks[2].done_when in notes_bounded


def test_citation_channels_are_separate(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """`Design N` fills `.citations`; `<NAME>.md` is recovered only by the prompt stage."""
    path = roadmap_example.write(tmp_path)
    tasks = parse_file(path, roadmap_example.phase)
    lines = path.read_text(encoding="utf-8").splitlines()

    # `_render_cited_specs` locates a doc ref under the *target root*, so give it one.
    migration = tmp_path / "docs" / "migration"
    migration.mkdir(parents=True)
    (migration / "EXTRACTION.md").write_text(
        "# Migration\n\n### 3.7 Roadmap model (D6/D15)\n\n"
        "### 3.9 Persisted GitHub contracts\n",
        encoding="utf-8",
    )
    repo = TargetRepo(
        root=tmp_path, git_dir=tmp_path / ".git", common_dir=tmp_path / ".git"
    )

    rendered = prompt_workflow._render_cited_specs(
        repo,
        tasks[0],
        lines[tasks[0].line - 1],
        prompt_workflow._done_when_block(lines, tasks[0].line - 1),
    )
    assert "- Design 11 → design.md §11" in rendered
    assert "- EXTRACTION.md → docs/migration/EXTRACTION.md §3.7" in rendered
    # The doc ref never reaches `.citations`, which is the `Design N` channel alone.
    assert tasks[0].citations == ["Design 11"]

    # A doc-ref-only entry still renders through the second channel.
    assert tasks[2].citations == []
    doc_ref_only = prompt_workflow._render_cited_specs(
        repo,
        tasks[2],
        lines[tasks[2].line - 1],
        prompt_workflow._done_when_block(lines, tasks[2].line - 1),
    )
    assert "- EXTRACTION.md → docs/migration/EXTRACTION.md §3.9" in doc_ref_only


_ENTRY_VARIANTS = [
    # Canonical: two-space bulleted field form.
    "  - Done when: the check passes.",
    # Tolerated by DONE_RE: bare, unbulleted, and at column 0.
    "  Done when: the check passes.",
    "Done when: the check passes.",
    # Tolerated: emphasis around the label, any casing, and no colon at all.
    "  - **Done when:** the check passes.",
    "  - DONE WHEN: the check passes.",
    "  - Done when the check passes.",
]


@pytest.mark.parametrize("done_line", _ENTRY_VARIANTS)
def test_done_when_forms_are_metamorphic(
    tmp_path: Path, roadmap_example: RoadmapExample, done_line: str
) -> None:
    """Every tolerated `Done when` spelling parses to identical fields (a metamorphic test).

    Deterministic and pinned (no generator, no dependency): this repo has no property-testing
    library and AGENTS.md forbids adding a dependency inside an unrelated task.
    """
    for gap in ("", "\n"):
        text = (
            "## Epic A: Alpha\n\n"
            "- [ ] **A1. One task** (Design 11)\n"
            f"{gap}{done_line}\n"
            "\n- [ ] **A2. Two**\n  - Done when: second.\n"
        )
        path = tmp_path / "07 - Variants.md"
        path.write_text(text, encoding="utf-8")

        tasks = parse_file(path, roadmap_example.phase)

        assert [task.task for task in tasks] == ["A1", "A2"]
        assert tasks[0].done is False
        assert tasks[0].done_when == "the check passes."
        assert tasks[0].citations == ["Design 11"]
        # The tolerated blank line before `Done when` does not leak into the next entry.
        assert tasks[1].done_when == "second."
        # Both readers agree the block is one line and stop before the next entry.
        lines = text.splitlines()
        assert "the check passes." in prompt_workflow._done_when_block(lines, 2)


def test_blank_line_inside_the_block_truncates_both_readers(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    text = (
        "## Epic A: Alpha\n\n"
        "- [ ] **A1. One task**\n"
        "  - Done when: the first paragraph.\n"
        "\n"
        "  A paragraph after a blank line.\n"
    )
    path = tmp_path / "07 - Truncated.md"
    path.write_text(text, encoding="utf-8")

    tasks = parse_file(path, roadmap_example.phase)
    assert tasks[0].done_when == "the first paragraph."
    block = prompt_workflow._done_when_block(text.splitlines(), tasks[0].line - 1)
    assert block == "  - Done when: the first paragraph."


def test_blank_lines_before_done_when_are_tolerated(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """E0.7 rule 5 is stale: both shipped readers skip blank lines *before* the label."""
    text = (
        "## Epic A: Alpha\n\n"
        "- [ ] **A1. One task**\n"
        "\n"
        "  Prose between the entry and its check.\n"
        "\n"
        "  - Done when: still found.\n"
    )
    path = tmp_path / "07 - Gaps.md"
    path.write_text(text, encoding="utf-8")

    tasks = parse_file(path, roadmap_example.phase)
    assert tasks[0].done_when == "still found."
    assert "still found." in prompt_workflow._done_when_block(text.splitlines(), 2)


def test_field_bullet_indent_is_exactly_two_spaces() -> None:
    assert prompt_workflow._FIELD_BULLET_RE.match("  - Tests: x")
    assert prompt_workflow._FIELD_BULLET_RE.match("  - Done when: x")
    assert prompt_workflow._FIELD_BULLET_RE.match("  - Notes: x")
    for line in (
        "   - Tests: x",  # three spaces
        " - Tests: x",  # one space
        "    - Tests: x",  # four spaces
        "  -Tests: x",  # no space after the dash
        "\t- Tests: x",  # tab
        "  Tests: x",  # unbulleted
    ):
        assert not prompt_workflow._FIELD_BULLET_RE.match(line), line


def test_a_second_done_when_line_is_never_merged(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """The doc's §6 rule: a bulleted second line truncates the block, a bare one continues it.

    `parse_file` keeps the first Done-when in both forms; `_done_when_block` differs — the
    bulleted `  - Done when:` is a field bullet (§7) and bounds the block, so the second
    bulleted line is silently dropped from the stage evidence bundle.
    """
    header = "## Epic A: Alpha\n\n- [ ] **A1. One task**\n"

    # Canonical (bulleted) second Done-when: a field-bullet boundary — the block truncates.
    bulleted = tmp_path / "07 - Bulleted.md"
    bulleted.write_text(
        header + "  - Done when: first.\n  - Done when: second.\n", encoding="utf-8"
    )
    tasks = parse_file(bulleted, roadmap_example.phase)
    assert tasks[0].done_when == "first."  # `parse_file` keeps the first, in both forms
    block = prompt_workflow._done_when_block(
        (header + "  - Done when: first.\n  - Done when: second.\n").splitlines(),
        tasks[0].line - 1,
    )
    assert block == "  - Done when: first."
    assert "second." not in block  # truncated at the field bullet, not merged

    # Bare (unbulleted) second Done-when: not a field bullet — carried as continuation.
    bare = tmp_path / "07 - Bare.md"
    bare.write_text(
        header + "  - Done when: first.\n  Done when: second.\n", encoding="utf-8"
    )
    tasks = parse_file(bare, roadmap_example.phase)
    assert tasks[0].done_when == "first."
    block = prompt_workflow._done_when_block(
        (header + "  - Done when: first.\n  Done when: second.\n").splitlines(),
        tasks[0].line - 1,
    )
    assert "second." in block

    # And the doc's §6 bullet states the distinction rather than the false blanket claim.
    text = roadmap_example.doc.read_text(encoding="utf-8")
    assert "**truncates the" in text  # the bulleted-second truncation rule is stated
    assert "_done_when_block` includes the second" not in text  # the old false claim is gone


def test_a_misindented_field_is_swallowed_into_the_done_when_block(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """The doc's indent trap: four spaces is not a boundary, so the field leaks in."""
    text = (
        "## Epic A: Alpha\n\n"
        "- [ ] **A1. One task**\n"
        "  - Done when: the check.\n"
        "    - Tests: tests/test_thing.py\n"
        "  - Deliverable: the thing.\n"
    )
    path = tmp_path / "07 - Indent.md"
    path.write_text(text, encoding="utf-8")

    tasks = parse_file(path, roadmap_example.phase)
    block = prompt_workflow._done_when_block(text.splitlines(), tasks[0].line - 1)

    assert "Tests:" in block  # mis-indented: swallowed into the Done-when block
    assert "Deliverable:" not in block  # correctly indented: a real boundary


# --------------------------------------------------------------------------- #
# The documented traps
# --------------------------------------------------------------------------- #


def test_missing_period_collapses_the_id(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """E0.7 rule 1 / the doc's §5 trap, asserted rather than described."""
    text = (
        "## Epic E0: Extraction\n\n"
        "- [x] **E0.1 Create the new repository**\n"
        "  - Done when: the repo exists.\n"
    )
    path = tmp_path / "07 - Collapsed.md"
    path.write_text(text, encoding="utf-8")

    tasks = parse_file(path, roadmap_example.phase)

    assert [task.task for task in tasks] == ["E0"]
    assert tasks[0].title == "1 Create the new repository"
    assert tasks[0].epic == "E"
    assert find_task(tasks, roadmap_example.phase, "E0", "E0.1") is None


def test_phase_id_comes_from_the_filename_not_the_heading(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    lines = (
        "{heading}\n\n## Epic A: Alpha\n\n- [ ] **A1. One task**\n  - Done when: done.\n"
    )

    # Matching heading sets the cosmetic title; the phase is still the filename's `07`.
    matching = tmp_path / roadmap_example.name
    matching.write_text(lines.format(heading="# Phase 07: Seven"), encoding="utf-8")
    task = parse_file(matching, roadmap_example.phase)[0]
    assert task.phase == "07"
    assert task.phase_title == "Seven"

    # `7` is the same phase (`parse_file`'s guard strips the leading zero)...
    stripped = tmp_path / "07 - Stripped.md"
    stripped.write_text(lines.format(heading="# Phase 7: Seven"), encoding="utf-8")
    assert parse_file(stripped, roadmap_example.phase)[0].phase_title == "Seven"

    # ...but a heading for `0` never matches a `00 -` file, and the phase is unaffected.
    zero = tmp_path / "00 - Zero.md"
    zero.write_text(lines.format(heading="# Phase 0: Zero"), encoding="utf-8")
    zero_task = parse_file(zero, "00")[0]
    assert zero_task.phase == "00"
    assert zero_task.phase_title is None


@pytest.mark.parametrize(
    ("filename", "phase"),
    [("07 - Example Roadmap.md", "07"), ("02.5 - Extraction II.md", "02.5")],
)
def test_documented_filename_forms(filename: str, phase: str) -> None:
    assert _FILENAME_RE.match(filename).group(1) == phase


@pytest.mark.parametrize(
    "filename",
    ["7 - Example Roadmap.md", "000 - Extraction.md", "example-roadmap.md"],
)
def test_documented_rejected_filenames(filename: str) -> None:
    assert _FILENAME_RE.match(filename) is None


def test_epic_heading_does_not_supply_the_epic(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """`## Epic X:` is cosmetic: `epic` is derived, so a mismatched heading is inert."""
    text = (
        "## Epic ZZ: Mismatched\n\n"
        "- [ ] **E5.1. One task**\n"
        "  - Done when: done.\n"
    )
    path = tmp_path / "07 - Mismatched.md"
    path.write_text(text, encoding="utf-8")

    task = parse_file(path, roadmap_example.phase)[0]

    assert task.epic == "E5"
    assert task.epic_title == "Mismatched"
    assert find_task([task], roadmap_example.phase, "E5", "E5.1") is not None
