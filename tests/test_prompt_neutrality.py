"""Neutrality contract for the toolkit's neutralised defaults (E7.2 + MF.2).

Two sets are covered: the five bucket (ii) prompts E7.2 neutralised (§4.2), and the three bucket
(iii) prompts MF.2 **retained and neutralised** — `task-prompt.md`, `update-traceability.md` and
`update-architecture.md`, the ones the default registry invokes, which had to become product-free
to keep a target repo with no `aidw/` folder runnable (§8.3; `design.md` §17 M4). The vocabulary is
the same for both: a toolkit default names no package manager, no product path and no product doc.

Original E7.2 framing follows.

Executable half of §6 E7.2: *the rendered prompt for each of the five names no package
manager, no product path and no product doc — asserted against both a Mythical-Forge-shaped
config and a neutral one, not by grepping the templates.*

**Rendered, never grepped.** §5.4 excludes bucket (ii) from the byte-frozen coverage
precisely because E7.2 edits those five files, and two later changes land *around* the
template without touching it: a repo override (§3.6 precedence 2) and the conventions
injection E7.3 adds. A template grep would then prove the wrong text. Rendering at the
prompt's own ``$1`` arity is the text Pi actually receives, so that is what is asserted.

**The vocabulary** is the done-when's three categories plus requirements 4–5, split into
four tuples below: package managers (§3.4 "a toolkit prompt must not name a package
manager"), product scopes (§4.2's scope examples), product path literals (§3.4 ``paths.*``
whose defaults are Mythical Forge's, D17), and product doc/verifier tokens (§4.2's
remaining row entries). Tokens already absent from these files at the base revision
(``yarn``, ``Design 21``, ``Zod``, ``fast-check``, ``(03-E2.9)``, ``apps/``, ``infra/``)
stay in the vocabulary as regression guards: a zero-hit grep for one is not the
stop-and-ask trigger, it is a guard that must stay quiet. (``(03-E2.9)`` is misattributed
to ``pr.md`` by §4.2's row — it lives in the pr-publisher agent guidance, §4.3. The real
``pr.md`` task-id examples are ``02-D2`` and ``(D2)``.)

**Three traps this module closes**, each pinned by its own test rather than a comment:

1. *Keys vs paths.* The prompts must now name ``implementation_results_dir``; they must
   never name ``docs/implementation-results``. A blanket ``results``/``implementation``
   match would fail the required reference, so the matcher distinguishes underscore-keys
   from slash-paths and only the latter are forbidden.
2. *Whole words vs substrings.* Bare ``infra`` is forbidden; ``infrastructure`` — legitimate
   wording in ``fix-next-review-followup.md`` — is not.
3. *The neutral leg must not be vacuous.* A neutral config that left any named ``paths.*``
   key to fall back to the toolkit default is D17's Mythical Forge layout again, and the
   "also resolves under a neutral config" claim would prove nothing. The fixture below
   overrides every seeded ``paths.*`` leaf with a value that differs from the default.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from aidw.paths import toolkit_root
from aidw.prompts import PromptError, load_prompt_file, render, render_prompt_file
from aidw.target_config import (
    SOURCE_CONFIG,
    SOURCE_DEFAULT,
    PathsConfig,
    ResolvedConfig,
    TargetConfig,
    resolve_config,
)

# --------------------------------------------------------------------------- #
# The five files §4.2 lists as bucket (ii), each with the positional variables the
# workflow passes it. `test.md` takes none; the record prompt its optional branch override,
# the pr prompt its task id, the implement prompt its task-prompt file. The fix prompt keeps
# its `$1` PR (§6 E7.2) and gained `$2`, the absolute closing-body path, when 05-P1.2 moved
# the close behind the push — so it takes two here, which is what the F1 stage passes.
# --------------------------------------------------------------------------- #

VARIABLES: Mapping[str, tuple[str, ...]] = {
    "test.md": (),
    "pr.md": ("07-E9.9",),
    "fix-next-review-followup.md": (
        "https://example.test/pull/1",
        "/state/runs/fix-1/artifacts/iter1-closing-body.md",
    ),
    "record-implementation-results.md": ("07-E9.9",),
    "impliment-task.md": ("07-E9.9-prompt.md",),
}

#: Toolkit-internal stage references must survive, but by **stage name**. MF.2 moved seventeen
#: product prompts out of the toolkit, so a toolkit default may no longer point at a prompt file
#: it does not ship (``aidt/prompts/x.md`` was both stale and untruthful after the extraction);
#: naming the stage is the durable form, because the stage is what actually exists.
STAGE_REFERENCES: Mapping[str, tuple[str, ...]] = {
    "test.md": (
        "the `/update-traceability` stage",
        "the `/record-implementation-results` stage",
    ),
    "pr.md": (),
    "fix-next-review-followup.md": (),
    "record-implementation-results.md": ("the `/pr` stage",),
    "impliment-task.md": (
        "the `/test` stage",
        "the `/update-traceability` stage",
        "the `/record-implementation-results` stage",
        "the `/update-architecture` stage",
        "the `/pr` stage",
    ),
}

#: §3.4: a toolkit prompt must not name a package manager; the repo owns its gate commands.
PACKAGE_MANAGERS = ("pnpm", "npm", "yarn", "uv")

#: §4.2's product scope examples (``pr.md``) plus the scope the prompts may not assume.
PRODUCT_SCOPES = (
    "@mythical-forge",
    "mythical-forge",
    "rules-engine",
    "player-api",
    "shared-types",
    "infra",
)

#: §3.4/§4.2 product **path literals**. The config *keys* are the replacement and must
#: stay writable — see ``test_the_matcher_separates_config_keys_from_product_paths``.
PRODUCT_PATHS = (
    "docs/task-prompts",
    "docs/implementation-results",
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
)

#: §4.2 product doc/verifier tokens removed by requirements 4–5.
PRODUCT_DOCS = (
    "Design 21",
    "srd:",
    "matrix-check",
    "srd-traceability",
    "Zod",
    "fast-check",
    "02-D2",
    "(D2)",
    "(03-E2.9)",
    "AGENTS.md §6",
    "AWS",
)

#: The four §3.4 ``paths.*`` write-targets the ``--ignore`` scope derives from (R18).
SCOPE_KEYS = (
    "implementation_results_dir",
    "architecture_dir",
    "roadmap_dir",
    "task_prompts_dir",
)

#: The keys each prompt must point at instead of a literal — "the prompts point at keys,
#: not one repo's literals" (§6 E7.2). ``github.markers.parent`` is D5-frozen config.
NAMED_KEYS: Mapping[str, tuple[str, ...]] = {
    "test.md": (
        "task_prompts_dir",
        "implementation_results_dir",
        "architecture_dir",
        "roadmap_dir",
    ),
    "pr.md": SCOPE_KEYS,
    "fix-next-review-followup.md": (*SCOPE_KEYS, "github.markers.parent"),
    "record-implementation-results.md": (
        *SCOPE_KEYS,
        "build_results_template",
        "task_prompts_dir",
    ),
    "impliment-task.md": (
        *SCOPE_KEYS,
        "roadmap_dir",
        "implementation_results_dir",
    ),
}

#: The conventions source every neutralised prompt may name (§3.4/§3.8, D16). Bare
#: ``AGENTS.md`` stays legal — only the ``§6`` property-test reference was product text.
CONVENTIONS_SOURCES = ("aidw/conventions.md", "AGENTS.md")

_POSITIONAL = re.compile(r"\$(\d+)")


def _path(name: str) -> Path:
    return toolkit_root() / "prompts" / name


def _rendered(name: str) -> str:
    return render_prompt_file(_path(name), VARIABLES[name])


def _flat(name: str) -> str:
    """The rendered prompt with runs of whitespace collapsed, for phrase assertions.

    The prompts are hard-wrapped prose, so a phrase can straddle a newline; the contract is
    the sentence, not the line break.
    """
    return " ".join(_rendered(name).split())


# --------------------------------------------------------------------------- #
# The matcher — whole words for bare tokens, literals for everything else
# --------------------------------------------------------------------------- #


def _token_pattern(token: str) -> re.Pattern[str]:
    """One forbidden token as a regex.

    A bare lowercase word (``infra``, ``uv``) is matched with ``\\b`` on both sides so
    ``infrastructure`` and ``uvular`` do not trip it. Anything else — a path, a scoped
    package name, ``srd:``, ``(D2)`` — is matched as an escaped literal, because its
    punctuation is the signal.
    """
    if re.fullmatch(r"[a-z]+", token):
        return re.compile(rf"\b{re.escape(token)}\b")
    return re.compile(re.escape(token))


def _vocabulary() -> tuple[str, ...]:
    return (*PACKAGE_MANAGERS, *PRODUCT_SCOPES, *PRODUCT_PATHS, *PRODUCT_DOCS)


def _forbidden_hits(text: str) -> list[str]:
    """Every forbidden token present in ``text``, in vocabulary order."""
    return [token for token in _vocabulary() if _token_pattern(token).search(text)]


def _iter_prompts() -> Iterator[str]:
    yield from VARIABLES


def _mythical_forge_shaped_config() -> ResolvedConfig:
    """§5.4's config: ``schema_version: 1`` and nothing else, resolved by the real resolver.

    D17 makes the toolkit defaults Mythical Forge's layout, so this is the config a
    Mythical-Forge-shaped repo resolves through.
    """
    return resolve_config(TargetConfig(schema_version=1))


#: Every seeded ``paths.*`` leaf overridden, each value distinct from the §3.4/D17 default
#: and free of every forbidden literal, so a prompt that still carried a default would
#: fail the "under a neutral config" leg. ``agent_configs_dir`` stays unset: it has no
#: default to fall back to, and no prompt names it.
NEUTRAL_PATHS = PathsConfig(
    roadmap_dir="plan/roadmap",
    roadmap_glob="task-*.md",
    task_prompts_dir="plan/briefs",
    implementation_results_dir="build/output",
    build_results_template="build/output/RESULTS-TEMPLATE.md",
    architecture_dir="design/architecture",
)


def _neutral_config() -> ResolvedConfig:
    """A repo that shares no layout with the defaults; ``github`` deliberately unstated."""
    return resolve_config(TargetConfig(schema_version=1, paths=NEUTRAL_PATHS))


# --------------------------------------------------------------------------- #
# Arity — the five files keep the variables their stages pass today
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_each_prompt_declares_exactly_the_arity_its_stage_passes(name: str) -> None:
    """``test.md`` takes none; each other prompt exactly the variables its stage passes.

    Both directions are pinned: the template's positional indices are exactly ``1..n`` for a
    prompt with ``n`` variables (so rendering with fewer raises), and there are none for
    ``test.md`` (so it renders without any). Rendering leaves no ``$<digit>`` behind, which
    is what proves the text the agent receives has no unfilled placeholder.
    """
    text = load_prompt_file(_path(name))
    expected = VARIABLES[name]
    indices = {int(match) for match in _POSITIONAL.findall(text)}

    assert indices == set(range(1, len(expected) + 1)), name

    rendered = render(text, expected)
    assert not _POSITIONAL.search(rendered), name
    for index, value in enumerate(expected):
        assert value in rendered, (name, index + 1)
    if expected:
        with pytest.raises(PromptError):
            render(text, list(expected[:-1]))


# --------------------------------------------------------------------------- #
# The neutrality assertion itself, over the whole vocabulary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_no_rendered_prompt_names_a_package_manager_product_path_or_product_doc(
    name: str,
) -> None:
    """The rendered prompt carries no forbidden token (§6 E7.2 done-when).

    Collected rather than failing on the first hit: one run reports every offending token
    with the prompt that carries it.
    """
    hits = _forbidden_hits(_rendered(name))

    assert hits == [], f"{name}: forbidden token(s) in the rendered prompt: {hits}"


def test_the_vocabulary_covers_every_category_without_overlap() -> None:
    """The four categories are the whole vocabulary and none is empty.

    A category quietly emptied (say ``PRODUCT_PATHS`` losing its entries) would make the
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

    The prompts *must* name ``implementation_results_dir`` and friends (that is the fix),
    while ``docs/implementation-results`` is the defect. Pinning both halves here keeps a
    later "tidy-up" from widening the vocabulary into a blanket
    ``results``/``implementation`` match that would forbid the required references.
    """
    keys = [
        "implementation_results_dir",
        "build_results_template",
        "roadmap_dir",
        "task_prompts_dir",
        "architecture_dir",
        "github.markers.parent",
        "paths.implementation_results_dir",
        "docs/task_prompts_dir",  # a path, but not one of the forbidden literals
    ]
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
    }
    for literal, token in literals.items():
        assert _forbidden_hits(literal) == [token], literal


def test_the_matcher_matches_bare_scope_tokens_as_whole_words_only() -> None:
    """``infra`` is forbidden; ``infrastructure`` is legitimate wording.

    The same whole-word rule covers the other bare tokens: ``uv``/``npm``/``pnpm`` are
    package managers, ``pnpm-workspace.yaml`` still contains the whole word, and a scoped
    package name is matched as a literal because its ``@``/``-`` is the signal.
    """
    assert _forbidden_hits("deployed infrastructure, schema, and security") == []
    assert _forbidden_hits("infra") == ["infra"]
    assert _forbidden_hits("an infra/ directory") == ["infra", "infra/"]
    assert _forbidden_hits("uv sync --frozen") == ["uv"]
    assert _forbidden_hits("uvular") == []
    assert _forbidden_hits("a pnpm-workspace.yaml file") == ["pnpm"]
    assert _forbidden_hits("@mythical-forge/rules-engine") == [
        "@mythical-forge",
        "mythical-forge",
        "rules-engine",
    ]


# --------------------------------------------------------------------------- #
# The prescribed replacements are actually present (requirements 4–5)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_each_prompt_keeps_the_gate_recording_idiom(name: str) -> None:
    """Neutralising the concrete commands must not remove the shared gate contract."""
    assert "aidw gate run" in _rendered(name)


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_toolkit_stage_cross_references_are_preserved(name: str) -> None:
    rendered = _rendered(name)
    for reference in STAGE_REFERENCES[name]:
        assert reference in rendered, f"{name}: lost {reference}"


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_each_prompt_names_the_config_keys_instead_of_a_literal(name: str) -> None:
    """Every key the prompt needs is named, and resolves in both configs (§6 E7.2).

    Named-but-unresolvable would be the same failure as a literal: the agent would have
    nothing to look up. ``paths.*`` keys resolve by leaf name; the marker key keeps its
    dotted path.
    """
    rendered = _rendered(name)

    for key in NAMED_KEYS[name]:
        assert key in rendered, f"{name}: does not name {key}"

    for config in (_mythical_forge_shaped_config(), _neutral_config()):
        for key in NAMED_KEYS[name]:
            path = key if key.startswith("github.") else f"paths.{key}"
            resolved = config[path]
            assert resolved.value is not None, (name, path)
            assert resolved.source in (SOURCE_DEFAULT, SOURCE_CONFIG), (name, path)


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_no_named_path_resolves_to_text_the_rendered_prompt_contains(name: str) -> None:
    """Derived from config, not from the literal list: the *value* never appears.

    This is the metamorphic half of the neutrality check. The token list is a fixed
    vocabulary; this assertion asks the same question of whatever each config resolves to,
    so a future default path is covered without editing the vocabulary.
    """
    rendered = _rendered(name)

    for config in (_mythical_forge_shaped_config(), _neutral_config()):
        for key in NAMED_KEYS[name]:
            if key.startswith("github."):
                continue
            value = config[f"paths.{key}"].value
            assert isinstance(value, str), (name, key)
            assert value not in rendered, (name, key, value)


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_each_prompt_points_at_the_repos_conventions_source(name: str) -> None:
    """Gate commands and stack rules come from the repo (§3.4/D16), so each names them."""
    rendered = _rendered(name)

    for source in CONVENTIONS_SOURCES:
        assert source in rendered, f"{name}: does not name {source}"


def test_the_record_prompt_states_the_neutral_replacements_requirements_4_and_5_fix() -> None:
    assert "the repo's property-test policy" in _rendered("impliment-task.md")
    assert (
        "unavailable credentials or external dependencies"
        in _rendered("fix-next-review-followup.md")
    )


# --------------------------------------------------------------------------- #
# The neutral fixture has to be a *different* repo, or its leg proves nothing
# --------------------------------------------------------------------------- #


def test_the_neutral_config_overrides_every_named_path_key_with_a_distinct_value() -> None:
    """No named ``paths.*`` key falls back to the §3.4/D17 default under the neutral config.

    Each value differs from the default and carries no forbidden literal, so a prompt that
    still carried a default path could not pass the neutral leg by coincidence.
    """
    mythical = _mythical_forge_shaped_config()
    neutral = _neutral_config()
    named_paths = {
        key for keys in NAMED_KEYS.values() for key in keys if not key.startswith("github.")
    }
    assert named_paths == {
        "implementation_results_dir",
        "architecture_dir",
        "roadmap_dir",
        "task_prompts_dir",
        "build_results_template",
    }

    for key in sorted(named_paths):
        path = f"paths.{key}"
        assert mythical[path].source == SOURCE_DEFAULT, path
        assert neutral[path].source == SOURCE_CONFIG, path
        assert neutral[path].value != mythical[path].value, path
        assert _forbidden_hits(str(neutral[path].value)) == [], path
        # The whole fixture shares no layout with the defaults, not just the named leaves.
    for key in ("roadmap_dir", "roadmap_glob", "task_prompts_dir", "architecture_dir"):
        assert neutral[f"paths.{key}"].value != mythical[f"paths.{key}"].value


def test_the_frozen_parent_marker_resolves_through_the_default_in_both_configs() -> None:
    """D5/§3.9: the marker *value* is frozen and the neutral fixture does not redeclare it.

    ``github.markers.parent`` is the one key that must resolve identically under both
    configs; a neutral override would be a marker migration across live issues, which is
    out of scope (§9).
    """
    mythical = _mythical_forge_shaped_config()
    neutral = _neutral_config()

    for config in (mythical, neutral):
        assert config["github.markers.parent"].source == SOURCE_DEFAULT
        assert config["github.markers.parent"].value is not None
    assert neutral["github.markers.parent"].value == mythical["github.markers.parent"].value


def test_rendering_is_pure_and_does_not_mutate_its_inputs() -> None:
    """Rendering reads the file, substitutes, and changes nothing (§6 E7.2).

    Two renders agree byte-for-byte, the supplied variables are untouched, and the prompt
    file on disk is unchanged — so the neutrality assertion cannot be affected by the
    order the five prompts are rendered in.
    """
    for name in _iter_prompts():
        variables = list(VARIABLES[name])
        before = _path(name).read_bytes()

        first = render(load_prompt_file(_path(name)), variables)
        second = render_prompt_file(_path(name), variables)

        assert first == second, name
        assert variables == list(VARIABLES[name]), name
        assert _path(name).read_bytes() == before, name


# --------------------------------------------------------------------------- #
# Behaviours §6 E7.2 requires to survive the edit
# --------------------------------------------------------------------------- #


def test_the_record_prompt_keeps_its_preserved_behaviours() -> None:
    """The missing-template rule, the fixture guidance and the run-once rule stay.

    Removing the surrounding package-manager matrix is E7.2's job; deleting these with it
    would change the stage's semantics, which §6 E7.2 forbids.
    """
    rendered = _flat("record-implementation-results.md")

    # Stop and report a missing configured template — never invent or substitute.
    assert "stop and report it" in rendered
    assert "do not invent a structure" in rendered
    assert "do not substitute another document" in rendered
    assert "paths.build_results_template" in rendered
    # `mktemp -d` and the repo's fixtures instead of scratch repos (§6 E7.2).
    assert "mktemp -d" in rendered
    assert "prefer the repo's existing fixtures over" in rendered
    assert "git init" in rendered
    assert "scratch demos" in rendered
    # Each gate command runs exactly once; every row derives from that one invocation.
    assert "Run each command exactly once" in rendered
    assert "single invocation" in rendered


def test_the_implement_prompt_keeps_aidt_owned_branch_setup() -> None:
    """§3.2: AIDT creates the branch; the agent must not (no ``git checkout -b`` remains)."""
    rendered = _rendered("impliment-task.md")

    assert "AIDT owns branch setup" in rendered
    assert "`aidw implement` creates the task branch" in rendered
    assert "git checkout -b" not in rendered
    assert "git switch" not in rendered
    assert "git reset --hard" not in rendered


#: Recipes the non-interactive runner refuses (§6 E7.2).
BLOCKED_RECIPES = ("rm -rf", "git init")

#: A recipe mention is acceptable only when it is a prohibition — the prompts tell the
#: agent *not* to reach for it. ``record`` states both rules, so a bare "must not appear"
#: check would fail on the guidance that is the point.
PROHIBITION_MARKERS = ("do not", "never", "instead of", "prefer")


def _unguarded_recipe_mentions(text: str) -> list[tuple[str, str]]:
    """Each blocked-recipe mention with no negation in the preceding clause."""
    flat = " ".join(text.split()).lower()
    unguarded: list[tuple[str, str]] = []
    for recipe in BLOCKED_RECIPES:
        start = flat.find(recipe)
        while start != -1:
            window = flat[max(0, start - 80) : start]
            if not any(marker in window for marker in PROHIBITION_MARKERS):
                unguarded.append((recipe, flat[start : start + len(recipe)]))
            start = flat.find(recipe, start + len(recipe))
    return unguarded


@pytest.mark.parametrize("name", sorted(VARIABLES))
def test_no_prompt_instructs_a_command_the_noninteractive_runner_blocks(name: str) -> None:
    """§6 E7.2: no prompt instructs a command the non-interactive session refuses.

    Destructive recipes (``rm -rf``) and scratch repositories (``git init``) may only be
    mentioned as prohibitions — ``record`` tells the agent not to use them and to build into
    ``$(mktemp -d)`` and use the repo's fixtures instead. A recipe named as an instruction
    (a shell block, a bare imperative) has no negation in front of it and fails here.
    """
    assert _unguarded_recipe_mentions(_rendered(name)) == []


def test_the_recipe_guard_rejects_an_instructed_recipe() -> None:
    """The guard is live: an imperative ``rm -rf`` is caught, the prohibition is not."""
    assert _unguarded_recipe_mentions("```bash\nrm -rf build\n```") == [
        ("rm -rf", "rm -rf")
    ]
    assert _unguarded_recipe_mentions("Do not `rm -rf`; build into `$(mktemp -d)` instead.") == []


# --------------------------------------------------------------------------- #
# The three retained toolkit defaults (MF.2)
# --------------------------------------------------------------------------- #

#: The §4.2 bucket (iii) prompts MF.2 kept instead of moving them, with the positional variables
#: their stages pass (`aidw/stage_registry.py`: P1 passes phase/epic/task, I3 the branch, I4 the
#: branch and base branch). They are the ones the *default* chains invoke, which is exactly why
#: the toolkit cannot hand them to the target repo.
RETAINED_DEFAULTS: Mapping[str, tuple[str, ...]] = {
    "task-prompt.md": ("02", "L5", "L5.2"),
    "update-traceability.md": ("07-E9.9",),
    "update-architecture.md": ("07-E9.9", "main"),
}

#: The config keys each retained default must name instead of a product literal (§3.4/D17).
#: A prompt that named the literal would be wrong for every repo whose layout differs — which is
#: precisely the failure these three were rewritten to remove.
RETAINED_KEYS: Mapping[str, tuple[str, ...]] = {
    "task-prompt.md": ("roadmap_dir", "task_prompts_dir"),
    # W1.1/Z13 reverses the H3.1 note that used to live here. H3.1 moved the roadmap
    # *tick* to the core ``/update-roadmap`` stage, but I3 must still name ``roadmap_dir``:
    # it now names the tree it may never edit, and naming the config key is what keeps that
    # prohibition free of the ``docs/tasks`` product literal. Leaving the old comment would
    # assert the opposite of the prompt and make this coverage pin nothing.
    "update-traceability.md": (
        "task_prompts_dir",
        "implementation_results_dir",
        "roadmap_dir",
    ),
    "update-architecture.md": ("architecture_dir",),
}


@pytest.mark.parametrize("name", sorted(RETAINED_DEFAULTS))
def test_retained_defaults_name_no_package_manager_product_path_or_product_doc(
    name: str,
) -> None:
    """The retained defaults are product-free, by the same vocabulary as bucket (ii).

    They are the toolkit's defaults for `P1`/`I3`/`I4`, so a product token here would leak into
    every repo that does not override them — the de-branding the extraction exists to finish.
    """
    hits = _forbidden_hits(render_prompt_file(_path(name), RETAINED_DEFAULTS[name]))

    assert hits == [], f"{name}: forbidden token(s) in the rendered prompt: {hits}"


@pytest.mark.parametrize("name", sorted(RETAINED_DEFAULTS))
def test_retained_defaults_name_config_keys_that_resolve_under_both_configs(
    name: str,
) -> None:
    """Every key they point the agent at is named *and* resolvable, in both configs.

    The neutral leg is what stops the default layout from coming back in through wording: if a
    retained default still said where Mythical Forge keeps its files, nothing here would notice.
    """
    rendered = render_prompt_file(_path(name), RETAINED_DEFAULTS[name])

    for config in (_mythical_forge_shaped_config(), _neutral_config()):
        for key in RETAINED_KEYS[name]:
            assert key in rendered, f"{name}: does not name {key}"
            resolved = config[f"paths.{key}"]
            assert resolved.value is not None, (name, key)
            assert resolved.source in (SOURCE_DEFAULT, SOURCE_CONFIG), (name, key)


def test_the_traceability_default_states_the_roadmap_ownership_rule() -> None:
    """W1.1/Z13: the prompt names the key and the owning stage, and forbids the edit.

    The vocabulary sweep proves no ``docs/tasks`` literal came back; this proves the rule the
    literal was replaced *by* is in the rendered text, so a later neutralisation cannot drop
    the ownership sentence and stay green by naming the key in a heading alone.
    """
    rendered = " ".join(
        render_prompt_file(
            _path("update-traceability.md"), RETAINED_DEFAULTS["update-traceability.md"]
        ).split()
    )

    assert "paths.roadmap_dir" in rendered
    assert "/update-roadmap" in rendered
    assert "None for traceability" in rendered
    assert "Never edit anything under it" in rendered
    assert "docs/tasks" not in rendered
