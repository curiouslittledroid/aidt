"""Frozen matching semantics for the review-followup scripts (EXTRACTION.md §3.9, D5, E6.2).

E6.2 is a **tests-only** task: the matching code paths are frozen, not edited. This file
pins them so a plausible-looking "improvement" fails here instead of orphaning every
persisted GitHub parent/child and making the next publish create duplicates (§3.9, D5).

Five separate semantics are pinned, each with a positive control so a vector cannot pass
vacuously:

1. **Comment bodies are compared byte-for-byte** (`logic.py:has_exact_comment` keeps
   ``body == exact``). Trailing whitespace, a case change, a newline, or extra prose all
   fail. ``test_logic.py`` already pins the core cases; the vectors here complete the set
   (every frozen body × six mutations, plus the availability/approval decisions that read
   them) without editing that file — the roadmap's "suite passes unmodified" is provable
   only while the pre-existing tests stay byte-identical.
2. **Markers match literally, never as a regex** (§3.9 "exact string match"). The rendered
   parent/child/summary marker contains URL dots, which are regex metacharacters: a body
   that substitutes one character for a dot must not match, while the byte-exact marker
   does. `gh.py:find_parent_issues` keeps ``marker not in str(body or "")``;
   `publish_review_followups.py:find_marked_issues` keeps ``marker not in issue["body"]``.
3. **Label names are compared case-sensitively** (`availability`, `priority_label`,
   `approval_plan`, `is_approved` all use ``name in labels`` over the exact literal, so
   ``Review-follow-up`` is a *different* label from ``review-follow-up``). Each vector uses
   a fully-specified child (state ``OPEN``, no status comments) so the ``False``/``None``
   result can only come from the label mismatch, with the exact-case twin as control.
4. **"Ensure existing" never overwrites** (`ensure_labels` keeps ``if name in existing:
   continue``). There is no label-edit call anywhere in the scripts, so the pin is that
   `create_label` is never called for an existing name — not that some no-op edit is
   harmless, which would invite adding one. A wrong-case existing name is a different
   label, so it must not suppress creation of the exact one either.
5. **Purity**: no vector mutates `constants.LABEL_DEFINITIONS`, `gh.LABEL_DEFINITIONS`, or
   its own inputs, and the matching paths shell out only through the one ``gh`` listing
   call each of them legitimately needs.

Run with: uv run pytest prompts/scripts/review-followup/tests

``pyproject.toml`` collects this directory alongside the toolkit's own ``tests/``.

The tests are deliberately **env-var-free** (no ``AIDW_REVIEW_FOLLOWUP_CONFIG``): they pin
the frozen semantics, so expected markers and definitions are read through ``gh``'s
accessors (which own the handoff) rather than assumed to be the ``constants`` literals.
`test_github_config.py` owns the configured/fail-closed handoff contract and its reload
fixture; nothing here reloads a module.
"""

from __future__ import annotations

import copy
import random
import re
from pathlib import Path
from typing import Callable

import pytest

import constants
import gh
import logic
import publish_review_followups
import review_followup
from proc import UsageError

SCRIPT_DIR = Path(__file__).resolve().parents[1]

#: A canonical browser PR URL, as `gh pr view --json url` returns it (§3.9).
PR_URL = "https://github.com/mythical-forge/aidt/pull/237"

#: Explicit `seed` + `numRuns` for the two property tests below, so a failing case is
#: reproducible from this file alone (no hypothesis dependency is added for one module's
#: property test; the RNG is seeded and the run count pinned instead).
PROPERTY_SEED = 20261105
PROPERTY_RUNS = 64

#: Values a near-miss probe substitutes for a URL ``.``. ``.`` is excluded: the probe must
#: change the byte. A space is included because a regex ``.`` matches it too, so the
#: property catches a matcher built on ``re.search`` rather than an accidental literal.
PROBE_CHARS = "xX-_ 0#"

#: How a label name can be *not* the exact frozen literal. ``wrong-case`` is the vector
#: §3.9 names ("do not normalise … case anywhere in that path"); the others pin that a
#: ``.strip()``/normalisation never enters the same path either.
LABEL_MUTATIONS: dict[str, Callable[[str], str]] = {
    "wrong-case": lambda name: name.capitalize(),  # approve-fix -> Approve-fix
    "upper-case": lambda name: name.upper(),
    "leading-space": lambda name: " " + name,
    "trailing-space": lambda name: name + " ",
}

#: How a frozen comment body can be *not* the exact literal (§3.9: strict equality).
BODY_MUTATIONS: dict[str, Callable[[str], str]] = {
    "trailing-space": lambda body: body + " ",
    "leading-space": lambda body: " " + body,
    "trailing-newline": lambda body: body + "\n",
    "case-change": lambda body: body.swapcase(),
    "extra-prose": lambda body: body + " was recorded",
    "empty": lambda body: "",
}

FROZEN_COMMENT_BODIES = (
    constants.STATUS_IN_PROGRESS,
    constants.STATUS_FIXED,
    constants.DECISION_APPROVE_FIX,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def child(**overrides: object) -> logic.ChildIssue:
    """A fully-specified child issue; each vector overrides only what it discriminates.

    Defaults are an ``OPEN`` child with no status comments, so the fixture itself can never
    be the reason a wrong-case label vector returns ``False``/``None``.
    """
    values: dict[str, object] = {
        "number": 238,
        "title": "Preserve matching semantics",
        "url": "https://github.com/mythical-forge/aidt/issues/238",
        "state": "OPEN",
        "labels": ["review-follow-up", "must-fix", "approve-fix"],
        "comment_bodies": [],
    }
    values.update(overrides)
    return logic.ChildIssue(**values)  # type: ignore[arg-type]


def rendered_marker(kind: str, pr_url: str = PR_URL) -> str:
    """Render one marker through ``gh``, the accessor that owns the config handoff."""
    if kind == "parent":
        return gh.parent_marker(pr_url)
    if kind == "child":
        return gh.child_marker(pr_url, "F1")
    if kind == "summary":
        return gh.summary_marker(pr_url)
    raise AssertionError(f"unknown marker kind {kind!r}")


def issue_rows(*bodies: str, pull_requests: bool = False) -> list[dict]:
    """Fake ``gh api repos/…/issues`` rows, one per body, in listing order."""
    rows = [
        {
            "number": index,
            "title": f"issue {index}",
            "html_url": f"https://github.com/mythical-forge/aidt/issues/{index}",
            "state": "open",
            "body": body,
        }
        for index, body in enumerate(bodies, start=1)
    ]
    if pull_requests:
        rows.insert(0, {**rows[0], "number": 900, "pull_request": {"url": "u"}})
    return rows


def list_issues_returning(rows: list[dict]) -> Callable[[str], list[dict]]:
    """A ``list_issues`` replacement returning *fresh copies*, counting its calls."""
    calls: list[str] = []

    def _list_issues(repo: str) -> list[dict]:
        calls.append(repo)
        return copy.deepcopy(rows)

    _list_issues.calls = calls  # type: ignore[attr-defined]
    return _list_issues


class FakeLabelRepo:
    """``gh label list``/``gh label create`` against an in-memory label set.

    ``create_label`` appends to the set so ``ensure_labels``' post-create verification
    passes exactly as it would against a real repository, and every call is recorded so a
    test can assert both *which* names were created and *with which* definition.
    """

    def __init__(self, labels: list[dict] | None = None) -> None:
        self.labels = labels or []
        self.created: list[tuple[str, str, str]] = []
        self.list_calls = 0

    def label_list(self, _repo: str) -> list[dict]:
        self.list_calls += 1
        return [dict(label) for label in self.labels]

    def create_label(self, _repo: str, name: str, color: str, description: str) -> None:
        self.created.append((name, color, description))
        self.labels.append({"name": name, "color": color, "description": description})

    @property
    def created_names(self) -> list[str]:
        return [name for name, _, _ in self.created]


@pytest.fixture(autouse=True)
def frozen_label_definitions_untouched():
    """Purity (requirement 5): no vector mutates either home of the frozen definitions."""
    constants_before = copy.deepcopy(constants.LABEL_DEFINITIONS)
    gh_before = copy.deepcopy(gh.LABEL_DEFINITIONS)
    yield
    assert constants.LABEL_DEFINITIONS == constants_before
    assert gh.LABEL_DEFINITIONS == gh_before


@pytest.fixture
def no_shell_out(monkeypatch):
    """Matching paths must not invoke ``gh`` beyond their one listing call."""

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("a matching path must not shell out")

    monkeypatch.setattr(gh, "run", _boom)
    monkeypatch.setattr(gh, "probe", _boom)


# ---------------------------------------------------------------------------
# 1. Comment bodies: strict equality, no whitespace/case normalisation (§3.9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exact", FROZEN_COMMENT_BODIES)
def test_has_exact_comment_matches_the_frozen_body_byte_for_byte(exact: str) -> None:
    """``body == exact``: the exact literal matches, nothing else does."""
    assert logic.has_exact_comment([exact], exact) is True
    # a mention inside a longer body is not a match
    assert logic.has_exact_comment([f"Recorded: {exact}"], exact) is False
    assert logic.has_exact_comment([], exact) is False


@pytest.mark.parametrize("exact", FROZEN_COMMENT_BODIES)
@pytest.mark.parametrize("mutation", BODY_MUTATIONS.values(), ids=BODY_MUTATIONS.keys())
def test_has_exact_comment_rejects_every_mutation_of_the_frozen_body(
    exact: str, mutation: Callable[[str], str]
) -> None:
    """No trailing whitespace, newline, case change, prefix, or suffix matches.

    This is the §3.9 rule read literally: ``logic.py`` compares with ``==``, so a
    ``.strip()``/``.casefold()`` "tidy-up" of the comparison fails every one of these.
    """
    mutated = mutation(exact)
    assert mutated != exact
    assert logic.has_exact_comment([mutated], exact) is False


def test_a_trailing_newline_on_a_status_comment_does_not_block_availability() -> None:
    """The decision that reads the flag, not just the flag itself: whitespace is a non-match."""
    with_newline = child(comment_bodies=[constants.STATUS_FIXED + "\n"])
    assert logic.availability(with_newline) == logic.Availability(True, None)
    # positive control: the byte-exact body does block
    exact = child(comment_bodies=[constants.STATUS_FIXED])
    assert logic.availability(exact) == logic.Availability(False, "STATUS_FIXED")


def test_a_trailing_newline_on_the_decision_comment_does_not_approve_a_child() -> None:
    """``is_approved`` reads the same strict equality; a padded decision is not the decision."""
    padded = child(
        labels=["review-follow-up", "must-fix", "approve-fix"],
        comment_bodies=[constants.DECISION_APPROVE_FIX + "\n"],
    )
    assert logic.is_approved(padded) is False
    assert logic.approval_plan(padded).add_decision_comment is True
    # positive control: the exact body approves and is inert afterwards
    exact = child(
        labels=["review-follow-up", "must-fix", "approve-fix"],
        comment_bodies=[constants.DECISION_APPROVE_FIX],
    )
    assert logic.is_approved(exact) is True
    assert logic.approval_plan(exact).add_decision_comment is False


# ---------------------------------------------------------------------------
# 2. Markers: literal string match, never a regex (§3.9)
# ---------------------------------------------------------------------------


def test_find_parent_issues_finds_the_issue_carrying_the_exact_marker(
    monkeypatch, no_shell_out
) -> None:
    """Positive control for the near-miss vectors: the byte-exact marker matches."""
    marker = rendered_marker("parent")
    listing = list_issues_returning(issue_rows(f"{marker}\n\n## Source\n"))
    monkeypatch.setattr(gh, "list_issues", listing)

    parents = gh.find_parent_issues("mythical-forge/aidt", PR_URL)

    assert [parent.number for parent in parents] == [1]
    assert parents[0].url == "https://github.com/mythical-forge/aidt/issues/1"
    assert parents[0].state == "OPEN"
    assert listing.calls == ["mythical-forge/aidt"]  # one listing, no other gh call


def test_find_parent_issues_ignores_a_body_whose_url_dot_was_substituted(
    monkeypatch, no_shell_out
) -> None:
    """The regex-near-miss vector (§3.9, D5).

    The rendered marker's URL dots are regex metacharacters: `re.search(marker, body)`
    "for flexibility" matches this body and orphans the real parent, while the frozen
    `marker not in body` does not.
    """
    marker = rendered_marker("parent")
    dot = marker.index(".")
    near_miss = marker[:dot] + "x" + marker[dot + 1 :]
    assert near_miss != marker and len(near_miss) == len(marker)

    rows = issue_rows(near_miss, marker)
    monkeypatch.setattr(gh, "list_issues", list_issues_returning(rows))

    parents = gh.find_parent_issues("mythical-forge/aidt", PR_URL)

    assert [parent.number for parent in parents] == [2]  # only the byte-exact one


def test_find_parent_issues_matches_the_marker_inside_a_longer_published_body(
    monkeypatch, no_shell_out
) -> None:
    """The frozen contract is `marker in body`, not `body == marker` (§3.9).

    Published parents carry marker *plus* prose; tightening this to equality would orphan
    every existing parent just as surely as a regex matcher would.
    """
    marker = rendered_marker("parent")
    body = f"{marker}\n\n## Purpose\n\nGroups the findings from the review.\n"
    monkeypatch.setattr(gh, "list_issues", list_issues_returning(issue_rows(body)))

    assert [parent.number for parent in gh.find_parent_issues("o/r", PR_URL)] == [1]


def test_find_parent_issues_ignores_pull_requests_carrying_the_marker(
    monkeypatch, no_shell_out
) -> None:
    """The candidate filter stays: only non-PR issues are parent candidates."""
    marker = rendered_marker("parent")
    monkeypatch.setattr(
        gh, "list_issues", list_issues_returning(issue_rows(marker, pull_requests=True))
    )

    parents = gh.find_parent_issues("mythical-forge/aidt", PR_URL)

    assert [parent.number for parent in parents] == [1]


@pytest.mark.parametrize("kind", ["parent", "child", "summary"])
def test_find_marked_issues_finds_the_issue_carrying_the_exact_marker(
    monkeypatch, no_shell_out, kind: str
) -> None:
    """Positive control for the publisher's marker search, for all three frozen markers."""
    marker = rendered_marker(kind)
    listing = list_issues_returning(issue_rows("unrelated body", f"{marker}\n"))
    monkeypatch.setattr(publish_review_followups, "list_issues", listing)

    found = publish_review_followups.find_marked_issues("mythical-forge/aidt", marker)

    assert [row["number"] for row in found] == [2]
    assert found[0]["url"] == "https://github.com/mythical-forge/aidt/issues/2"
    assert listing.calls == ["mythical-forge/aidt"]


@pytest.mark.parametrize("kind", ["parent", "child", "summary"])
def test_find_marked_issues_ignores_a_body_whose_url_dot_was_substituted(
    monkeypatch, no_shell_out, kind: str
) -> None:
    """Same near-miss vector on the publisher's search (`publish_review_followups.py`)."""
    marker = rendered_marker(kind)
    dot = marker.index(".")
    near_miss = marker[:dot] + "-" + marker[dot + 1 :]

    rows = issue_rows(near_miss, marker)
    monkeypatch.setattr(
        publish_review_followups, "list_issues", list_issues_returning(rows)
    )

    found = publish_review_followups.find_marked_issues("mythical-forge/aidt", marker)

    assert [row["number"] for row in found] == [2]


@pytest.mark.parametrize("kind", ["parent", "child", "summary"])
def test_property_a_marker_with_one_substituted_url_character_never_matches(
    monkeypatch, no_shell_out, kind: str
) -> None:
    """Property: substituting any one character for a URL ``.`` never matches; restoring it does.

    Seeded (`PROPERTY_SEED`) and run a pinned number of times (`PROPERTY_RUNS`) so the
    failure is reproducible. The metamorphic relation is both directions in one iteration:
    the near miss must find nothing, and the byte-exact marker must find the issue — so an
    implementation that matches *nothing* fails too.
    """
    rng = random.Random(PROPERTY_SEED)
    pr_url = "https://github.com/mythical-forge/aidt.core/pull/237"
    marker = rendered_marker(kind, pr_url)
    dot_positions = [index for index, char in enumerate(marker) if char == "."]
    assert len(dot_positions) >= 2  # the probe positions exist: the URL really has dots

    for _ in range(PROPERTY_RUNS):
        position = rng.choice(dot_positions)
        replacement = rng.choice(PROBE_CHARS)
        near_miss = marker[:position] + replacement + marker[position + 1 :]
        assert near_miss != marker
        assert len(near_miss) == len(marker)

        monkeypatch.setattr(
            publish_review_followups,
            "list_issues",
            list_issues_returning(issue_rows(near_miss)),
        )
        assert publish_review_followups.find_marked_issues("o/r", marker) == []

        monkeypatch.setattr(
            publish_review_followups,
            "list_issues",
            list_issues_returning(issue_rows(marker)),
        )
        assert [
            row["number"]
            for row in publish_review_followups.find_marked_issues("o/r", marker)
        ] == [1]


def test_property_find_parent_issues_never_matches_a_substituted_url_dot(
    monkeypatch, no_shell_out
) -> None:
    """The same property on ``gh.find_parent_issues``, which renders the marker itself."""
    rng = random.Random(PROPERTY_SEED)
    marker = rendered_marker("parent")
    dot_positions = [index for index, char in enumerate(marker) if char == "."]

    for _ in range(PROPERTY_RUNS):
        position = rng.choice(dot_positions)
        near_miss = (
            marker[:position] + rng.choice(PROBE_CHARS) + marker[position + 1 :]
        )
        monkeypatch.setattr(gh, "list_issues", list_issues_returning(issue_rows(near_miss)))
        assert gh.find_parent_issues("o/r", PR_URL) == []

        monkeypatch.setattr(gh, "list_issues", list_issues_returning(issue_rows(marker)))
        assert [parent.number for parent in gh.find_parent_issues("o/r", PR_URL)] == [1]


def test_find_parent_issues_does_not_mutate_the_listing_or_the_marker(
    monkeypatch, no_shell_out
) -> None:
    """Purity: the search reads its rows and mutates neither them nor the marker."""
    marker = rendered_marker("parent")
    rows = issue_rows(marker)
    before = copy.deepcopy(rows)
    monkeypatch.setattr(
        gh, "list_issues", lambda _repo: copy.deepcopy(rows)
    )

    parents = gh.find_parent_issues("o/r", PR_URL)

    assert [parent.number for parent in parents] == [1]
    assert rows == before
    assert gh.parent_marker(PR_URL) == marker


# ---------------------------------------------------------------------------
# 3. Labels: case-sensitive membership, no folding, no stripping (§3.9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate", LABEL_MUTATIONS.values(), ids=LABEL_MUTATIONS.keys()
)
def test_no_approve_fix_name_variant_satisfies_the_approval_checks(
    mutate: Callable[[str], str]
) -> None:
    """Wrong-case (and space-padded) ``Approve-fix`` is a different label, not the approval."""
    variant = mutate(constants.LABEL_APPROVE_FIX)
    assert variant != constants.LABEL_APPROVE_FIX

    wrong = child(labels=["review-follow-up", "must-fix", variant])
    assert logic.availability(wrong) == logic.Availability(False, "MISSING_APPROVE_FIX")
    assert logic.approval_plan(wrong).add_labels == [constants.LABEL_APPROVE_FIX]
    assert (
        logic.is_approved(
            child(
                labels=["review-follow-up", variant],
                comment_bodies=[constants.DECISION_APPROVE_FIX],
            )
        )
        is False
    )

    # controls: the exact-case twin yields exactly what the variant denies
    twin = child(labels=["review-follow-up", "must-fix", constants.LABEL_APPROVE_FIX])
    assert logic.availability(twin) == logic.Availability(True, None)
    assert logic.approval_plan(twin).add_labels == []
    assert (
        logic.is_approved(
            child(
                labels=["review-follow-up", constants.LABEL_APPROVE_FIX],
                comment_bodies=[constants.DECISION_APPROVE_FIX],
            )
        )
        is True
    )


@pytest.mark.parametrize(
    "mutate", LABEL_MUTATIONS.values(), ids=LABEL_MUTATIONS.keys()
)
def test_no_priority_label_name_variant_is_read_as_a_priority(
    mutate: Callable[[str], str]
) -> None:
    """``priority_label`` returns ``None`` for ``Must-fix``; the exact twin returns it."""
    for exact in constants.PRIORITY_LABELS:
        variant = mutate(exact)
        assert variant != exact
        assert logic.priority_label(["review-follow-up", variant, "approve-fix"]) is None
        # the variant neither counts as the label nor makes two exact labels look ambiguous
        assert (
            logic.priority_label([variant, exact, mutate(constants.PRIORITY_LABELS[2])])
            == exact
        )
        # control: the exact-case twin is the label
        assert logic.priority_label(["review-follow-up", exact]) == exact


@pytest.mark.parametrize(
    "mutate", LABEL_MUTATIONS.values(), ids=LABEL_MUTATIONS.keys()
)
def test_no_decision_pending_name_variant_blocks_or_is_removed(
    mutate: Callable[[str], str]
) -> None:
    """A wrong-case ``Decision-pending`` blocks nothing and is never planned for removal."""
    variant = mutate(constants.LABEL_DECISION_PENDING)
    assert variant != constants.LABEL_DECISION_PENDING

    wrong = child(
        labels=["review-follow-up", "must-fix", "approve-fix", variant],
        comment_bodies=[constants.DECISION_APPROVE_FIX],
    )
    verdict = logic.availability(wrong)
    assert verdict.reason != "DECISION_PENDING"
    assert verdict == logic.Availability(True, None)
    assert logic.approval_plan(wrong).remove_labels == []
    assert logic.approval_plan(wrong).add_labels == []
    assert logic.is_approved(wrong) is True

    # control: the exact-case twin is blocked and is planned for removal
    twin = child(
        labels=[
            "review-follow-up",
            "must-fix",
            "approve-fix",
            constants.LABEL_DECISION_PENDING,
        ],
        comment_bodies=[constants.DECISION_APPROVE_FIX],
    )
    assert logic.availability(twin) == logic.Availability(False, "DECISION_PENDING")
    assert logic.approval_plan(twin).remove_labels == [constants.LABEL_DECISION_PENDING]
    assert logic.is_approved(twin) is False


def test_property_case_perturbation_never_satisfies_a_label_check() -> None:
    """Property: case-folding a label name on the child never satisfies the frozen checks.

    Seeded (`PROPERTY_SEED`) with `PROPERTY_RUNS` iterations. Each iteration perturbs a
    random subset of the frozen role labels and asserts the approval state still denies —
    with the unperturbed twin proving the fixture is not vacuous.
    """
    rng = random.Random(PROPERTY_SEED)
    frozen_labels = [
        constants.LABEL_REVIEW_FOLLOW_UP,
        constants.LABEL_APPROVE_FIX,
        constants.LABEL_DECISION_PENDING,
        *constants.PRIORITY_LABELS,
    ]

    for _ in range(PROPERTY_RUNS):
        perturbed = rng.sample(frozen_labels, rng.randint(1, len(frozen_labels)))
        variants = [
            name.upper() if rng.random() < 0.5 else name.capitalize()
            for name in perturbed
        ]
        assert all(name not in variants for name in frozen_labels)

        wrong = child(labels=variants, comment_bodies=[constants.DECISION_APPROVE_FIX])
        assert logic.availability(wrong).reason == "MISSING_APPROVE_FIX"
        assert logic.approval_plan(wrong).add_labels == [constants.LABEL_APPROVE_FIX]
        assert logic.is_approved(wrong) is False
        assert logic.priority_label(variants) is None

        twin = child(
            labels=["review-follow-up", "must-fix", "approve-fix"],
            comment_bodies=[constants.DECISION_APPROVE_FIX],
        )
        assert logic.availability(twin) == logic.Availability(True, None)
        assert logic.is_approved(twin) is True


# ---------------------------------------------------------------------------
# 4. "Ensure existing" never overwrites (D5)
# ---------------------------------------------------------------------------


def test_ensure_labels_never_creates_an_existing_label_again(monkeypatch) -> None:
    """``if name in existing: continue``: no create, and no rewrite of its definition.

    The existing entry carries a deliberately *repo-edited* colour/description, different
    from `gh.LABEL_DEFINITIONS`, so a "reconcile the definition" regression shows up as a
    create (or edit) call with that pair rather than passing silently.
    """
    existing = {
        "name": constants.LABEL_REVIEW_FOLLOW_UP,
        "color": "000001",
        "description": "repo-edited description",
    }
    fake = FakeLabelRepo([dict(existing)])
    monkeypatch.setattr(publish_review_followups, "label_list", fake.label_list)
    monkeypatch.setattr(publish_review_followups, "create_label", fake.create_label)

    publish_review_followups.ensure_labels("mythical-forge/aidt", False)

    assert constants.LABEL_REVIEW_FOLLOW_UP not in fake.created_names
    assert fake.created_names == [
        name
        for name in constants.PUBLISHER_LABELS
        if name != constants.LABEL_REVIEW_FOLLOW_UP
    ]
    for name, color, description in fake.created:
        assert (color, description) != (existing["color"], existing["description"])
        assert (color, description) == (
            gh.LABEL_DEFINITIONS[name]["color"],
            gh.LABEL_DEFINITIONS[name]["description"],
        )
    # the existing label's colour/description are untouched, not "corrected"
    assert fake.labels[0] == existing


def test_ensure_labels_creates_the_exact_name_when_only_a_wrong_case_one_exists(
    monkeypatch,
) -> None:
    """GitHub label names are case-sensitive: ``Review-follow-up`` ≠ ``review-follow-up``.

    A case-folding "improvement" here would skip creation and leave the publisher adding a
    label that does not exist; the pin is that every publisher label is created.
    """
    wrong_case = {
        "name": "Review-follow-up",
        "color": "5319E7",
        "description": "Review-generated task or parent issue",
    }
    fake = FakeLabelRepo([dict(wrong_case)])
    monkeypatch.setattr(publish_review_followups, "label_list", fake.label_list)
    monkeypatch.setattr(publish_review_followups, "create_label", fake.create_label)

    publish_review_followups.ensure_labels("mythical-forge/aidt", False)

    assert fake.created_names == list(constants.PUBLISHER_LABELS)
    assert fake.created[0] == (
        constants.LABEL_REVIEW_FOLLOW_UP,
        gh.LABEL_DEFINITIONS[constants.LABEL_REVIEW_FOLLOW_UP]["color"],
        gh.LABEL_DEFINITIONS[constants.LABEL_REVIEW_FOLLOW_UP]["description"],
    )
    assert fake.labels[0] == wrong_case  # the wrong-case label is left alone


def test_ensure_labels_creates_nothing_on_a_dry_run(monkeypatch, capsys) -> None:
    """The dry run reports every missing label and creates none of them."""
    fake = FakeLabelRepo([])
    monkeypatch.setattr(publish_review_followups, "label_list", fake.label_list)
    monkeypatch.setattr(publish_review_followups, "create_label", fake.create_label)

    publish_review_followups.ensure_labels("mythical-forge/aidt", True)

    assert fake.created == []
    out = capsys.readouterr().out
    for name in constants.PUBLISHER_LABELS:
        assert f"[dry-run] would create missing label: {name}" in out


def test_ensure_labels_fails_closed_on_a_missing_definition(monkeypatch) -> None:
    """A publisher label with no definition stops before anything is created."""
    definitions = {
        name: dict(definition)
        for name, definition in gh.LABEL_DEFINITIONS.items()
        if name != "must-fix"
    }
    monkeypatch.setattr(publish_review_followups, "LABEL_DEFINITIONS", definitions)
    existing = [
        {"name": name, "color": "111111", "description": "existing"}
        for name in constants.PUBLISHER_LABELS
        if name != "must-fix"
    ]
    fake = FakeLabelRepo(existing)
    monkeypatch.setattr(publish_review_followups, "label_list", fake.label_list)
    monkeypatch.setattr(publish_review_followups, "create_label", fake.create_label)

    with pytest.raises(UsageError, match="No label definition for must-fix"):
        publish_review_followups.ensure_labels("mythical-forge/aidt", False)

    assert fake.created == []


def test_ensure_approve_label_creates_only_when_the_exact_name_is_missing(monkeypatch) -> None:
    """The approver's "ensure existing" path (``review_followup.ensure_approve_label``).

    Same frozen rule as the publisher's: an exact existing name is a no-op, a wrong-case one
    is a different label and is created.
    """
    exact = FakeLabelRepo(
        [{"name": constants.LABEL_APPROVE_FIX, "color": "000001", "description": "edited"}]
    )
    monkeypatch.setattr(review_followup, "label_list", exact.label_list)
    monkeypatch.setattr(review_followup, "create_label", exact.create_label)
    assert review_followup.ensure_approve_label("mythical-forge/aidt") is False
    assert exact.created == []
    assert exact.labels[0]["color"] == "000001"

    wrong_case = FakeLabelRepo(
        [{"name": "Approve-fix", "color": "B8D64A", "description": "wrong case"}]
    )
    monkeypatch.setattr(review_followup, "label_list", wrong_case.label_list)
    monkeypatch.setattr(review_followup, "create_label", wrong_case.create_label)
    assert review_followup.ensure_approve_label("mythical-forge/aidt") is True
    assert wrong_case.created_names == [constants.LABEL_APPROVE_FIX]


LABEL_EDIT_CALL = re.compile(r"""["']label["']\s*,\s*["']edit["']""")


@pytest.mark.parametrize(
    "script", ["gh.py", "review_followup.py", "publish_review_followups.py"]
)
def test_no_script_issues_a_label_edit(script: str) -> None:
    """Structural: "never overwrite" holds because no label-edit call exists at all.

    Pinning only "``create_label`` is not called for existing names" would be vacuous if an
    overwrite arrived as an edit; this is the other half of the same guarantee (D5).
    """
    source = (SCRIPT_DIR / script).read_text(encoding="utf-8")
    assert LABEL_EDIT_CALL.search(source) is None
