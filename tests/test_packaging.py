"""Contract and property tests for the installable package (E8.1, EXTRACTION.md §3.12/D9).

``aidw/paths.py:toolkit_root()`` is ``Path(__file__).parent.parent``: it works installed
only if ``prompts/``, ``agent-configs/`` and ``agents/`` land *beside* ``aidw/`` inside
site-packages, exactly as they are siblings of the package in the checkout (§3.12). The
wheel therefore force-includes those three repo-root dirs to the wheel root, and the sdist —
which hatchling fills with every git-tracked file — is what the wheel is assembled from, so
the force-included dirs must be tracked and complete (Requirements 2-4).

The observable proof (Requirement 5) is ``aidw doctor``'s ``toolkit root`` check
(:func:`aidw.doctor._check_toolkit_root`): it reports ``OK`` for a site-packages-shaped
unpack of the real wheel and the exact ``missing: prompts, scripts, agent-configs, agents``
``FAIL`` for a wheel built without the force-include table — the bug this task exists to
prevent. ``tests/test_toolkit_paths.py`` stays unchanged as the layout regression guard: no
``paths.py`` edit is part of this task.

The builds here run with ``uv build --no-build-isolation`` against the interpreter running
the tests, with ``UV_OFFLINE=1``, so the proof needs no network: ``hatchling`` is a locked
dev-group dependency (``pyproject.toml``; ``uv sync --frozen`` provisions it) and CI's
``uv run --frozen pytest`` stays offline. Default build isolation would fetch the backend
from PyPI and fail there.

Also ``D7``/``D9``: repo and distribution ``aidt``, import package and console script
``aidw`` — one name each, no dynamic versioning here (E8.3 owns ``aidw --version``).
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from aidw import __version__, cli, doctor, inventory, paths
from aidw.paths import ToolkitPaths, toolkit_root

PROJECT_ROOT = toolkit_root()
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

#: Requirement 2/§3.12: the repo-root siblings of ``aidw/`` that are runtime assets, mapped
#: to their wheel destination (the wheel root). Exactly three — nothing else is bundled.
RUNTIME_ASSET_DIRS = {
    "prompts": "prompts",
    "agent-configs": "agent-configs",
    "agents": "agents",
}

#: The same dirs as payload prefixes, for membership tests over wheel/sdist entry names.
ASSET_PREFIXES = tuple(f"{name}/" for name in RUNTIME_ASSET_DIRS)

#: Requirement 3's exclusion list: dev-time content that must never become wheel payload.
#: ``README.md`` is deliberately absent — it ships as wheel *metadata* (``readme``).
DEV_TIME_PAYLOAD_PREFIXES = ("tests/", "docs/", "design.md", "uv.lock", ".github/")

#: A build is a few seconds; the ceiling only exists so a hung build fails instead of
#: hanging the suite (fail closed).
BUILD_TIMEOUT_SECONDS = 600


# ---------------------------------------------------------------------------
# Harness: build the real distributions once per module
# ---------------------------------------------------------------------------


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def _build(
    out_dir: Path, *, project: Path = PROJECT_ROOT, wheel_only: bool = False
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run ``uv build`` into ``out_dir``; return the completed process and the dir.

    ``--no-build-isolation`` builds against the environment running these tests, which has
    ``hatchling`` from the locked dev group, so no network is needed (``UV_OFFLINE=1``
    makes that a hard requirement rather than a hope). ``--python sys.executable`` picks
    that environment explicitly instead of inheriting ``VIRTUAL_ENV`` from whatever shell
    launched pytest — the same reason ``VIRTUAL_ENV`` is stripped from the child env.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "uv",
        "build",
        "--no-build-isolation",
        "--no-build-logs",
        "--no-create-gitignore",
        "--python",
        sys.executable,
        "--out-dir",
        str(out_dir),
    ]
    if wheel_only:
        command.insert(2, "--wheel")

    env = {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}
    env["UV_OFFLINE"] = "1"
    completed = subprocess.run(
        command,
        cwd=project,
        capture_output=True,
        text=True,
        timeout=BUILD_TIMEOUT_SECONDS,
        env=env,
    )
    return completed, out_dir


def _require_success(
    completed: subprocess.CompletedProcess[str], out_dir: Path
) -> Path:
    """Assert the build succeeded, echoing both streams when it did not (fail closed)."""
    assert completed.returncode == 0, (
        f"`uv build` failed in {out_dir} (exit {completed.returncode})\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return out_dir


def _single(directory: Path, suffix: str) -> Path:
    found = sorted(directory.glob(f"*{suffix}"))
    assert len(found) == 1, f"expected exactly one *{suffix} in {directory}: {found}"
    return found[0]


def _wheel_entries(wheel: Path) -> tuple[str, ...]:
    with zipfile.ZipFile(wheel) as archive:
        return tuple(sorted(entry for entry in archive.namelist() if not entry.endswith("/")))


def _wheel_member(wheel: Path, suffix: str) -> str:
    with zipfile.ZipFile(wheel) as archive:
        matches = sorted(name for name in archive.namelist() if name.endswith(suffix))
        assert len(matches) == 1, f"expected exactly one {suffix} in {wheel}: {matches}"
        return archive.read(matches[0]).decode("utf-8")


def _sdist_entries(sdist: Path) -> tuple[str, ...]:
    """Every file the sdist carries, relative to its single top-level ``aidt-<version>/``."""
    with tarfile.open(sdist) as archive:
        names = [member.name for member in archive.getmembers() if member.isfile()]
    assert names, f"{sdist} carries no files"
    prefix = names[0].split("/", 1)[0] + "/"
    assert all(name.startswith(prefix) for name in names), f"{sdist} has more than one root"
    return tuple(sorted(name[len(prefix):] for name in names))


def _unpack_wheel(wheel: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(destination)
    return destination


def _tracked_files() -> tuple[str, ...]:
    """Every git-tracked path, repo-relative.

    The sdist is filled from the tracked tree, so "tracked" — not "present on disk" — is
    the set bundling has to be judged against: a force-included dir that were ignored or
    untracked would silently ship empty.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(rel for rel in result.stdout.split("\0") if rel)


#: What a build reads and force-includes — the tree it must not rewrite while packaging it.
#: Scoped deliberately: the suite is parallel, so a whole-tree snapshot would also observe
#: unrelated modules' scratch state and flake.
BUILD_SCOPE = ("aidw", "prompts", "agent-configs", "agents", "pyproject.toml", "uv.lock")


def _git_state() -> str:
    """Tracked and untracked-but-not-ignored state under :data:`BUILD_SCOPE`."""
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *BUILD_SCOPE,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@dataclass(frozen=True)
class Distribution:
    """The built wheel and sdist plus their (sorted) payload entry names."""

    wheel: Path
    sdist: Path
    wheel_entries: tuple[str, ...]
    sdist_entries: tuple[str, ...]


@pytest.fixture(scope="module")
def distribution(tmp_path_factory: pytest.TempPathFactory) -> Distribution:
    """Build the wheel and sdist once for the module (each build is a few seconds)."""
    out_dir = tmp_path_factory.mktemp("dist") / "build"
    completed, out_dir = _build(out_dir)
    _require_success(completed, out_dir)
    wheel = _single(out_dir, ".whl")
    sdist = _single(out_dir, ".tar.gz")
    return Distribution(
        wheel=wheel,
        sdist=sdist,
        wheel_entries=_wheel_entries(wheel),
        sdist_entries=_sdist_entries(sdist),
    )


@pytest.fixture(autouse=True)
def _stub_external_clis(fake_external_clis: None) -> None:  # noqa: ARG001
    """The doctor assertions here are about the installed toolkit root, not ``pi``/``gh``."""


# ---------------------------------------------------------------------------
# Requirement 1: the settled identity (D7) and the single version source
# ---------------------------------------------------------------------------


def test_pyproject_identity_is_the_settled_name_version_and_script() -> None:
    """D7 settles "pick one": repo/distribution ``aidt``, import package + CLI ``aidw``."""
    project = _pyproject()["project"]

    assert project["name"] == "aidt"
    assert project["version"] == "1.1.0"
    assert project["version"] == __version__
    assert project["scripts"] == {"aidw": "aidw.cli:main"}
    # The console script must name a real callable (E8.3 owns `aidw --version`, not this).
    assert callable(cli.main)
    # `README.md` is wheel metadata, never payload (Requirement 3).
    assert project["readme"] == "README.md"


def test_version_has_exactly_one_source() -> None:
    """No dynamic versioning and no second version table (Requirement 1)."""
    document = _pyproject()

    assert "version" not in document["project"].get("dynamic", [])
    assert "version" not in document.get("tool", {}).get("hatch", {})
    # `aidw/__init__.py` stays the in-code copy the future `--version` reads.
    assert (PROJECT_ROOT / "aidw" / "__init__.py").is_file()


def test_wheel_metadata_carries_that_identity(distribution: Distribution) -> None:
    metadata = _wheel_member(distribution.wheel, ".dist-info/METADATA")

    assert "Name: aidt" in metadata
    assert f"Version: {__version__}" in metadata


# ---------------------------------------------------------------------------
# Requirement 2/3: exactly the three runtime asset dirs are force-included
# ---------------------------------------------------------------------------


def test_wheel_force_includes_exactly_the_three_runtime_asset_dirs() -> None:
    wheel_target = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel_target["packages"] == ["aidw"]
    assert wheel_target["force-include"] == RUNTIME_ASSET_DIRS
    assert not set(wheel_target["force-include"]).intersection(DEV_TIME_PAYLOAD_PREFIXES)


def test_wheel_ships_the_task_prompt_under_prompts(distribution: Distribution) -> None:
    """One hand-checked example of the spec contract: ``prompts/task-prompt.md``."""
    assert "prompts/task-prompt.md" in distribution.wheel_entries


def test_wheel_ships_every_required_prompt(distribution: Distribution) -> None:
    """Derived from the constant, not one hardcoded path: any missing prompt breaks a stage."""
    expected = {f"prompts/{name}" for name in inventory.REQUIRED_PROMPTS}

    missing = sorted(expected - set(distribution.wheel_entries))
    assert missing == []


def test_wheel_ships_every_required_script(distribution: Distribution) -> None:
    """`prompts check` from an installed tool fails on any one missing script (§3.6)."""
    expected = {f"prompts/{rel}" for rel in inventory.REQUIRED_SCRIPTS}

    missing = sorted(expected - set(distribution.wheel_entries))
    assert missing == []
    # Requirement 4: the whole `review-followup/` dir survives, not just its entry points.
    assert any(
        entry.startswith("prompts/scripts/review-followup/")
        for entry in distribution.wheel_entries
    )


def test_wheel_ships_agent_configs_and_agent_context(distribution: Distribution) -> None:
    configs = [
        entry
        for entry in distribution.wheel_entries
        if entry.startswith("agent-configs/") and entry.endswith(".yaml")
    ]
    contexts = [
        entry
        for entry in distribution.wheel_entries
        if entry.startswith("agents/") and entry.endswith("/AGENTS.md")
    ]

    assert configs, "wheel carries no agent-configs/*.yaml"
    assert contexts, "wheel carries no agents/*/AGENTS.md"


def test_wheel_ships_every_tracked_runtime_asset(distribution: Distribution) -> None:
    """Bundling is complete, not a sample: every tracked file in the three dirs ships."""
    expected = {rel for rel in _tracked_files() if rel.startswith(ASSET_PREFIXES)}

    assert expected
    missing = sorted(expected - set(distribution.wheel_entries))
    assert missing == []


def test_wheel_ships_the_import_package(distribution: Distribution) -> None:
    expected = {rel for rel in _tracked_files() if rel.startswith("aidw/")}

    assert expected
    assert sorted(expected - set(distribution.wheel_entries)) == []


def test_wheel_declares_the_aidw_console_script(distribution: Distribution) -> None:
    entry_points = _wheel_member(distribution.wheel, ".dist-info/entry_points.txt")

    assert "[console_scripts]" in entry_points
    assert "aidw = aidw.cli:main" in entry_points


@pytest.mark.parametrize("prefix", DEV_TIME_PAYLOAD_PREFIXES)
def test_wheel_carries_no_dev_time_payload(
    distribution: Distribution, prefix: str
) -> None:
    """Requirement 3's exclusion list — the negative vector for the force-include table."""
    leaked = [
        entry
        for entry in distribution.wheel_entries
        if entry == prefix or entry.startswith(prefix)
    ]

    assert leaked == []


def test_readme_is_wheel_metadata_not_payload(distribution: Distribution) -> None:
    assert "README.md" not in distribution.wheel_entries
    # ... but its content is the long description, so it does reach the wheel.
    metadata = _wheel_member(distribution.wheel, ".dist-info/METADATA")
    assert "# AIDT — AI Developer Tools" in metadata


# ---------------------------------------------------------------------------
# Requirement 4: the sdist carries the same assets, which the wheel is built from
# ---------------------------------------------------------------------------


def test_sdist_carries_the_same_runtime_assets(distribution: Distribution) -> None:
    for dirname in RUNTIME_ASSET_DIRS:
        assert any(
            entry.startswith(f"{dirname}/") for entry in distribution.sdist_entries
        ), f"sdist carries no {dirname}/"

    assert "prompts/task-prompt.md" in distribution.sdist_entries
    expected = {f"prompts/{rel}" for rel in inventory.REQUIRED_SCRIPTS}
    assert sorted(expected - set(distribution.sdist_entries)) == []


def test_wheel_assets_match_the_sdist_assets(distribution: Distribution) -> None:
    """`uv build` assembles the wheel from the sdist: the same three dirs, file for file."""

    def assets(entries: tuple[str, ...]) -> set[str]:
        return {entry for entry in entries if entry.startswith(ASSET_PREFIXES)}

    assert assets(distribution.wheel_entries) == assets(distribution.sdist_entries)


# ---------------------------------------------------------------------------
# Requirement 5: the observable proof — doctor's `toolkit root` check
# ---------------------------------------------------------------------------


def _toolkit_root_check(monkeypatch: pytest.MonkeyPatch, root: Path) -> doctor.Check:
    """Run doctor's ``toolkit root`` check against ``root`` as the installed toolkit."""
    monkeypatch.setattr(paths, "toolkit_root", lambda: root)
    return next(
        check for check in doctor.collect_checks() if check.name == "toolkit root"
    )


def test_installed_layout_satisfies_the_doctor_toolkit_root_check(
    distribution: Distribution, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unpacked wheel is the site-packages layout: ``toolkit_root`` == the wheel root."""
    root = _unpack_wheel(distribution.wheel, tmp_path / "site-packages")

    check = _toolkit_root_check(monkeypatch, root)

    assert check.status == doctor.OK
    assert check.detail == str(root)
    assert "missing:" not in check.detail

    installed = ToolkitPaths.resolve()
    assert installed.root == root
    assert installed.scripts_dir == root / "prompts" / "scripts"
    # The dirs the checkout test asserts must also hold for the *installed* copy.
    assert (installed.prompts_dir / "task-prompt.md").is_file()
    assert (installed.scripts_dir / "review-followup" / "review_followup.py").is_file()
    assert list(installed.agent_configs_dir.glob("*.yaml"))
    assert [child for child in installed.agents_dir.iterdir() if child.is_dir()]


def _copy_tracked_tree(destination: Path) -> Path:
    """A buildable copy of the tracked tree, for the without-the-fix negative vector."""
    for rel in _tracked_files():
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / rel, target)
    return destination


def _strip_force_include(pyproject: Path) -> None:
    """Delete the force-include section, keeping a valid TOML document behind."""
    kept: list[str] = []
    skipping = False
    for line in pyproject.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith("["):
            skipping = line.strip() == "[tool.hatch.build.targets.wheel.force-include]"
        if not skipping:
            kept.append(line)
    pyproject.write_text("".join(kept), encoding="utf-8")

    with pyproject.open("rb") as handle:
        wheel_target = tomllib.load(handle)["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert "force-include" not in wheel_target


def test_doctor_fails_closed_when_the_wheel_omits_the_asset_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact bug E8.1 exists to prevent: a wheel with only ``aidw/`` must FAIL.

    This is the fail-closed half of Requirement 5 — `missing: prompts, scripts,
    agent-configs, agents` is what an installed ``aidw doctor`` reported before the
    force-include table existed.
    """
    project = _copy_tracked_tree(tmp_path / "checkout")
    _strip_force_include(project / "pyproject.toml")

    completed, out_dir = _build(tmp_path / "dist", project=project, wheel_only=True)
    _require_success(completed, out_dir)
    wheel = _single(out_dir, ".whl")
    entries = _wheel_entries(wheel)

    assert not [entry for entry in entries if entry.startswith(ASSET_PREFIXES)]
    assert "prompts/task-prompt.md" not in entries

    root = _unpack_wheel(wheel, tmp_path / "site-packages")
    check = _toolkit_root_check(monkeypatch, root)

    assert check.status == doctor.FAIL
    assert check.detail == (
        f"{root} (missing: prompts, scripts, agent-configs, agents)"
    )


# ---------------------------------------------------------------------------
# Purity: the build writes nothing into the toolkit tree and is location-independent
# ---------------------------------------------------------------------------


def test_build_is_location_independent_and_writes_nothing_to_the_tree(
    distribution: Distribution, tmp_path: Path
) -> None:
    """Metamorphic + purity: only the output dir differs, so only the output dir changes."""
    before = _git_state()

    completed, out_dir = _build(tmp_path / "again")
    _require_success(completed, out_dir)

    second_wheel = _single(out_dir, ".whl")
    second_sdist = _single(out_dir, ".tar.gz")
    assert _wheel_entries(second_wheel) == distribution.wheel_entries
    assert _sdist_entries(second_sdist) == distribution.sdist_entries
    # The build must not touch the tree it packaged (no generated files, no rewrites).
    assert _git_state() == before


# ---------------------------------------------------------------------------
# Seeded property run: bundling is "tracked file under the three dirs", both directions
# ---------------------------------------------------------------------------

#: Pinned seed and run count (AGENTS.md "Tests": pytest only, no ``hypothesis``, so a
#: reproducible sample is the generator and there is no shrinking).
PACKAGING_PROPERTY_SEED = 8101
PACKAGING_PROPERTY_RUNS = 40
PACKAGING_PROPERTY_SAMPLE = 6


def test_bundling_property_is_the_three_tracked_asset_dirs(
    distribution: Distribution,
) -> None:
    """Seeded property run (seed/runs pinned above): payload == the three asset dirs.

    For every sampled git-tracked path outside ``aidw/``:

    * the **sdist** carries it (Requirement 4's premise: hatchling ships the tracked tree,
      which is why the wheel can be assembled from the sdist at all);
    * the **wheel** carries it exactly when it lives under one of the three force-included
      dirs — never a subset (the missing-assets bug) and never an extra (Requirement 3);
    * when it is carried, the wheel bytes equal the checkout's — bundling is a verbatim
      copy, so the shipped prompts and scripts cannot drift from the tested ones.
    """
    candidates = sorted(rel for rel in _tracked_files() if not rel.startswith("aidw/"))
    assert candidates

    wheel = set(distribution.wheel_entries)
    sdist = set(distribution.sdist_entries)
    rng = random.Random(PACKAGING_PROPERTY_SEED)

    with zipfile.ZipFile(distribution.wheel) as archive:
        for case in range(PACKAGING_PROPERTY_RUNS):
            for rel in rng.sample(candidates, PACKAGING_PROPERTY_SAMPLE):
                label = (case, rel)
                bundled = rel.startswith(ASSET_PREFIXES)

                assert rel in sdist, label
                assert (rel in wheel) is bundled, label
                if bundled:
                    assert archive.read(rel) == (PROJECT_ROOT / rel).read_bytes(), label
