"""Tests for human-in-the-loop gate decisions."""

from __future__ import annotations

import pytest

from aidw.gates import (
    DENY,
    GATE_DEFAULT_ENV,
    HUMAN,
    HUMAN_DEFAULT,
    HUMAN_DENIED,
    NONINTERACTIVE,
    GateDefault,
    decide,
    resolve_gate_default,
)


def _answer(monkeypatch, value: str) -> list[str]:
    """Answer every prompt with ``value``, recording the prompt strings shown."""
    seen: list[str] = []

    def fake_input(prompt: str) -> str:
        seen.append(prompt)
        return value

    monkeypatch.setattr("builtins.input", fake_input)
    return seen


# --- non-interactive / short-circuit mechanisms ----------------------------- #


def test_approve_all() -> None:
    outcome = decide("g", "summary", approve_all=True, noninteractive=True)
    assert outcome.approved
    assert outcome.mechanism == "--yes"


def test_skip_gates() -> None:
    outcome = decide("g", "summary", skip={"g"}, noninteractive=True)
    assert outcome.approved
    assert outcome.mechanism.startswith("--skip-gates")


def test_noninteractive_denies() -> None:
    """A default of approve is for a human at a terminal, not for a script."""
    outcome = decide("g", "summary", noninteractive=True)
    assert not outcome.approved
    assert outcome.mechanism == NONINTERACTIVE
    assert outcome.decision == "denied"


def test_noninteractive_denies_even_with_approve_default() -> None:
    outcome = decide("g", "summary", gate_default="approve", noninteractive=True)
    assert not outcome.approved
    assert outcome.mechanism == NONINTERACTIVE


# --- deny beats the blunter approvals --------------------------------------- #


def test_deny_gates_refuses() -> None:
    outcome = decide("g", "summary", deny={"g"}, noninteractive=True)
    assert not outcome.approved
    assert outcome.mechanism == f"{DENY} g"


def test_deny_gates_beats_approve_all() -> None:
    outcome = decide("g", "summary", approve_all=True, deny={"g"}, noninteractive=True)
    assert not outcome.approved


def test_deny_gates_beats_skip_gates() -> None:
    outcome = decide("g", "summary", skip={"g"}, deny={"g"}, noninteractive=True)
    assert not outcome.approved


def test_deny_gates_is_scoped_to_named_gates() -> None:
    outcome = decide("other", "summary", deny={"g"}, noninteractive=True)
    assert not outcome.approved
    assert outcome.mechanism == NONINTERACTIVE


# --- interactive default is approve ----------------------------------------- #


def test_enter_approves_by_default(monkeypatch) -> None:
    _answer(monkeypatch, "")
    outcome = decide("g", "summary", noninteractive=False)
    assert outcome.approved
    assert outcome.mechanism == HUMAN_DEFAULT


def test_typed_yes_approves(monkeypatch) -> None:
    _answer(monkeypatch, "y")
    outcome = decide("g", "summary", noninteractive=False)
    assert outcome.approved
    assert outcome.mechanism == HUMAN


def test_typed_no_denies_despite_approve_default(monkeypatch) -> None:
    _answer(monkeypatch, "n")
    outcome = decide("g", "summary", noninteractive=False)
    assert not outcome.approved
    assert outcome.mechanism == HUMAN_DENIED


def test_prompt_shows_approve_default_marker(monkeypatch) -> None:
    prompts = _answer(monkeypatch, "")
    decide("g", "summary", noninteractive=False)
    assert "[Y/n]" in prompts[-1]


# --- --gate-default deny restores the strict prompt ------------------------- #


def test_gate_default_deny_denies_on_enter(monkeypatch) -> None:
    _answer(monkeypatch, "")
    outcome = decide("g", "summary", gate_default="deny", noninteractive=False)
    assert not outcome.approved
    assert outcome.mechanism == HUMAN_DENIED


def test_gate_default_deny_accepts_typed_yes(monkeypatch) -> None:
    _answer(monkeypatch, "y")
    outcome = decide("g", "summary", gate_default="deny", noninteractive=False)
    assert outcome.approved
    assert outcome.mechanism == HUMAN


def test_gate_default_deny_shows_deny_marker(monkeypatch) -> None:
    prompts = _answer(monkeypatch, "")
    decide("g", "summary", gate_default="deny", noninteractive=False)
    assert "[y/N]" in prompts[-1]


def test_gate_default_accepts_enum(monkeypatch) -> None:
    _answer(monkeypatch, "")
    outcome = decide("g", "summary", gate_default=GateDefault.deny, noninteractive=False)
    assert not outcome.approved


def test_unrecognised_answer_reprompts(monkeypatch) -> None:
    answers = iter(["maybe", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    outcome = decide("g", "summary", noninteractive=False)
    assert outcome.approved


# --- resolution precedence -------------------------------------------------- #


def test_resolve_defaults_to_approve() -> None:
    assert resolve_gate_default() is True


def test_resolve_flag_wins_over_env(monkeypatch) -> None:
    monkeypatch.setenv(GATE_DEFAULT_ENV, "approve")
    assert resolve_gate_default("deny") is False


def test_resolve_env_overrides_fallback(monkeypatch) -> None:
    monkeypatch.setenv(GATE_DEFAULT_ENV, "deny")
    assert resolve_gate_default() is False


def test_resolve_ignores_unknown_env(monkeypatch, capsys) -> None:
    monkeypatch.setenv(GATE_DEFAULT_ENV, "perhaps")
    assert resolve_gate_default() is True
    assert "ignoring AIDW_GATE_DEFAULT" in capsys.readouterr().err


def test_resolve_rejects_unknown_flag() -> None:
    with pytest.raises(ValueError):
        resolve_gate_default("perhaps")
