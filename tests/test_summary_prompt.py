"""Contract tests for the `I8` summary prompt (X1.1; design §§8.2, 17 Z3).

``prompts/summarize-implementation-results.md`` is the executable specification of the
narrative summary stage: it owns exactly one artifact, reads the build results as its only
evidence, and runs no gate. These tests are its contract, mirroring
``tests/test_prompt_neutrality.py``'s rendered-prose approach rather than grepping for exact
sentences:

* **Rendered, never templated.** The prompt is read and rendered at its own ``$1`` arity, so
  the text asserted is the text Pi receives (frontmatter stripped, ``$1`` substituted).
* **Ownership and input.** The rendered body names `<implementation_results_dir>/<branch>/summary.md`
  as the only file it may write and `<implementation_results_dir>/<branch>/build-results.md` as
  its input — by *config key*, never a hardcoded target-owned directory.
* **Fixed order, free wording.** §17 Z3 fixes the five sections' order and content and leaves
  the exact heading wording to the implementer, so this test pins five enumerated sections in
  order by concept, not by literal heading string.
* **No gate.** The prompt must never instruct a lint/build/test command; the gate numbers come
  from the build results `I5` already recorded.
* **Honesty.** Recorded failures and `unverified` rows must survive, and no fix may be invented.

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

PROMPT_NAME = "summarize-implementation-results.md"
PROMPT_PATH = toolkit_root() / "prompts" / PROMPT_NAME

#: The one positional variable the `I8` stage passes (``stage_registry``: ``("{branch}",)``).
BRANCH = "04-X1.1"

#: The five section concepts §17 Z3 fixes, in order. Matched case-insensitively as tokens so
#: a reworded heading (explicitly allowed) still satisfies the contract.
SECTION_TOKENS = (
    "problem",
    "core idea",
    "built",
    "deliberately did not do",
    "verification",
)

#: Command tokens that would be a gate instruction. The prompt names no package manager and
#: no runner; it cites the numbers the build results already record instead.
GATE_TOKENS = ("pytest", "uv run", "uv sync", "npm ", "pnpm", "yarn", "make ")

#: Product path literals a toolkit default may not assume (§3.4/§4.2): the config *keys* are
#: the replacement.
PRODUCT_PATHS = (
    "docs/implementation-results",
    "docs/task-prompts",
    "docs/architecture",
    "docs/tasks",
)

_POSITIONAL = re.compile(r"\$(\d+)")
_NUMBERED = re.compile(r"^(\d+)\. \*\*(.+?)\*\*", re.MULTILINE)


def _raw() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _body() -> str:
    return load_prompt_file(PROMPT_PATH)


def _rendered() -> str:
    return render(_body(), (BRANCH,))


def _flat(text: str) -> str:
    """The text with runs of whitespace collapsed, for phrase assertions.

    A prompt body is hard-wrapped prose, so a phrase can straddle a line break; asserting on
    the flattened form keeps the contract about the words, not the wrapping.
    """
    return re.sub(r"\s+", " ", text)


def _instructions(rendered: str) -> str:
    """The rendered `Instructions` section, up to the next `##` heading."""
    start = rendered.index("## Instructions")
    end = rendered.index("\n## ", start + 1)
    return rendered[start:end]


# --------------------------------------------------------------------------- #
# Front matter and arity
# --------------------------------------------------------------------------- #


def test_frontmatter_matches_the_record_prompts_shape() -> None:
    """Same front-matter shape as `record-implementation-results.md` (X1.1 req 1)."""
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


# --------------------------------------------------------------------------- #
# Ownership, input, and self-containment
# --------------------------------------------------------------------------- #


def test_it_owns_exactly_the_summary_artifact_beside_the_build_results() -> None:
    """One owned artifact: `<implementation_results_dir>/<branch>/summary.md`."""
    rendered = _rendered()

    assert "<implementation_results_dir>/<branch>/summary.md" in rendered
    # The one file it may write is declared as such, not merely mentioned.
    assert "only file this prompt may write" in _flat(rendered)
    # And everything it must leave alone is named.
    flat = _flat(rendered)
    for target in ("implementation code", "tests", "specs", "roadmap", "architecture"):
        assert target in flat, target


def test_it_reads_the_build_results_as_its_single_source_of_truth() -> None:
    """`build-results.md` is the input; a summary without it is invention."""
    rendered = _rendered()

    assert "<implementation_results_dir>/<branch>/build-results.md" in rendered
    assert "single source of truth" in _flat(rendered)
    # The task prompt is the second, scoped input (purpose/scope/non-goals only).
    assert "paths.task_prompts_dir" in rendered
    assert "non-goals" in _flat(rendered).lower()


def test_it_names_config_keys_not_hardcoded_target_directories() -> None:
    """Self-contained for `aidw prompts check` (X1.1 req 1's last bullet)."""
    rendered = _rendered()

    assert "paths.implementation_results_dir" in rendered
    for literal in PRODUCT_PATHS:
        assert literal not in rendered, literal
    assert FOREIGN_PREFIX not in rendered


# --------------------------------------------------------------------------- #
# The five sections, in order, wording free
# --------------------------------------------------------------------------- #


def test_the_instructions_enumerate_exactly_five_sections_in_the_fixed_order() -> None:
    """§17 Z3: order and content fixed; heading wording is implementer freedom.

    The five numbered section entries are matched by concept rather than by literal
    heading, so a reworded heading satisfies the contract while a reordered, merged or
    dropped section does not.
    """
    items = [
        (int(number), body)
        for number, body in _NUMBERED.findall(_instructions(_rendered()))
    ]

    assert len(items) == len(SECTION_TOKENS) == 5
    assert [number for number, _ in items] == [1, 2, 3, 4, 5]
    for (_number, body), token in zip(items, SECTION_TOKENS):
        assert token in body.lower(), (token, body)


def test_it_tells_the_writer_to_explain_why_without_re_tabling_the_audit_rows() -> None:
    """Descriptive voice: no second Files-Changed table, no second gate table."""
    rendered = _rendered()

    flat = _flat(rendered)
    assert "Descriptive voice" in flat
    assert "do **not** re-table the Files-Changed list" in flat
    # Verification is narrative as well: the prompt must cite I5's recorded outcomes,
    # not create a second gate-results table from them.
    assert "gate outcomes" in flat
    assert "in prose" in flat


# --------------------------------------------------------------------------- #
# No gate, no invented results
# --------------------------------------------------------------------------- #


def test_it_never_instructs_a_lint_build_or_test_command() -> None:
    """X1.1 trap: `I5` is the only stage that buys the gate; re-running it doubles it."""
    rendered = _rendered().lower()
    present = [token for token in GATE_TOKENS if token in rendered]

    assert present == [], present
    # And the prohibition is explicit, not merely absent.
    flat = _flat(rendered)
    assert "never re-run a verification gate" in flat.lower()
    assert "it runs no gate" in flat.lower()


def test_it_preserves_recorded_failures_and_unverified_rows() -> None:
    """Honesty: a recorded failure stays a failure; `unverified` keeps its reason."""
    rendered = _rendered().lower()

    assert "unverified" in rendered
    assert "a recorded failure stays a failure" in rendered
    assert "never invent" in rendered or "no invented results" in rendered
    assert "fabrication" in rendered


# --------------------------------------------------------------------------- #
# Property sweep (pinned seed + numRuns; no hypothesis dependency)
# --------------------------------------------------------------------------- #

PROPERTY_SEED = 4_110_2026
PROPERTY_NUM_RUNS = 32


def test_property_every_rendering_keeps_the_contract_and_never_mutates_the_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        assert "<implementation_results_dir>/<branch>/summary.md" in rendered, branch
        assert "<implementation_results_dir>/<branch>/build-results.md" in rendered, branch
        assert "## Instructions" in rendered, branch
        items = _NUMBERED.findall(_instructions(rendered))
        assert len(items) == 5, branch
        for (_number, body), token in zip(items, SECTION_TOKENS):
            assert token in body.lower(), (branch, token)
        for literal in PRODUCT_PATHS:
            assert literal not in rendered, (branch, literal)

    # Purity: the template is unchanged after every rendering.
    assert _body() == before


def test_property_seed_and_run_count_are_pinned() -> None:
    """The property test's budget is explicit, matching the repo's pytest-only convention."""
    assert PROPERTY_SEED == 4_110_2026
    assert PROPERTY_NUM_RUNS == 32
    assert isinstance(PROMPT_PATH, Path) and PROMPT_PATH.is_file()
