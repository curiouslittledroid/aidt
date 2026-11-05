"""Classification and destination-marker contract for the prompt library (E7.1).

Executable half of ``docs/migration/prompt-classification.md``, which applies
EXTRACTION.md §4.2's three buckets to the toolkit's 31 top-level ``prompts/*.md`` files:

- **bucket (i)** generic, ship as-is (6 files);
- **bucket (ii)** mixed, neutralised in E7.2 (5 files);
- **bucket (iii)** wholly Mythical Forge, moved to ``aidw/prompts/`` at cutover, §7 MF.2
  (20 files).

Membership is spec-fixed by §4.2's *named lists*, never re-derived by grepping for product
tokens: §4.2 deliberately keeps ``git-update.md`` and ``review-findings-to-github.md`` in
(i) despite their frozen marker strings and ``task-prompt.md`` in (iii) even though it names
``aidt/prompts``. The table↔directory check is therefore bidirectional — a future prompt
added without a classification row, or a stale row for a deleted prompt, fails here rather
than at cutover.

Until MF.2 nothing moves. Each bucket (iii) file carries its intended destination as a
``destination:`` frontmatter field, and the marker is inert because
``aidw/prompts.py:strip_frontmatter`` removes the leading ``---`` block before rendering —
so the text Pi receives is byte-identical to the text before the marker existed. A marker
placed in the *body* would render into the agent message, which is the trap these tests
close. The marker also must never contain the foreign prefix ``.pi/prompts``: that sentinel
(``aidw/inventory.py:FOREIGN_PREFIX``) turns ``aidw prompts check`` red for every file under
``prompts/``.
"""

from __future__ import annotations

import io
import re
import subprocess
import tarfile
from functools import lru_cache
from pathlib import Path

import pytest

from aidw.paths import toolkit_root
from aidw.prompts import load_prompt_file, strip_frontmatter

DOC_REL = Path("docs") / "migration" / "prompt-classification.md"
SPEC_REL = Path("docs") / "migration" / "EXTRACTION.md"

#: §4.2 (i) "Generic — ship as-is (6)".
BUCKET_GENERIC = (
    "approve-review-followups.md",
    "code-review.md",
    "git-update.md",
    "review-findings-to-github.md",
    "task-review-fixes.md",
    "task-review.md",
)

#: §4.2 (ii) "Mixed — path and tooling names, small edits (5)".
BUCKET_MIXED = (
    "fix-next-review-followup.md",
    "impliment-task.md",
    "pr.md",
    "record-implementation-results.md",
    "test.md",
)

#: §4.2 (iii) "Wholly Mythical Forge — product prompts (20)".
BUCKET_PRODUCT = (
    "doc-lambdas.md",
    "implement-srd-followup.md",
    "integration-tests.md",
    "manual-test-plan.md",
    "show-updated-integration-tests.md",
    "show-updated-player-actions.md",
    "task-prompt.md",
    "update-architecture.md",
    "update-authentication-sequence-diagram.md",
    "update-infrastructure-diagram.md",
    "update-lambda-dataflow-diagram.md",
    "update-player-ws-message-flow-diagram.md",
    "update-rules-engine-diagram-combat.md",
    "update-rules-engine-diagram-movement.md",
    "update-rules-engine-diagram-progression.md",
    "update-rules-engine-diagram-skills.md",
    "update-rules-engine-diagram-spells.md",
    "update-rules-engine-diagram-vision-world.md",
    "update-rules-engine-diagram.md",
    "update-traceability.md",
)

EXPECTED_BUCKET: dict[str, str] = {
    **{name: "i" for name in BUCKET_GENERIC},
    **{name: "ii" for name in BUCKET_MIXED},
    **{name: "iii" for name in BUCKET_PRODUCT},
}

#: One action per bucket, as the classification table states it (owner in brackets).
ACTION_BY_BUCKET = {
    "i": "ship as-is",
    "ii": "neutralise in E7.2",
    "iii": "move at cutover in MF.2",
}

MARKER_FIELD = "destination:"
MARKER_VALUE = "mythical-forge/aidw/prompts/"
MARKER_LINE = f"{MARKER_FIELD} {MARKER_VALUE}"

#: The destination folder as the classification table names it (prose, not frontmatter).
PRODUCT_DESTINATION = "aidw/prompts/"

#: The three bucket (iii) files that had no frontmatter before E7.1 and therefore gained a
#: minimal block carrying only the destination field.
NO_FRONTMATTER = ("integration-tests.md", "manual-test-plan.md", "task-prompt.md")

#: §4.2 spells six of the twenty as one brace expression rather than six names.
BRACE_GROUP = (
    "update-rules-engine-diagram-{combat,movement,progression,skills,spells,vision-world}.md"
)

#: Bucket (i)/(ii) files keep their destination in the table only — no marker in the file.
UNMARKED = (*BUCKET_GENERIC, *BUCKET_MIXED)

#: ``| `file.md` | bucket | action | destination |`` — the table's only row shape.
_TABLE_ROW = re.compile(r"^\|\s*`([^`]+\.md)`\s*\|(.+)\|\s*$")
_FRONTMATTER_BLOCK = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)


# ---------------------------------------------------------------------------
# Doc and directory readers
# ---------------------------------------------------------------------------


def _doc() -> str:
    return (toolkit_root() / DOC_REL).read_text(encoding="utf-8")


def _section_42() -> str:
    """§4.2's block: its heading up to the next ``###`` heading."""
    spec = (toolkit_root() / SPEC_REL).read_text(encoding="utf-8")
    start = spec.index("### 4.2 Prompts")
    end = spec.index("### 4.3 ", start)
    return spec[start:end]


def _prompt_files() -> list[str]:
    """The 31 top-level ``prompts/*.md`` files.

    ``aidw.inventory.list_files`` also returns ``scripts/review-followup/*.py`` (the bundled
    review helpers, ``REQUIRED_SCRIPTS``). Those are toolkit-owned code, not prompts, so the
    prompt set is taken from the directory's top level only.
    """
    root = toolkit_root() / "prompts"
    return sorted(path.name for path in root.glob("*.md") if path.is_file())


def _table_rows(text: str | None = None) -> dict[str, list[str]]:
    """Every classification row, keyed by filename; values are bucket/action/destination."""
    rows: dict[str, list[str]] = {}
    for line in (text if text is not None else _doc()).splitlines():
        match = _TABLE_ROW.match(line)
        if match is None:
            continue
        name = match.group(1)
        cells = [cell.strip() for cell in match.group(2).split("|")]
        assert len(cells) == 3, (
            f"row for {name!r} must have bucket/action/destination columns, got {cells}"
        )
        assert name not in rows, f"duplicate classification row for {name!r}"
        rows[name] = cells
    return rows


def _raw(name: str) -> str:
    return (toolkit_root() / "prompts" / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _parent_prompt_text() -> dict[str, str]:
    """Load the parent revision's prompt bytes as the E7.1 no-body-edit oracle.

    The implementation adds metadata to files that are already tracked, so checking only
    that the marker is absent from the current body would miss an accidental body edit. A
    single archive keeps this regression check independent of the implementation's own
    classification constants and avoids one Git process per prompt.
    """
    completed = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD", "--", "prompts"],
        cwd=toolkit_root(),
        check=True,
        capture_output=True,
    )
    with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
        return {
            member.name.removeprefix("prompts/"): archive.extractfile(member).read().decode(
                "utf-8"
            )
            for member in archive.getmembers()
            if member.isfile() and member.name.startswith("prompts/")
        }


def _frontmatter_block(raw: str) -> str:
    """The leading ``---`` … ``---`` block including its delimiters, or ``""``."""
    match = _FRONTMATTER_BLOCK.match(raw)
    return match.group(0) if match is not None else ""


def _marker_lines(block: str) -> list[str]:
    return [line for line in block.splitlines() if line.startswith(MARKER_FIELD)]


# ---------------------------------------------------------------------------
# The inventory: table ↔ directory, in both directions
# ---------------------------------------------------------------------------


def test_table_classifies_exactly_the_prompt_files_that_exist():
    """Bidirectional completeness: no unclassified file, no stale row.

    A one-way "every row exists on disk" check silently passes when a future prompt is
    added without a classification row, which is precisely the failure E7.1 must prevent.
    """
    rows = set(_table_rows())
    files = set(_prompt_files())

    assert rows - files == set(), f"rows for files that do not exist: {sorted(rows - files)}"
    assert files - rows == set(), f"prompts with no classification: {sorted(files - rows)}"
    assert rows == files


def test_the_classification_covers_the_specs_31_files():
    """§4.2 counts 6 + 5 + 20 = 31; a drift in any bucket changes this total."""
    assert len(_prompt_files()) == 31
    assert (len(BUCKET_GENERIC), len(BUCKET_MIXED), len(BUCKET_PRODUCT)) == (6, 5, 20)
    assert set(EXPECTED_BUCKET) == set(_prompt_files())
    assert (
        set(BUCKET_GENERIC) | set(BUCKET_MIXED) | set(BUCKET_PRODUCT)
    ) == set(_prompt_files())
    # The three buckets partition the inventory: no file is in two, none in none.
    assert set(BUCKET_GENERIC) & set(BUCKET_MIXED) == set()
    assert set(BUCKET_GENERIC) & set(BUCKET_PRODUCT) == set()
    assert set(BUCKET_MIXED) & set(BUCKET_PRODUCT) == set()


def test_table_bucket_membership_is_the_section_4_2_assignment():
    """Each row's bucket cell is the spec's bucket for that file — 6/5/20 exactly.

    A classification re-derived by grep (product tokens, package names, ``aidt/prompts``)
    fails here: §4.2's frozen-marker files and ``task-prompt.md`` would land elsewhere.
    """
    rows = _table_rows()

    for name, cells in rows.items():
        bucket = cells[0].strip("()")
        assert bucket in ACTION_BY_BUCKET, f"{name}: unrecognised bucket {cells[0]!r}"
        assert bucket == EXPECTED_BUCKET[name], (
            f"{name}: classified as ({bucket}), §4.2 says ({EXPECTED_BUCKET[name]})"
        )

    assert sum(1 for cells in rows.values() if cells[0].strip("()") == "i") == 6
    assert sum(1 for cells in rows.values() if cells[0].strip("()") == "ii") == 5
    assert sum(1 for cells in rows.values() if cells[0].strip("()") == "iii") == 20


def test_bucket_membership_matches_the_spec_s_named_lists():
    """§4.2 itself names every file this module classifies, in its stated bucket.

    The doc is the source of truth, so the guard reads each bucket's subsection: an edit to
    §4.2's lists that this table (and these constants) did not follow fails rather than
    silently diverging. This intentionally does not classify by product-token grepping.
    """
    section = _section_42()
    generic_start = section.index("**(i) Generic")
    mixed_start = section.index("**(ii) Mixed", generic_start)
    product_start = section.index("**(iii) Wholly", mixed_start)
    generic = section[generic_start:mixed_start]
    mixed = section[mixed_start:product_start]
    product = section[product_start:]

    assert all(f"`{name}`" in generic for name in BUCKET_GENERIC)
    assert all(f"`{name}`" in mixed for name in BUCKET_MIXED)

    assert BRACE_GROUP in product
    prefix, rest = BRACE_GROUP.split("{", 1)
    stems = rest.removesuffix("}.md").split(",")
    expanded = {f"{prefix}{stem}.md" for stem in stems}
    # Exactly the six child-diagram prompts, no more: the parent diagram is named
    # separately in §4.2 and keeps its own row.
    child_diagrams = {
        name
        for name in BUCKET_PRODUCT
        if name.startswith("update-rules-engine-diagram-")
    }
    assert expanded == child_diagrams
    assert "update-rules-engine-diagram.md" not in child_diagrams
    assert all(
        f"`{name}`" in product for name in set(BUCKET_PRODUCT) - expanded
    )


def test_each_row_states_its_bucket_s_action_and_destination():
    """Action and destination follow the bucket; the table states one of each per row."""
    rows = _table_rows()

    for name, (bucket_cell, action, destination) in rows.items():
        bucket = bucket_cell.strip("()")
        assert action == ACTION_BY_BUCKET[bucket], (
            f"{name}: ({bucket}) action must be {ACTION_BY_BUCKET[bucket]!r}, "
            f"doc says {action!r}"
        )
        if bucket == "iii":
            assert "Mythical Forge" in destination
            assert PRODUCT_DESTINATION in destination
        else:
            assert "toolkit" in destination
            # The remain-in-the-toolkit buckets never point at the new repo's folder. At
            # MF.2 Mythical Forge supplies *overrides* for bucket (ii) (D14 pt 2); the
            # toolkit default itself does not move.
            assert PRODUCT_DESTINATION not in destination


def test_the_table_parser_fails_closed_on_a_malformed_row():
    """The guard is not vacuous: a row missing a column, or a duplicate, is rejected."""
    malformed = "| `code-review.md` | (i) | ship as-is |\n"
    with pytest.raises(AssertionError):
        _table_rows(malformed)

    duplicate = (
        "| `code-review.md` | (i) | ship as-is | toolkit `prompts/` |\n"
        "| `code-review.md` | (i) | ship as-is | toolkit `prompts/` |\n"
    )
    with pytest.raises(AssertionError):
        _table_rows(duplicate)


# ---------------------------------------------------------------------------
# The marker: present, frontmatter-only, inert
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", BUCKET_PRODUCT)
def test_product_prompts_declare_their_destination_in_frontmatter(name: str) -> None:
    """Bucket (iii) carries exactly one ``destination:`` field, in the leading block."""
    raw = _raw(name)
    block = _frontmatter_block(raw)

    assert block != "", f"{name}: no leading frontmatter block"
    assert _marker_lines(block) == [MARKER_LINE], (
        f"{name}: expected one `{MARKER_LINE}` field in the frontmatter block, "
        f"found {_marker_lines(block)}"
    )
    # Exactly once in the whole file, so no stray copy can live in the body.
    assert raw.count(MARKER_LINE) == 1


@pytest.mark.parametrize("name", BUCKET_PRODUCT)
def test_the_marker_never_reaches_the_rendered_prompt(name: str) -> None:
    """The note is inert: frontmatter is stripped, so the rendered body carries no marker.

    A body note would render into the agent message and change the prompt's behaviour;
    ``aidw/prompts.py:strip_frontmatter`` only removes the leading block, which is why the
    marker belongs there and nowhere else.
    """
    raw = _raw(name)
    block = _frontmatter_block(raw)
    body = strip_frontmatter(raw)

    assert MARKER_FIELD not in body
    assert MARKER_VALUE not in body
    # The file is exactly "block + body": nothing precedes the block and nothing else was
    # added by the marker.
    assert raw == block + body
    # The loader Pi's message comes from returns that same body.
    assert load_prompt_file(toolkit_root() / "prompts" / name) == body


@pytest.mark.parametrize("name", BUCKET_PRODUCT)
def test_product_prompt_rendering_matches_the_parent_revision(name: str) -> None:
    """Adding the destination field does not change the prompt sent to Pi.

    Compare the rendered current file with the parent revision, rather than merely checking
    that the current marker is in a frontmatter block. This catches an accidental body edit
    in the same change, including edits to the three files that had no frontmatter before E7.1.
    """
    assert load_prompt_file(toolkit_root() / "prompts" / name) == strip_frontmatter(
        _parent_prompt_text()[name]
    )


@pytest.mark.parametrize("name", UNMARKED)
def test_unmarked_prompt_content_matches_the_parent_revision(name: str) -> None:
    """Bucket (i)/(ii) prompts are byte-for-byte unchanged in this metadata-only task."""
    assert _raw(name) == _parent_prompt_text()[name]


@pytest.mark.parametrize("name", NO_FRONTMATTER)
def test_files_without_frontmatter_gained_only_the_minimal_block(name: str) -> None:
    """The three NO-FM files got ``---`` + the field + ``---``, and nothing else.

    A note appended after the ``# `` heading would render; a block that also carried other
    fields would not be the "minimal block carrying only that field" E7.1 specifies.
    """
    raw = _raw(name)
    block = _frontmatter_block(raw)

    assert block == f"---\n{MARKER_LINE}\n---\n"
    assert raw == block + strip_frontmatter(raw)
    assert strip_frontmatter(raw).startswith("# ")


@pytest.mark.parametrize(
    "name", [name for name in BUCKET_PRODUCT if name not in NO_FRONTMATTER]
)
def test_existing_frontmatter_was_extended_not_replaced(name: str) -> None:
    """The 17 files that already had frontmatter kept their existing fields."""
    block = _frontmatter_block(_raw(name))

    assert block.startswith("---\n")
    assert block.endswith("---\n")
    assert "description:" in block
    # Every non-empty line of the block is a ``key: value`` field, so the block was not
    # flattened into prose by the edit.
    for line in block.splitlines():
        assert line == "---" or re.match(r"^[a-z][a-z-]*:\s?\S", line), line


@pytest.mark.parametrize("name", UNMARKED)
def test_generic_and_mixed_prompts_carry_no_marker(name: str) -> None:
    """Bucket (i)/(ii) destinations live in the table only — no field, no body edit.

    Bucket (ii)'s neutralisation is E7.2's: those five files must still read exactly as they
    do today, and ``pr.md`` in particular is already "partly edited ahead of E7.2" (§4.2) and
    must be left as found.
    """
    raw = _raw(name)

    # Asserted on the raw text, which is strictly stronger than asserting on the body: no
    # field exists, so none can leak into the renderable text.
    assert MARKER_FIELD not in raw
    assert MARKER_VALUE not in raw
