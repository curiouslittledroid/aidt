"""The release helper's contract (``scripts/release.py``, ``docs/releasing.md``).

Two things are tested, and they are different in kind.

**The version sites.** ``docs/releasing.md`` §1 makes the awkward part explicit: the version
lives in three places, and the third — the literal inside
``test_pyproject_identity_is_the_settled_name_version_and_script`` — is deliberately *not*
derived from the other two, because that test is the guard for them. A release helper that
bumped two of the three, or that rewrote a second matching line somewhere else in the file,
would leave a tree that passes review and fails CI. The pure helpers are therefore tested
against tiny fixture files, not against this repository: a test that bumped the real
``pyproject.toml`` would have to revert it, and a failed revert edits a release.

**The refusals.** Every one happens before the first write, so it is provable with a throwaway
repository: dirty tree, not on ``main``, ``main`` behind ``origin``, disagreeing sites, a
non-forward bump, an existing tag. ``--dry-run`` is total — it prints the edits and mutates
nothing — which is what makes it safe to run against the real tree.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release.py"

#: A minimal stand-in for the three version sites. The extra `version`-ish lines are there on
#: purpose: `requires-python`, a dependency floor and a `version` inside a comment must all
#: survive untouched, which is what pins the patterns to whole lines.
PYPROJECT = """\
[project]
name = "aidt"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "packaging>=24.0",
    # not a `version = "..."` line, and must not be rewritten
    "pyyaml>=6.0",
]

[tool.hatch.build]
include = ["aidw"]
"""

INIT_MODULE = '''\
"""AIDT."""

__version__ = "1.0.0"
'''

PACKAGING_TEST = '''\
from aidw import __version__


def test_pyproject_identity_is_the_settled_name_version_and_script() -> None:
    project = {"version": "1.0.0"}
    assert project["name"] == "aidt"
    assert project["version"] == "1.0.0"
    assert project["version"] == __version__
'''


def _load():
    """``scripts/release.py`` as a module, loaded by path (it is not an importable package).

    It is registered in ``sys.modules`` *before* execution because the module uses
    ``@dataclass``, whose decorator resolves the owning module through ``sys.modules`` — the
    one thing ``module_from_spec`` alone does not arrange.
    """
    name = "aidt_release_script"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def release():
    return _load()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A throwaway "checkout" carrying the three version sites at 1.0.0."""
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "aidw").mkdir()
    (tmp_path / "aidw" / "__init__.py").write_text(INIT_MODULE, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_packaging.py").write_text(PACKAGING_TEST, encoding="utf-8")
    return tmp_path


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )


def _git_repo(root: Path, *, branch: str = "main") -> Path:
    """``root`` as a committed repository whose ``origin/main`` is itself.

    ``_require_up_to_date`` reads ``origin/main``, so the fixture needs a real remote: a bare
    sibling that the checkout pushes to and then re-reads. Without it a refusal test would
    "pass" on a fetch failure instead of on the rule it claims to pin.
    """
    origin = root.parent / f"{root.name}-origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    _git(root, "init", "-b", branch)
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    _git(root, "push", "-u", "origin", branch)
    _git(root, "fetch", "origin", branch)
    return root


# ---------------------------------------------------------------------------
# Versions and tags
# ---------------------------------------------------------------------------


def test_parse_version_accepts_a_semantic_release(release) -> None:
    assert str(release.parse_version("1.1.0")) == "1.1.0"
    assert str(release.parse_version(" 2.0.12 ")) == "2.0.12"


@pytest.mark.parametrize("bad", ["v1.1.0", "1.1", "1", "1.1.0-rc1", "latest", ""])
def test_parse_version_refuses_anything_but_major_minor_patch(release, bad) -> None:
    """The tag prefix is named in the message, because that is the mistake people make."""
    with pytest.raises(release.ReleaseError):
        release.parse_version(bad)


def test_the_v_prefix_error_names_the_version_without_it(release) -> None:
    with pytest.raises(release.ReleaseError, match=r"without it \('1\.1\.0'\)"):
        release.parse_version("v1.1.0")


def test_tag_name_is_v_plus_the_version(release) -> None:
    assert release.tag_name(release.parse_version("1.1.0")) == "v1.1.0"


# ---------------------------------------------------------------------------
# The three sites
# ---------------------------------------------------------------------------


def test_read_version_sites_reads_all_three(release, tree: Path) -> None:
    assert release.read_version_sites(tree) == {
        "[project].version": "1.0.0",
        "aidw.__version__": "1.0.0",
        "the packaging test's literal": "1.0.0",
    }


def test_read_version_sites_refuses_an_unreadable_or_ambiguous_site(release, tree: Path) -> None:
    """A pattern that matches twice is a hard error: guessing which line to bump is worse."""
    (tree / "aidw" / "__init__.py").write_text(
        '__version__ = "1.0.0"\n__version__ = "1.0.0"\n', encoding="utf-8"
    )
    with pytest.raises(release.ReleaseError, match="exactly one aidw.__version__ line"):
        release.read_version_sites(tree)


def test_plan_bump_rewrites_exactly_the_three_version_lines(release, tree: Path) -> None:
    edits = {relative: new for relative, _old, new in release.plan_bump(tree, release.parse_version("1.1.0"))}

    assert set(edits) == {"pyproject.toml", "aidw/__init__.py", "tests/test_packaging.py"}

    pyproject = edits["pyproject.toml"]
    assert 'version = "1.1.0"' in pyproject
    # Untouched neighbours, including a dependency floor that looks like a version.
    assert 'requires-python = ">=3.11"' in pyproject
    assert '"packaging>=24.0"' in pyproject
    assert 'version = "1.0.0"' not in pyproject

    assert '__version__ = "1.1.0"' in edits["aidw/__init__.py"]

    packaging = edits["tests/test_packaging.py"]
    assert 'assert project["version"] == "1.1.0"' in packaging
    # The same literal as *data* inside the test stays put: only the assertion is the site.
    assert 'project = {"version": "1.0.0"}' in packaging
    assert 'assert project["name"] == "aidt"' in packaging


def test_plan_bump_keeps_the_packaging_assertions_indentation(release, tree: Path) -> None:
    """The assert line's leading whitespace is preserved, so the file stays valid Python."""
    (tree / "tests" / "test_packaging.py").write_text(
        PACKAGING_TEST.replace(
            '    assert project["version"] == "1.0.0"',
            '        assert project["version"] == "1.0.0"',
        ),
        encoding="utf-8",
    )
    edits = {relative: new for relative, _old, new in release.plan_bump(tree, release.parse_version("1.2.3"))}

    assert '        assert project["version"] == "1.2.3"' in edits["tests/test_packaging.py"]


def test_plan_bump_refuses_sites_that_disagree(release, tree: Path) -> None:
    """A half-finished bump is not a base to build a release on."""
    (tree / "aidw" / "__init__.py").write_text('__version__ = "0.9.0"\n', encoding="utf-8")

    with pytest.raises(release.ReleaseError, match="the version sites disagree"):
        release.plan_bump(tree, release.parse_version("1.1.0"))


@pytest.mark.parametrize("target,reason", [("1.0.0", "already"), ("0.9.0", "lower")])
def test_plan_bump_refuses_a_version_that_does_not_move_forward(
    release, tree: Path, target: str, reason: str
) -> None:
    with pytest.raises(release.ReleaseError, match=reason):
        release.plan_bump(tree, release.parse_version(target))


# ---------------------------------------------------------------------------
# The preflight refusals, against a throwaway repository
# ---------------------------------------------------------------------------


def test_bump_refuses_a_dirty_tree_before_writing_anything(
    release, tree: Path, capsys
) -> None:
    _git_repo(tree)
    (tree / "scratch.txt").write_text("untracked\n", encoding="utf-8")

    code = release.main(["--root", str(tree), "bump", "1.1.0"])

    assert code == 2
    assert "working tree is dirty" in capsys.readouterr().err
    # Nothing was bumped: the refusal is before the first write, not after it.
    assert 'version = "1.0.0"' in (tree / "pyproject.toml").read_text(encoding="utf-8")


def test_bump_refuses_a_task_branch(release, tree: Path, capsys) -> None:
    _git_repo(tree)
    _git(tree, "switch", "-c", "00-E9.4")

    code = release.main(["--root", str(tree), "bump", "1.1.0"])

    assert code == 2
    assert "on branch '00-E9.4'" in capsys.readouterr().err


def test_bump_dry_run_prints_the_plan_and_writes_nothing(release, tree: Path, capsys) -> None:
    _git_repo(tree)

    code = release.main(["--root", str(tree), "bump", "1.1.0", "--dry-run"])

    assert code == 0
    out = capsys.readouterr().out
    assert "bump: pyproject.toml" in out
    assert "would run: uv lock" in out
    assert "would run: git commit -m chore(release): AIDT 1.1.0" in out or (
        "would run: git commit" in out
    )
    # Before and after: the files still say 1.0.0.
    for relative in ("pyproject.toml", "aidw/__init__.py", "tests/test_packaging.py"):
        assert "1.0.0" in (tree / relative).read_text(encoding="utf-8")


def test_bump_refuses_when_main_is_behind_origin(release, tree: Path, capsys) -> None:
    """A release is cut on merged history: a local-only commit is refused."""
    _git_repo(tree)
    (tree / "later.txt").write_text("local only\n", encoding="utf-8")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-m", "local only")

    code = release.main(["--root", str(tree), "bump", "1.1.0", "--dry-run"])

    assert code == 2
    assert "is not origin/main" in capsys.readouterr().err


def test_tag_refuses_an_existing_tag(release, tree: Path, capsys) -> None:
    """A published tag is immutable history, so an existing one is never moved."""
    _git_repo(tree)
    _git(tree, "tag", "-a", "v1.0.0", "-m", "AIDT v1.0.0")

    code = release.main(["--root", str(tree), "tag", "1.0.0"])

    assert code == 2
    assert "already exists" in capsys.readouterr().err


def test_tag_refuses_a_tree_that_does_not_carry_the_version(
    release, tree: Path, capsys
) -> None:
    """Tagging a tree at another version is how the tag and the wheel metadata diverge."""
    _git_repo(tree)

    code = release.main(["--root", str(tree), "tag", "1.1.0"])

    assert code == 2
    assert "the tree carries 1.0.0, not 1.1.0" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The script's own CLI surface
# ---------------------------------------------------------------------------


def test_the_three_subcommands_are_the_documented_ones(release) -> None:
    """``bump`` / ``tag`` / ``verify``, matching ``docs/releasing.md`` §1–§3."""
    parser = release.build_parser()

    assert "bump" in parser._subparsers._group_actions[0].choices
    assert "tag" in parser._subparsers._group_actions[0].choices
    assert "verify" in parser._subparsers._group_actions[0].choices


def test_the_gate_list_is_the_agents_md_set(release) -> None:
    """The helper cannot invent or drop a gate: the list is AGENTS.md's, verbatim."""
    assert ("uv", "lock", "--check") in release.GATES
    assert ("uv", "sync", "--frozen") in release.GATES
    assert (
        "uv",
        "run",
        "aidw",
        "gate",
        "run",
        "suite",
        "--",
        "uv",
        "run",
        "--frozen",
        "pytest",
    ) in release.GATES
    for tail in (
        ("doctor",),
        ("agents", "validate", "--strict"),
        ("prompts", "check"),
    ):
        assert ("uv", "run", "aidw", *tail) in release.GATES
