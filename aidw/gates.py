"""Human-in-the-loop gates (design §6).

Every gate is skippable. ``--yes`` approves all gates in a run; ``--skip-gates name``
skips specific gates; ``--deny-gates name`` refuses specific gates even when another
switch would approve them. Every decision and skip is recorded in state.

**The interactive default is approve.** Pressing Enter at a gate prompt approves it.
Three overrides exist, in increasing scope:

- ``--deny-gates name`` refuses that gate in this run, whatever else is set.
- ``--gate-default deny`` asks again the old way: Enter no longer approves, and the
  prompt reads ``[y/N]``.
- ``AIDW_GATE_DEFAULT=deny`` sets that default for every invocation in the shell
  without repeating the flag.

A non-interactive session still fails closed with or without a default: there is no
human present to accept it, so ``--yes`` (or ``--skip-gates``) remains the only way
through. That distinction is deliberate — the default is a convenience for a human at
a terminal, not an auto-approval for a script.
"""

from __future__ import annotations

import enum
import os
import sys
from dataclasses import dataclass

APPROVE_ALL = "--yes"
SKIP = "--skip-gates"
DENY = "--deny-gates"
GATE_DEFAULT = "--gate-default"
GATE_DEFAULT_ENV = "AIDW_GATE_DEFAULT"

HUMAN = "human"
HUMAN_DEFAULT = "human-default"
HUMAN_DENIED = "human-denied"
NONINTERACTIVE = "noninteractive"


class GateDefault(str, enum.Enum):
    """How an interactive gate resolves when the human presses Enter."""

    approve = "approve"
    deny = "deny"


@dataclass
class GateOutcome:
    name: str
    approved: bool
    mechanism: str
    detail: str = ""

    @property
    def decision(self) -> str:
        return "approved" if self.approved else "denied"


def _is_noninteractive() -> bool:
    if os.environ.get("AIDW_NONINTERACTIVE") == "1":
        return True
    return not sys.stdin.isatty()


def resolve_gate_default(flag: str | GateDefault | None = None) -> bool:
    """Resolve whether Enter approves, as a boolean.

    Precedence: the ``--gate-default`` value, then ``$AIDW_GATE_DEFAULT``, then
    approve. An unrecognised environment value is ignored with a warning rather than
    silently flipping the default.
    """
    if flag is not None:
        value = str(getattr(flag, "value", flag)).strip().lower()
        if value not in (GateDefault.approve.value, GateDefault.deny.value):
            raise ValueError(
                f"invalid gate default {flag!r}; expected "
                f"{GateDefault.approve.value!r} or {GateDefault.deny.value!r}"
            )
        return value == GateDefault.approve.value

    raw = (os.environ.get(GATE_DEFAULT_ENV) or "").strip().lower()
    if not raw:
        return True
    if raw not in (GateDefault.approve.value, GateDefault.deny.value):
        print(
            f"ignoring {GATE_DEFAULT_ENV}={raw!r}; expected 'approve' or 'deny'",
            file=sys.stderr,
        )
        return True
    return raw == GateDefault.approve.value


def _ask(gate_name: str, default_approve: bool) -> GateOutcome:
    """Read one answer, returning an outcome that records how it was reached."""
    marker = "[Y/n] " if default_approve else "[y/N] "
    while True:
        try:
            answer = input(f"Approve gate '{gate_name}'? {marker}").strip().lower()
        except EOFError:
            return GateOutcome(gate_name, False, NONINTERACTIVE)

        if answer in ("y", "yes"):
            return GateOutcome(gate_name, True, HUMAN)
        if answer in ("n", "no"):
            return GateOutcome(gate_name, False, HUMAN_DENIED)
        if answer == "":
            return GateOutcome(
                gate_name, default_approve, HUMAN_DEFAULT if default_approve else HUMAN_DENIED
            )
        print(f"Please answer 'y' or 'n', or press Enter for the default")


def decide(
    gate_name: str,
    summary: str,
    *,
    approve_all: bool = False,
    skip: set[str] | None = None,
    deny: set[str] | None = None,
    gate_default: str | GateDefault | None = None,
    noninteractive: bool | None = None,
) -> GateOutcome:
    """Resolve a gate to an outcome, prompting a human when needed.

    ``deny`` is checked before ``approve_all`` and ``skip``: an explicit refusal must
    not be overridden by a blunter switch. ``approve_all`` and ``skip`` short-circuit
    without prompting. Otherwise, if the session is interactive, the summary is
    printed and an answer is read, where Enter accepts the resolved default
    (approve unless ``--gate-default deny`` / ``$AIDW_GATE_DEFAULT=deny``).

    A non-interactive session never auto-approves on the default; only ``--yes`` or
    ``--skip-gates`` get it through, and any other gate fails closed.
    """
    if deny and gate_name in deny:
        return GateOutcome(gate_name, False, f"{DENY} {gate_name}")
    if approve_all:
        return GateOutcome(gate_name, True, APPROVE_ALL)
    if skip and gate_name in skip:
        return GateOutcome(gate_name, True, f"{SKIP} {gate_name}")

    default_approve = resolve_gate_default(gate_default)

    if noninteractive is None:
        noninteractive = _is_noninteractive()

    if noninteractive:
        return GateOutcome(gate_name, False, NONINTERACTIVE)

    print(f"\n=== Gate: {gate_name} ===")
    print(summary)
    return _ask(gate_name, default_approve)
