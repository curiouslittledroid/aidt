"""The deferred close: ``review_followup.py close`` and its shared tail (05-P1.2).

P1.2 moves *when* a follow-up issue is closed — ``aidw fix`` closes it only after ``F5
commit-and-push`` has pushed a tree containing the fix (design §8.4, §17 Z9) — without moving
*what* closing does. So ``close`` must post the same frozen exact-match ``Status: fixed``
comment (§7.2), refuse the same things ``fixed`` refuses, and prove the write afterwards. The
shared rule is ``logic.close_plan`` and the shared write is
``review_followup.apply_close``; these tests pin both, plus the fact that ``fixed`` still
behaves as it did for callers that are not the ``fix`` workflow.

Everything here is pure: ``resolve_context``/``find_single_parent``/``load_children`` and every
``gh`` write are replaced with in-memory fakes, so no test shells out to ``gh`` or touches a
repository. ``test_logic.py`` owns the pure ``close_plan`` table; this module owns the command.

Run with: uv run pytest prompts/scripts/review-followup/tests
"""

from __future__ import annotations

import json

import pytest

import gh
import logic
import review_followup
from logic import ChildIssue
from proc import UsageError


def issue(**overrides: object) -> ChildIssue:
    """A child issue, by default the in-flight child ``start`` left behind."""
    values: dict[str, object] = {
        "number": 101,
        "title": "Fix the loop",
        "url": "https://github.com/o/r/issues/101",
        "state": "OPEN",
        "labels": ["review-follow-up", "must-fix", "approve-fix"],
        "comment_bodies": ["Status: in progress"],
    }
    values.update(overrides)
    return ChildIssue(**values)  # type: ignore[arg-type]


class FakeGithub:
    """In-memory GitHub state: one PR, one parent, one mutable child, recorded writes."""

    def __init__(self, child: ChildIssue, *, survive: bool = True) -> None:
        self.child = child
        self.survive = survive
        self.comments: list[tuple[int, str]] = []
        self.closed: list[tuple[int, str]] = []

    def get_issue(self, _repo: str, number: int) -> ChildIssue:
        assert number == self.child.number
        return self.child

    def add_comment(self, _repo: str, number: int, body: str) -> None:
        self.comments.append((number, body))
        self.child = ChildIssue(
            number=self.child.number,
            title=self.child.title,
            url=self.child.url,
            state=self.child.state,
            labels=self.child.labels,
            comment_bodies=[*self.child.comment_bodies, body],
        )

    def close_issue(self, _repo: str, number: int, body: str) -> None:
        self.closed.append((number, body))
        # The post-close read is the contract: a write that does not survive the re-read
        # (or one GitHub silently refused) must fail the command, never exit 0.
        self.child = ChildIssue(
            number=self.child.number,
            title=self.child.title,
            url=self.child.url,
            state="CLOSED" if self.survive else "OPEN",
            labels=(
                self.child.labels
                if self.survive
                else [label for label in self.child.labels if label != "approve-fix"]
            ),
            comment_bodies=self.child.comment_bodies,
        )


def patch_github(monkeypatch, fake: FakeGithub) -> None:
    """Point the command at the fake repository; nothing else may reach ``gh``."""
    context = review_followup.Context(
        repo="o/r",
        pr=gh.PrInfo(
            number=7,
            title="A PR",
            url="https://github.com/o/r/pull/7",
            state="OPEN",
            headRefName="03-E4.1",
            baseRefName="main",
        ),
        branch="03-E4.1",
        branch_matches=True,
    )
    monkeypatch.setattr(review_followup, "resolve_context", lambda _pr: context)
    monkeypatch.setattr(
        review_followup,
        "find_single_parent",
        lambda _repo, _url: gh.ParentIssue(
            number=100,
            title="Review follow-ups",
            url="https://github.com/o/r/issues/100",
            state="OPEN",
        ),
    )
    monkeypatch.setattr(
        review_followup, "load_children", lambda _repo, _parent: [fake.child]
    )
    monkeypatch.setattr(review_followup, "get_issue", fake.get_issue)
    monkeypatch.setattr(review_followup, "add_comment", fake.add_comment)
    monkeypatch.setattr(review_followup, "close_issue", fake.close_issue)


def body_file(tmp_path, text: str = "Implemented on the current PR branch.\n") -> str:
    path = tmp_path / "closing-body.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


BODY = "Implemented on the current PR branch.\n\n**Verification**\n- `pytest` — 12 passed\n"


def run(argv: list[str], capsys) -> tuple[int, dict]:
    code = review_followup.main(argv)
    payload = json.loads(capsys.readouterr().out)
    return code, payload


# ── the happy path ────────────────────────────────────────────────────────


def test_close_posts_the_exact_marker_once_and_closes_with_the_body(
    tmp_path, monkeypatch, capsys
) -> None:
    """One call: exact ``Status: fixed``, then close, then a passing re-read."""
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)
    body = body_file(tmp_path, BODY)

    code, payload = run(["close", "--pr", "7", "--issue", "101", "--body-file", body], capsys)

    assert code == 0
    assert fake.comments == [(101, "Status: fixed")]
    assert fake.closed == [(101, BODY.strip())]
    assert payload["action"] == "closed"
    assert payload["statusCommentAdded"] is True
    assert payload["labelsIntact"] is True
    assert payload["issue"]["state"] == "CLOSED"


def test_close_is_idempotent_when_the_marker_is_already_present(
    tmp_path, monkeypatch, capsys
) -> None:
    """A rerun (or a marker posted by an earlier attempt) never duplicates the comment."""
    fake = FakeGithub(issue(comment_bodies=["Status: in progress", "Status: fixed"]))
    patch_github(monkeypatch, fake)

    code, payload = run(
        ["close", "--pr", "7", "--issue", "101", "--body-file", body_file(tmp_path)],
        capsys,
    )

    assert code == 0
    assert fake.comments == []
    assert payload["statusCommentAdded"] is False
    assert len(fake.closed) == 1


def test_repeating_a_completed_close_is_a_no_op(
    tmp_path, monkeypatch, capsys
) -> None:
    """Closed **and** marked fixed: nothing to write, exit 0 — never a conflict."""
    fake = FakeGithub(issue(state="CLOSED", comment_bodies=["Status: fixed"]))
    patch_github(monkeypatch, fake)

    code, payload = run(
        ["close", "--pr", "7", "--issue", "101", "--body-file", body_file(tmp_path)],
        capsys,
    )

    assert code == 0
    assert payload["action"] == "none"
    assert payload["reason"] == "ALREADY_CLOSED_AND_FIXED"
    assert fake.comments == [] and fake.closed == []


def test_dry_run_reports_the_plan_without_any_write(
    tmp_path, monkeypatch, capsys
) -> None:
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)
    body = body_file(tmp_path)

    code, payload = run(
        ["close", "--pr", "7", "--issue", "101", "--body-file", body, "--dry-run"],
        capsys,
    )

    assert code == 0
    assert payload["action"] == "dry-run"
    assert payload["wouldComment"] == "Status: fixed"
    assert payload["wouldClose"] is True
    assert payload["bodyFile"] == body
    assert fake.comments == [] and fake.closed == []


# ── the body guards (fail closed before any close action) ─────────────────


def test_a_body_that_repeats_the_status_marker_is_refused(
    tmp_path, monkeypatch, capsys
) -> None:
    """The marker is its own exact-match comment; a body repeating it would double it."""
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)

    code = review_followup.cli(
        [
            "close",
            "--pr",
            "7",
            "--issue",
            "101",
            "--body-file",
            body_file(tmp_path, "Status: fixed\n\nImplemented.\n"),
        ]
    )

    assert code == 2
    assert "Status: fixed" in capsys.readouterr().err
    assert fake.comments == [] and fake.closed == []


def test_a_body_prefixed_by_the_status_marker_is_refused(
    tmp_path, monkeypatch, capsys
) -> None:
    """The deferred-close contract rejects any body beginning with ``Status: fixed``."""
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)

    code = review_followup.cli(
        [
            "close",
            "--pr",
            "7",
            "--issue",
            "101",
            "--body-file",
            body_file(tmp_path, "Status: fixed — verification details\n"),
        ]
    )

    assert code == 2
    assert "Status: fixed" in capsys.readouterr().err
    assert fake.comments == [] and fake.closed == []


def test_a_missing_body_file_is_refused_before_any_github_call(
    tmp_path, monkeypatch, capsys
) -> None:
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)

    code = review_followup.cli(
        ["close", "--pr", "7", "--issue", "101", "--body-file", str(tmp_path / "nope.md")]
    )

    assert code == 2
    assert "--body-file not found" in capsys.readouterr().err
    assert fake.comments == [] and fake.closed == []


def test_an_empty_body_file_is_refused(tmp_path, monkeypatch, capsys) -> None:
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)

    code = review_followup.cli(
        [
            "close",
            "--pr",
            "7",
            "--issue",
            "101",
            "--body-file",
            body_file(tmp_path, "   \n\n"),
        ]
    )

    assert code == 2
    assert "is empty" in capsys.readouterr().err
    assert fake.comments == [] and fake.closed == []


def test_a_missing_body_flag_is_refused(tmp_path, monkeypatch, capsys) -> None:
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)

    code = review_followup.cli(["close", "--pr", "7", "--issue", "101"])

    assert code == 2
    assert "Missing --body-file" in capsys.readouterr().err
    assert fake.closed == []


# ── the selection guards ──────────────────────────────────────────────────


def test_close_requires_an_explicit_issue(tmp_path, monkeypatch, capsys) -> None:
    """`close` never re-derives a selection: the in-flight child is not first-available."""
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)

    code = review_followup.cli(["close", "--pr", "7", "--body-file", body_file(tmp_path)])

    assert code == 2
    assert "Missing --issue" in capsys.readouterr().err
    assert fake.comments == [] and fake.closed == []


def test_close_does_not_re_run_the_first_available_guard(
    tmp_path, monkeypatch, capsys
) -> None:
    """The regression the prompt warns about: a later available child must not matter.

    ``select`` would skip the in-flight issue and pick #102, so any reuse of ``fixed``'s
    selection step would refuse this close with ``EXIT_CONFLICT``. Resolving by ``--issue``
    alone is what makes the deferred close possible at all.
    """
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)
    monkeypatch.setattr(
        review_followup,
        "load_children",
        lambda _repo, _parent: [
            fake.child,
            issue(number=102, title="The next one", comment_bodies=[]),
        ],
    )

    code, payload = run(
        ["close", "--pr", "7", "--issue", "101", "--body-file", body_file(tmp_path)],
        capsys,
    )

    assert code == 0
    assert payload["issue"]["number"] == 101
    assert fake.closed == [(101, "Implemented on the current PR branch.")]


def test_an_issue_that_is_not_a_child_is_refused(tmp_path, monkeypatch, capsys) -> None:
    fake = FakeGithub(issue())
    patch_github(monkeypatch, fake)

    code = review_followup.cli(
        ["close", "--pr", "7", "--issue", "999", "--body-file", body_file(tmp_path)]
    )

    assert code == 2
    assert "not a native child" in capsys.readouterr().err
    assert fake.closed == []


# ── the label / state guards ──────────────────────────────────────────────


def test_a_child_missing_a_required_label_is_refused(
    tmp_path, monkeypatch, capsys
) -> None:
    fake = FakeGithub(issue(labels=["review-follow-up", "must-fix"]))
    patch_github(monkeypatch, fake)

    code = review_followup.cli(
        ["close", "--pr", "7", "--issue", "101", "--body-file", body_file(tmp_path)]
    )

    assert code == 4
    err = capsys.readouterr().err
    assert "approve-fix" in err
    assert "Refusing to close" in err
    assert fake.comments == [] and fake.closed == []


def test_a_closed_issue_without_the_marker_is_never_reopened(
    tmp_path, monkeypatch, capsys
) -> None:
    fake = FakeGithub(issue(state="CLOSED", comment_bodies=["Status: in progress"]))
    patch_github(monkeypatch, fake)

    code = review_followup.cli(
        ["close", "--pr", "7", "--issue", "101", "--body-file", body_file(tmp_path)]
    )

    assert code == 4
    assert "Refusing to reopen" in capsys.readouterr().err
    assert fake.closed == []


# ── the post-close verification ───────────────────────────────────────────


def test_a_close_that_did_not_survive_the_re_read_fails_verification(
    tmp_path, monkeypatch, capsys
) -> None:
    """An exit-0 ``gh`` call is not evidence: the re-read decides (design §10)."""
    fake = FakeGithub(issue(), survive=False)
    patch_github(monkeypatch, fake)

    code = review_followup.cli(
        ["close", "--pr", "7", "--issue", "101", "--body-file", body_file(tmp_path)]
    )

    assert code == 1
    assert "post-close verification failed" in capsys.readouterr().err
    assert len(fake.closed) == 1


# ── the contract `fixed` keeps ────────────────────────────────────────────


def test_fixed_still_closes_in_stage_through_the_same_tail(
    tmp_path, monkeypatch, capsys
) -> None:
    """``fixed`` is kept: selection plus the identical marker, close and verification."""
    fake = FakeGithub(issue(comment_bodies=[]))
    patch_github(monkeypatch, fake)
    body = body_file(tmp_path, BODY)

    code, payload = run(["fixed", "--pr", "7", "--issue", "101", "--body-file", body], capsys)

    assert code == 0
    assert fake.comments == [(101, "Status: fixed")]
    assert fake.closed == [(101, BODY.strip())]
    assert payload["action"] == "closed"


# ── the help contract ─────────────────────────────────────────────────────


def test_help_and_usage_list_the_close_command(capsys) -> None:
    """The CLI surface names it, and an unknown command's error lists it too (req 2)."""
    assert review_followup.main(["help"]) == 0
    assert "review_followup.py close" in capsys.readouterr().out

    with pytest.raises(UsageError) as raised:
        logic.parse_args(["frobnicate"])
    assert "close" in str(raised.value)
    assert "close" in logic.COMMANDS
