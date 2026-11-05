# Build Results — 00-E6.3: Freeze test (the D5 guard)

**Branch:** `00-E6.3`
**Date:** 2026-11-05
**Spec:** `docs/migration/EXTRACTION.md` §2 (locked decision D5), §3.9 (persisted GitHub contracts — freeze semantics), §3.12 (repo layout authority), §5.4 (verification at every step — the "no-regression" check)

## Summary

**Purpose:** Add the executable D5 guard — a golden test asserting that a Mythical-Forge-shaped config resolves to marker strings, label definitions, comment bodies and role names that are byte-identical to the `baseline-verbatim` tag, so that "no currently-persisted string in GitHub changes" is enforced by CI rather than by review.

| Decision | Why it matters |
|----------|---------------|
| The oracle is the tag, never the working tree (`git show baseline-verbatim:prompts/scripts/review-followup/constants.py`, exec'd into a fresh module namespace) | The current `constants.py` is the thing under test; comparing it to itself would make the golden vacuous. Only the tagged verbatim copy is an independent oracle. |
| Marker **templates** are pinned as well as one rendering, recovered by self-substitution (`baseline.parent_marker("{pr_url}")`) | Byte-identity on a single probe passes for a pre-rendered literal that breaks every real PR. Pinning the template is the assertion that has teeth. |
| Values are compared, never source text | E6.1 legitimately rewrote the current file (module-level templates, new docstrings), so the two files are not byte-identical by design. Frozen surfaces are values, not source. |
| Both the resolved path (`resolve_config(TargetConfig(schema_version=1))`) and `TOOLKIT_DEFAULTS.github` are pinned against the baseline | The config-less fallback/handoff default is itself a frozen surface (D17: toolkit defaults *are* Mythical Forge's values); pinning only the resolved path would let the default drift. |
| A missing `baseline-verbatim` tag raises, never skips or xfails | A silent skip disables the D5 guard exactly where it matters. The failure mode this test exists to prevent is orphaned parents and duplicate issue creation. |
| `.github/workflows/ci.yml` fetches full history (`fetch-depth: 0`) | The tag is the root commit, so the default shallow, tagless clone in CI makes `git show baseline-verbatim` fail — locally the tag exists and the golden passes while CI goes red. Req 7 must land with the test. |
| The golden lives under repo-root `tests/`, not `prompts/scripts/review-followup/tests/` | That tree is stdlib-only and copied into other repos; it can import neither `aidw.target_config` nor run `git show` (§3.12). |

**Where it fits in the roadmap:** Final task of epic **E6** (extraction of the toolkit from Mythical Forge). It depends on **E6.1**, which moved the frozen marker and label literals into config with frozen defaults (`github.markers.*`, `github.labels.*`), and on **E6.2**'s matching semantics. It is the verification half of the extraction's contracts epic: §5.4's no-regression check made executable, protecting D5 across every later refactor of the config plumbing.

**Scope:** One new repo-root test module (8 tests) that reads the `baseline-verbatim` tag and asserts byte-identity across every surface §3.9 freezes: three marker templates plus their rendered output, six labels × name/colour/description, three comment bodies, five role-name constants, and `TOOLKIT_DEFAULTS.github` directly. The only non-test change is the `actions/checkout` `fetch-depth: 0` in `.github/workflows/ci.yml`. It deliberately stops short of: documenting the freeze (`docs/target-repo-config.md`, E6.4), any change to E6.1's config plumbing or E6.2's `test_matching_semantics.py`, bucket-(i) prompt byte-identity (MF.2's concern), and re-deriving frozen values from a new source.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_baseline_verbatim_golden.py` | Created | The D5 freeze golden: loads the tagged baseline `constants.py` by bytes into a fresh namespace, loads the current file by path under a distinct module name, and asserts byte-identity of the three marker templates and renderings, all six label definitions, the three comment bodies, five role-name constants, and `TOOLKIT_DEFAULTS.github` — failing loudly when the tag is absent. |
| `docs/task-prompts/00-E6.3-prompt.md` | Created | Task brief for this task (written by the task-prompt stage). |
| `.github/workflows/ci.yml` | Modified | Adds `fetch-depth: 0` (with its rationale comment) to the `actions/checkout` step so the `baseline-verbatim` root-commit tag exists when CI runs `uv run --frozen pytest`. |
| `docs/tasks/00 - Extraction.md` | Modified | Traceability stage: ticks **E6.3** complete in the 00-Extraction roadmap. |

---

## Verification Results

All gate rows below were run once, in this recording, against the working tree at commit `6f23eb7` + the uncommitted change set described above. `aidw gate run` reported tree id **`2eef0882d0f6`** for every gate.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.46ms` (lockfile in sync, no resolution) |
| Build | `uv build --out-dir $(mktemp -d)` | ✅ `Successfully built aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` |
| Test / suite | `uv run --frozen aidw gate run suite $SCOPE -- uv run --frozen pytest` | ✅ `1449 passed in 26.81s` — gate `suite`, tree `2eef0882d0f6`, stage `record-implementation-results`, 2026-11-05T06:17:31Z |
| Doctor | `uv run --frozen aidw gate run doctor $SCOPE -- uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` — the two warnings are the expected `dirty working tree` and `missing .mcp.json`; gate `doctor`, tree `2eef0882d0f6`, 2026-11-05T06:17:36Z |
| Agents validate | `uv run --frozen aidw gate run agents-validate $SCOPE -- uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents-validate`, tree `2eef0882d0f6`, 2026-11-05T06:17:39Z |
| Prompts check | `uv run --frozen aidw gate run prompts-check $SCOPE -- uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts-check`, tree `2eef0882d0f6`, 2026-11-05T06:17:39Z |
| Lint | — | ❌ **unverified** — no linter, formatter or type-checker is configured in this repo (`AGENTS.md` §Gates / `design.md` §15), so there is no lint gate to run |
| Whitespace | `git diff --check` | ✅ clean (no output, exit 0) |

`$SCOPE` = `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` (the write-targets of the other stages of this workflow; nothing a gate reads is excluded).

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1449 | ✅ Pass (`1449 passed in 26.81s`, gate `suite`, tree `2eef0882d0f6`, 2026-11-05T06:17:31Z) |
| `tests/test_baseline_verbatim_golden.py` | 8 | ✅ Pass (collected via `pytest --collect-only -q` — 8 tests; all executed inside the same full-suite invocation above, which reported 0 failures, so no second run was bought) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Tag oracle readable — `git show baseline-verbatim:prompts/scripts/review-followup/constants.py` | ✅ exits 0 from this checkout (tag `d3cc1bc`, "chore: verbatim copy of aidt/ from mythical-forge@31c720af…") |
| `test_the_three_frozen_markers_are_byte_identical_rendered_and_as_templates` | ✅ pass (in the `suite` run above) |
| `test_all_six_frozen_labels_are_byte_identical_in_name_colour_and_description` | ✅ pass |
| `test_frozen_comment_bodies_and_role_names_are_byte_identical` | ✅ pass |
| `test_toolkit_defaults_github_equals_the_baseline_directly` | ✅ pass |
| `test_an_absent_baseline_tag_raises_instead_of_skipping` | ✅ pass |
| `test_the_baseline_module_never_aliases_the_current_constants` | ✅ pass |
| `test_the_mythical_forge_shaped_config_resolves_purely` | ✅ pass |
| `test_the_golden_reads_both_oracles_without_mutating_them` | ✅ pass |
| Mutation check — temporarily perturb one frozen value (a label colour, a marker character, a comment body), confirm the golden fails, revert | ❌ **unverified** — implementing it here would mutate the tree this document records, which the record stage must not do; the assertion is covered by the four byte-identity tests above |
| CI tag availability — `git show baseline-verbatim` succeeds in a fresh CI checkout with `fetch-depth: 0` | ❌ **unverified** — requires a GitHub Actions run; locally the tag is present regardless of the change, so this cannot be observed here |

---

## Deviations observed during recording

- **Gate stack.** The stage prompt's `pnpm install` / `pnpm -r lint|build|test` rows are another repo's stack; this repo is Python/uv and its `AGENTS.md` names `uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`. Those were run, plus `uv build` to fill the template's Build row. No `pnpm` command was executed.
- **CI diff shape.** The task prompt describes the CI change as "one line"; the delivered change is `fetch-depth: 0` plus a four-line comment explaining why the root-commit tag needs full history. Behaviourally it is still the single checkout option.

---

## Non-Goals (NOT implemented)

- ❌ E6.4 "Document the freeze" narrative in `docs/target-repo-config.md` (why config-with-frozen-defaults, what a rename breaks) — separate task.
- ❌ Any change to E6.1's config plumbing (`aidw/github.py` serializer, `aidw/target_config.py` defaults, the `AIDW_REVIEW_FOLLOWUP_CONFIG` handoff) or E6.2's `test_matching_semantics.py` — already delivered, left untouched.
- ❌ No bucket-(i) prompt byte-identity coverage: §5.4 also freezes resolved prompts, but that is MF.2's (Mythical Forge override) concern.
- ❌ No re-derivation of the frozen values from a new source, and no writing markers/labels/comment bodies into any prompt or doc beyond what already exists.
- ❌ No commit, push or PR opened by this stage (`prompts/pr.md` owns delivery).
