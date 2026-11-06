"""Drift-proof checks for the operator guide (``README.md``, E9.4).

E9.4 rewrites the README from the pre-extraction viewpoint ("the toolkit lives at ``aidt/``
inside the Mythical Forge repo, run everything from there") to the post-extraction one: an
installed ``aidw`` driving Pi against a **target repo**, with the toolkit root and the target
repo root as two independent roots (design.md §1.1, §3.2; EXTRACTION.md §3.12). The roadmap's
"Done when" is a human-read criterion — "the §0 audience can operate the toolkit without
reading ``aidw/``" — so these checks are its executable half (AGENTS.md: pytest is the only
verification; E9.1/E9.2/E9.3 precedent).

What is pinned, against the file read from the toolkit root (``aidw.paths.toolkit_root()``):

- the "Interim state" banner and every pre-extraction path phrase are **gone**. ``aidt`` is
  *not* banned: the provenance note and the install/release URLs keep it legitimately, so the
  markers are the specific path phrases, never the bare word — a blanket ``rg aidt`` sweep
  would delete the install commands and the provenance trail;
- the opening frames the toolkit as driving **a target repo**, not a product application;
- the quickstart is an *operator* path (install → bootstrap → ``aidw doctor`` →
  ``aidw tasks --todo`` → ``aidw prompt …``) and the rest of the guide puts the installed
  ``aidw`` in the command position. The one exception is the payload after
  ``aidw gate run <key> --``, which is the *target repo's* command and keeps its real form;
- the ``aidw/`` dual-role note survives (inside the toolkit ``aidw/`` is code; inside a target
  repo it is configuration — design.md §3.2);
- the Troubleshooting table carries the stale-``gh`` failure (``subIssues``, ``gh`` ≥ 2.94.0,
  ``which -a gh``) and the three worktree-layout failures, cross-linked to the E8.4
  "Supported and rejected layouts" section in that section's own vocabulary rather than
  duplicated with invented check names;
- the "Layout" section matches design.md §3's tree and cross-links it, and the three shipped
  contract docs are linked (never re-pasted — a second copy drifts from the files the parser
  and config tests read);
- the Development section is the one place the checkout forms (``uv sync``, ``uv run aidw``)
  belong, and it names this repository's own CI instead of the retired "not wired into the
  product's ``pnpm -r test`` CI" claim (design F5).

The seeded property run at the bottom proves the marker check is *membership* rather than
position-sensitive: injecting a banned phrase at any line boundary — including inside a fenced
block or a table cell — is always caught, and nothing else is reported. Pinned seed and run
count, pytest only: the repo carries no ``hypothesis`` dependency (AGENTS.md "Tests"), so a
reproducible sample is the generator and there is no shrinking.
"""

from __future__ import annotations

import random

from aidw.paths import toolkit_root

_RELATIVE_PATH = "README.md"

# The pre-extraction path phrases E9.4 sweeps (Reqs 1 and 6), including the two whole-sentence
# ``aidt/`` markers the path fragments do not match. The bare word ``aidt`` is deliberately
# absent: it is the repository's name, and the provenance note and install URLs need it.
_PRE_EXTRACTION_MARKERS = (
    "cd aidt",
    "aidt/runs/",
    "aidt/prompts/",
    "aidt/agent-configs",
    "aidt/aidw/",
    "./aidt/aidw/aidw doctor",
    "from `aidt/`",
    "outside `aidt/`",
    "Interim state",
    "design F5",
)

# What the same sweep must leave in place: the provenance trail and the two D9 install forms.
_LEGITIMATE_AIDT_REFERENCES = (
    "verbatim copy of `aidt/` from `mythical-forge@",
    "git+https://github.com/curiouslittledroid/aidt@v0.1.0",
)

# The ``aidw/`` dual-role note (design.md §3.2, D7) — the naming contract a README rewrite is
# most likely to flatten into one role.
_DUAL_ROLE_PHRASES = (
    "`aidw/` means two different things",
    "Python **code**",
    "**configuration**",
    "`aidw/config.yaml`",
    "`aidw/conventions.md`",
    "`aidw/prompts/`",
)

# The three shipped contract docs (Req 6). Present *by link* and on disk; their field tables and
# worked examples are the docs' to own (E9.1/E9.2 trap: a second copy drifts).
_CONTRACT_DOCS = (
    "docs/target-repo-config.md",
    "docs/roadmap-format.md",
    "docs/releasing.md",
)

# design.md §3 / EXTRACTION.md §3.12 top-level tree (Req 4). ``fixtures/target-repo/`` is not
# optional there: the override mechanism, the stage model and the roadmap format are only
# proven by running the real workflows against a fixture repo.
_LAYOUT_ENTRIES = (
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
    "uv.lock",
    ".github/workflows/ci.yml",
)

_WORKTREE_ANCHOR = "[Supported and rejected layouts](#supported-and-rejected-layouts)"

# Each Req 5(b) failure with the diagnostic that actually exists for it (E8.4 vocabulary): the
# ``clone-of-a-worktree`` layout name, the two ``aidw doctor`` check names it FAILs, and git's
# own refusal for a branch that is already checked out in ``main/`` — which no doctor check
# covers, so the row names the git symptom rather than inventing one.
_WORKTREE_LAYOUT_ROWS = (
    ("clone-of-a-worktree", "`control worktree`"),
    ("is a bare repository", "`target repo`"),
    ("already checked out", "no `aidw doctor` check covers this one"),
)

# Pinned seed and run count (AGENTS.md "Tests": pytest only, no ``hypothesis``).
README_PROPERTY_SEED = 9401
README_PROPERTY_RUNS = 40

_DEVELOPMENT_HEADING = "## Development"


def _readme() -> str:
    return (toolkit_root() / _RELATIVE_PATH).read_text(encoding="utf-8")


def _normalise(text: str) -> str:
    """Collapse whitespace, so a marker is matched even when a paragraph re-wraps.

    The README wraps at 100 columns, so ``verbatim copy of `aidt/` from`` and the
    ``mythical-forge@<sha>`` that completes it sit on different lines. Matching the flattened
    text keeps the checks about *content*, never about where a line break landed.
    """
    return " ".join(text.split())


def _section(doc: str, heading: str, next_heading: str | None = None) -> str:
    """Return one section, or ``""`` when its heading is gone.

    Fail closed: a deleted heading is exactly the drift these checks report, so a missing
    section must come back as a violation for the caller to list rather than raise here.
    """
    start = doc.find(heading)
    if start < 0:
        return ""
    if next_heading is None:
        return doc[start:]
    end = doc.find(next_heading, start)
    return doc[start:] if end < 0 else doc[start:end]


def _table_rows(section: str) -> list[str]:
    """The markdown table rows of one section, as written."""
    return [line for line in section.splitlines() if line.startswith("|") and line.endswith("|")]


# ---------------------------------------------------------------------------
# Checkers: pure functions of the document text (no I/O, no mutation, repeatable)
# ---------------------------------------------------------------------------


def _marker_violations(doc: str) -> list[str]:
    """Every pre-extraction marker that survived the sweep."""
    flat = _normalise(doc)
    return [marker for marker in _PRE_EXTRACTION_MARKERS if marker in flat]


def _survivor_violations(doc: str) -> list[str]:
    """Every legitimate ``aidt`` reference the sweep must *not* have removed."""
    flat = _normalise(doc)
    return [ref for ref in _LEGITIMATE_AIDT_REFERENCES if ref not in flat]


def _intro_violations(doc: str) -> list[str]:
    """The opening frames a target repo and the two roots, not a product application."""
    intro = _section(doc, "# AIDT", "## Install")
    flat = _normalise(intro)
    violations: list[str] = []
    if "target repo" not in flat:
        violations.append("opening does not name the target repo")
    if "toolkit root" not in flat or "target repo root" not in flat:
        violations.append("opening does not name the toolkit root and the target repo root")
    if "mythical forge application" in flat.lower():
        violations.append("opening still frames the toolkit as developing a product application")
    return violations


def _dual_role_violations(doc: str) -> list[str]:
    """The ``aidw/`` dual-role note survives (design.md §3.2)."""
    flat = _normalise(doc)
    return [phrase for phrase in _DUAL_ROLE_PHRASES if phrase not in flat]


def _quickstart_violations(doc: str) -> list[str]:
    """The quickstart is reproducible by an operator who has only installed the toolkit."""
    section = _normalise(_section(doc, "## Quickstart", "## Workflows"))
    violations: list[str] = []
    for required in (
        "[Install](#install)",
        "[Workspace layout and bootstrap](#workspace-layout-and-bootstrap)",
        "aidw doctor",
        "aidw tasks --todo",
        "aidw prompt <phase> <epic> <task>",
    ):
        if required not in section:
            violations.append(f"quickstart is missing {required!r}")
    for forbidden in ("cd aidt", "uv sync", "uv run"):
        if forbidden in section:
            violations.append(f"quickstart still needs {forbidden!r} (it is the operator path)")
    return violations


def _command_position_violations(doc: str) -> list[str]:
    """The installed ``aidw`` is the command position everywhere but Development.

    Two things must hold together, and the task's trap is that a uniform rewrite breaks one
    of them: no ``uv run aidw``/``uv sync`` outside Development (a toolkit developer reading
    that section loses the one place those forms are correct), and the payload after
    ``aidw gate run <key> --`` keeps the target repo's own command.
    """
    before, separators, _development = doc.partition(_DEVELOPMENT_HEADING)
    if not separators:
        return ["Development section is missing, so the checkout forms have no home"]

    flat_before = _normalise(before)
    violations = [
        f"{form!r} appears outside Development"
        for form in ("uv run aidw", "uv sync")
        if form in flat_before
    ]

    workflows = _normalise(_section(doc, "## Workflows", "## Commands"))
    for payload in (
        "aidw gate run suite -- uv run --frozen pytest",
        "aidw gate run suite -- pnpm -r test",
    ):
        if payload not in workflows:
            violations.append(f"gate payload was rewritten: {payload!r} is missing")
    return violations


def _troubleshooting_rows(doc: str) -> list[str]:
    return _table_rows(_section(doc, "## Troubleshooting", "## Layout"))


def _stale_gh_violations(doc: str) -> list[str]:
    """The stale-``gh`` row names the symptom, the floor, the check and the finder."""
    rows = [row for row in _troubleshooting_rows(doc) if "subIssues" in row]
    if not rows:
        return ["Troubleshooting has no stale-gh row naming `subIssues`"]
    if len(rows) > 1:
        return [f"Troubleshooting has {len(rows)} stale-gh rows; expected exactly one"]
    row = rows[0]
    violations = [
        f"stale-gh row is missing {required!r}"
        for required in ("2.94", "`gh version`", "FAIL", "which -a gh", "PATH")
        if required not in row
    ]
    return violations


def _worktree_layout_violations(doc: str) -> list[str]:
    """Each worktree-layout failure is a Troubleshooting row that cross-links E8.4.

    The cross-link is the point: the accepted/rejected layouts are one section's contract
    (E8.4), and a second copy of the reasoning in the symptom table is what drifts. Each row
    must therefore carry its own real diagnostic *and* the anchor.
    """
    if "### Supported and rejected layouts" not in doc:
        return ["the E8.4 'Supported and rejected layouts' section is gone, so the anchor dangles"]

    rows = _troubleshooting_rows(doc)
    violations: list[str] = []
    for symptom, diagnostic in _WORKTREE_LAYOUT_ROWS:
        matches = [row for row in rows if symptom in row]
        if not matches:
            violations.append(f"Troubleshooting has no worktree-layout row for {symptom!r}")
            continue
        row = matches[0]
        if diagnostic not in row:
            violations.append(f"row for {symptom!r} does not name {diagnostic!r}")
        if _WORKTREE_ANCHOR not in row:
            violations.append(f"row for {symptom!r} does not cross-link E8.4")
    return violations


def _layout_violations(doc: str) -> list[str]:
    """The Layout section is design.md §3's tree, cross-linked rather than re-owned."""
    section = _normalise(_section(doc, "## Layout", _DEVELOPMENT_HEADING))
    violations = [
        f"Layout is missing {entry!r}" for entry in _LAYOUT_ENTRIES if entry not in section
    ]
    if "design.md` §3" not in section:
        violations.append("Layout does not defer to design.md §3 for the tree")
    return violations


def _contract_link_violations(doc: str) -> list[str]:
    """The three shipped contract docs are *linked* from Documentation, and the targets exist.

    Scoped to the Documentation subsection and to the markdown link form deliberately: the
    Install section also cites the release runbook, so a whole-document substring check would
    stay green after the Documentation bullet was dropped.
    """
    root = toolkit_root()
    section = _normalise(_section(doc, "### Documentation", _DEVELOPMENT_HEADING))
    violations: list[str] = []
    for relative in _CONTRACT_DOCS:
        if f"](./{relative})" not in section:
            violations.append(f"Documentation does not link {relative}")
        elif not (root / relative).is_file():
            violations.append(f"README links {relative}, which is not a file")
    return violations


def _development_violations(doc: str) -> list[str]:
    """Development owns the checkout forms and names this repository's own CI."""
    section = _normalise(_section(doc, _DEVELOPMENT_HEADING))
    violations = [
        f"Development is missing {required!r}"
        for required in (
            "uv sync --frozen",
            "uv run --frozen pytest",
            ".github/workflows/ci.yml",
            "pytest` is the only verification",
        )
        if required not in section
    ]
    # The retired pre-extraction claim: AIDT's tests are not wired into the product's pipeline.
    for forbidden in ("pnpm", "not wired into"):
        if forbidden in section:
            violations.append(
                f"Development still carries the pre-extraction CI claim ({forbidden!r})"
            )
    return violations


# ---------------------------------------------------------------------------
# The guide as it ships
# ---------------------------------------------------------------------------


def test_the_interim_banner_and_pre_extraction_markers_are_gone() -> None:
    """Req 1: the banner is deleted and no swept path phrase survives anywhere."""
    violations = _marker_violations(_readme())
    assert not violations, f"pre-extraction markers survived the sweep: {violations}"


def test_provenance_and_install_urls_survive_the_sweep() -> None:
    """Req 1 trap: the sweep bans *phrases*, never the repository's own name."""
    violations = _survivor_violations(_readme())
    assert not violations, f"legitimate `aidt` references were swept away: {violations}"


def test_purpose_frames_a_target_repo_and_the_two_roots() -> None:
    """Req 2: the opening is post-extraction (design.md header, §1.1)."""
    violations = _intro_violations(_readme())
    assert not violations, "\n".join(violations)


def test_the_dual_role_note_survives() -> None:
    """Req 2 / design.md §3.2: ``aidw/`` is code here and configuration in a target repo."""
    violations = _dual_role_violations(_readme())
    assert not violations, f"the `aidw/` dual-role note lost {violations}"


def test_quickstart_is_an_operator_path() -> None:
    """Req 3: install → bootstrap → doctor → tasks → prompt, with no checkout requirement."""
    violations = _quickstart_violations(_readme())
    assert not violations, "\n".join(violations)


def test_the_installed_aidw_is_the_command_position() -> None:
    """Req 3: operator examples use ``aidw``; the gate payload keeps the repo's own command."""
    violations = _command_position_violations(_readme())
    assert not violations, "\n".join(violations)


def test_troubleshooting_carries_the_stale_gh_failure() -> None:
    """Req 5(a): ``subIssues`` from a stale/shadowed ``gh``, the 2.94.0 floor, ``which -a gh``."""
    violations = _stale_gh_violations(_readme())
    assert not violations, "\n".join(violations)


def test_troubleshooting_carries_the_worktree_layout_failures() -> None:
    """Req 5(b): each rejected layout, its real diagnostic, and the E8.4 cross-link."""
    violations = _worktree_layout_violations(_readme())
    assert not violations, "\n".join(violations)


def test_layout_matches_the_extraction_tree() -> None:
    """Req 4: the stale ``aidt/`` tree is replaced by design.md §3's, cross-linked."""
    violations = _layout_violations(_readme())
    assert not violations, "\n".join(violations)


def test_the_three_contract_docs_are_cross_linked() -> None:
    """Req 6: link the shipped contracts, never re-paste their tables (E9.1/E9.2 trap)."""
    violations = _contract_link_violations(_readme())
    assert not violations, "\n".join(violations)


def test_development_owns_the_checkout_forms_and_this_repos_ci() -> None:
    """Req 6: ``uv sync``/``uv run`` live here, with CI named — the F5 claim is retired."""
    violations = _development_violations(_readme())
    assert not violations, "\n".join(violations)


# ---------------------------------------------------------------------------
# Fail-closed, purity, and non-vacuity
# ---------------------------------------------------------------------------


def test_checkers_are_pure_and_fail_closed() -> None:
    """The checkers are pure functions of the text, and an emptied guide fails loudly.

    Purity: they take the document as an argument (no file read of their own), return the
    same result twice, and leave the README's bytes untouched. Fail-closed: an empty document
    is not "clean" — the survivors and the layout/section requirements become violations, so
    truncating the README cannot turn the checks green.
    """
    doc = _readme()
    before = (toolkit_root() / _RELATIVE_PATH).read_bytes()

    checkers = (
        _marker_violations,
        _survivor_violations,
        _intro_violations,
        _dual_role_violations,
        _quickstart_violations,
        _command_position_violations,
        _stale_gh_violations,
        _worktree_layout_violations,
        _layout_violations,
        _contract_link_violations,
        _development_violations,
    )

    first = [checker(doc) for checker in checkers]
    second = [checker(doc) for checker in checkers]
    assert first == second
    assert (toolkit_root() / _RELATIVE_PATH).read_bytes() == before

    # Empty text: the section-scoped checkers must report, not raise, and the checks that
    # assert presence must not pass vacuously.
    assert _survivor_violations("") == list(_LEGITIMATE_AIDT_REFERENCES)
    assert _dual_role_violations("") == list(_DUAL_ROLE_PHRASES)
    assert _layout_violations("")
    assert _contract_link_violations("")
    assert _development_violations("")
    assert _worktree_layout_violations("")
    assert _stale_gh_violations("")
    assert _quickstart_violations("")
    assert _command_position_violations("")
    # The one checker whose "no markers" answer is legitimately empty for an empty document.
    assert _marker_violations("") == []


def test_the_checks_are_not_vacuous() -> None:
    """Every check fires on the edit it exists to catch.

    The reversions are the ones the task names: put the banner and a path phrase back, drop a
    contract-doc link, drop a worktree-layout row, drop the dual-role note, reintroduce
    ``uv run aidw`` into an operator example, and reintroduce the retired CI claim. A check
    that passes on all of those would let exactly the drift this task removed return.
    """
    doc = _readme()

    banner = doc.replace(
        "## Status",
        "> **Interim state.** Sections below still read from the pre-extraction viewpoint, where\n"
        "> the toolkit lived at `aidt/` inside the Mythical Forge repository (for example `cd aidt`).\n\n"
        "## Status",
        1,
    )
    assert banner != doc
    assert _marker_violations(banner), "a re-inserted banner must be caught"

    for marker in _PRE_EXTRACTION_MARKERS:
        reverted = doc + f"\n{marker}\n"
        # `in`, not `==`: `./aidt/aidw/aidw doctor` contains `aidt/aidw/`, so one injection can
        # legitimately report two overlapping markers.
        assert marker in _marker_violations(reverted), marker

    missing_provenance = doc.replace("verbatim copy of `aidt/` from", "verbatim copy of", 1)
    assert missing_provenance != doc
    assert _survivor_violations(missing_provenance), "a dropped provenance note must be caught"

    head, separator, documentation = doc.partition("### Documentation")
    missing_link = head + separator + documentation.replace(
        "[`docs/releasing.md`](./docs/releasing.md)", "`docs/releasing.md`", 1
    )
    assert missing_link != doc
    assert _contract_link_violations(missing_link), "a dropped contract-doc link must be caught"

    head, separator, troubleshooting = doc.partition("## Troubleshooting")
    dropped_row = head + separator + troubleshooting.replace(
        _WORKTREE_ANCHOR, "the layouts section", 1
    )
    assert dropped_row != doc
    assert _worktree_layout_violations(dropped_row), "a dropped E8.4 cross-link must be caught"

    dropped_gh = doc.replace("which -a gh", "the PATH", 1)
    assert dropped_gh != doc
    assert _stale_gh_violations(dropped_gh), "a stale-gh row without `which -a gh` must be caught"

    dropped_dual_role = doc.replace("`aidw/` means two different things", "`aidw/` has a role", 1)
    assert dropped_dual_role != doc
    assert _dual_role_violations(dropped_dual_role), "a flattened dual-role note must be caught"

    checkout_in_quickstart = doc.replace(
        "   aidw doctor", "   uv run aidw doctor", 1
    )
    assert checkout_in_quickstart != doc
    assert _quickstart_violations(checkout_in_quickstart), (
        "an operator example that needs a checkout must be caught"
    )

    rewritten_gate = doc.replace(
        "aidw gate run suite -- uv run --frozen pytest",
        "uv run aidw gate run suite --",
        1,
    )
    assert rewritten_gate != doc
    assert _command_position_violations(rewritten_gate), (
        "a rewritten gate payload must be caught"
    )

    head, separator, development = doc.partition(_DEVELOPMENT_HEADING)
    dropped_ci = head + separator + development.replace(".github/workflows/ci.yml", "ci.yml")
    assert dropped_ci != doc
    assert _development_violations(dropped_ci), "a Development section without CI must be caught"

    retired_claim = doc + (
        "\nAIDT tests are intentionally **not** wired into the product's `pnpm -r test` CI.\n"
    )
    assert _development_violations(retired_claim), "the retired CI claim must be caught"


# ---------------------------------------------------------------------------
# Seeded property run: marker detection is membership, not position
# ---------------------------------------------------------------------------


def test_marker_detection_property_is_membership() -> None:
    """Seeded property run (seed/runs pinned above): injection anywhere is always caught.

    For every sampled (marker, line boundary) pair, the doctored document reports the injected
    marker — no false negative from it landing inside a fenced block, a table cell or a
    heading — and reports nothing unrelated: every reported marker is a substring of the
    injected phrase. (One injection can report two markers when the phrase nests one inside
    another, which is why the check is containment, not equality.) The baseline must be empty
    for either answer to mean anything, so this subsumes the sweep test rather than restating
    it.
    """
    doc = _readme()
    assert _marker_violations(doc) == []

    lines = doc.splitlines(keepends=True)
    rng = random.Random(README_PROPERTY_SEED)

    for case in range(README_PROPERTY_RUNS):
        marker = rng.choice(_PRE_EXTRACTION_MARKERS)
        index = rng.randrange(len(lines) + 1)
        doctored = "".join(lines[:index]) + f"Note: {marker}\n" + "".join(lines[index:])
        violations = _marker_violations(doctored)
        assert marker in violations, (case, index, marker)
        assert all(reported in marker for reported in violations), (
            case,
            index,
            marker,
            violations,
        )
