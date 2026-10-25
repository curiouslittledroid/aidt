"""Tests for prompt loading and rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from aidw.paths import aidt_root
from aidw.prompts import (
    PromptError,
    load_prompt_file,
    render,
    render_prompt_file,
    strip_frontmatter,
)


def test_strip_frontmatter_removes_block() -> None:
    text = "---\ndescription: hi\n---\n# Body\ncontent\n"
    assert strip_frontmatter(text) == "# Body\ncontent\n"


def test_strip_frontmatter_noop_without_block() -> None:
    text = "# Body\ncontent\n"
    assert strip_frontmatter(text) == text


def test_render_substitutes_positional_variables() -> None:
    assert render("a $1 b $2 c", ["X", "Y"]) == "a X b Y c"


def test_render_preserves_shell_references() -> None:
    text = "run $runner --pr $pr ${VAR} and $1"
    assert render(text, ["ONE"]) == "run $runner --pr $pr ${VAR} and ONE"


def test_render_raises_when_variable_missing() -> None:
    with pytest.raises(PromptError):
        render("need $1 and $2", ["only-one"])


def test_render_raises_on_zero() -> None:
    with pytest.raises(PromptError):
        render("bad $0", ["x"])


def test_render_no_variables_is_noop() -> None:
    assert render("plain text") == "plain text"


def test_render_real_task_prompt() -> None:
    path = aidt_root() / "prompts" / "task-prompt.md"
    rendered = render_prompt_file(path, ["03", "E2", "E2.9"])
    assert "$1" not in rendered
    assert "03" in rendered
    assert "E2.9" in rendered


def test_load_prompt_strips_frontmatter() -> None:
    path = aidt_root() / "prompts" / "pr.md"
    text = load_prompt_file(path)
    assert not text.startswith("---")
    assert "# " in text
