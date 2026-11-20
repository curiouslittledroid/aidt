"""Prompt library inventory after the MF.2 cutover (EXTRACTION.md §4.2, E7.1 + MF.2).

Executable half of ``docs/migration/prompt-classification.md``. §4.2 fixed the inventory by
naming three buckets over the toolkit's 31 top-level ``prompts/*.md`` files:

- **bucket (i)** generic, ship as-is (6 files);
- **bucket (ii)** mixed, neutralised in E7.2 (5 files);
- **bucket (iii)** wholly Mythical Forge (20 files).

**The cutover split bucket (iii).** 17 of the 20 moved to Mythical Forge's ``aidw/prompts/``
(MF.2), where they shadow the toolkit default by filename; the other 3 were **retained here and
neutralised**, because the default registry invokes them — ``task-prompt.md`` is stage ``P1`` of
the ``prompt`` workflow, and ``update-traceability.md`` / ``update-architecture.md`` are stages
``I3`` / ``I4`` of the default ``implement`` chain. Deleting those three would make a target repo
with no ``aidw/`` folder unable to run at all, which is §8.3's acceptance criterion, so MF.2's
"none remains in the toolkit" is deviated from deliberately (`design.md` §17, M4).

**Membership stays spec-fixed, never grepped.** §4.2 deliberately kept ``git-update.md`` and
``review-findings-to-github.md`` in (i) despite their frozen marker strings, and ``task-prompt.md``
in (iii) even though it named the toolkit's own prompt directory. The table↔directory check is
bidirectional in both directions that matter now: a file present here with no row fails, and a file
§4.2 assigns that is neither present nor listed as moved fails.

**Deliberate exceptions were carved out after the cutover (class (v)).** C1.3 inlines the
repo's resolved gate commands into the five gate-recording prompts (design §7.3 step 5);
``code-review.md`` is one of them, so its review-order step 6 gained gate-command guidance. G1.1
adds the required ``Kind:`` classification line and the full-re-read rule to ``task-review.md``
(design §8.1, §17 Z18). A byte-frozen file nobody may edit cannot stay frozen once it is edited:
both are re-classified ``(v)`` in the doc and removed from :data:`BYTE_FROZEN`, while every other
bucket (i) file stays byte-frozen. The spec's own bucket (i) list is still §4.2's six — the
exceptions are asserted explicitly rather than silently narrowing the spec's membership.

**Two retired mechanisms are gone by design.** E7.1's ``destination:`` frontmatter marker travelled
with the 17 files and no toolkit prompt carries it any more (asserted below, so it cannot creep
back); and the "metadata-only edit changed no body" comparisons are now meaningful only for bucket
(i) minus class (v), which is the one class whose contract is still "byte-identical".
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
from aidw.prompts import PromptError, load_prompt_file, render

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

#: The three §4.2 bucket (iii) files that stayed: the default registry invokes them, so the
#: toolkit needs a product-free default for each (MF.2 retention, `design.md` §17 M4).
BUCKET_RETAINED = (
    "task-prompt.md",
    "update-architecture.md",
    "update-traceability.md",
)

#: The seventeen §4.2 bucket (iii) files that moved to Mythical Forge's ``aidw/prompts/`` at
#: MF.2. They must be absent from the toolkit, and their names are still the contract there.
BUCKET_MOVED = (
    "doc-lambdas.md",
    "implement-srd-followup.md",
    "integration-tests.md",
    "manual-test-plan.md",
    "show-updated-integration-tests.md",
    "show-updated-player-actions.md",
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
)

#: §4.2 (iii) as the spec states it: 20 files, the union of the two tuples above.
BUCKET_PRODUCT = (*BUCKET_RETAINED, *BUCKET_MOVED)

#: Prompts added **after** the MF.2 cutover, so §4.2's 31-file inventory does not classify
#: them. Class (iv) is their own row: `update-roadmap.md` is H3.1's core `I7` stage,
#: `summarize-implementation-results.md` is X1.1's core `I8` stage,
#: `write-integration-test-guide.md` is X1.2's core `I9` stage and `fix-commit.md` is
#: 05-P1.1's core `F5 commit-and-push` stage — all new toolkit defaults that are none of
#: "ship as-is", "neutralised in E7.2" or "retained from (iii)" — back-dating any of them
#: into one of those would misstate its provenance.
POST_CUTOVER = (
    "update-roadmap.md",
    "summarize-implementation-results.md",
    "write-integration-test-guide.md",
    "fix-commit.md",
)

#: The post-cutover **re-classification** (class (v)): a file §4.2 placed in bucket (i) that a
#: later task had to edit, so it can no longer honestly be called "ship as-is".
#: ``code-review.md`` is C1.3's file — its review-order step 6 gained the resolved-gate-commands
#: guidance — and ``task-review.md`` is G1.1's, whose finding block gained the required ``Kind:``
#: line plus the full-re-read rule (design §8.1, §17 Z18). Neither is deliberately folded into
#: bucket (ii) (whose five files are fixed by §4.2 as product-neutralised) or bucket (iv) (which
#: means "added after the cutover"). Every other bucket-(i) file stays byte-frozen.
RECLASSIFIED_AFTER_CUTOVER = ("code-review.md", "task-review.md")

#: Every prompt the toolkit ships, and the only files the table may list.
TOOLKIT_PROMPTS = (
    *BUCKET_GENERIC,
    *BUCKET_MIXED,
    *BUCKET_RETAINED,
    *POST_CUTOVER,
)

EXPECTED_CLASS: dict[str, str] = {
    **{
        name: "i"
        for name in BUCKET_GENERIC
        if name not in RECLASSIFIED_AFTER_CUTOVER
    },
    **{name: "v" for name in RECLASSIFIED_AFTER_CUTOVER},
    **{name: "ii" for name in BUCKET_MIXED},
    **{name: "iii" for name in BUCKET_RETAINED},
    **{name: "iv" for name in POST_CUTOVER},
}

#: One action per class, as the classification table states it (owner in brackets).
ACTION_BY_CLASS = {
    "i": "ship as-is",
    "ii": "neutralised in E7.2",
    "iii": "retained and neutralised in MF.2",
    "iv": "added after the cutover",
    "v": "re-classified out of (i) after the cutover",
}

#: The destination cell for every class: all fourteen stay in the toolkit. The seventeen
#: moved files are listed outside the table, so no row may name the target repo's folder.
TOOLKIT_DESTINATION = "toolkit `prompts/`"
TARGET_DESTINATION = "aidw/prompts/"

#: E7.1's pending-move marker. Retired at MF.2 (the move happened) — asserted absent so it
#: cannot creep back into a prompt body, where it would render into the agent message.
RETIRED_MARKER = "destination:"

#: Bucket (i) minus the post-cutover re-classification is byte-frozen: it is the class whose
#: action was "ship as-is". Buckets (ii)/(iii) were edited by E7.2 and MF.2 respectively, class
#: (v) was edited by C1.3, and their contracts are ``tests/test_prompt_neutrality.py`` (for the
#: neutralised four) and the C1.3 gate-block tests.
BYTE_FROZEN = tuple(
    name for name in BUCKET_GENERIC if name not in RECLASSIFIED_AFTER_CUTOVER
)

#: The positional variables each retained default must declare, as its stage passes them
#: (``aidw/stage_registry.py``): P1 passes phase/epic/task, I3 the branch, I4 branch+base.
STAGE_ARITY: dict[str, tuple[str, ...]] = {
    "task-prompt.md": ("02", "L5", "L5.2"),
    "update-traceability.md": ("07-E9.9",),
    "update-architecture.md": ("07-E9.9", "main"),
}

#: §4.2 spells six of the twenty as one brace expression rather than six names.
BRACE_GROUP = (
    "update-rules-engine-diagram-{combat,movement,progression,skills,spells,vision-world}.md"
)

#: ``| `file.md` | class | action | destination |`` — the table's only row shape.
_TABLE_ROW = re.compile(r"^\|\s*`([^`]+\.md)`\s*\|(.+)\|\s*$")
_POSITIONAL = re.compile(r"\$(\d+)")


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
    """The top-level ``prompts/*.md`` files the toolkit ships.

    ``aidw.inventory.list_files`` also returns ``scripts/review-followup/*.py`` (the bundled
    review helpers, ``REQUIRED_SCRIPTS``). Those are toolkit-owned code, not prompts, so the
    prompt set is taken from the directory's top level only.
    """
    root = toolkit_root() / "prompts"
    return sorted(path.name for path in root.glob("*.md") if path.is_file())


def _table_rows(text: str | None = None) -> dict[str, list[str]]:
    """Every classification row, keyed by filename; values are class/action/destination."""
    rows: dict[str, list[str]] = {}
    for line in (text if text is not None else _doc()).splitlines():
        match = _TABLE_ROW.match(line)
        if match is None:
            continue
        name = match.group(1)
        cells = [cell.strip() for cell in match.group(2).split("|")]
        assert len(cells) == 3, (
            f"row for {name!r} must have class/action/destination columns, got {cells}"
        )
        assert name not in rows, f"duplicate classification row for {name!r}"
        rows[name] = cells
    return rows


def _raw(name: str) -> str:
    return (toolkit_root() / "prompts" / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _baseline_revision() -> str:
    """The pre-E7.1 revision: the first parent of the commit that introduced the marker.

    ``git log -S`` (pickaxe) lists every commit that changed how often ``RETIRED_MARKER``+value
    occurs under ``prompts/`` — the E7.1 commit that added the markers and the MF.2 commit that
    removed them with the files. ``--reverse`` puts the introduction first, so that commit's first
    parent is the tree the marker commit was applied to, which is what bucket (i)'s "unchanged"
    claim is measured against. Resolving it from the marker rather than from ``HEAD`` keeps the
    oracle armed after the cutover merge: ``merge-base HEAD origin/main`` collapses to ``HEAD`` on
    ``main``, the compare-the-tree-to-itself tautology review follow-up #108 closed.

    Pickaxe needs only history, which CI already fetches in full for the D5 freeze golden
    (``fetch-depth: 0``, ``.github/workflows/ci.yml``).
    """
    marker_line = f"{RETIRED_MARKER} mythical-forge/aidw/prompts/"
    completed = subprocess.run(
        ["git", "log", "--reverse", "--format=%H", f"-S{marker_line}", "--", "prompts"],
        cwd=toolkit_root(),
        check=True,
        capture_output=True,
        text=True,
    )
    shas = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not shas:
        # An error, never a skip (the BaselineTagError rule, tests/test_baseline_verbatim_
        # golden.py): a guard that quietly disarms is exactly the defect this oracle exists
        # to prevent.
        raise RuntimeError(
            f"no commit in {toolkit_root()} history introduced '{marker_line}' under "
            "prompts/ — the classification oracle has no baseline; a shallow clone needs "
            "`fetch-depth: 0` (.github/workflows/ci.yml) rather than a disarmed guard."
        )
    return f"{shas[0]}^"


@lru_cache(maxsize=1)
def _parent_prompt_text() -> dict[str, str]:
    """The pre-E7.1 prompt bytes, as bucket (i)'s unchanged-content oracle."""
    completed = subprocess.run(
        ["git", "archive", "--format=tar", _baseline_revision(), "--", "prompts"],
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


# ---------------------------------------------------------------------------
# The inventory: table ↔ directory, in both directions
# ---------------------------------------------------------------------------


def test_table_lists_exactly_the_prompt_files_that_exist():
    """Bidirectional completeness: no unclassified file, no stale row.

    A one-way "every row exists on disk" check silently passes when a future prompt is added
    without a classification row, or when a moved prompt's row outlives the file.
    """
    rows = set(_table_rows())
    files = set(_prompt_files())

    assert rows - files == set(), f"rows for files that do not exist: {sorted(rows - files)}"
    assert files - rows == set(), f"prompts with no classification: {sorted(files - rows)}"
    assert rows == files == set(TOOLKIT_PROMPTS)


def test_the_moved_prompts_are_gone_from_the_toolkit():
    """MF.2 moved seventeen product prompts out; the toolkit must not ship them again.

    Their names remain Mythical Forge's contract (it owns the files under ``aidw/prompts/``),
    so re-adding one here would silently shadow the target's own copy with a stale one.
    """
    present = set(_prompt_files())
    reappeared = sorted(present & set(BUCKET_MOVED))

    assert reappeared == [], f"product prompts moved at MF.2 are back: {reappeared}"


def test_the_classification_partitions_the_specs_31_files():
    """§4.2 counts 6 + 5 + 20 = 31; the cutover splits (iii) into 3 retained + 17 moved."""
    assert (len(BUCKET_GENERIC), len(BUCKET_MIXED), len(BUCKET_PRODUCT)) == (6, 5, 20)
    assert (len(BUCKET_RETAINED), len(BUCKET_MOVED)) == (3, 17)
    assert len(set(BUCKET_PRODUCT)) == len(BUCKET_PRODUCT)
    # 14 files at the cutover plus the post-cutover defaults (H3.1's `I7`, X1.1's `I8`,
    # X1.2's `I9`, 05-P1.1's `F5`).
    assert len(_prompt_files()) == 14 + len(POST_CUTOVER) == 18

    classes = (set(BUCKET_GENERIC), set(BUCKET_MIXED), set(BUCKET_PRODUCT))
    # The three §4.2 buckets partition the inventory: no file is in two, none in none.
    assert classes[0] & classes[1] == set()
    assert classes[0] & classes[2] == set()
    assert classes[1] & classes[2] == set()
    assert set().union(*classes) == (
        set(BUCKET_GENERIC) | set(BUCKET_MIXED) | set(BUCKET_RETAINED)
    ) | set(BUCKET_MOVED)
    assert set(EXPECTED_CLASS) == set(TOOLKIT_PROMPTS)


def test_bucket_membership_matches_the_spec_s_named_lists():
    """§4.2 itself names every file this module classifies, in its stated bucket.

    The spec is read directly, so an edit to §4.2's lists that this module did not follow fails
    rather than silently diverging. It intentionally does not classify by product-token grepping.
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

    prefix, rest = BRACE_GROUP.split("{", 1)
    stems = rest.removesuffix("}.md").split(",")
    expanded = {f"{prefix}{stem}.md" for stem in stems}
    # Exactly the six child-diagram prompts, no more: the parent diagram is named separately
    # in §4.2 and keeps its own entry.
    child_diagrams = {
        name for name in BUCKET_PRODUCT if name.startswith("update-rules-engine-diagram-")
    }
    assert expanded == child_diagrams
    assert "update-rules-engine-diagram.md" not in child_diagrams
    assert all(f"`{name}`" in product for name in set(BUCKET_PRODUCT) - expanded)


def test_each_row_states_its_class_action_and_destination():
    """Action and destination follow the class; the table states one of each per row."""
    for name, (class_cell, action, destination) in _table_rows().items():
        expected_class = EXPECTED_CLASS[name]
        (shown,) = re.findall(r"\((iv|v|i{1,3})\)", class_cell) or [""]

        assert shown == expected_class, (
            f"{name}: classified as ({shown}), the cutover says ({expected_class})"
        )
        assert action == ACTION_BY_CLASS[expected_class], (
            f"{name}: ({expected_class}) action must be "
            f"{ACTION_BY_CLASS[expected_class]!r}, doc says {action!r}"
        )
        assert destination == TOOLKIT_DESTINATION, (
            f"{name}: every prompt the toolkit ships stays in {TOOLKIT_DESTINATION!r}, "
            f"doc says {destination!r}"
        )
        assert TARGET_DESTINATION not in destination


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


def test_the_reclassified_prompts_are_out_of_the_spec_bucket_and_the_freeze():
    """The class-(v) files: §4.2 still says (i), the tree no longer can.

    §4.2's bucket-(i) list is a historical authoring claim, so it is kept verbatim (the test
    above still reads it). What must not survive is the *freeze*: a file whose bytes changed
    cannot be called byte-identical to its baseline without the guard disagreeing with the
    tree. The exceptions are asserted in both directions, so neither the doc nor the constant
    can drift and no third file can quietly leave the freeze.
    """
    assert RECLASSIFIED_AFTER_CUTOVER == ("code-review.md", "task-review.md")
    for name in RECLASSIFIED_AFTER_CUTOVER:
        assert EXPECTED_CLASS[name] == "v", name
        assert name in BUCKET_GENERIC, name
        assert name not in BYTE_FROZEN, name
        # Non-vacuous: the file really did move, which is why the class is required.
        assert _raw(name) != _parent_prompt_text()[name], name
    # The split is complete: every §4.2 (i) file is either still frozen or explicitly freed.
    assert set(BYTE_FROZEN) | set(RECLASSIFIED_AFTER_CUTOVER) == set(BUCKET_GENERIC)
    assert set(BYTE_FROZEN) & set(RECLASSIFIED_AFTER_CUTOVER) == set()


# ---------------------------------------------------------------------------
# The retired marker and the surviving byte-frozen class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", TOOLKIT_PROMPTS)
def test_no_toolkit_prompt_carries_the_retired_destination_marker(name: str) -> None:
    """The MF.2 pending-move marker is retired with the files that carried it.

    Asserted on the raw text, which is strictly stronger than asserting on the body: a marker
    outside the leading frontmatter block would render into the agent message, and the move it
    tracked has happened. Naming the target's override folder is still legitimate — a prompt may
    tell the agent that a repo shadow lives under ``aidw/prompts/`` (§12.3) — so only the
    ``destination:`` *field* is retired.
    """
    assert RETIRED_MARKER not in _raw(name)


@pytest.mark.parametrize("name", BYTE_FROZEN)
def test_bucket_i_prompts_are_unchanged_since_the_pre_marker_baseline(name: str) -> None:
    """Bucket (i)'s action is "ship as-is", so its bytes must not have moved.

    Scoped to bucket (i) minus class (v): §5.4 excludes bucket (ii) from byte-frozen coverage
    precisely because E7.2 neutralised it, bucket (iii) was rewritten at MF.2, and C1.3 edited
    ``code-review.md`` and G1.1 edited ``task-review.md`` (class (v),
    ``test_the_reclassified_prompts_are_out_of_the_spec_bucket_and_the_freeze``). The contracts
    for the neutralised files are ``tests/test_prompt_neutrality.py``.
    """
    assert _raw(name) == _parent_prompt_text()[name]


# ---------------------------------------------------------------------------
# The three retained defaults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", BUCKET_RETAINED)
def test_retained_defaults_render_at_the_arity_their_stage_passes(name: str) -> None:
    """Each retained default keeps the positional variables its stage supplies.

    The stage registry renders these with plain data (``stage_registry.py``): the author stage
    passes phase/epic/task, the traceability stage the branch, the architecture stage the branch
    and base branch. Losing a placeholder silently empties an argument the prompt relies on, and
    adding one makes ``render`` raise at run time.
    """
    text = load_prompt_file(toolkit_root() / "prompts" / name)
    expected = STAGE_ARITY[name]
    indices = {int(match) for match in _POSITIONAL.findall(text)}

    assert indices == set(range(1, len(expected) + 1)), name

    rendered = render(text, expected)
    assert not _POSITIONAL.search(rendered), name
    for value in expected:
        assert value in rendered, (name, value)
    with pytest.raises(PromptError):
        render(text, expected[:-1])
