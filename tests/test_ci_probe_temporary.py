"""Temporary probe for E0.5: proves CI fails when a test fails.

This file is deleted in the next commit on this branch.
"""

from __future__ import annotations


def test_deliberately_broken_probe() -> None:
    assert False, "intentional CI probe failure (E0.5); deleted in the next commit"
