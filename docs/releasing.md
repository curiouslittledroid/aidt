# Releasing AIDT

> How a version bump becomes an installable release (D9) and how a target repo pins one
> (D10, EXTRACTION.md §3.11). The install forms live in
> [`README.md` §Install](../README.md#install); the target-repo config field contract lives in
> [`docs/target-repo-config.md`](./target-repo-config.md). This document is the **release
> process** only — it does not restate either, so there is nothing here to drift.

Two names, as everywhere in this repository: the repository and distribution are **`aidt`**, the
import package and console command are **`aidw`** (D7). A release is a **git tag** cut on merged
`main`; nothing is published to PyPI (D9, §3.11).

## What counts as a release tag

| Tag | What it is |
|---|---|
| `v<X.Y.Z>` — e.g. `v0.1.0` | A **release**. Annotated, cut on merged `main`, installable with D9's two forms below. |
| `baseline-verbatim` | **Not a release.** D8's verbatim-import marker: the single "copy `aidt/` unmodified" commit. `tests/test_baseline_verbatim_golden.py` diffs frozen GitHub strings against it, so it is never retagged, renamed, deleted, or reused as a release pin. |

Release tags carry the `v` prefix and are **annotated** (`git tag -a`); `baseline-verbatim` is
unprefixed and is history, not distribution. The two schemes are deliberately distinct.

## 1. Bump the version — three edits, in lockstep

Versions are **semantic** (EXTRACTION.md §3.11): `MAJOR.MINOR.PATCH`, and which component moves is
decided by what the change does to the contract — incompatible change, new capability, or fix —
not by how many commits landed.

There is **no dynamic versioning** (`tests/test_packaging.py::test_version_has_exactly_one_source`
pins that), so one version exists in three places, all three change in the **same commit**, and
the lockfile is re-synced with them:

| # | Site | What changes |
|---|---|---|
| 1 | `pyproject.toml` → `[project].version` | `version = "X.Y.Z"` — the metadata every wheel and sdist records. |
| 2 | `aidw/__init__.py` → `__version__` | `__version__ = "X.Y.Z"` — the in-code copy `aidw --version`, `aidw doctor` and every run's `state.json` read. |
| 3 | `tests/test_packaging.py` → `test_pyproject_identity_is_the_settled_name_version_and_script` | The hardcoded `"0.1.0"` literal became `"X.Y.Z"`. This test also asserts `project["version"] == __version__`, so it is the guard for sites 1 and 2 — but its own literal is a third site and is **not** derived from either. |

A bump that edits only one source, or forgets the test's literal, fails that test — that is the
guard working, not a flake.

The **fourth** edit is `uv.lock`: it records the project's own version
(`[[package]] name = "aidt"` → `version = "X.Y.Z"`), so a bump leaves it stale. Re-sync it in the
same commit:

```bash
uv lock            # updates the locked project version
uv lock --check    # fails now if the lock is stale; this is the gate CI's --frozen does NOT give
```

`uv sync --frozen` deliberately does not catch this — it accepts the lock as written and builds
the editable project from `pyproject.toml`, so a stale lock installs fine locally while
`uv lock --check` proves it wrong. That is why the lock edit is part of the bump, not an
afterthought.

Verify the bump locally, before the PR:

```bash
uv lock --check
uv sync --frozen
uv run --frozen pytest tests/test_packaging.py
uv run aidw --version     # prints `aidt X.Y.Z`
uv run aidw doctor        # `toolkit version` check reports X.Y.Z
```

`aidw --version` and `aidw doctor` are **the release smoke checks**: the first proves the console
script and the in-code version agree, the second proves the toolkit resolves its own root,
prompts, agent configs and the `git`/`gh`/`pi` externals. A release whose smoke checks fail is not
a release — fix it and tag again with a new version, never move the tag.

Ship the bump through the normal delivery path: one branch, one PR, review, merge to `main`.
AIDT never merges, and no stage pushes tags.

## 2. Cut the annotated tag on merged `main`

The tag is cut **after** the release commit is on `main` — the commit the PR merged, whose tree
already contains the bump and everything the PR carried (this doc included).

```bash
git switch main
git pull --ff-only
git tag -a v0.1.0 -m "AIDT v0.1.0"
git push origin v0.1.0
```

- `git tag -a` is **annotated**, not lightweight: the release tag is a released object with an
  author, date and message, which is what `git show v0.1.0` and `git describe` report.
- `v0.1.0` is the first release. Later releases use the tag matching the bumped
  `[project].version` — `v0.2.0`, `v0.2.1`, … — never a tag whose version differs from the tree's.
- The tag must be cut from a clean `main`: `git status --porcelain` empty, and `HEAD` equal to
  `git rev-parse v<X.Y.Z>^{commit}`.
- **Never tag a task branch.** A tag pushed from a branch such as `00-E8.5` pins the pre-merge
  commit: the install forms then build a tree that lacks whatever the PR still carries (for the
  first release: this document), so the release and `main` disagree while both look released.
  Branch publication and tagging are separate operations; `prompts/pr.md` pushes only the branch.

Check the tag before and after pushing it:

```bash
git show --stat v0.1.0                 # annotated tag, message, release commit
git rev-parse v0.1.0^{commit} HEAD      # the same commit
git ls-remote --tags origin v0.1.0     # after the push: the tag exists on origin
```

## 3. Verify the release — D9's two install forms, from a clean tool venv

A tag is not proven by `git tag`; it is proven by installing from it. D9 fixes two forms, and
both are pinned to the tag.

**Primary — `uv tool install`**, for an `aidw` on `PATH` for everyday use:

```bash
uv tool install "git+https://github.com/curiouslittledroid/aidt@v0.1.0"
aidw --version
aidw doctor
```

Expect `aidt 0.1.0` from `--version`, and `aidw doctor` to report `toolkit version 0.1.0`,
`toolkit root`, `git version`, `prompts` and `agent configs` as `ok`. (Run `doctor` from a
bootstrapped workspace's control worktree — the workspace/layout checks describe that layout, not
an arbitrary directory.)

**Secondary — `uvx`**, a one-off run with nothing installed:

```bash
uvx --from "git+https://github.com/curiouslittledroid/aidt@v0.1.0" aidw --version
```

`--from <git-url>` is required: a bare `uvx aidw` resolves a package named `aidw` from PyPI, which
is not this repository.

**From a clean tool venv**, so a cached build or a leftover environment cannot make an older
install look like the new tag. `uv tool install` owns its env; point uv's tool and cache
directories at a throwaway location and run the primary form against it:

```bash
UV_TOOL_DIR=/tmp/aidt-release-check/tools \
UV_TOOL_BIN_DIR=/tmp/aidt-release-check/bin \
UV_CACHE_DIR=/tmp/aidt-release-check/cache \
  uv tool install "git+https://github.com/curiouslittledroid/aidt@v0.1.0"

/tmp/aidt-release-check/bin/aidw --version
/tmp/aidt-release-check/bin/aidw doctor   # from a control worktree, as above
```

The same form works against a **local** git URL, which is how the documented sequence is proven
before the first release tag exists — cut a throwaway tag in a scratch clone of the release commit
and install from it with `git+file:///path/to/scratch-clone@v0.1.0` in place of the GitHub URL.
That exercises the tag, the build backend and the console script end-to-end without pushing
anything.

If any step fails, do **not** move or re-push the tag. Fix the tree, bump the version, merge, and
cut the next `v<X.Y.Z>`: a published tag is immutable history.

## 4. Target repos: pin, and upgrade deliberately

A target repo declares the release it was verified against in its tracked
`aidw/config.yaml` (D10/§3.11):

```yaml
schema_version: 1
requires_toolkit: ">=0.1.0"
```

- `requires_toolkit` is an optional **PEP 440 specifier** compared with
  [`packaging`](https://packaging.pypa.io/) against this toolkit's own version, in
  `aidw/target_config.py:check_compatibility`. The documented shape is a lower bound
  (`">=X.Y.Z"`); it is a specifier, so `">=0.1.0,<0.3"` and friends are legal, and a bare
  `0.1.0` is not the pin form.
- **Two independent refusals, not one.** `requires_toolkit` is compared against
  `aidw.__version__`; `schema_version` is an **integer** compared against
  `SUPPORTED_SCHEMA_VERSION`. `schema_version` describes the config file's shape, not the
  toolkit release, so it is not the version pin and changing it is not an upgrade. Both rules are
  evaluated in `check_compatibility`, and a config can violate both.
- Every field, default, and the "Unset, not defaulted" rule for these two keys live in
  [`docs/target-repo-config.md`](./target-repo-config.md#top-level) — read it there; this
  document does not copy the table.

**The refusal.** When the specifier is unsatisfied or unparseable, the toolkit refuses to run
(§3.11). `aidw doctor`'s `compat status` check carries the verdict and fails closed (non-zero
exit); at a target with `requires_toolkit: ">=99.0.0"` it reports:

```text
[ fail ] compat status     error: config.yaml: `requires_toolkit` '>=99.0.0' is not satisfied by this toolkit's version 0.1.0; upgrade `aidt` to a version matching '>=99.0.0', or relax the pin in `config.yaml`.
```

The `error: <config file>: ` prefix is the issue's source; the rest is
`check_compatibility`'s message. An invalid specifier is refused with an actionable message
rather than a traceback:

```text
[ fail ] compat status     error: config.yaml: `requires_toolkit` 'not-a-spec' is not a valid version specifier; use a PEP 440 specifier such as ">=1.0.0", or upgrade `aidt`.
```

**Upgrade deliberately.** The pin is a claim about testing, so it moves only after the new
toolkit has been tested:

1. Install the newer release with the primary form, pinned to its own tag.
2. In the target repo, run `aidw doctor` and read `compat status` — it compares the new
   `aidw.__version__` with the pin and reports the verdict (and names the field when it refuses).
3. Run the workflows and gates you rely on against the new toolkit. Only after they pass, bump
   `requires_toolkit` to the release you just verified, in the commit whose code depends on it.
4. Never bump the pin first and hope: an untested pin turns `aidw doctor` from a compatibility
   report into a claim nobody checked, and it hides the upgrade behind a passing check.

A target repo that leaves `requires_toolkit` unset expresses no constraint and gets no
compatibility verdict from the pin (it still gets the `schema_version` check). That is a
deliberate choice to track the toolkit, not a default that happens to work: the pin is how a repo
records the release it was verified against, so it is what a repo depending on the toolkit should
carry.

## Checklist for a release

- [ ] Version bumped in all **three** sites, in one commit, semver per §3.11.
- [ ] `uv.lock` re-synced (`uv lock`) and committed with the bump; `uv lock --check` green.
- [ ] `uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor` green on the release
      commit; PR merged to `main`.
- [ ] `aidw --version` + `aidw doctor` pass locally from the checkout.
- [ ] Annotated `v<X.Y.Z>` tag cut on clean, up-to-date `main`, pointing at the release commit.
- [ ] Tag pushed; `git ls-remote --tags origin v<X.Y.Z>` confirms it.
- [ ] Primary `uv tool install` and secondary `uvx --from` forms verified from a clean tool venv;
      `aidw --version` reports the bumped version.
- [ ] `baseline-verbatim` untouched.

## Related documents

- [`README.md` §Install](../README.md#install) — the operator-facing install forms.
- [`docs/target-repo-config.md`](./target-repo-config.md) — `schema_version`, `requires_toolkit`
  and every other config field.
- [`docs/migration/EXTRACTION.md`](./migration/EXTRACTION.md) §3.11 (version and compatibility,
  D10), §2 (locked decisions: D8 the verbatim tag, D9 distribution, D10 the version pin), §3.12
  (repo layout).
- `aidw/target_config.py:check_compatibility` — the §3.11 refusal, and
  `tests/test_target_config.py` / `tests/test_doctor.py` — its contract tests.
