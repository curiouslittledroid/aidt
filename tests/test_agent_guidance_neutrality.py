"""Neutrality contract for the shipped agent guidance (E7.4, EXTRACTION.md §4.3).

Executable half of §6 E7.4: every file in ``agents/*/AGENTS.md`` is agent context shipped to Pi
for **any** target repo, so none of them may name a product, a package manager, or a product
document. E7.4 edits the four files §4.3 singles out (``implementer``, ``recorder``,
``pr-publisher``, ``task-author``); the assertion runs over the whole glob, because the other
seven are already clean and must stay clean (the §4.3 "Other 8" row).

**Grepped, not rendered** — the opposite of ``tests/test_prompt_neutrality.py``. These files are
not prompt templates: Pi receives their bytes verbatim as ``--append-system-prompt``
(``aidw/agents.py:125-126``), so the file *is* the text the agent gets and a grep proves exactly
the right thing.

**The vocabulary** is the §4.3 rows' product tokens, split into the same four categories
``tests/test_prompt_neutrality.py`` uses — package managers, product scopes, product path
literals, product doc/verifier tokens — so the two neutrality contracts cannot drift into
disagreeing definitions of "product text". Tokens absent from the files at the base revision
(``yarn``, ``Zod``, ``fast-check``, ``docs/rules-coverage``, ``AGENTS.md §6`` …) stay in the
vocabulary as regression guards: a zero-hit grep for one is not a stop-and-ask trigger, it is a
guard that must stay quiet.

**Four traps this module closes**, each pinned by its own test rather than a comment:

1. *Stage references are not product paths.* ``aidt/prompts/*.md`` (e.g. ``aidt/prompts/pr.md``)
   is a toolkit-internal stage reference that E7.5 owns changing, so Requirement 5 preserves it.
   A blanket "no product path" matcher would flag it and destroy the very text it must keep.
2. *Keys vs paths.* The recorder must name ``paths.build_results_template`` and
   ``paths.implementation_results_dir``; it must never name ``docs/implementation-results`` or
   ``TEMPLATE.md``. A blanket ``results``/``implementation`` match forbids the required
   reference — see ``test_the_matcher_separates_config_keys_from_product_paths``.
3. *Conventions sources stay.* Bare ``AGENTS.md`` and ``aidw/conventions.md`` are legal, indeed
   required (D16): the stack rules were *moved* to them, not deleted. Only the numbered-section
   forms (``AGENTS.md §3``, ``AGENTS.md §6``) are product text.
4. *The implementer's core drop would go untested.* Dropping ``/update-traceability`` and
   ``/update-architecture`` removes text no vocabulary token matches, so it needs its own
   assertion (``test_the_implementer_names_no_traceability_or_architecture_stage``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from aidw.paths import toolkit_root

# --------------------------------------------------------------------------- #
# The seed: the whole glob, not the four edited files (Requirement 6)
# --------------------------------------------------------------------------- #

#: Property-test seed and run count (AGENTS.md "Tests": pytest only, no ``hypothesis``, so the
#: sample *is* the seed and there is no shrinking). Series 1 sweeps every guidance file the
#: toolkit ships, sorted — ``numRuns = AGENTS_NUM_RUNS = len(AGENTS_SEED)``; series 2 sweeps the
#: vocabulary — ``numRuns = VOCABULARY_NUM_RUNS``. Both are pinned by
#: ``test_the_property_seeds_are_the_whole_sample``.
AGENTS_SEED: tuple[Path, ...] = tuple(
    sorted((toolkit_root() / "agents").glob("*/AGENTS.md"))
)
AGENTS_NUM_RUNS = len(AGENTS_SEED)

#: The four files §4.3 assigns to E7.4, relative to the toolkit root.
EDITED = (
    "agents/implementer/AGENTS.md",
    "agents/recorder/AGENTS.md",
    "agents/pr-publisher/AGENTS.md",
    "agents/task-author/AGENTS.md",
)

# --------------------------------------------------------------------------- #
# The vocabulary — the four categories, mirroring tests/test_prompt_neutrality.py
# --------------------------------------------------------------------------- #

#: §3.4: the repo owns its gate commands, so the guidance may not name a package manager.
PACKAGE_MANAGERS = ("pnpm", "npm", "yarn", "uv")

#: §4.2's product scope examples plus the bare stack token §4.3's implementer row carries.
PRODUCT_SCOPES = (
    "@mythical-forge",
    "mythical-forge",
    "rules-engine",
    "player-api",
    "shared-types",
    "infra",
)

#: §3.4/§4.3 product **path literals**. The config *keys* are the replacement and must stay
#: writable — see ``test_the_matcher_separates_config_keys_from_product_paths``.
PRODUCT_PATHS = (
    "docs/implementation-results",
    "docs/task-prompts",
    "docs/architecture",
    "docs/tasks",
    "docs/rules-coverage",
    "docs/conventions/",
    "tests/integration",
    "services/",
    "packages/",
    "apps/",
    "infra/",
    "catalog.json",
    "vectors.ts",
    "report.md",
    ".test.ts",
    "TEMPLATE.md",
)

#: §4.3's product doc/verifier tokens: the implementer's SRD row, the pr-publisher's task-id
#: example, and the numbered ``AGENTS.md`` section references that pointed at the product repo.
PRODUCT_DOCS = (
    "SRD",
    "srd:",
    "matrix-check",
    "srd-traceability",
    "catalog",
    "vector matrix",
    "Design 21",
    "AWS",
    "Zod",
    "fast-check",
    "(03-E2.9)",
    "03-E2.9",
    "AGENTS.md §3",
    "AGENTS.md §6",
)

#: D16's conventions sources — the *replacement* for the moved stack rules, so both bare names
#: stay legal. Only the numbered-section forms above are product text.
CONVENTIONS_SOURCES = ("aidw/conventions.md", "AGENTS.md")

#: Toolkit-internal stage references, deliberately **not** a neutrality violation (Requirement 5).
#: Every agent names its stage as a bare slash-command and pins no prompt **path**: the toolkit's
#: `prompts/` does not live at `aidt/prompts/` (and the target repo's copy of it is deleted at
#: cutover), so a path there was stale for every repo and dangled for the one it named. The stage
#: name is the durable reference — it is what AIDT actually schedules.
STAGE_REFERENCES: dict[str, tuple[str, ...]] = {
    "implementer": ("/impliment-task",),
    "recorder": ("/record-implementation-results",),
    "pr-publisher": ("/pr",),
    "task-author": ("/task-prompt",),
}

#: Requirement 1: the two product stages leave the implementer. No vocabulary token matches
#: either string, so without this tuple the core drop of E7.4 would go untested.
DROPPED_STAGES = ("/update-traceability", "/update-architecture")


def _path(name: str) -> Path:
    return toolkit_root() / "agents" / name / "AGENTS.md"


def _read(name: str) -> str:
    return _path(name).read_text(encoding="utf-8")


def _flat(name: str) -> str:
    """The file with runs of whitespace collapsed, for phrase assertions.

    The guidance is hard-wrapped prose, so a phrase can straddle a newline; the contract is
    the sentence, not the line break.
    """
    return " ".join(_read(name).split())


# --------------------------------------------------------------------------- #
# The matcher — whole words for bare tokens, literals for everything else
# --------------------------------------------------------------------------- #


def _token_pattern(token: str) -> re.Pattern[str]:
    """One forbidden token as a regex.

    A bare alphabetic word (``infra``, ``uv``, ``SRD``, ``AWS``) is matched with ``\\b`` on both
    sides, so ``infrastructure``, ``uvular`` and ``AWSOME`` do not trip it. Anything else — a
    path, a scoped package name, ``(03-E2.9)``, ``vector matrix`` — is matched as an escaped
    literal, because its punctuation or its space is the signal.
    """
    if re.fullmatch(r"[A-Za-z]+", token):
        return re.compile(rf"\b{re.escape(token)}\b")
    return re.compile(re.escape(token))


def _vocabulary() -> tuple[str, ...]:
    return (*PACKAGE_MANAGERS, *PRODUCT_SCOPES, *PRODUCT_PATHS, *PRODUCT_DOCS)


VOCABULARY_NUM_RUNS = len(_vocabulary())


def _forbidden_hits(text: str) -> list[str]:
    """Every forbidden token present in ``text``, in vocabulary order."""
    return [token for token in _vocabulary() if _token_pattern(token).search(text)]


def _iter_agents() -> Iterator[str]:
    """The agent id of every discovered guidance file, from the one glob."""
    for seed_path in AGENTS_SEED:
        yield seed_path.parent.name


#: A numbered section of a target repo's ``AGENTS.md`` is product text (the implementer's
#: ``AGENTS.md`` §3 was the product's stack rule, ``§6`` its traceability rule). The backtick
#: is optional because the base revision wrapped the name in code spans.
_AGENTS_SECTION = re.compile(r"AGENTS\.md`?\s*§\d")

#: A claim that something *other than AIDT* sets up the branch. ``creat(?:e|ing)`` — never
#: ``creates`` — deliberately keeps §3.2's own statement ("``aidw prompt`` creates the task
#: branch and its worktree") legal: the fact is that AIDT creates it, not the agent.
_BRANCH_RECIPE = re.compile(
    r"\bcreat(?:e|ing)\b[^.]{0,60}?\bbranch\b|\bgit (?:checkout -b|switch)\b",
    re.IGNORECASE,
)

#: A branch recipe may appear only as a prohibition — the guidance tells the agent *not* to
#: reach for it (``task-fixer``: "Do not create a branch, commit, push …").
PROHIBITION_MARKERS = ("do not", "don't", "never", "not ", "instead of", "without")


def _unguarded_branch_recipes(text: str) -> list[str]:
    """Each branch-recipe mention with no negation in the preceding clause."""
    flat = " ".join(text.split()).lower()
    unguarded: list[str] = []
    for match in _BRANCH_RECIPE.finditer(flat):
        window = flat[max(0, match.start() - 60) : match.start()]
        if not any(marker in window for marker in PROHIBITION_MARKERS):
            unguarded.append(match.group(0))
    return unguarded


#: §3.2's one legal "creates" sentence: the fact is that ``aidw prompt`` — AIDT, not the
#: agent — creates the task branch and its worktree. It is stripped before the guard below
#: runs. Backtick-insensitive, because the file wraps the command in a code span
#: (`` `aidw prompt` ``); whitespace is flattened by the caller, because the file
#: hard-wraps mid-sentence (review follow-up #116).
_LEGAL_PROMPT_CREATES = re.compile(
    r"aidw\s+prompt\s+creates\s+the\s+task\s+branch\s+and\s+its\s+worktree",
    re.IGNORECASE,
)

#: The "creates" form ``_BRANCH_RECIPE`` deliberately does not match — in both orders the
#: claim occurs in: the base revision's task-author wording put the branch first ("…branch
#: the prompt creates."), a reworded revert puts it last ("the prompt creates the …
#: branch"). ``_BRANCH_RECIPE`` keeps §3.2's own sentence legal by skipping ``creates``
#: entirely, so it can never catch this claim on its own; this guard is the whole-glob half
#: of Requirement 4 (review follow-up #116).
_PROMPT_CREATES_BRANCH = re.compile(
    r"\bprompt\b[^.]{0,40}?\bcreates\b[^.]{0,40}?\bbranch\b"
    r"|\bbranch\b[^.]{0,40}?\bprompt\b[^.]{0,40}?\bcreates\b",
    re.IGNORECASE,
)


def _prompt_creates_branch_claims(text: str) -> list[str]:
    """Remaining "a prompt creates the branch" claims after the one legal sentence goes."""
    flat = " ".join(text.split()).replace("`", "")
    return _PROMPT_CREATES_BRANCH.findall(_LEGAL_PROMPT_CREATES.sub("", flat))


# --------------------------------------------------------------------------- #
# The seed is the whole glob, and every config can still reach its file
# --------------------------------------------------------------------------- #


def _configured_guidance_paths() -> set[Path]:
    """Every ``agents_md:`` target declared by an ``agent-configs/*.yaml`` file."""
    declared: set[Path] = set()
    for config in sorted((toolkit_root() / "agent-configs").glob("*.yaml")):
        raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        agents_md = raw.get("agents_md")
        if agents_md is not None:
            declared.add(toolkit_root() / str(agents_md))
    return declared


def test_the_property_seeds_are_the_whole_sample() -> None:
    """The seed is complete, not a convenient subset (a seed that shrinks proves nothing)."""
    discovered = list((toolkit_root() / "agents").glob("*/AGENTS.md"))
    assert AGENTS_NUM_RUNS == len(AGENTS_SEED) == len(discovered)
    assert AGENTS_NUM_RUNS >= len(EDITED) == 4
    assert set(EDITED) <= {str(path.relative_to(toolkit_root())) for path in AGENTS_SEED}
    assert VOCABULARY_NUM_RUNS == len(set(_vocabulary())) == len(_vocabulary())
    assert VOCABULARY_NUM_RUNS >= 40
    # Requirement 7: every shipped guidance file is still reachable from a config, so the
    # sweep cannot pass over a file no agent loads.
    assert set(AGENTS_SEED) <= _configured_guidance_paths()


@pytest.mark.parametrize(
    "config",
    sorted((toolkit_root() / "agent-configs").glob("*.yaml")),
    ids=lambda path: path.stem,
)
def test_every_agent_config_still_reaches_its_guidance_file(config: Path) -> None:
    """§4.3 / Requirement 7: the edited files stay reachable via each YAML's ``agents_md:``.

    ``aidw agents validate --strict`` is the gate; this is the same fact asserted where a
    later edit to any of the four could silently orphan a file.
    """
    raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    agents_md = raw.get("agents_md")
    assert agents_md is not None, config.name
    resolved = toolkit_root() / str(agents_md)
    assert resolved.is_file(), (config.name, agents_md)
    assert resolved in AGENTS_SEED, (config.name, agents_md)


# --------------------------------------------------------------------------- #
# The neutrality assertion itself, over the whole vocabulary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(_iter_agents()))
def test_no_agents_guidance_names_a_product_package_manager_or_product_doc(name: str) -> None:
    """The guidance carries no forbidden token (§6 E7.4 done-when).

    Collected rather than failing on the first hit: one run reports every offending token
    with the file that carries it.
    """
    hits = _forbidden_hits(_read(name))

    assert hits == [], f"agents/{name}/AGENTS.md: forbidden token(s): {hits}"


def test_the_vocabulary_covers_every_category_without_overlap() -> None:
    """The four categories are the whole vocabulary and none is empty.

    A category quietly emptied (say ``PRODUCT_DOCS`` losing its entries) would make the
    assertion above pass vacuously for that kind of token, which is exactly the failure a
    neutrality test must not have.
    """
    categories = (PACKAGE_MANAGERS, PRODUCT_SCOPES, PRODUCT_PATHS, PRODUCT_DOCS)

    assert all(category for category in categories)
    vocabulary = _vocabulary()
    assert len(vocabulary) == len(set(vocabulary))
    assert set(vocabulary) == set().union(*categories)


def test_the_matcher_separates_config_keys_from_product_paths() -> None:
    """The replacement keys must stay writable; the literals they replace must not be.

    The recorder *must* name ``paths.build_results_template`` and
    ``paths.implementation_results_dir`` (that is the fix); ``docs/implementation-results`` and
    ``TEMPLATE.md`` are the defect. Pinning both halves keeps a later "tidy-up" from widening
    the vocabulary into a blanket ``results``/``implementation`` match that would forbid the
    required references.
    """
    keys = (
        "paths.build_results_template",
        "paths.implementation_results_dir",
        "paths.roadmap_dir",
        "paths.task_prompts_dir",
        "paths.architecture_dir",
        "docs/task_prompts_dir",  # a path, but not one of the forbidden literals
    )
    for key in keys:
        assert _forbidden_hits(key) == [], key

    literals = {
        "docs/implementation-results": "docs/implementation-results",
        "docs/task-prompts": "docs/task-prompts",
        "docs/architecture": "docs/architecture",
        "docs/tasks": "docs/tasks",
        "catalog.json": "catalog.json",
        "vectors.ts": "vectors.ts",
        "report.md": "report.md",
        "thing.test.ts": ".test.ts",
        "docs/implementation-results/TEMPLATE.md": "docs/implementation-results",
    }
    for literal, token in literals.items():
        assert token in _forbidden_hits(literal), literal


def test_the_matcher_matches_bare_tokens_as_whole_words_only() -> None:
    """``infra`` and ``AWS`` are forbidden; ``infrastructure`` and ``AWSOME`` are not.

    The same whole-word rule covers the other bare tokens: ``uv``/``npm``/``pnpm`` are package
    managers, ``pnpm-workspace.yaml`` still contains the whole word, and a scoped package name
    is matched as a literal because its ``@``/``-`` is the signal.
    """
    assert _forbidden_hits("deployed infrastructure, schema, and security") == []
    assert _forbidden_hits("AWSOME and uvular") == []
    assert _forbidden_hits("infra") == ["infra"]
    assert _forbidden_hits("an infra/ directory") == ["infra", "infra/"]
    assert _forbidden_hits("uv sync --frozen") == ["uv"]
    assert _forbidden_hits("a pnpm-workspace.yaml file") == ["pnpm"]
    assert _forbidden_hits("AWS resources") == ["AWS"]
    assert _forbidden_hits("the SRD") == ["SRD"]
    assert _forbidden_hits("@mythical-forge/rules-engine") == [
        "@mythical-forge",
        "mythical-forge",
        "rules-engine",
    ]


def test_the_legal_replacements_are_not_forbidden() -> None:
    """Requirement 5's and D16's replacements must stay writable.

    The toolkit's own stage paths, the config keys, the two conventions sources, the neutral
    branch vocabulary and both task-id placeholders are the *fix*; forbidding any of them would
    make the four files impossible to write.
    """
    legal = (
        "aidt/prompts/pr.md",
        "aidt/prompts/record-implementation-results.md",
        "aidt/prompts/task-prompt.md",
        "paths.build_results_template",
        "paths.implementation_results_dir",
        *CONVENTIONS_SOURCES,
        "base branch",
        "never write on the base branch",
        "{phase}-{task}",
        "<phase>-<task>",
    )
    for text in legal:
        assert _forbidden_hits(text) == [], text


# --------------------------------------------------------------------------- #
# The prescribed replacements are actually present
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(STAGE_REFERENCES))
def test_toolkit_stage_references_are_preserved(name: str) -> None:
    """Requirement 5: E7.5 owns the ``aidt/prompts/*.md`` path change, not this task."""
    text = _read(name)
    for reference in STAGE_REFERENCES[name]:
        assert reference in text, f"agents/{name}/AGENTS.md: lost {reference}"


def test_the_implementer_names_no_traceability_or_architecture_stage() -> None:
    """Requirement 1 / D13: those are repo-optional stages, not the implementer's own steps.

    No vocabulary token matches either string, so this assertion — not the neutrality sweep —
    is what pins the core drop of E7.4.
    """
    text = _read("implementer")

    for dropped in DROPPED_STAGES:
        assert dropped not in text, dropped
    assert re.findall(r"(?<![A-Za-z0-9_])/[a-z][a-z0-9-]*", text) == ["/impliment-task"]
    assert "do not open a pr" in text.lower()
    assert "AGENTS.md" in text
    assert "aidw/conventions.md" in text


#: Review follow-up #117: the config's ``description:`` is what a human or router reads to
#: pick the agent, so it is guidance text under the same contract as the ``AGENTS.md`` file
#: it points at — and the pre-E7.4 clause ("then owns traceability and architecture docs in
#: the same session") contradicted the neutralised guidance (D13) while the sweep only reads
#: ``agents/*/AGENTS.md``. ``same session`` is guarded too because the promise's effect —
#: routing traceability/architecture work to the implementer — lives in that clause, not in
#: the two vocabulary words alone.
_CONFIG_DROPPED_CLAUSES = ("traceability", "architecture", "same session")


def _config_description(name: str) -> str:
    """The ``description:`` field of ``agent-configs/<name>.yaml``, whitespace flattened."""
    path = toolkit_root() / "agent-configs" / f"{name}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return " ".join(str(raw["description"]).split())


def _config_description_claims(text: str) -> list[str]:
    """Every pre-E7.4 duty clause token present in a config description."""
    flat = " ".join(text.split()).lower()
    return [token for token in _CONFIG_DROPPED_CLAUSES if token in flat]


def test_the_implementer_config_description_promises_no_traceability_or_architecture_duty() -> None:
    """Review follow-up #117: the catalogue entry matches the neutralised guidance (D13).

    The description is router-facing, so the pre-E7.4 clause there reintroduces the duty the
    neutralised ``agents/implementer/AGENTS.md`` denies even though the sweep never reads
    the YAML. The neutral duty — leaving the change uncommitted — must be present instead.
    """
    assert _config_description_claims(_config_description("implementer")) == []
    assert "uncommitted" in _config_description("implementer").lower()


def test_the_config_description_guard_is_live() -> None:
    """The guard is live on exactly the reverted wording review follow-up #117 quotes."""
    reverted = (
        "Implements a task prompt as code plus module contract/property tests, then owns "
        "traceability and architecture docs in the same session."
    )
    assert _config_description_claims(reverted) == list(_CONFIG_DROPPED_CLAUSES)


@pytest.mark.parametrize("name", sorted(_iter_agents()))
def test_no_agents_guidance_names_a_numbered_section_of_agents_md(name: str) -> None:
    """The implementer's ``AGENTS.md §3`` was the *product* repo's §3, not this toolkit's.

    The stack rule moved to the conventions sources, so a numbered-section reference to a
    target repo's ``AGENTS.md`` would now point at the wrong document.
    """
    assert _AGENTS_SECTION.findall(_read(name)) == [], name


def test_the_numbered_section_guard_is_live() -> None:
    """The guard is live, with and without the code span the base revision wrapped the name in."""
    assert _AGENTS_SECTION.findall("see `AGENTS.md` §3") != []
    assert _AGENTS_SECTION.findall("per AGENTS.md §6") != []
    assert _AGENTS_SECTION.findall("the repo's `AGENTS.md` and `aidw/conventions.md`") == []


def test_the_recorder_names_the_two_config_keys_instead_of_the_literals() -> None:
    """Requirement 2: config-driven paths, matching the neutralised record prompt."""
    text = _read("recorder")

    assert "paths.build_results_template" in text
    assert "paths.implementation_results_dir" in text
    assert "docs/implementation-results" not in text
    assert "TEMPLATE.md" not in text


def test_the_pr_publisher_uses_a_generic_task_id_example() -> None:
    """Requirement 3: the ``(03-E2.9)`` Mythical Forge task id is gone, the convention stays.

    The section headings and the never-merge / base-branch rules match ``prompts/pr.md``, so
    they are the generic conventions and are kept; only the repo-specific example changes.
    """
    text = _flat("pr-publisher")

    assert "(03-E2.9)" not in text
    assert "<phase>-<task>" in text
    assert "`## Summary`" in text
    assert "`## Changes`" in text
    assert "`## Verification`" in text
    assert "Never merge" in text
    assert "base branch" in text
    assert "Repo-specific PR conventions come from the repo's" in text
    assert "AGENTS.md" in text and "aidw/conventions.md" in text


def test_the_task_author_states_aidt_owns_branch_setup() -> None:
    """Requirement 4 / §3.2: AIDT creates the branch, and the agent never writes on the base."""
    text = _flat("task-author")

    assert "AIDT owns branch setup" in text
    assert "never" in text.lower() and "write on the base branch" in text.lower()
    assert "Work only on the dedicated" not in text


@pytest.mark.parametrize("name", sorted(_iter_agents()))
def test_no_agents_guidance_claims_a_prompt_creates_the_branch(name: str) -> None:
    """Requirement 4: no file may say the task prompt creates the ``{phase}-{task}`` branch.

    A recipe is legal only as a prohibition (``task-fixer`` tells the agent *not* to create a
    branch), so the guard mirrors the recipe guard in ``test_prompt_neutrality.py``. The
    "creates" form is guarded separately (review follow-up #116): ``_BRANCH_RECIPE`` skips
    ``creates`` to keep §3.2's own sentence legal, so this second assertion is what catches
    a revert of the E7.4 task-author wording — verbatim or reworded — anywhere in the glob,
    not just in the one file and one exact variant ``test_prompt_workflow.py`` pins.
    """
    assert _unguarded_branch_recipes(_read(name)) == [], name
    assert _prompt_creates_branch_claims(_read(name)) == [], name


def test_the_branch_guard_rejects_an_instructed_recipe() -> None:
    """The guard is live: an instructed recipe is caught, a prohibition and AIDT's fact are not."""
    assert _unguarded_branch_recipes("Before creating or switching to the branch, read it.") != []
    assert _unguarded_branch_recipes("```bash\ngit checkout -b task\n```") != []
    assert _unguarded_branch_recipes("Do not create a branch, commit, or push.") == []
    assert (
        _unguarded_branch_recipes("AIDT owns branch setup: `aidw prompt` creates the task branch.")
        == []
    )


def test_the_prompt_creates_guard_rejects_the_reverted_wording() -> None:
    """Review follow-up #116's trigger: the guard is live on both halves of the claim.

    The pre-E7.4 task-author sentence passes ``_unguarded_branch_recipes`` (reproduced in the
    issue) yet must fail this guard; §3.2's own sentence, once the allowlist strips it, must
    not. A reworded forward-order claim — the form a revert into any *other* guidance file
    would take, since the other files never carried the original sentence — is caught too.
    """
    reverted = (
        "Work only on the dedicated `{phase}-{task}` branch the prompt creates. "
        "Never write on `main`."
    )
    assert _unguarded_branch_recipes(reverted) == []
    assert _prompt_creates_branch_claims(reverted) != []
    assert _prompt_creates_branch_claims(
        "AIDT owns branch setup: `aidw prompt` creates the task branch and its worktree "
        "before this stage runs."
    ) == []
    assert (
        _prompt_creates_branch_claims(
            "The task prompt creates the dedicated `{phase}-{task}` branch for you."
        )
        != []
    )


# --------------------------------------------------------------------------- #
# Purity: reading the guidance changes nothing, and the matcher is order-free
# --------------------------------------------------------------------------- #


def test_reading_the_guidance_is_pure_and_repeatable() -> None:
    """Two reads agree byte-for-byte and the files on disk are unchanged.

    The neutrality verdict must not depend on the order the files are read in, any more than
    ``test_prompt_neutrality.py``'s may depend on the order the prompts are rendered in.
    """
    for seed_path in AGENTS_SEED:
        before = seed_path.read_bytes()

        first = seed_path.read_text(encoding="utf-8")
        second = seed_path.read_text(encoding="utf-8")

        assert first == second, seed_path.name
        assert seed_path.read_bytes() == before, seed_path.name
        assert _forbidden_hits(first) == _forbidden_hits(second), seed_path.name


# --------------------------------------------------------------------------- #
# Seeded property sweep: clean today, and every token is detectable tomorrow
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("seed_name", sorted(_iter_agents()))
def test_property_every_guidance_file_is_clean_and_every_planted_token_is_detected(
    seed_name: str,
) -> None:
    """Sweep 1 over the file seed: each file is clean, and each planted token is detected.

    For every guidance file (``numRuns = AGENTS_NUM_RUNS``) and every vocabulary token, the
    file as shipped has no hit, and the same text with the token appended does — so the clean
    verdict is the file's, not the matcher's blindness. Membership, not equality, because
    planted tokens overlap (``@mythical-forge`` also contains ``mythical-forge``).
    """
    text = _read(seed_name)
    assert _forbidden_hits(text) == [], seed_name

    for token in _vocabulary():
        planted = f"{text}\n{token}\n"
        assert token in _forbidden_hits(planted), (seed_name, token)


def test_property_every_vocabulary_token_matches_itself() -> None:
    """Sweep 2 over the vocabulary (``numRuns = VOCABULARY_NUM_RUNS``): no token is dead.

    A token the matcher cannot even match against its own text is a broken guard, not a
    satisfied one.
    """
    for token in _vocabulary():
        assert token in _forbidden_hits(token), token
