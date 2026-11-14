"""Contract tests for the `I9` integration-test-guide prompt (X1.2; design §§8.2, 17 Z6).

``prompts/write-integration-test-guide.md`` is the executable specification of the human-run
integration-test stage: it owns exactly one artifact, derives every scenario from the build
results, the task prompt and the branch's changed files, and **executes nothing**. These tests
are its contract, mirroring ``tests/test_summary_prompt.py``'s rendered-prose approach rather
than grepping for exact sentences:

* **Rendered, never templated.** The prompt is read and rendered at its own ``$1`` arity, so
  the text asserted is the text Pi receives (frontmatter stripped, ``$1`` substituted).
* **Ownership and input.** The rendered body names
  `<implementation_results_dir>/<branch>/integration-test-guide.md` as the only file it may
  write, and ``build-results.md``, the task prompt under ``paths.task_prompts_dir`` and the
  branch's changed files as its inputs — by *config key*, never a hardcoded target-owned
  directory.
* **Fixed order, free wording.** §17 Z6 fixes four sections in order and leaves the exact
  heading wording to the implementer, so this test pins four enumerated sections in order by
  concept, not by literal heading string; the scenario section carries the five roadmap-fixed
  per-scenario fields, and the two closing sections (teardown, could-not-exercise) are
  mandatory.
* **An instruction document, never an execution.** The prompt must never instruct a
  lint/build/test command, nor any command touching a cloud account, a browser or a deployed
  stack; read-only ``git`` and file inspection are the only commands allowed.
* **No invented commands.** An unconfirmable flag/subcommand/route is reported ``unconfirmed``;
  recorded ``unverified`` rows stay unverified.

The property sweep at the bottom is this repo's pytest-only substitute for ``hypothesis``
(AGENTS.md "Tests"): a pinned seed and run count, no shrinking. It renders the same template
across random branch names and asserts the invariants hold for every one, and that rendering
never mutates the template.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from aidw.inventory import FOREIGN_PREFIX
from aidw.paths import toolkit_root
from aidw.prompts import PromptError, load_prompt_file, render

PROMPT_NAME = "write-integration-test-guide.md"
PROMPT_PATH = toolkit_root() / "prompts" / PROMPT_NAME

#: The one positional variable the `I9` stage passes (``stage_registry``: ``("{branch}",)``).
BRANCH = "04-X1.2"

#: The four section concepts §17 Z6 fixes, in order (heading wording is implementer freedom).
SECTION_TOKENS = (
    "covers",
    "scenario",
    "teardown",
    "could not be exercised",
)

#: The five roadmap-fixed per-scenario fields, in order.
SCENARIO_FIELD_TOKENS = (
    "prerequisite",
    "command",
    "expected",
    "pass",
    "cost",
)

#: Command tokens that would be an execution instruction. The prompt names no package
#: manager and no runner: the human reading the guide runs it, never this stage.
EXECUTION_TOKENS = ("pytest", "uv run", "uv sync", "npm ", "pnpm", "yarn", "make ")

#: Product path literals a toolkit default may not assume (§3.4/§4.2): the config *keys* are
#: the replacement.
PRODUCT_PATHS = (
    "docs/implementation-results",
    "docs/task-prompts",
    "docs/architecture",
    "docs/tasks",
)

_POSITIONAL = re.compile(r"\$(\d+)")
#: Top-level numbered instruction entries (the scenarios' sub-fields are indented).
_SECTION = re.compile(r"^(\d+)\. \*\*(.+?)\*\*", re.MULTILINE)
#: Indented numbered entries: the scenario fields nested under the scenarios section.
_FIELD = re.compile(r"^\s+(\d+)\. \*\*(.+?)\*\*", re.MULTILINE)


def _raw() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _body() -> str:
    return load_prompt_file(PROMPT_PATH)


def _rendered() -> str:
    return render(_body(), (BRANCH,))


def _flat(text: str) -> str:
    """The text with runs of whitespace collapsed, for phrase assertions."""
    return re.sub(r"\s+", " ", text)


def _instructions(rendered: str) -> str:
    """The rendered `Instructions` section, up to the next `##` heading."""
    start = rendered.index("## Instructions")
    end = rendered.index("\n## ", start + 1)
    return rendered[start:end]


def _sections(rendered: str) -> list[tuple[int, str]]:
    """The top-level numbered entries as ``(number, bold heading)``, in document order."""
    return [(int(number), body) for number, body in _SECTION.findall(_instructions(rendered))]


def _bodies(rendered: str) -> dict[int, str]:
    """Each top-level section's full text: its own entry up to the next one.

    The bold heading alone is too narrow for the closing-section checks (which pin prose),
    and ``str.index`` on a numbered prefix would stop at the indented scenario sub-fields.
    """
    instructions = _instructions(rendered)
    matches = list(_SECTION.finditer(instructions))
    bodies: dict[int, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(instructions)
        bodies[int(match.group(1))] = instructions[match.start() : end]
    return bodies


def _scenarios(rendered: str) -> str:
    """The scenarios section, from its own entry up to the teardown entry."""
    return _bodies(rendered)[2]


# --------------------------------------------------------------------------- #
# Front matter and arity
# --------------------------------------------------------------------------- #


def test_frontmatter_matches_the_summary_prompts_shape() -> None:
    """Same front-matter shape as `summarize-implementation-results.md` (X1.2 req 1)."""
    raw = _raw()

    assert raw.startswith("---\n")
    front = raw.split("---\n", 2)[1]
    assert "description:" in front
    assert 'argument-hint: "[branch]"' in front


def test_the_prompt_declares_exactly_the_one_variable_its_stage_passes() -> None:
    """The registry passes ``{branch}``; a lost or extra placeholder breaks rendering."""
    indices = {int(match) for match in _POSITIONAL.findall(_body())}

    assert indices == {1}
    rendered = _rendered()
    assert not _POSITIONAL.search(rendered)
    assert BRANCH in rendered
    with pytest.raises(PromptError):
        render(_body(), ())


def test_branch_text_is_inserted_once_not_reinterpreted_as_a_template_field() -> None:
    """A branch containing placeholder-looking text remains literal after rendering."""
    branch = "feature-$1-{branch}"

    rendered = render(_body(), (branch,))

    assert branch in rendered
    assert "feature-04-X1.2" not in rendered


# --------------------------------------------------------------------------- #
# Ownership, input, and self-containment
# --------------------------------------------------------------------------- #


def test_it_owns_exactly_the_integration_guide_beside_the_build_results() -> None:
    """One owned artifact: `<implementation_results_dir>/<branch>/integration-test-guide.md`."""
    rendered = _rendered()

    assert "<implementation_results_dir>/<branch>/integration-test-guide.md" in rendered
    # The one file it may write is declared as such, not merely mentioned.
    assert "only file this prompt may write" in _flat(rendered)
    # And everything it must leave alone is named.
    flat = _flat(rendered)
    for target in ("implementation code", "tests", "specs", "roadmap", "architecture"):
        assert target in flat, target


def test_it_names_the_deliberate_not_integration_tests_filename() -> None:
    """D14 trap: `integration-tests.md` is a product prompt a target would shadow."""
    body = _raw()

    assert PROMPT_PATH.name == "write-integration-test-guide.md"
    assert "integration-tests.md" not in body


def test_it_reads_build_results_the_task_prompt_and_the_changed_files() -> None:
    """The three inputs: the recorded evidence, the task's scope, the touched surfaces."""
    rendered = _rendered()

    assert "<implementation_results_dir>/<branch>/build-results.md" in rendered
    assert "read it **in full**" in _flat(rendered)
    assert "paths.task_prompts_dir" in rendered
    # The changed files come from read-only git, the only commands the stage may run.
    assert "git diff --name-only" in rendered
    assert "git status" in rendered
    flat = _flat(rendered).lower()
    assert "read-only" in flat and "changed files" in flat


def test_it_names_config_keys_not_hardcoded_target_directories() -> None:
    """Self-contained for `aidw prompts check` (X1.2 req 1's last bullet)."""
    rendered = _rendered()

    assert "paths.implementation_results_dir" in rendered
    for literal in PRODUCT_PATHS:
        assert literal not in rendered, literal
    assert FOREIGN_PREFIX not in rendered


# --------------------------------------------------------------------------- #
# The four sections, in order, and the five fields per scenario
# --------------------------------------------------------------------------- #


def test_the_instructions_enumerate_exactly_four_sections_in_the_fixed_order() -> None:
    """§17 Z6: order and content fixed; heading wording is implementer freedom."""
    items = _sections(_rendered())

    assert len(items) == len(SECTION_TOKENS) == 4
    assert [number for number, _ in items] == [1, 2, 3, 4]
    for (_number, body), token in zip(items, SECTION_TOKENS):
        assert token in body.lower(), (token, body)


def test_every_scenario_carries_the_five_roadmap_fields_in_order() -> None:
    """The five fields are roadmap-fixed: a dropped or reordered one fails here."""
    fields = [(int(number), body) for number, body in _FIELD.findall(_scenarios(_rendered()))]

    assert len(fields) == len(SCENARIO_FIELD_TOKENS) == 5
    assert [number for number, _ in fields] == [1, 2, 3, 4, 5]
    for (_number, body), token in zip(fields, SCENARIO_FIELD_TOKENS):
        assert token in body.lower(), (token, body)


def test_the_two_closing_sections_are_mandatory() -> None:
    """Teardown and the honest "could not be exercised" section must both exist (trap)."""
    bodies = _bodies(_rendered())
    teardown = _flat(bodies[3]).lower()
    limit = _flat(bodies[4]).lower()

    assert "teardown" in teardown
    assert "could not be exercised in this environment" in limit
    assert "mandatory" in limit or "must" in limit
    # And the guide may not claim coverage it cannot confirm.
    assert "fabrication" in limit


def test_it_covers_the_surfaces_the_change_might_touch() -> None:
    """CLI/TUI, browser and external (for example cloud-provider) surfaces are named."""
    flat = _flat(_rendered()).lower()

    for token in ("cli", "tui", "browser", "cloud", "deployed"):
        assert token in flat, token


# --------------------------------------------------------------------------- #
# An instruction document, never an execution; no invented commands
# --------------------------------------------------------------------------- #


def test_it_never_instructs_a_test_gate_or_cloud_command() -> None:
    """AIDT writes the recipe and a human runs it: no execution token reaches the agent."""
    rendered = _rendered()
    present = [token for token in EXECUTION_TOKENS if token in rendered.lower()]

    assert present == [], present
    # And the prohibition is explicit, not merely absent.
    flat = _flat(rendered).lower()
    assert "never an execution" in flat
    assert "do **not** run an integration test" in flat
    assert "cloud account" in flat and "browser" in flat and "deployed stack" in flat
    assert "read-only `git`" in _flat(rendered)


def test_it_reports_unconfirmable_commands_instead_of_inventing_them() -> None:
    """X1.1's no-invented-results trap, restated for commands."""
    flat = _flat(_rendered())
    lowered = flat.lower()

    assert "unconfirmed" in flat
    assert "never invent" in lowered
    assert "traceab" in lowered
    # The rule is scoped to the three real sources, not to plausibility.
    for source in ("changed file", "build-results row", "task prompt"):
        assert source in flat, source


def test_it_preserves_recorded_unverified_rows() -> None:
    """Honesty: an `unverified` row keeps the reason the build results give."""
    rendered = _rendered().lower()

    assert "unverified" in rendered
    assert "no invented results" in rendered
    assert "never describe a fix" in rendered


# --------------------------------------------------------------------------- #
# Property sweep (pinned seed + numRuns; no hypothesis dependency)
# --------------------------------------------------------------------------- #

PROPERTY_SEED = 4_112_2026
PROPERTY_NUM_RUNS = 32


def test_property_every_rendering_keeps_the_contract_and_never_mutates_the_template() -> None:
    """Every generated branch renders a contract-complete body from the same template.

    ``seed = PROPERTY_SEED``, ``numRuns = PROPERTY_NUM_RUNS`` (pinned, not random per run).
    The generator is deliberately small — digits, dots, dashes and a slash — because a
    branch name reaches the prompt as literal text and must never be re-interpreted as a
    template field or a second positional variable.
    """
    template = _body()
    before = template
    rng = random.Random(PROPERTY_SEED)
    alphabet = "0123456789.-_/abcXYZ"

    for _run in range(PROPERTY_NUM_RUNS):
        branch = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40)))
        rendered = render(template, (branch,))

        assert not _POSITIONAL.search(rendered), branch
        assert "<implementation_results_dir>/<branch>/integration-test-guide.md" in rendered
        assert "<implementation_results_dir>/<branch>/build-results.md" in rendered
        assert "## Instructions" in rendered, branch
        items = _sections(rendered)
        assert len(items) == 4, branch
        for (_number, body), token in zip(items, SECTION_TOKENS):
            assert token in body.lower(), (branch, token)
        fields = _FIELD.findall(_scenarios(rendered))
        assert len(fields) == 5, branch
        for literal in PRODUCT_PATHS:
            assert literal not in rendered, (branch, literal)
        for token in EXECUTION_TOKENS:
            assert token not in rendered.lower(), (branch, token)

    # Purity: the template is unchanged after every rendering.
    assert _body() == before


def test_property_seed_and_run_count_are_pinned() -> None:
    """The property test's budget is explicit, matching the repo's pytest-only convention."""
    assert PROPERTY_SEED == 4_112_2026
    assert PROPERTY_NUM_RUNS == 32
    assert isinstance(PROMPT_PATH, Path) and PROMPT_PATH.is_file()
