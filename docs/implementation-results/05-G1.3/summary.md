# Summary — G1.3: Resolve `Design N` citations against a repo-declared spec directory

## 1. The problem it was solving

G1.2 gave `aidw prompt` a preflight that checks every spec section a roadmap entry cites before
the authoring stage is paid for. It did so on two assumptions taken from this repository's own
layout: that `Design N` means section `N` of a root `design.md`, and that the doc-ref channel
points at a single, uniquely locatable `<NAME>.md`. A target whose specs are one document per
design number — the normal authored-content layout, and Mythical Forge's — satisfies neither.
Over Mythical Forge's 299 roadmap entries, the build results record, all 45 distinct `Design N`
citations resolve to one file, and correcting only the file mapping still left 235 entries
failing on the section rule. The practical consequence was that no entry of such a repo could
pass the G1.2 preflight: a legitimate spec layout was being refused for a root `design.md` the
repo never had.

This is the final task of Epic G1 ("Prompt review depth"). It follows G1.2, whose preflight it
extends, and G1.1, whose finding classification it reuses. It supersedes the document assumption
recorded as decision Z19 only for repos that declare the new key.

## 2. The core idea

The fix is a configuration key, not a second parser dialect. A target may now declare an
optional `paths.specs_dir` holding numbered spec documents; when it does, `Design N` resolves
to the one flat file in that directory whose name carries the `Design <number> - ` prefix,
compared canonically. When the key is unset — which stays the default and the valid case — the
`Design N` channel behaves byte-identically to G1.2.

That the key is *unset rather than defaulted* is the decision the rest of the work follows from.
Seeding a repo-relative default would silently change every repo's citation contract, which is
exactly the "second per-repo dialect" design §1/D15 forbids; keeping it absent means a repository
whose specs are one root `design.md` sees no change at all, and the existing `READ_PATH_FILES`
fixtures and their gap pins pass unrebaselined. The second load-bearing choice is that
`specs_dir` is neither a read-path nor a write-target: absence is legitimate, so `validate_paths`
must never fail it, and the diagnosis is an advisory `aidw doctor` warning rather than a `FAIL`
or an exit-code decision. A third, subtler choice follows from the same reasoning: claims are
enumerated per *occurrence*, not per unique token, so an entry that cites the same design number
twice with different sections, or once bare and once with a section, has every occurrence's
window checked while the `(document, section)` pair — not the token — is what gets deduped.

## 3. What was built, piece by piece

**The config key and its resolver.** `aidw/target_config.py` gains `PathsConfig.specs_dir` and
its `PATH_FIELDS` entry, deliberately with no `TOOLKIT_DEFAULTS` entry (mirroring
`agent_configs_dir`) and deliberately in neither `READ_PATHS` nor `WRITE_TARGETS`; the module
docstring carries the rationale for that third class. The JSON schema and
`docs/target-repo-config.md` document the same shape, including the explicit "neither a
read-path nor a write-target" paragraph. `aidw config show` reports the new leaf with its
`unset`/`config` provenance like the other `paths.*` leaves.

**The spec-document resolver.** In `aidw/workflows/prompt.py`, `spec_document_number` built on
`_SPEC_DOCUMENT_RE` (`^Design (\d+(?:\.\d+)?) - `) is *the* filename rule — one named predicate,
not a doctor-local glob and not a second regex. `_spec_document_matches` scans `specs_dir` flat
with no recursion, so `Design 04` resolves `Design 4 - …` while `Design 20` never matches
`Design 20.1 - …`; both comparisons go through the existing `_canonical_number`. Zero or several
candidates produce a gap naming the resolved directory and the reason, and there is no fallback
to a root `design.md`.

**The citation-window enumeration.** `_cited_specs` was rewritten around a single merged token
scan (`_citation_tokens`) covering both channels, with each citation's window measured to the
next token of *either* channel (`_citation_window`, `_design_window`,
`_specs_mode_citations`). Two separate scans would misassign a `§` that follows a `Design N`
yet precedes an `<NAME>.md` token; one scan settles that boundary once. Because the scan steps
token by token rather than over a deduped token list, each occurrence keeps its own window: an
entry citing `Design 11 §5.3` and then `Design 11 §5` yields two distinct pairs, and no pair is
checked twice however often it is cited. A `§5.3A` token is checked as `5.3` and never reported
in lettered form: `_SECTION_RE` was deliberately not extended to capture letters, because a
lettered sub-part is a deeper heading in one spec and a plain list label in another, and no
deterministic rule spans both. A bare specs-mode `Design N` is a document-level claim — the
document exists and holds at least one non-blank, non-heading line (`_document_has_content`, the
analogue of `_section_state`) — never a `## N` heading.

**Gaps, remedy and evidence bundle.** `_spec_feasibility_gaps` gains the document-mode branch,
every gap naming the resolved path and its reason. `_refuse_spec_gaps` appends a
`paths.specs_dir` remedy line only when the cause is no `specs_dir` and no root `design.md`; a
section gap inside a present document already names its own repair, and a remedy line on every
refusal would be noise. `specs_dir` is threaded into `_render_cited_specs`,
`_render_evidence_bundle` and the preflight exactly as `roadmap_dir` is, so the `P2` bundle
prints the resolved path and every section the preflight checked from the same enumeration and
the two cannot disagree.

**The advisory doctor check.** `aidw/doctor.py` gains a `specs dir` check that emits `WARN` —
never `FAIL`, never an exit-code decision — for a declared directory that is missing, is not a
directory, or holds no numbered spec document, and for none declared while no root `design.md`
exists; it reports `OK` for a healthy specs directory or a root `design.md`. It imports
`spec_document_number` from the prompt workflow rather than growing a second rule, so the
diagnosis sees exactly what the preflight sees.

**The recorded decision and the drift pins.** `design.md` §8.1 and §12.1 gain the key and §17
records the decision as row **Z22** (appended, never reusing a number); `docs/roadmap-format.md`
§8.1 states where `N` resolves now. Six test files carry the coverage: the specs-mode cases sit
beside the untouched `READ_PATH_FILES` fixtures rather than replacing them, and include the
repeated-token window case and the bare-occurrence-beside-a-sectioned-one case. The config and
docs drift pins were re-baselined (`EXPECTED_DEFAULTS["specs_dir"]="unset"` and both `paths.*`
leaf lists), and `tests/test_doctor.py` pins the shared predicate with a directory holding only
non-conforming filenames (`notes.md`, `Design draft.md`), so a laxer doctor-local rule fails.

## 4. What it deliberately did not do

A configurable filename template for spec documents was rejected as a second per-repo dialect
(design §1/D15) — the roadmap Notes say so explicitly, and the fixed `Design <number> - `
prefix is what keeps one rule in one place.

No stub root `design.md` was added to a target repo to paper over the mismatch; the roadmap Notes
forbid that workaround, and it would hide rather than resolve the layout difference.

The `<NAME>.md` doc-ref channel keeps its existence-only bare-ref contract. Only its window
boundary changed, through the shared enumerator; the byte-identity guarantee belongs to the
`Design N` channel.

The one target-side change this work implies — adding `paths.specs_dir: docs/specs` to Mythical
Forge's `aidw/config.yaml` — is outside this branch and was not made. That is why the
target-repo exercise below is recorded as unverified rather than as a pass.

Epic B1 ("Batch fixes") is deliberately not started: Epic G1 ends at G1.3. And no edit was made
to `docs/tasks/*.md` here — the roadmap checkbox belongs to the roadmap-update stage — nor was
any commit, push or pull request made, which the delivery stage owns.

## 5. Verification

The build results record the repository's verification gate over the current tree, identified as
`2efae543353d`.

`uv sync --frozen` succeeded (`Checked 19 packages in 1ms`). `uv run --frozen aidw doctor`
succeeded with exit 0 and `24 checks: 0 failed, 2 warning(s)` — the two warnings being a dirty
working tree on this branch and a missing `.mcp.json` — with the new `specs dir` check reporting
that `paths.specs_dir` is unset and `Design N` resolves against the root `design.md`.
`uv run --frozen aidw agents validate --strict` succeeded (11 configs, 0 errors, 0 warnings),
`uv run --frozen aidw prompts check` succeeded (0 errors, 0 warnings), and `git diff --check`
reported no whitespace problems. No build gate exists in this repo and none was invented: the
project conventions declare no build command, so that row is recorded as not applicable.

The test gate **passed**: the full suite ran 2558 tests and all of them passed in 55.88s. The
build results cite that outcome from the gate store rather than re-running it — `reused: gate
'suite' passed for tree 2efae543353d at 2026-11-22T02:50:20Z by stage 'update-traceability'` —
against content differing only within the recording scope. The task-specific rows follow from
the same gate: the `specs dir` check is advisory only (exit 0, no failed checks), the config and
docs drift pins passed, and the G1.3 specs-mode prompt-workflow tests passed, cited from `gate
g13: passed (tree 2efae543353d, stage test, 25 passed, 734 deselected)` with the formerly failing
case also passing alone (`gate smoke: passed`, 1 passed, 292 deselected).

That formerly failing case deserves restating as the build results state it, because it is the
one outcome with a history. An earlier recording of the same stage observed `1 failed, 2556
passed` on tree `e241ed5eba82`, the failure being
`tests/test_prompt_workflow.py::test_g13_repeated_same_design_token_uses_each_token_window`,
where the `§5` window of a repeated `Design 11` token was not enumerated. The tree has since
advanced to `2efae543353d`, whose own recorded gates show that test passing both alone and in
the full suite. The build results state plainly that the recording stage neither caused nor fixed
that change — it modified no source, test or spec file — and that the pass recorded now is the
gate store's observation of the tree as it stands, not a re-run staged to overwrite the earlier
failure.

One task-specific row remains **unverified**: exercising `paths.specs_dir` against Mythical
Forge. It needs `paths.specs_dir: docs/specs` added to that repo's `aidw/config.yaml`, which is
outside this branch, and no target repo was touched by the recording stage.

One further deviation is recorded and worth restating plainly: the change set is uncommitted.
`main..HEAD` carries only the task-prompt commit, with all implementation, test and document
changes as working-tree modifications, which is why the tree identity above was computed from
the working tree relative to `main`.
