"""Whole-repo verification gates: identity, recording and same-tree reuse (E4.8).

The contract under test is the one the PR stage depends on: a run may cite a gate
outcome another stage recorded **for the same tree**, and it must never cite one it
cannot prove applies — a different tree, a different command, a different run, a failed
outcome, or a repo whose base branch will not resolve.

Identity is content, so committing the verified change set must not invalidate it, while
any content change must. These tests build real repositories so the git-side identity is
exercised rather than mocked.

The persistence contract (H0.1) is tested here too, because it is what makes a citation
possible at all: an outcome recorded by a stage's own ``aidw gate run`` subprocess must
still be in the file after the workflow's next ``save()``, the two writers must not drop
each other's rows, and an unlocked reader must never observe a torn file. Those tests
drive ``aidw/runner.py:run_stage`` against the real file (with a faked Pi result) instead
of faking a stage by setting ``AIDW_STAGE`` alone, which is why the loss stayed green.
"""

from __future__ import annotations

import fcntl
import json
import os
import random
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidw import runner as runner_mod
from aidw import verification
from aidw.cli import EXIT_USAGE, app
from aidw.config import load_all
from aidw.log import RunLogger
from aidw.paths import (
    STATE_DIR_ENV_VAR,
    RUN_ID_ENV_VAR,
    STAGE_ENV_VAR,
    TargetRepo,
    WorkspacePaths,
    toolkit_root,
)
from aidw.pi import PiResult, Usage
from aidw.runner import StageSpec, run_stage
from aidw.state import (
    GATE_FAILED,
    PASSED,
    GateOutcome,
    StageRecord,
    append_gate_outcomes,
    create_run,
    load,
    merge_gate_outcomes,
    outcome_identity,
    run_dir,
    save,
    state_lock_path,
    state_write_lock,
)

cli = CliRunner()


def _git(directory: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A target repo on branch ``task`` carrying one uncommitted change vs ``main``."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    _git(root, "checkout", "-q", "-b", "task")
    (root / "app.py").write_text("x = 2\n", encoding="utf-8")
    return root


@pytest.fixture
def run(tmp_path: Path, repo: Path):  # noqa: ARG001 - ensures the repo exists first
    runs_root = tmp_path / "runs"
    return create_run(runs_root, repo, "implement", label="task", branch="task"), runs_root


def _identity(repo: Path, **kwargs) -> str | None:
    return verification.tree_identity(repo, **kwargs)


def _passing(
    key: str = "suite",
    command: list[str] | None = None,
    tree: str = "t",
    summary: str = "439 passed in 97.98s",
    at: str = "2026-01-01T00:00:00Z",
) -> GateOutcome:
    return GateOutcome(
        key=key,
        command=command or ["true"],
        tree=tree,
        status=PASSED,
        stage="test",
        at=at,
        exit_code=0,
        summary=summary,
    )


# --------------------------------------------------------------------------- #
# Tree identity
# --------------------------------------------------------------------------- #


def test_identity_is_stable_across_calls(repo: Path) -> None:
    assert _identity(repo) == _identity(repo)


def test_identity_survives_staging_and_committing_the_verified_tree(repo: Path) -> None:
    """The PR stage's own flow: it gates, then commits, then cites.

    ``HEAD`` is deliberately not part of the identity, so committing the change set the
    gate just verified cannot invalidate its own outcome. Without this, the stage that
    commits is the one stage that can never reuse its own predecessors' work.
    """
    before = _identity(repo)
    _git(repo, "add", "-A")
    assert _identity(repo) == before  # staged, not committed
    _git(repo, "commit", "-qm", "feat: the change")
    assert _identity(repo) == before  # committed


def test_identity_changes_when_a_file_changes(repo: Path) -> None:
    before = _identity(repo)
    (repo / "app.py").write_text("x = 3\n", encoding="utf-8")
    assert _identity(repo) != before


def test_identity_changes_when_a_new_untracked_file_appears(repo: Path) -> None:
    """An untracked file is part of the tree a gate can depend on."""
    before = _identity(repo)
    (repo / "test_app.py").write_text("def test_it(): pass\n", encoding="utf-8")
    assert _identity(repo) != before


def test_identity_changes_when_a_file_is_deleted(repo: Path) -> None:
    before = _identity(repo)
    (repo / ".gitignore").unlink()
    assert _identity(repo) != before


def test_identity_changes_when_only_the_execution_bit_changes(repo: Path) -> None:
    before = _identity(repo)
    (repo / "app.py").chmod(0o755)
    assert _identity(repo) != before


def test_identity_ignores_gitignored_files(repo: Path) -> None:
    """Build output a gate does not read must not force a re-run."""
    before = _identity(repo)
    (repo / "ignored.txt").write_text("scratch\n", encoding="utf-8")
    assert _identity(repo) == before


def test_identity_excludes_named_paths(repo: Path) -> None:
    """The run's own state root must never be part of the gated content.

    With ``AIDW_STATE_DIR`` inside the repo and not gitignored, every stage's log write
    would otherwise change the identity, and no gate would ever be reused.
    """
    state_root = repo / ".aidw" / "state" / "slug"
    state_root.mkdir(parents=True)
    before = _identity(repo, exclude=(state_root,))
    (state_root / "state.json").write_text("{}\n", encoding="utf-8")
    assert _identity(repo, exclude=(state_root,)) == before
    # And without the exclusion it is visible, so the exclusion is the thing doing it.
    assert _identity(repo) != before


def test_identity_is_none_when_the_base_branch_does_not_resolve(tmp_path: Path) -> None:
    """Fail closed: an unknown base means "cannot prove", never "no changes"."""
    root = tmp_path / "trunk-only"
    root.mkdir()
    _git(root, "init", "-q", "-b", "trunk")
    (root / "a.txt").write_text("x\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")

    assert _identity(root, base="main") is None


def test_identity_is_none_for_a_repository_with_no_commits(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")

    assert _identity(root) is None


def test_identity_is_none_when_the_change_set_is_over_budget(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo that does not gitignore its dependencies must not stall a gate.

    Over budget the identity is unknown, so nothing is cited and the gate runs — the
    status quo — rather than hashing hundreds of thousands of untracked files.
    """
    monkeypatch.setattr(verification, "MAX_IDENTITY_PATHS", 0)
    assert _identity(repo) is None


def test_identity_is_none_when_the_content_is_over_the_byte_budget(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verification, "MAX_IDENTITY_BYTES", 1)

    assert _identity(repo) is None


def test_an_over_budget_tree_never_records_or_cites(
    repo: Path, run, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _runs_root = run
    monkeypatch.setattr(verification, "MAX_IDENTITY_PATHS", 0)

    first = verification.run_gate("suite", ["true"], repo_root=repo, run=state)
    second = verification.run_gate("suite", ["true"], repo_root=repo, run=state)

    assert not first.reused and not second.reused
    assert state.gate_outcomes == []


# --------------------------------------------------------------------------- #
# Declared scope
# --------------------------------------------------------------------------- #


def test_normalise_ignore_canonicalises_equivalent_spellings() -> None:
    assert verification.normalise_ignore(["docs/x/", "./docs/x", "docs/x"]) == ("docs/x",)
    assert verification.normalise_ignore(["b", "a"]) == ("a", "b")
    assert verification.normalise_ignore([]) == ()


@pytest.mark.parametrize("value", ["", "  ", ".", "./", "../outside", "/etc"])
def test_normalise_ignore_rejects_unsafe_prefixes(value: str) -> None:
    with pytest.raises(ValueError):
        verification.normalise_ignore([value])


def test_identity_ignores_a_declared_prefix(repo: Path) -> None:
    before = _identity(repo, ignore=("docs/implementation-results",))
    docs = repo / "docs" / "implementation-results" / "task"
    docs.mkdir(parents=True)
    (docs / "build-results.md").write_text("# results\n", encoding="utf-8")

    assert _identity(repo, ignore=("docs/implementation-results",)) == before
    # The same write without the declaration is visible, so the declaration is what did it.
    assert _identity(repo) != before


def test_a_declared_scope_is_cited_across_a_document_write(repo: Path, run) -> None:
    """The chain E4.8 exists for: I2 gates, I5 writes a document, I6 cites.

    Without a declared scope the results document that ``record`` writes makes the tree
    ``pr`` delivers unequal to the tree ``test`` gated, and the suite is bought again.
    """
    state, _runs_root = run
    scope = ("docs/implementation-results", "docs/architecture")
    command = ["sh", "-c", "echo 439 passed in 97.98s"]

    verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="test", ignore=scope
    )
    # I5's deliverable, written after the gate it reported on.
    docs = repo / "docs" / "implementation-results" / "task"
    docs.mkdir(parents=True)
    (docs / "build-results.md").write_text("# results\n", encoding="utf-8")

    cited = verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="pr", ignore=scope
    )

    assert cited.reused
    assert len(state.gate_outcomes) == 1
    assert "scope excludes: docs/architecture, docs/implementation-results" in cited.citation


def test_a_changed_code_file_still_reruns_under_a_declared_scope(repo: Path, run) -> None:
    """Ignoring documents must not become ignoring the gate's actual inputs."""
    state, _runs_root = run
    scope = ("docs/implementation-results",)
    command = ["true"]
    verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="test", ignore=scope
    )

    (repo / "app.py").write_text("x = 99\n", encoding="utf-8")
    after = verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="pr", ignore=scope
    )

    assert not after.reused


def test_a_differently_declared_scope_does_not_cite(repo: Path, run) -> None:
    """The scope is part of the claim, so a wider or narrower one cannot reuse it."""
    state, _runs_root = run
    command = ["true"]
    verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="test",
        ignore=("docs/implementation-results",),
    )

    wider = verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="pr",
        ignore=("docs/implementation-results", "docs/architecture"),
    )
    narrower = verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="pr", ignore=()
    )

    assert not wider.reused
    assert not narrower.reused


def test_equivalent_scope_spellings_still_cite(repo: Path, run) -> None:
    state, _runs_root = run
    command = ["true"]
    verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="test",
        ignore=("docs/implementation-results/", "./docs/architecture"),
    )

    cited = verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="pr",
        ignore=("docs/architecture", "docs/implementation-results"),
    )

    assert cited.reused


def test_describe_shows_the_declared_scope(repo: Path, run) -> None:
    state, _runs_root = run
    verification.run_gate(
        "suite", ["true"], repo_root=repo, run=state, ignore=("docs/implementation-results",)
    )

    text = "\n".join(verification.describe(state.gate_outcomes[0]))

    assert "scope excludes docs/implementation-results" in text


# --------------------------------------------------------------------------- #
# Running and citing
# --------------------------------------------------------------------------- #


def test_first_gate_runs_records_and_reports(repo: Path, run) -> None:
    state, _runs_root = run

    result = verification.run_gate(
        "suite",
        ["sh", "-c", "echo 439 passed in 97.98s"],
        repo_root=repo,
        run=state,
        stage="test",
    )

    assert result.passed
    assert not result.reused
    assert result.exit_code == 0
    assert result.summary == "439 passed in 97.98s"
    assert result.tree == _identity(repo)
    assert len(state.gate_outcomes) == 1
    recorded = state.gate_outcomes[0]
    assert recorded.key == "suite"
    assert recorded.stage == "test"
    assert recorded.command == ["sh", "-c", "echo 439 passed in 97.98s"]
    assert recorded.tree == result.tree
    assert recorded.at


def test_same_tree_and_command_is_cited_without_running(repo: Path, run, tmp_path: Path) -> None:
    state, _runs_root = run
    # The marker lives *outside* the repo on purpose: writing it into the tree would
    # change the identity, and the second call would correctly re-run.
    marker = tmp_path / "runs.txt"
    command = ["sh", "-c", f"echo ran >> {marker}; echo 439 passed"]

    first = verification.run_gate("suite", command, repo_root=repo, run=state, stage="test")
    second = verification.run_gate("suite", command, repo_root=repo, run=state, stage="pr")

    assert not first.reused
    assert second.reused
    assert second.exit_code == 0
    assert marker.read_text(encoding="utf-8").count("ran") == 1  # the gate ran once
    assert len(state.gate_outcomes) == 1  # nothing new recorded


def test_writing_into_the_gated_tree_invalidates_its_own_outcome(repo: Path, run) -> None:
    """A gate that mutates the tree it gated invalidates its own citation.

    This is the deliberate strictness of a content identity: the recorded outcome is no
    longer evidence about the tree that now exists.
    """
    state, _runs_root = run
    command = ["sh", "-c", f"echo ran >> {repo / 'side-effect.txt'}; true"]

    verification.run_gate("suite", command, repo_root=repo, run=state, stage="test")
    again = verification.run_gate("suite", command, repo_root=repo, run=state, stage="pr")

    assert not again.reused
    assert len(state.gate_outcomes) == 2


def test_citation_names_the_origin(repo: Path, run) -> None:
    state, _runs_root = run
    command = ["sh", "-c", "echo 439 passed in 97.98s"]
    verification.run_gate("suite", command, repo_root=repo, run=state, stage="test")
    cited = verification.run_gate("suite", command, repo_root=repo, run=state, stage="pr")

    line = cited.citation
    assert line.startswith("reused: gate 'suite' passed")
    assert verification.short_tree(state.gate_outcomes[0].tree) in line
    assert "by stage 'test'" in line
    assert "(439 passed in 97.98s)" in line
    assert state.gate_outcomes[0].at in line


def test_a_run_result_without_output_has_no_summary_parenthesis(repo: Path, run) -> None:
    state, _runs_root = run
    verification.run_gate("suite", ["true"], repo_root=repo, run=state, stage="test")

    cited = verification.run_gate("suite", ["true"], repo_root=repo, run=state, stage="pr")

    assert cited.citation.endswith("by stage 'test'")


def test_force_reruns_a_gate_the_tree_already_passed(repo: Path, run) -> None:
    state, _runs_root = run
    command = ["true"]
    verification.run_gate("suite", command, repo_root=repo, run=state, stage="test")

    forced = verification.run_gate(
        "suite", command, repo_root=repo, run=state, stage="pr", force=True
    )

    assert not forced.reused
    assert len(state.gate_outcomes) == 2


def test_a_different_key_does_not_cite_another_gates_outcome(repo: Path, run) -> None:
    state, _runs_root = run
    command = ["true"]
    verification.run_gate("suite", command, repo_root=repo, run=state, stage="test")

    other = verification.run_gate("lint", command, repo_root=repo, run=state, stage="pr")

    assert not other.reused


def test_a_different_command_under_the_same_key_runs(repo: Path, run) -> None:
    """A key names one gate: a different command is a different question."""
    state, _runs_root = run
    verification.run_gate("suite", ["true"], repo_root=repo, run=state, stage="test")

    widened = verification.run_gate(
        "suite", ["sh", "-c", "true"], repo_root=repo, run=state, stage="pr"
    )

    assert not widened.reused


def test_changed_content_reruns_even_with_a_recorded_pass(repo: Path, run) -> None:
    state, _runs_root = run
    command = ["true"]
    verification.run_gate("suite", command, repo_root=repo, run=state, stage="test")

    (repo / "app.py").write_text("x = 3\n", encoding="utf-8")
    after_edit = verification.run_gate("suite", command, repo_root=repo, run=state, stage="pr")

    assert not after_edit.reused
    assert after_edit.tree != state.gate_outcomes[0].tree


def test_a_failed_gate_is_recorded_and_never_cited(repo: Path, run) -> None:
    state, _runs_root = run
    command = ["sh", "-c", "echo nope; exit 3"]

    first = verification.run_gate("suite", command, repo_root=repo, run=state, stage="test")
    second = verification.run_gate("suite", command, repo_root=repo, run=state, stage="pr")

    assert first.status == GATE_FAILED
    assert first.exit_code == 3
    assert not second.reused
    assert second.exit_code == 3
    assert len(state.gate_outcomes) == 2
    assert all(o.status == GATE_FAILED for o in state.gate_outcomes)


def test_without_a_run_nothing_is_recorded_or_cited(repo: Path) -> None:
    first = verification.run_gate("suite", ["true"], repo_root=repo, run=None)
    second = verification.run_gate("suite", ["true"], repo_root=repo, run=None)

    assert not first.reused
    assert not second.reused
    assert first.outcome is None
    assert "no run to record into" in first.note


def test_an_unresolvable_base_never_records_or_cites(tmp_path: Path) -> None:
    """No base branch, no identity: the gate runs, and no false citation is possible."""
    root = tmp_path / "trunk-only"
    root.mkdir()
    _git(root, "init", "-q", "-b", "trunk")
    (root / "a.txt").write_text("x\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    state = create_run(tmp_path / "runs", root, "implement", label="t", branch="trunk")

    first = verification.run_gate("suite", ["true"], repo_root=root, run=state)
    second = verification.run_gate("suite", ["true"], repo_root=root, run=state)

    assert first.tree is None and second.tree is None
    assert not first.reused and not second.reused
    assert state.gate_outcomes == []
    assert "not resolvable" in first.note


def test_a_missing_command_reports_127_and_does_not_raise(repo: Path, run) -> None:
    state, _runs_root = run

    result = verification.run_gate(
        "suite", ["definitely-not-a-command-xyz"], repo_root=repo, run=state
    )

    assert result.exit_code == 127
    assert result.status == GATE_FAILED
    assert "command not found" in result.output


def test_a_timeout_is_reported_as_124(repo: Path, run) -> None:
    state, _runs_root = run

    result = verification.run_gate(
        "suite", ["sh", "-c", "sleep 5"], repo_root=repo, run=state, timeout=0.2
    )

    assert result.exit_code == 124
    assert "timed out" in result.output


def test_summary_is_the_last_non_empty_line(repo: Path, run) -> None:
    state, _runs_root = run

    result = verification.run_gate(
        "suite",
        ["sh", "-c", "printf 'line one\\n\\n439 passed in 97.98s\\n\\n'"],
        repo_root=repo,
        run=state,
    )

    assert result.summary == "439 passed in 97.98s"


def test_output_tail_is_bounded(repo: Path, run) -> None:
    """A gate must not be able to flood the agent's context with its log."""
    state, _runs_root = run

    result = verification.run_gate(
        "suite", ["sh", "-c", "seq 1 200"], repo_root=repo, run=state, tail=5
    )

    assert result.tail_lines(5) == ["196", "197", "198", "199", "200"]
    assert len(result.tail_lines(5)) == 5


def test_the_gate_runs_in_the_repo_root(repo: Path, run) -> None:
    """A relative command must mean the target repo, not the caller's cwd."""
    state, _runs_root = run
    script = repo / "gate.sh"
    script.write_text("#!/bin/sh\necho from-the-repo\n", encoding="utf-8")
    script.chmod(0o755)

    result = verification.run_gate("smoke", ["./gate.sh"], repo_root=repo, run=state)

    assert "from-the-repo" in result.output


# --------------------------------------------------------------------------- #
# State: lookup, persistence, and forward compatibility
# --------------------------------------------------------------------------- #


def test_gate_outcome_lookup_returns_the_newest_for_key_and_tree(repo: Path, run) -> None:
    state, _runs_root = run
    older = _passing(at="2026-01-01T00:00:00Z")
    newer = _passing(at="2026-01-02T00:00:00Z")
    state.record_gate_outcome(older)
    state.record_gate_outcome(newer)

    assert state.gate_outcome("suite", "t") is newer
    assert state.gate_outcome("suite", "other-tree") is None
    assert state.gate_outcome("lint", "t") is None


def test_gate_outcomes_round_trip_through_state_json(repo: Path, run) -> None:
    state, runs_root = run
    state.record_gate_outcome(_passing())
    save(run_dir(runs_root, state.run_id), state)

    reloaded = load(run_dir(runs_root, state.run_id))

    assert reloaded.gate_outcomes == state.gate_outcomes
    assert reloaded.gate_outcome("suite", "t").summary == "439 passed in 97.98s"


def test_a_state_file_without_gate_outcomes_still_loads(repo: Path, run) -> None:
    """Old runs must keep loading: only the schema *version* gates a load (E4.8)."""
    state, runs_root = run
    directory = run_dir(runs_root, state.run_id)
    payload = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    payload.pop("gate_outcomes")

    (directory / "state.json").write_text(json.dumps(payload), encoding="utf-8")

    assert load(directory).gate_outcomes == []


def test_describe_lists_the_origin_and_the_command(repo: Path, run) -> None:
    state, _runs_root = run
    state.record_gate_outcome(
        _passing(key="suite", command=["uv", "run", "--frozen", "pytest"])
    )

    text = "\n".join(verification.describe(state.gate_outcomes[0]))

    assert "gate suite: passed" in text
    assert "stage test" in text
    assert "439 passed in 97.98s" in text
    assert "uv run --frozen pytest" in text


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _state_base(tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``AIDW_STATE_DIR`` at a tmp base and return the repo's state root.

    The resolved root is ``<base>/<repo-slug>``, so it can only be computed *after* the
    environment variable is set — reading it first would silently name a different
    directory and every run lookup below would miss.

    An inherited run identity is scrubbed here. When the suite is itself run as an
    ``aidw gate`` (dogfooding), ``AIDW_RUN_ID``/``AIDW_STAGE`` are set by the parent
    run; the ``gate run`` tests below would then record into that run instead of the
    tmp one and fail on a leaked stage. Cases that need an identity set it explicitly
    after this call, so clearing it first costs nothing.
    """
    base = tmp_path / "state"
    base.mkdir(exist_ok=True)
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(base))
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(STAGE_ENV_VAR, raising=False)
    monkeypatch.chdir(repo)
    return WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root


def test_cli_gate_run_records_into_the_env_run(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: a stage's own ``aidw gate run`` lands in that stage's run."""
    state_root = _state_base(tmp_path, repo, monkeypatch)
    state = create_run(state_root / "runs", repo, "implement", label="task", branch="task")
    monkeypatch.setenv(RUN_ID_ENV_VAR, state.run_id)
    monkeypatch.setenv(STAGE_ENV_VAR, "test")

    first = cli.invoke(app, ["gate", "run", "suite", "--", "sh", "-c", "echo 439 passed"])
    second = cli.invoke(app, ["gate", "run", "suite", "--", "sh", "-c", "echo 439 passed"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "passed: gate 'suite' passed" in first.output
    assert "reused: gate 'suite' passed" in second.output

    reloaded = load(state_root / "runs" / state.run_id)
    assert len(reloaded.gate_outcomes) == 1
    assert reloaded.gate_outcomes[0].stage == "test"
    assert reloaded.gate_outcomes[0].summary == "439 passed"


def test_a_run_cites_the_suite_across_the_record_stage_and_reruns_after_a_code_edit(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E4.8 end to end through the CLI: ``test`` gates, ``record`` cites, an edit re-runs.

    The gate command appends a line to a counter **outside** the repository, and derives
    its summary from that counter. The side effect is the proof: it counts how many times
    the suite was really bought, which output text alone cannot show. A counter *inside*
    the repo would change the tree identity and defeat the very reuse under test, so it
    deliberately lives in ``tmp_path``.

    The recorded row is asserted for origin, not for a transcribed number: stage, tree and
    timestamp come from the first stage that passed the gate, and the summary is the count
    that run produced. ``record`` writing its results document inside the declared scope is
    what I5 does after gating; a source edit outside the scope must invalidate the citation.
    """
    state_root = _state_base(tmp_path, repo, monkeypatch)
    state = create_run(state_root / "runs", repo, "implement", label="task", branch="task")
    monkeypatch.setenv(RUN_ID_ENV_VAR, state.run_id)

    counter = tmp_path / "gate-counter.txt"
    command = [
        "sh",
        "-c",
        f'echo run >> "{counter}"; '
        f'printf "%s\\n" "$(wc -l < "{counter}" | tr -d " ") checks passed"',
    ]
    scope = ["--ignore", "docs/implementation-results"]

    def gate(stage: str):
        monkeypatch.setenv(STAGE_ENV_VAR, stage)
        result = cli.invoke(app, ["gate", "run", "suite", *scope, "--", *command])
        assert result.exit_code == 0, result.output
        return result

    first = gate("test")
    assert "passed: gate 'suite' passed" in first.output
    assert counter.read_text(encoding="utf-8").splitlines() == ["run"]

    # I5's deliverable, written *after* the gate it reports on, inside the declared scope.
    results = repo / "docs" / "implementation-results" / "task"
    results.mkdir(parents=True)
    (results / "build-results.md").write_text("# results\n", encoding="utf-8")

    cited = gate("record")

    assert "reused: gate 'suite' passed" in cited.output
    assert "scope excludes: docs/implementation-results" in cited.output
    assert len(counter.read_text(encoding="utf-8").splitlines()) == 1  # no second run

    reloaded = load(state_root / "runs" / state.run_id)
    assert len(reloaded.gate_outcomes) == 1
    origin = reloaded.gate_outcomes[0]
    assert origin.stage == "test"
    assert origin.summary == "1 checks passed"
    assert origin.at
    assert verification.short_tree(origin.tree) in cited.output
    assert origin.at in cited.output

    # A change outside the declared scope is a changed gate input: the suite must re-run.
    (repo / "app.py").write_text("x = 3\n", encoding="utf-8")

    fresh = gate("record")

    assert "passed: gate 'suite' passed" in fresh.output
    assert "reused:" not in fresh.output
    assert len(counter.read_text(encoding="utf-8").splitlines()) == 2
    rerun = load(state_root / "runs" / state.run_id).gate_outcomes
    assert [outcome.stage for outcome in rerun] == ["test", "record"]
    assert rerun[-1].summary == "2 checks passed"


def test_cli_gate_run_propagates_a_failing_exit_code(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = _state_base(tmp_path, repo, monkeypatch)
    create_run(state_root / "runs", repo, "implement", label="task", branch="task")

    result = cli.invoke(app, ["gate", "run", "lint", "--", "sh", "-c", "exit 7"])

    assert result.exit_code == 7
    assert "failed: gate 'lint' failed" in result.output


def test_cli_gate_run_records_into_the_branch_run_without_an_env_identity(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A human at a terminal has no run id to hand; the current branch's run is meant."""
    state_root = _state_base(tmp_path, repo, monkeypatch)
    state = create_run(state_root / "runs", repo, "implement", label="task", branch="task")
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)

    result = cli.invoke(app, ["gate", "run", "suite", "--", "sh", "-c", "echo 439 passed"])

    assert result.exit_code == 0, result.output
    recorded = load(state_root / "runs" / state.run_id).gate_outcomes
    assert len(recorded) == 1
    assert recorded[0].stage == "cli"


def test_cli_gate_run_ignores_a_parent_run_identity(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dogfooding: the suite run as an ``aidw gate`` inherits the parent's identity.

    That identity names a run in the parent's state root, so honouring it would fail
    with ``unknown run`` here; ``_state_base`` must scrub it.
    """
    monkeypatch.setenv(RUN_ID_ENV_VAR, "parent-run")
    monkeypatch.setenv(STAGE_ENV_VAR, "pr")
    state_root = _state_base(tmp_path, repo, monkeypatch)
    state = create_run(state_root / "runs", repo, "implement", label="task", branch="task")

    result = cli.invoke(app, ["gate", "run", "suite", "--", "sh", "-c", "echo 439 passed"])

    assert result.exit_code == 0, result.output
    recorded = load(state_root / "runs" / state.run_id).gate_outcomes
    assert len(recorded) == 1
    assert recorded[0].stage == "cli"


def test_cli_gate_run_records_nothing_when_there_is_no_run_at_all(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No run anywhere: the gate still runs — never skipped, never recorded."""
    state_root = _state_base(tmp_path, repo, monkeypatch)
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)

    result = cli.invoke(app, ["gate", "run", "suite", "--", "sh", "-c", "echo 439 passed"])

    assert result.exit_code == 0, result.output
    assert "no run to record into" in result.output or not (state_root / "runs").exists()


def test_cli_gate_run_rejects_an_invalid_ignore_prefix(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state_base(tmp_path, repo, monkeypatch)

    result = cli.invoke(
        app, ["gate", "run", "suite", "--ignore", "../escape", "--", "true"]
    )

    assert result.exit_code == EXIT_USAGE
    assert "invalid --ignore prefix" in result.output


def test_cli_gate_run_threads_the_declared_scope(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scope must survive the CLI: without it, reuse across a doc write is lost."""
    state_root = _state_base(tmp_path, repo, monkeypatch)
    state = create_run(state_root / "runs", repo, "implement", label="task", branch="task")
    monkeypatch.setenv(RUN_ID_ENV_VAR, state.run_id)
    scope = ["--ignore", "docs/implementation-results"]

    first = cli.invoke(
        app, ["gate", "run", "suite", *scope, "--", "sh", "-c", "echo 439 passed"]
    )
    docs = repo / "docs" / "implementation-results"
    docs.mkdir(parents=True)
    (docs / "build-results.md").write_text("# results\n", encoding="utf-8")
    second = cli.invoke(
        app, ["gate", "run", "suite", *scope, "--", "sh", "-c", "echo 439 passed"]
    )

    assert first.exit_code == 0, first.output
    assert "reused: gate 'suite' passed" in second.output
    assert "scope excludes: docs/implementation-results" in second.output


def test_cli_gate_run_without_a_command_is_a_usage_error(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state_base(tmp_path, repo, monkeypatch)

    result = cli.invoke(app, ["gate", "run", "suite"])

    assert result.exit_code == EXIT_USAGE
    assert "usage: aidw gate run" in result.output


def test_cli_gate_unknown_action_is_a_usage_error(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state_base(tmp_path, repo, monkeypatch)

    result = cli.invoke(app, ["gate", "wat"])

    assert result.exit_code == EXIT_USAGE
    assert "unknown action" in result.output


def test_cli_gate_unknown_run_id_is_a_usage_error(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state_base(tmp_path, repo, monkeypatch)

    result = cli.invoke(app, ["gate", "run", "suite", "--run", "nope", "--", "true"])

    assert result.exit_code == EXIT_USAGE
    assert "unknown run: nope" in result.output


def test_cli_gate_list_shows_recorded_outcomes(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = _state_base(tmp_path, repo, monkeypatch)
    state = create_run(state_root / "runs", repo, "implement", label="task", branch="task")
    state.record_gate_outcome(_passing())
    save(state_root / "runs" / state.run_id, state)

    result = cli.invoke(app, ["gate", "list", "--run", state.run_id])

    assert result.exit_code == 0, result.output
    assert "gate suite: passed" in result.output
    assert "439 passed in 97.98s" in result.output


def test_cli_runs_show_lists_gate_outcomes(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = _state_base(tmp_path, repo, monkeypatch)
    state = create_run(state_root / "runs", repo, "implement", label="task", branch="task")
    state.record_gate_outcome(_passing())
    save(state_root / "runs" / state.run_id, state)

    result = cli.invoke(app, ["runs", "show", state.run_id])

    assert result.exit_code == 0, result.output
    assert "gate suite: passed (tree t, stage test" in result.output


# --------------------------------------------------------------------------- #
# Gate outcomes across stage boundaries (H0.1, design §9.2)
#
# Two processes write this file: the workflow (``state.save``) and the ``aidw gate run``
# subprocess a stage's agent spawns (``state.append_gate_outcomes``). The contract is that
# neither drop the other's rows and that no lock-free reader ever sees a torn file.
# --------------------------------------------------------------------------- #


def _outcome(
    key: str,
    *,
    tree: str = "t",
    stage: str = "cli",
    at: str = "2026-01-01T00:00:00Z",
) -> GateOutcome:
    return GateOutcome(
        key=key,
        command=["true"],
        tree=tree,
        status=PASSED,
        stage=stage,
        at=at,
        exit_code=0,
        summary=f"{key} ok",
    )


def _pi_result() -> PiResult:
    """A faked Pi result: the argv is built and passed, no model and no process."""
    return PiResult(
        exit_code=0,
        session_id="s",
        final_message="ok",
        usage=Usage(cost_usd=0.0, total_tokens=0),
        duration_seconds=0.1,
        event_count=1,
        tool_calls=0,
        tool_errors=0,
        stop_reason="end_turn",
        stderr="",
        timed_out=False,
        attempts=1,
        jsonl_path="",
        out_path=None,
    )


def _run_workflow_stage(
    state,
    runs_root: Path,
    target: Path,
    monkeypatch,
    *,
    name: str = "record",
) -> StageRecord:
    """Drive the real ``runner.run_stage`` so the *workflow's* ``save()`` is exercised.

    Faking a stage with ``AIDW_STAGE`` alone (what the earlier tests did) never runs the
    workflow's own write, which is exactly why the loss was green.
    """
    agents, issues = load_all(toolkit_root(), target)
    assert [issue for issue in issues if issue.level == "error"] == []
    monkeypatch.setattr(runner_mod, "execute", lambda *args, **kwargs: _pi_result())
    return run_stage(
        StageSpec(
            name=name,
            agent_id="code-reviewer",
            prompt=toolkit_root() / "prompts" / "test.md",
            variables=[],
        ),
        repo_root=target,
        toolkit_root=toolkit_root(),
        state=state,
        logger=RunLogger(run_dir(runs_root, state.run_id)),
        agents=agents,
        runs_root=runs_root,
    )


def test_a_cli_gate_outcome_survives_the_workflows_next_save(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 3(i): the stale-handle round trip, not the write.

    The workflow holds the ``RunState`` ``create_run`` returned. The agent's
    ``aidw gate run`` lands its outcome on disk. The workflow then saves through that
    pre-gate handle — no reload in between — and the outcome must still be there,
    row for row.
    """
    state_root = _state_base(tmp_path, repo, monkeypatch)
    runs_root = state_root / "runs"
    state = create_run(runs_root, repo, "implement", label="round-trip", branch="task")
    monkeypatch.setenv(RUN_ID_ENV_VAR, state.run_id)
    monkeypatch.setenv(STAGE_ENV_VAR, "impliment-task")
    directory = run_dir(runs_root, state.run_id)

    gated = cli.invoke(app, ["gate", "run", "suite", "--", "sh", "-c", "echo 439 passed"])

    assert gated.exit_code == 0, gated.output
    before = load(directory).gate_outcomes
    assert len(before) == 1
    assert before[0].stage == "impliment-task"

    _run_workflow_stage(state, runs_root, repo, monkeypatch)

    after = load(directory)
    assert [asdict(outcome) for outcome in after.gate_outcomes] == [asdict(before[0])]
    assert after.gate_outcomes[0].summary == "439 passed"
    assert [record.name for record in after.stages] == ["record"]


def test_a_stage_record_written_while_a_cli_gate_runs_survives_its_write(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 3(ii): the other direction of the symmetric loss.

    The CLI holds the run copy it loaded *before* executing the gate command; the
    workflow writes a stage record while that command is running. The CLI's publish must
    not be a full-state save of its stale copy, or the stage record disappears.
    """
    state_root = _state_base(tmp_path, repo, monkeypatch)
    runs_root = state_root / "runs"
    state = create_run(runs_root, repo, "implement", label="overlap", branch="task")
    monkeypatch.setenv(RUN_ID_ENV_VAR, state.run_id)
    directory = run_dir(runs_root, state.run_id)
    real_run_gate = verification.run_gate

    def gate_between_two_writers(*args, **kwargs):
        result = real_run_gate(*args, **kwargs)
        _run_workflow_stage(state, runs_root, repo, monkeypatch)
        return result

    monkeypatch.setattr(verification, "run_gate", gate_between_two_writers)

    result = cli.invoke(app, ["gate", "run", "suite", "--", "sh", "-c", "echo 439 passed"])

    assert result.exit_code == 0, result.output
    reloaded = load(directory)
    assert [record.name for record in reloaded.stages] == ["record"]
    assert [outcome.key for outcome in reloaded.gate_outcomes] == ["suite"]


def test_two_overlapping_cli_gate_runs_both_record_an_outcome(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 3/4: Pi runs tool calls in parallel; both outcomes must land.

    ``runner._STATE_LOCK`` is in-process only, so this is what the per-run state lock
    exists for. The command sleeps so the two invocations really do overlap.
    """
    state_root = _state_base(tmp_path, repo, monkeypatch)
    runs_root = state_root / "runs"
    state = create_run(runs_root, repo, "implement", label="parallel", branch="task")
    monkeypatch.setenv(RUN_ID_ENV_VAR, state.run_id)
    monkeypatch.setenv(STAGE_ENV_VAR, "impliment-task")

    def gate(key: str):
        # Typer's CliRunner swaps process-global stdout/stderr during isolation, so
        # invoking two runners in threads races the test harness itself. Use two real
        # aidw CLI processes here: this is the cross-process lock contract, and the
        # sequential CliRunner tests above still cover the in-process CLI seam.
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "from aidw.cli import main; main()",
                "gate",
                "run",
                key,
                "--",
                "sh",
                "-c",
                "sleep 0.3; echo ok",
            ],
            cwd=repo,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(gate, key) for key in ("lint", "build")]
        results = [future.result() for future in futures]

    assert [result.returncode for result in results] == [0, 0]
    recorded = load(run_dir(runs_root, state.run_id)).gate_outcomes
    assert sorted(outcome.key for outcome in recorded) == ["build", "lint"]


#: How many times each writer writes in the overlap-integrity test below.
READER_WRITES = 30


def test_no_unlocked_reader_observes_a_torn_or_stage_losing_state(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 2: the atomic rename, not the lock, keeps an unlocked read whole.

    Three threads: a reader that only ever ``load``s (no lock — a concurrent citation,
    ``aidw runs show``), the CLI's append writer, and the workflow's full-state writer.
    Every observed read must parse and still carry the stage record already on disk; the
    both-rows-present assertion at the end is in addition to those observations.
    """
    state_root = _state_base(tmp_path, repo, monkeypatch)
    runs_root = state_root / "runs"
    state = create_run(runs_root, repo, "implement", label="reader", branch="task")
    _run_workflow_stage(state, runs_root, repo, monkeypatch, name="impliment-task")
    directory = run_dir(runs_root, state.run_id)
    preexisting = {"impliment-task"}

    failures: list[str] = []
    reads = 0
    stop = threading.Event()

    def reader() -> None:
        nonlocal reads
        while not stop.is_set():
            try:
                observed = load(directory)
            except Exception as exc:  # noqa: BLE001 - any read failure is the finding
                failures.append(f"{type(exc).__name__}: {exc}")
                return
            names = {record.name for record in observed.stages}
            if not preexisting <= names:
                failures.append(f"stage record missing: {sorted(names)}")
                return
            reads += 1

    def appender() -> None:
        for index in range(READER_WRITES):
            append_gate_outcomes(directory, [_outcome(f"g{index:02d}")])

    def saver() -> None:
        for index in range(READER_WRITES):
            state.record_stage(
                StageRecord(
                    name=f"save-{index:02d}",
                    agent="code-reviewer",
                    model="<provider/model>",
                )
            )
            save(directory, state)

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for future in (pool.submit(appender), pool.submit(saver)):
                future.result()
    finally:
        stop.set()
        thread.join()

    assert failures == []
    assert reads >= 10  # the overlap window was really observed, not skipped
    final = load(directory)
    assert [outcome.key for outcome in final.gate_outcomes] == [
        f"g{index:02d}" for index in range(READER_WRITES)
    ]
    assert {record.name for record in final.stages} == preexisting | {
        f"save-{index:02d}" for index in range(READER_WRITES)
    }


def test_one_test_gate_is_cited_by_record_and_by_pr(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance chain, with a counter outside the repository as the proof.

    ``test`` gates tree ``T``; ``record`` and ``pr`` cite it, with a workflow save and a
    document write (inside the declared scope) in between, and the command is executed
    exactly once. The counter is outside the repo so counting cannot change the identity.
    """
    state_root = _state_base(tmp_path, repo, monkeypatch)
    runs_root = state_root / "runs"
    state = create_run(runs_root, repo, "implement", label="chain", branch="task")
    monkeypatch.setenv(RUN_ID_ENV_VAR, state.run_id)
    directory = run_dir(runs_root, state.run_id)

    counter = tmp_path / "gate-counter.txt"
    command = [
        "sh",
        "-c",
        f'echo run >> "{counter}"; '
        f'printf "%s\\n" "$(wc -l < "{counter}" | tr -d " ") checks passed"',
    ]
    scope = ["--ignore", "docs/implementation-results"]

    def gate(stage: str):
        monkeypatch.setenv(STAGE_ENV_VAR, stage)
        result = cli.invoke(app, ["gate", "run", "suite", *scope, "--", *command])
        assert result.exit_code == 0, result.output
        return result

    first = gate("test")
    assert "passed: gate 'suite' passed" in first.output

    # The record stage's own save, then its deliverable written inside the declared scope.
    _run_workflow_stage(state, runs_root, repo, monkeypatch, name="record")
    results = repo / "docs" / "implementation-results" / "chain"
    results.mkdir(parents=True)
    (results / "build-results.md").write_text("# results\n", encoding="utf-8")

    cited_record = gate("record")
    _run_workflow_stage(state, runs_root, repo, monkeypatch, name="pr")
    cited_pr = gate("pr")

    assert "reused: gate 'suite' passed" in cited_record.output
    assert "reused: gate 'suite' passed" in cited_pr.output
    assert "by stage 'test'" in cited_pr.output
    assert len(counter.read_text(encoding="utf-8").splitlines()) == 1

    reloaded = load(directory)
    assert [outcome.stage for outcome in reloaded.gate_outcomes] == ["test"]
    assert {record.name for record in reloaded.stages} == {"record", "pr"}


def test_gate_list_and_runs_show_report_outcomes_after_the_process_exits(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 5: the evidence outlives the run process, not just its memory."""
    state_root = _state_base(tmp_path, repo, monkeypatch)
    state = create_run(state_root / "runs", repo, "implement", label="exit", branch="task")
    monkeypatch.setenv(RUN_ID_ENV_VAR, state.run_id)
    monkeypatch.setenv(STAGE_ENV_VAR, "record")

    def aidw_process(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "from aidw.cli import main; main()",
                *args,
            ],
            cwd=repo,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )

    for key in ("lint", "suite"):
        result = aidw_process("gate", "run", key, "--", "sh", "-c", f"echo {key} ok")
        assert result.returncode == 0, result.stderr + result.stdout

    # Nothing in memory can supply these: the gate writer process has exited, the stage
    # identity is gone, and the run is named explicitly, exactly as a later operator
    # process would use it.
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(STAGE_ENV_VAR, raising=False)

    listed = aidw_process("gate", "list", "--run", state.run_id)
    shown = aidw_process("runs", "show", state.run_id)

    assert listed.returncode == 0, listed.stderr + listed.stdout
    assert shown.returncode == 0, shown.stderr + shown.stdout
    for key in ("lint", "suite"):
        assert f"gate {key}: passed" in listed.stdout
        assert f"gate {key}: passed" in shown.stdout


def test_the_state_lock_excludes_a_second_holder_and_is_reusable(tmp_path: Path) -> None:
    """The lock is a per-run mutex beside ``state.json``, never under ``locks/``."""
    directory = tmp_path / "run"

    with state_write_lock(directory):
        fd = os.open(state_lock_path(directory), os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    with state_write_lock(directory):  # released, so a peer's next write gets in
        pass

    assert state_lock_path(directory) == directory / "state.json.lock"
    assert state_lock_path(directory).exists()  # never unlinked: that races a new inode


def test_save_publishes_atomically_and_leaves_only_the_state_and_its_lock(
    tmp_path: Path,
) -> None:
    """Requirement 2: the temp file lives in the run directory and is renamed away."""
    state = create_run(tmp_path, tmp_path, "implement", label="atomic")
    directory = run_dir(tmp_path, state.run_id)

    save(directory, state)

    assert sorted(path.name for path in directory.iterdir()) == [
        "state.json",
        "state.json.lock",
    ]
    assert json.loads((directory / "state.json").read_text(encoding="utf-8"))[
        "schema_version"
    ] == 1


def test_a_state_file_that_cannot_be_read_is_never_overwritten(tmp_path: Path) -> None:
    """Fail closed: an unparseable file holds evidence, so it is not replaced."""
    state = create_run(tmp_path, tmp_path, "implement", label="corrupt")
    directory = run_dir(tmp_path, state.run_id)
    (directory / "state.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        save(directory, state)
    with pytest.raises(json.JSONDecodeError):
        append_gate_outcomes(directory, [_outcome("suite")])

    assert (directory / "state.json").read_text(encoding="utf-8") == "{not json"
    assert [path for path in directory.iterdir() if path.suffix == ".tmp"] == []


def test_two_distinct_outcomes_for_one_key_are_both_kept() -> None:
    """The dedup hazard (Requirement 3): two processes ran it, so both are evidence."""
    first = _outcome("suite", at="2026-01-01T00:00:00Z")
    second = _outcome("suite", at="2026-01-01T00:00:01Z")

    assert merge_gate_outcomes([first], [second]) == [first, second]
    # The same row seen twice (in-memory copy and disk copy) collapses; a distinct one
    # never does.
    assert merge_gate_outcomes([first], [first]) == [first]


#: Pinned seed and run count for the merge property (AGENTS.md "Tests": pytest only, no
#: hypothesis, so the sample is the generator and there is no shrinking).
MERGE_PROPERTY_SEED = 9017
MERGE_PROPERTY_RUNS = 64


def test_merge_gate_outcomes_is_a_lossless_union_of_distinct_rows() -> None:
    """Seeded property run (seed/runs pinned above): the merge drops and reorders nothing.

    For every sampled pair of lists the merge is exactly ``base`` followed by the
    ``extra`` rows whose identity is not already in ``base``. The expectation is computed
    here from the identity rule, independently of the function under test, and the inputs
    are asserted unchanged afterwards (the merge is pure: no mutation, no I/O).
    """
    rng = random.Random(MERGE_PROPERTY_SEED)
    keys = ("suite", "lint", "build", "srd")
    stages = ("test", "record", "pr", "cli")
    statuses = (PASSED, GATE_FAILED)
    scopes: tuple[tuple[str, ...], ...] = ((), ("docs/implementation-results",))
    summaries = ("", "ok", "412 passed")

    def row() -> GateOutcome:
        return GateOutcome(
            key=rng.choice(keys),
            command=[rng.choice(("true", "false")), str(rng.randint(0, 3))],
            tree=rng.choice(("t1", "t2")),
            status=rng.choice(statuses),
            stage=rng.choice(stages),
            at=f"2026-01-0{rng.randint(1, 9)}T00:00:0{rng.randint(0, 9)}Z",
            exit_code=rng.randint(0, 2),
            duration_seconds=float(rng.randint(0, 5)),
            summary=rng.choice(summaries),
            ignored=list(rng.choice(scopes)),
        )

    for case in range(MERGE_PROPERTY_RUNS):
        base = [row() for _ in range(rng.randint(0, 5))]
        extra = [row() for _ in range(rng.randint(0, 5))]
        base_before = [asdict(outcome) for outcome in base]
        extra_before = [asdict(outcome) for outcome in extra]

        expected = list(base)
        seen = {outcome_identity(outcome) for outcome in base}
        for candidate in extra:
            identity = outcome_identity(candidate)
            if identity not in seen:
                seen.add(identity)
                expected.append(candidate)

        merged = merge_gate_outcomes(base, extra)

        assert [asdict(outcome) for outcome in merged] == [
            asdict(outcome) for outcome in expected
        ], case
        assert [asdict(outcome) for outcome in base] == base_before, case
        assert [asdict(outcome) for outcome in extra] == extra_before, case
        assert all(
            any(outcome is source for source in (*base, *extra)) for outcome in merged
        ), case
