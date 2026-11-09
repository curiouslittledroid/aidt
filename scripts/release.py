#!/usr/bin/env python3
"""Release helper: bump the version in its three homes, gate, deliver, and cut the tag.

Implements the process in ``docs/releasing.md`` (D9, EXTRACTION.md §3.11) as one command,
because the sequence has five places that must agree and two of them (``uv.lock`` and the
tag's commit) are only correct if they are updated in the same step:

1. ``pyproject.toml`` → ``[project].version``;
2. ``aidw/__init__.py`` → ``__version__`` (the in-code copy every run records);
3. ``tests/test_packaging.py`` → the hardcoded literal in
   ``test_pyproject_identity_is_the_settled_name_version_and_script``, which is a *third*
   site and is deliberately not derived from either of the others (the test that guards the
   first two would stop guarding them);
4. ``uv.lock`` → the project's own locked version, re-synced with ``uv lock``, never edited
   by hand (``uv sync --frozen`` accepts a stale lock, so ``uv lock --check`` is the proof);
5. the annotated ``v<X.Y.Z>`` tag, cut **on merged ``main``**, never on a branch.

Three subcommands, each of which is safe to run on its own, so a release can be split across
a PR merge and a later tagging session::

    uv run python scripts/release.py bump 1.1.0            # gates + branch + commit + PR
    uv run python scripts/release.py bump 1.1.0 --direct   # gates + commit on main + push
    uv run python scripts/release.py tag 1.1.0             # annotated tag on merged main
    uv run python scripts/release.py verify 1.1.0          # D9 install forms from a clean venv

``--dry-run`` prints every edit and every command without writing, running or pushing
anything; it is the way to see what a release would do. Every refusal (dirty tree, not on
``main``, ``main`` behind ``origin``, the three version sites disagreeing, an existing tag, a
non-forward bump) happens *before* the first write, with the fix in the message.

Usage reference: ``docs/releasing.md``. The gates are the ones ``AGENTS.md`` fixes, run in
their documented form (``aidw gate run suite -- uv run --frozen pytest`` included), so the
recorded outcome is the one the next stage would cite.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version

#: The three files that carry the version, and the one line in each. Each pattern captures
#: exactly the version literal and is applied with ``count=1``, so a second copy is an error
#: rather than a silent partial rewrite.
PYPROJECT = "pyproject.toml"
INIT_MODULE = "aidw/__init__.py"
PACKAGING_TEST = "tests/test_packaging.py"

VERSION_SITES: tuple[tuple[str, str, str], ...] = (
    (PYPROJECT, r'(?m)^version = "(\d+\.\d+\.\d+)"$', "[project].version"),
    (INIT_MODULE, r'(?m)^__version__ = "(\d+\.\d+\.\d+)"$', "aidw.__version__"),
    (
        PACKAGING_TEST,
        r'(?m)^(\s*)assert project\["version"\] == "(\d+\.\d+\.\d+)"$',
        "the packaging test's literal",
    ),
)

#: The gates AGENTS.md fixes, in order. ``uv lock`` runs before ``--check`` because the bump
#: is what makes the lock stale; ``uv sync --frozen`` then proves the lock builds.
GATES: tuple[tuple[str, ...], ...] = (
    ("uv", "lock"),
    ("uv", "lock", "--check"),
    ("uv", "sync", "--frozen"),
    ("uv", "run", "aidw", "gate", "run", "suite", "--", "uv", "run", "--frozen", "pytest"),
    ("uv", "run", "aidw", "doctor"),
    ("uv", "run", "aidw", "agents", "validate", "--strict"),
    ("uv", "run", "aidw", "prompts", "check"),
)

REPO_URL = "git+https://github.com/curiouslittledroid/aidt"


class ReleaseError(RuntimeError):
    """A refusal. Always raised before the first write, and always actionable."""


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested without a repository)
# --------------------------------------------------------------------------- #


def parse_version(text: str) -> Version:
    """``text`` as a ``MAJOR.MINOR.PATCH`` version, refusing anything else.

    A leading ``v`` is the *tag's* spelling, not the version's: ``v1.1.0`` → ``1.1.0`` is a
    common slip, so it is named in the error instead of being accepted silently. Pre-release
    and build-metadata forms are refused too — ``docs/releasing.md`` settles the scheme as
    semantic ``MAJOR.MINOR.PATCH``, and a ``-rc1`` in the tree would make the tag, the wheel
    metadata and the ``requires_toolkit`` comparisons disagree about what was released.
    """
    raw = text.strip()
    if raw.lower().startswith("v"):
        raise ReleaseError(
            f"{raw!r} carries the tag prefix; pass the version without it ({raw[1:]!r})"
        )
    if not re.fullmatch(r"\d+\.\d+\.\d+", raw):
        raise ReleaseError(
            f"{raw!r} is not a MAJOR.MINOR.PATCH release version; "
            "docs/releasing.md settles the scheme as semantic, e.g. 1.1.0"
        )
    return Version(raw)


def tag_name(version: Version) -> str:
    """The annotated tag for ``version``: ``v`` plus the version (``docs/releasing.md`` §2)."""
    return f"v{version}"


def read_version_sites(root: Path) -> dict[str, str]:
    """The version currently written at each of the three sites, keyed by site label."""
    found: dict[str, str] = {}
    for relative, pattern, label in VERSION_SITES:
        text = (root / relative).read_text(encoding="utf-8")
        matches = re.findall(pattern, text)
        if len(matches) != 1:
            raise ReleaseError(
                f"{relative}: expected exactly one {label} line matching "
                f"{pattern!r}, found {len(matches)} — refusing to guess which one to bump"
            )
        match = matches[0]
        found[label] = match if isinstance(match, str) else match[-1]
    return found


def plan_bump(root: Path, new_version: Version) -> list[tuple[str, str, str]]:
    """The ``(relative path, old text, new text)`` edits the bump makes, without writing.

    Refuses when the three sites disagree (a half-finished bump is not something to build on),
    when the new version is not an increase (a release is always forward), and when the tree
    already carries the requested version (nothing to do, so the caller re-decides).
    """
    current = read_version_sites(root)
    distinct = set(current.values())
    if len(distinct) != 1:
        raise ReleaseError(
            "the version sites disagree — "
            + ", ".join(f"{label}={value}" for label, value in sorted(current.items()))
            + "; fix them to one value before releasing"
        )
    (old_raw,) = distinct
    old_version = Version(old_raw)
    if new_version == old_version:
        raise ReleaseError(f"the tree is already at {old_version}; pass the next version")
    if new_version < old_version:
        raise ReleaseError(
            f"{new_version} is lower than the tree's {old_version}; a release only moves forward"
        )

    edits: list[tuple[str, str, str]] = []
    for relative, pattern, label in VERSION_SITES:
        text = (root / relative).read_text(encoding="utf-8")
        edits.append((relative, text, replace_version_literal(text, pattern, str(new_version))))
    return edits


def replace_version_literal(text: str, pattern: str, new_version: str) -> str:
    """Swap the version literal in ``text``, keeping whatever precedes it on the line."""

    def _sub(match: re.Match[str]) -> str:
        start = match.start(1) - match.start()
        end = match.end(1) - match.start()
        whole = match.group(0)
        if len(match.groups()) == 2:
            # `(\s*)assert ...` — the indentation is group 1, the version group 2.
            start = match.start(2) - match.start()
            end = match.end(2) - match.start()
        return whole[:start] + new_version + whole[end:]

    new_text, count = re.subn(pattern, _sub, text, count=1)
    if count != 1:
        raise ReleaseError(f"no version literal matched {pattern!r}; nothing was changed")
    return new_text


# --------------------------------------------------------------------------- #
# Command execution
# --------------------------------------------------------------------------- #


@dataclass
class Runner:
    """Runs (or only prints) the shell commands, in one place so ``--dry-run`` is total.

    Every command runs with ``cwd = root``, never in the caller's directory: ``--root`` exists
    so the helper can be pointed at a checkout (a test fixture, a scratch clone), and a
    ``git status`` that silently inspected the *caller's* repository instead of the target one
    would either refuse for the wrong reason or, worse, commit the wrong tree.
    """

    cwd: Path
    dry_run: bool = False

    def run(
        self,
        args: tuple[str, ...] | list[str],
        *,
        check: bool = True,
        capture: bool = False,
        env: dict[str, str] | None = None,
    ) -> str:
        printable = " ".join(args)
        if self.dry_run:
            print(f"  would run: {printable}", flush=True)
            return ""
        print(f"  run: {printable}", flush=True)
        completed = subprocess.run(
            list(args),
            cwd=self.cwd,
            check=check,
            text=True,
            capture_output=capture,
            env=env,
        )
        return (completed.stdout or "").strip() if capture else ""

    def read(self, args: tuple[str, ...] | list[str]) -> str:
        """Run a **read-only** inspection and return its output — even under ``--dry-run``.

        The preflight refusals must describe the real tree, so ``git status``, ``git
        rev-parse`` and ``git ls-remote`` always execute; only commands that write, install,
        commit, push or tag are suppressed. A dry run that skipped these would either refuse
        on empty strings or claim a clean tree it never looked at.
        """
        print(f"  check: {' '.join(args)}", flush=True)
        completed = subprocess.run(
            list(args), cwd=self.cwd, check=False, text=True, capture_output=True
        )
        return (completed.stdout or "").strip()

    def run_ok(self, args: tuple[str, ...] | list[str], **kwargs: object) -> bool:
        """Whether the command succeeds — used for the checks that must fail *closed*."""
        if self.dry_run:
            print(f"  would run: {' '.join(args)}", flush=True)
            return False
        return (
            subprocess.run(
                list(args),
                cwd=self.cwd,
                check=False,
                text=True,
                capture_output=True,
                **kwargs,
            ).returncode
            == 0
        )


def _git(*args: str) -> tuple[str, ...]:
    return ("git", *args)


def _current_branch(runner: Runner) -> str:
    return runner.read(_git("rev-parse", "--abbrev-ref", "HEAD"))


def _require_clean_tree(runner: Runner) -> None:
    status = runner.read(_git("status", "--porcelain"))
    if status:
        raise ReleaseError(
            "the working tree is dirty; commit or stash first:\n" + status
        )


def _require_on_main(runner: Runner) -> None:
    branch = _current_branch(runner)
    if branch != "main":
        raise ReleaseError(
            f"on branch {branch!r}; a release bump starts from an up-to-date 'main' "
            "(run this from the control worktree, docs/releasing.md §1)"
        )


def _require_up_to_date(runner: Runner) -> None:
    """``main`` must equal ``origin/main``: a release is cut on merged history only."""
    runner.run(_git("fetch", "origin", "main"))
    head = runner.read(_git("rev-parse", "HEAD"))
    remote = runner.read(_git("rev-parse", "origin/main"))
    if head != remote:
        raise ReleaseError(
            f"main ({head[:8]}) is not origin/main ({remote[:8]}); "
            "run `git pull --ff-only` first"
        )


def _tag_exists(runner: Runner, tag: str) -> tuple[bool, bool]:
    """``(local, remote)`` existence of ``tag`` — history is immutable, so both refuse."""
    local = runner.run_ok(_git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"))
    remote_out = runner.read(_git("ls-remote", "--tags", "origin", tag))
    return local, bool(remote_out)


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #


def cmd_bump(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    version = parse_version(args.version)
    runner = Runner(cwd=root, dry_run=args.dry_run)

    print(f"release {version} — bump ({'plan only' if args.dry_run else 'for real'})")
    _require_clean_tree(runner)
    _require_on_main(runner)
    _require_up_to_date(runner)

    edits = plan_bump(root, version)
    for relative, _old, _new in edits:
        print(f"  bump: {relative}")
    if not args.dry_run:
        for relative, _old, new_text in edits:
            (root / relative).write_text(new_text, encoding="utf-8")

    if not args.skip_gates:
        print("gates:")
        for command in GATES:
            runner.run(command)
    else:
        print("gates: skipped (--skip-gates) — docs/releasing.md requires them before a tag")

    message = f"chore(release): AIDT {version}"
    if args.direct:
        print("delivering directly on main (no PR):")
        runner.run(_git("add", "-A"))
        runner.run(_git("commit", "-m", message))
        runner.run(_git("push", "origin", "main"))
        if args.tag:
            return _cut_tag(root, version, runner, dry_run=args.dry_run)
        print(
            f"\nnext: merge nothing — the commit is on main. Cut the tag with:\n"
            f"  uv run python scripts/release.py tag {version}"
        )
        return 0

    branch = f"release/{tag_name(version)}"
    print(f"delivering through a PR (branch {branch}, docs/releasing.md §1):")
    runner.run(_git("switch", "-c", branch))
    runner.run(_git("add", "-A"))
    runner.run(_git("commit", "-m", message))
    runner.run(_git("push", "-u", "origin", branch))
    if shutil.which("gh") is None:
        raise ReleaseError(
            "`gh` is not on PATH, so the PR was not opened; push succeeded — open it by hand "
            f"from {branch} to main, or re-run with --direct"
        )
    body = (
        f"Bump AIDT to {version} (`docs/releasing.md` §1).\n\n"
        "Three version sites plus the lockfile, in one commit:\n"
        f"- `{PYPROJECT}` `[project].version`\n"
        f"- `{INIT_MODULE}` `__version__`\n"
        f"- `{PACKAGING_TEST}` (the hardcoded literal that guards the two above)\n"
        "- `uv.lock` via `uv lock` (`uv lock --check` proves it)\n\n"
        "## Verification\n\n"
        "The release helper ran the gates before committing:\n\n"
        "```\n"
        + "\n".join(" ".join(command) for command in GATES)
        + "\n```\n\n"
        "Merge this, then cut the annotated tag on merged `main`: "
        f"`uv run python scripts/release.py tag {version}`."
    )
    runner.run(
        (
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            message,
            "--body",
            body,
        )
    )
    print(
        f"\nnext: merge the PR, then cut the tag on merged main:\n"
        f"  uv run python scripts/release.py tag {version}"
    )
    return 0


def _cut_tag(root: Path, version: Version, runner: Runner, *, dry_run: bool) -> int:
    tag = tag_name(version)
    tree_version = read_version_sites(root)[EXTRA_LABEL]
    if tree_version != str(version):
        raise ReleaseError(
            f"the tree carries {tree_version}, not {version} — tag the tree you released"
        )
    local, remote = _tag_exists(runner, tag)
    if local or remote:
        raise ReleaseError(
            f"tag {tag} already exists ({'local' if local else 'origin'}); "
            "a published tag is immutable — bump the version and tag the next release"
        )
    runner.run(_git("tag", "-a", tag, "-m", f"AIDT {tag}"))
    runner.run(_git("push", "origin", tag))
    runner.run(_git("show", "--stat", tag))
    print(
        "\nnext: prove the tag by installing from it (docs/releasing.md §3):\n"
        f"  uv run python scripts/release.py verify {version}"
    )
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    version = parse_version(args.version)
    runner = Runner(cwd=root, dry_run=args.dry_run)

    print(f"release {version} — annotated tag ({'plan only' if args.dry_run else 'for real'})")
    _require_clean_tree(runner)
    _require_on_main(runner)
    _require_up_to_date(runner)
    return _cut_tag(root, version, runner, dry_run=args.dry_run)


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    version = parse_version(args.version)
    tag = tag_name(version)
    runner = Runner(cwd=root, dry_run=args.dry_run)

    print(f"release {version} — install from {REPO_URL}@{tag} (D9's two forms)")
    if not args.dry_run:
        _local, remote = _tag_exists(runner, tag)
        if not remote:
            raise ReleaseError(f"tag {tag} is not on origin; tag and push it first")

    with tempfile.TemporaryDirectory(prefix="aidt-release-check-") as scratch:
        base = Path(scratch)
        env = clean_venv_env(base)
        # A clean tool venv is the point: a cached build must not make an older install look
        # like the new tag (docs/releasing.md §3).
        runner.run(
            ("uv", "tool", "install", f"{REPO_URL}@{tag}"), env=_merge_env(env)
        )
        printed = runner.run(
            (str(base / "bin" / "aidw"), "--version"), capture=True, env=_merge_env(env)
        )
        if not args.dry_run and printed.strip() != f"aidt {version}":
            raise ReleaseError(
                f"`aidw --version` printed {printed!r}, expected 'aidt {version}'"
            )
        runner.run(
            ("uvx", "--from", f"{REPO_URL}@{tag}", "aidw", "--version"),
            env=_merge_env(env),
        )
    print(
        "\nlast check, from a bootstrapped workspace's control worktree (needs the target "
        "layout, so it is not run here):\n  aidw doctor"
    )
    return 0


def clean_venv_env(base: Path) -> dict[str, str]:
    """The env overrides that make a *clean* tool venv: uv's three directories, nothing else.

    Isolating ``UV_TOOL_DIR``/``UV_TOOL_BIN_DIR``/``UV_CACHE_DIR`` is what stops a cached build
    making an older install look like the new tag (``docs/releasing.md`` §3).

    ``HOME`` and ``PATH`` are deliberately **not** overridden. The install clones a *private*
    repository, so it authenticates with the machine's git credentials; overriding ``HOME``
    hides ``~/.gitconfig`` and its credential helper, and the fetch then fails with
    ``could not read Username for 'https://github.com': terminal prompts disabled`` — which is
    exactly how the first post-1.1.0 run of ``verify`` failed.
    """
    return {
        "UV_TOOL_DIR": str(base / "tools"),
        "UV_TOOL_BIN_DIR": str(base / "bin"),
        "UV_CACHE_DIR": str(base / "cache"),
    }


def _merge_env(overrides: dict[str, str]) -> dict[str, str]:
    """The operator's environment with the clean-venv overrides applied on top."""
    return {**os.environ, **overrides}


#: The label ``read_version_sites`` uses for the in-code copy; kept as a constant so the
#: tag step cannot drift from the bump step.
EXTRA_LABEL = VERSION_SITES[1][2]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release.py",
        description="Bump, gate, deliver and tag an AIDT release (docs/releasing.md).",
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parent.parent),
        help="repository root (default: the toolkit this script ships in)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(target: argparse.ArgumentParser) -> None:
        target.add_argument("version", help="MAJOR.MINOR.PATCH, without the 'v' prefix")
        target.add_argument(
            "--dry-run",
            action="store_true",
            help="print every edit and command; write, run and push nothing",
        )

    bump = sub.add_parser("bump", help="bump the three sites + lock, gate, then deliver")
    _common(bump)
    bump.add_argument(
        "--direct",
        action="store_true",
        help="commit straight to main and push (pre-1.0 practice; skips review and CI)",
    )
    bump.add_argument(
        "--tag",
        action="store_true",
        help="with --direct, also cut and push the annotated tag",
    )
    bump.add_argument(
        "--skip-gates", action="store_true", help="skip the AGENTS.md gate set (not advised)"
    )
    bump.set_defaults(func=cmd_bump)

    tag = sub.add_parser("tag", help="cut and push the annotated tag on merged main")
    _common(tag)
    tag.set_defaults(func=cmd_tag)

    verify = sub.add_parser("verify", help="install the tag from a clean tool venv (D9 forms)")
    _common(verify)
    verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ReleaseError as error:
        print(f"release refused: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        failed = " ".join(str(part) for part in error.cmd)
        print(f"command failed ({error.returncode}): {failed}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
