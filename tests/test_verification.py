"""Whole-repo verification gates: identity, recording and same-tree reuse (E4.8).

The contract under test is the one the PR stage depends on: a run may cite a gate
outcome another stage recorded **for the same tree**, and it must never cite one it
cannot prove applies — a different tree, a different command, a different run, a failed
outcome, or a repo whose base branch will not resolve.

Identity is content, so committing the verified change set must not invalidate it, while
any content change must. These tests build real repositories so the git-side identity is
exercised rather than mocked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidw import verification
from aidw.cli import EXIT_USAGE, app
from aidw.paths import STATE_DIR_ENV_VAR, RUN_ID_ENV_VAR, STAGE_ENV_VAR, TargetRepo, WorkspacePaths
from aidw.state import (
    GATE_FAILED,
    PASSED,
    GateOutcome,
    create_run,
    load,
    run_dir,
    save,
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
