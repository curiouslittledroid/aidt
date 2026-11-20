# Integration Test Guide — G1.1: Finding classification (`spec-gap` / `prompt-gap`)

## 1. What this guide covers

This is a **hand-run** procedure for branch `05-G1.1`, which teaches the prompt-review loop
(`aidw prompt`, stage `P2`) to classify each reviewer finding as `spec-gap` or `prompt-gap` and
to stop fail-closed — run `blocked`, exit 3, gate `approve-task-prompt` recorded `denied` with
mechanism `spec-gap` or `unclassified` — instead of paying a fix stage for a defect only the
cited spec or roadmap can close. It walks the surfaces the change actually touches: the
`prompts/task-review.md` / `agents/task-reviewer/AGENTS.md` contract, the `aidw/findings.py`
parser and its unchanged published manifest, the `aidw/workflows/prompt.py` classification stop
and its `--resume` refusal, and the delta-brief shrink in `aidw/stage_registry.py`. Nothing in
this document was executed by the toolkit: the commands are for you to run, in your environment,
with your credentials.

## 2. Scenarios

### 2a. Repository tooling (existing gates)

#### A1 — The reviewer prompt requires `Kind:`

1. **Prerequisites** — a checkout of this branch with the dependencies installed (`uv sync
   --frozen` once, as recorded in the build results). No credentials.
2. **Command(s) or steps** — read `prompts/task-review.md` around the finding format, then run:

   ```bash
   uv run --frozen aidw prompts check
   ```

3. **Expected observable result** — `prompts/task-review.md` shows a `Kind: spec-gap /
   prompt-gap` line inside the finding block, a one-line definition of each value, and the
   "keep the labels plain" sentence extended to name `Kind:`. The command prints
   `resolved repo prompts: 0 error(s), 0 warning(s)` and exits 0.
4. **How to tell pass from fail** — pass requires **both** the file content above **and**
   `0 error(s), 0 warning(s)`. An `error` line, a non-zero exit, or a `Kind:` line that is
   missing or bold/backticked in the format block is a fail.
5. **Cost, permission or destructive warning** — none (read-only check over the repo's prompts).

#### A2 — The reviewer agent context mirrors `Kind:` and stays read-only

1. **Prerequisites** — as A1.
2. **Command(s) or steps** — read `agents/task-reviewer/AGENTS.md`, then run:

   ```bash
   uv run --frozen aidw agents validate --strict
   ```

3. **Expected observable result** — the `## Output` section lists `kind` among the finding
   fields and states that a finding without a valid `Kind:` is not a complete review. The
   command prints `11 agent config(s): 0 error(s), 0 warning(s)` and exits 0.
4. **How to tell pass from fail** — pass is `0 error(s), 0 warning(s)` **and** a
   `task-reviewer` entry that has not gained write tools; a new `error`, a `--strict` warning,
   or any write tool added to `task-reviewer` (it must remain in `READ_ONLY_AGENTS`) is a fail.
5. **Cost, permission or destructive warning** — none.

#### A3 — Traceability docs still match the code

1. **Prerequisites** — as A1.
2. **Command(s) or steps** — this exact trio was recorded as passing in the build results
   (17 tests, gate run `traceability`):

   ```bash
   uv run --frozen pytest tests/test_design_doc.py tests/test_workflow_stages_doc.py tests/test_target_repo_config_doc.py
   ```

3. **Expected observable result** — all three files collect and pass; no `assert` failure
   naming a §17 row, a `P2` row in `docs/workflow-stages.md`, or a `paths.*` field.
4. **How to tell pass from fail** — pass requires the `N passed` line with `failed`/`error`
   absent. A failure naming a design row, the stages table or the config doc means an edit
   drifted from its code; do not "fix" the test.
5. **Cost, permission or destructive warning** — none.

#### A4 — The focused behaviour suites

1. **Prerequisites** — as A1.
2. **Command(s) or steps** — the build results record these as covered inside the single full
   `uv run --frozen pytest` run (2446 passed, cited from gate run `suite`); to watch them
   directly:

   ```bash
   uv run --frozen pytest tests/test_findings.py tests/test_prompt_workflow.py tests/test_stage_registry.py tests/test_prompt_classification.py
   ```

3. **Expected observable result** — collected tests pass, including ones whose names mention
   `kind`/`spec_gap`/`unclassified` and the delta-brief shrink.
4. **How to tell pass from fail** — pass is a green run with no `failed`/`error` count. A
   failure in `test_g11_*`, `test_kind_*`, or the `Kind:` shrink test is a real regression; a
   failure caused by your local environment (missing `uv`, wrong Python) is not.
5. **Cost, permission or destructive warning** — none. The suite spawns temporary git repos
   under your temp directory; it does not touch your working tree or network.

### 2b. Custom CLI and library surfaces

#### B1 — `Kind:` parses, round-trips, and never enters the manifest

1. **Prerequisites** — the branch's working tree, dependencies synced. No Pi, no model, no
   credentials. The snippet uses only names added/changed by this task in `aidw/findings.py`
   (`parse_review_findings`, `_finding_text_block`, `to_manifest`, `SPEC_GAP`, `PROMPT_GAP`).
2. **Command(s) or steps** — run from the repo root:

   ```bash
   uv run python - <<'PY'
   from aidw import findings

   REVIEW = """\
   ```text
   Priority: Must fix
   Confidence: 5
   Kind: spec-gap
   What I found: The prompt requires a field the cited spec never defines.
   Why it matters: The implementer would invent a schema decision.
   Trigger and effect: Any implementation follows the invented field.
   Where: docs/task-prompts/x-prompt.md, requirement 4.
   Suggested fix: Change the spec first.
   ```

   ```text
   Priority: Could fix
   Confidence: 3
   What I found: A stale path in the deliverables.
   Why it matters: Minor confusion.
   Trigger and effect: None observable today.
   Where: docs/task-prompts/x-prompt.md, Deliverables.
   Suggested fix: Point at the current path.
   ```
   """

   parsed, problems = findings.parse_review_findings(REVIEW)
   assert problems == [], problems
   assert [f.kind for f in parsed] == [findings.SPEC_GAP, findings.PROMPT_GAP]

   # `Kind:` is optional at parse level: no kind, no problem.
   plain, plain_problems = findings.parse_review_findings(REVIEW.replace("Kind: spec-gap\n", ""))
   assert plain_problems == [] and plain[0].kind == ""

   block = findings._finding_text_block(parsed[0])
   assert "Kind: spec-gap" in block
   assert findings.parse_review_findings(block)[0][0].kind == findings.SPEC_GAP

   manifest = findings.to_manifest(parsed)
   assert all("kind" not in entry for entry in manifest["findings"])
   print("parser, re-emitter and manifest shape: OK")
   PY
   ```

3. **Expected observable result** — the script prints `parser, re-emitter and manifest shape:
   OK` and exits 0.
4. **How to tell pass from fail** — pass is that exact line and exit 0. An `AssertionError`
   naming `problems`, `kind`, `Kind: spec-gap`, or `kind` inside a manifest entry is a fail, and
   so is a traceback (which would mean the snippet no longer matches the tree — re-read
   `aidw/findings.py` rather than editing it).
5. **Cost, permission or destructive warning** — none; in-memory only, writes no files.

#### B2 — The classification stop's precedence

1. **Prerequisites** — as B1. The snippet uses `aidw.workflows.prompt.classification_stop` and
   its two mechanism constants, both added by this task. Note this exercises the pure decision
   function, **not** the whole stage loop (that is B5 and is not deterministic).
2. **Command(s) or steps**:

   ```bash
   uv run python - <<'PY'
   from aidw.findings import parse_review_findings
   from aidw.workflows.prompt import classification_stop

   def block(kind_line: str, what: str) -> str:
       lines = ["```text", "Priority: Must fix", "Confidence: 5"]
       if kind_line:
           lines.append(kind_line)
       lines += [
           f"What I found: {what}",
           "Why it matters: It matters.",
           "Trigger and effect: Always.",
           "Where: docs/task-prompts/x-prompt.md.",
           "Suggested fix: Fix it.",
           "```",
       ]
       return "\n".join(lines)

   # An unclassified finding beats a spec-gap finding.
   both, _ = parse_review_findings(block("", "no kind") + "\n\n" + block("Kind: spec-gap", "a spec gap"))
   assert classification_stop(both)[0] == "unclassified", classification_stop(both)

   # A spec-gap finding wins over a prompt-gap finding.
   gap, _ = parse_review_findings(block("Kind: prompt-gap", "p") + "\n\n" + block("Kind: spec-gap", "s"))
   assert classification_stop(gap)[0] == "spec-gap", classification_stop(gap)

   # An unrecognised kind is unclassified.
   odd, _ = parse_review_findings(block("Kind: nope", "n"))
   assert classification_stop(odd)[0] == "unclassified", classification_stop(odd)

   # Only prompt-gaps: no stop, so the existing fix loop runs.
   none, _ = parse_review_findings(block("Kind: prompt-gap", "p"))
   assert classification_stop(none) is None, classification_stop(none)

   print("classification precedence: OK")
   PY
   ```

3. **Expected observable result** — prints `classification precedence: OK`, exit 0.
4. **How to tell pass from fail** — pass is that line and exit 0. Any `AssertionError` on a
   mechanism value is a fail; in particular a result of `review-loop` for a spec-gap would
   re-arm the `--resume` fix cycle this task removes.
5. **Cost, permission or destructive warning** — none.

#### B3 — The delta-brief shrink keeps `Kind:`

1. **Prerequisites** — as B1. Uses `aidw.stage_registry.render_delta_brief` (keyword-only
   `previous_review`, `diff`), the shrink path the task prompt names as the trap for a dropped
   classification.
2. **Command(s) or steps**:

   ```bash
   uv run python - <<'PY'
   from aidw import stage_registry
   from aidw.findings import _finding_text_block, parse_review_findings

   REVIEW = """\
   ```text
   Priority: Must fix
   Confidence: 5
   Kind: spec-gap
   What I found: The prompt requires a field the cited spec never defines.
   Why it matters: The implementer would invent a schema decision.
   Trigger and effect: Any implementation follows the invented field.
   Where: docs/task-prompts/x-prompt.md, requirement 4.
   Suggested fix: Change the spec first.
   ```
   """

   parsed, _ = parse_review_findings(REVIEW)
   previous = _finding_text_block(parsed[0]) + "\n" + ("reviewer context " * 200)
   brief = stage_registry.render_delta_brief(previous_review=previous, diff=None)
   assert "Kind: spec-gap" in brief
   assert parse_review_findings(brief)[0][0].kind == "spec-gap"
   print("delta brief preserves Kind: OK")
   PY
   ```

3. **Expected observable result** — prints `delta brief preserves Kind: OK`, exit 0.
4. **How to tell pass from fail** — pass is that line and exit 0. If the brief is missing
   `Kind:` or re-parses with an empty `kind`, a shrunk previous review would silently lose the
   classification — a fail, even if the rest of the brief looks right.
5. **Cost, permission or destructive warning** — none.

#### B4 — `aidw prompt --dry-run` still plans the same loop

1. **Prerequisites** — the branch's dependencies synced; the working tree state you are
   testing. `--dry-run` needs no clean tree and no Pi, so it works from `05-G1.1`. The task must
   resolve in the target repo's roadmap phase file (directory `paths.roadmap_dir`, filename
   matched by `paths.roadmap_glob`).
2. **Command(s) or steps** — confirm the task resolves, then plan:

   ```bash
   uv run aidw tasks --show "05 G1 G1.1"
   uv run aidw prompt 05 G1 G1.1 --dry-run
   ```

3. **Expected observable result** — `aidw tasks --show` prints the `G1.1` entry (title, branch
   `05-G1.1`, "Done when", cited specs). The dry run prints the planned stages including
   `task-prompt` and `task-review-1` with a `(planned)` marker, ends with
   `dry-run complete; Pi not invoked`, and returns exit 0. No run is created under the state
   root and no worktree is added.
4. **How to tell pass from fail** — pass requires the plan to name `task-prompt` then
   `task-review-1`, the `Pi not invoked` line, exit 0, and **no** new entry from
   `uv run aidw runs list`. A Pi invocation, a created branch/worktree, a config error, or a
   plan that omits either stage is a fail.
5. **Cost, permission or destructive warning** — none expected; `--dry-run` performs no writes
   and no network fetch. If you see anything written, stop — that is the failure, not a cost.

#### B5 — A real run stops on a `spec-gap` finding (model-dependent)

1. **Prerequisites** — `pi` installed and authenticated, and a **control worktree on the
   configured base branch (`repo.base_branch`) with a clean working tree**, because a real
   `aidw prompt` run refuses otherwise (exit 4). A roadmap task whose prompt genuinely contains
   a defect only the cited spec or roadmap can close, and a target repo whose
   `paths.*` read-paths exist. This spends model tokens.
2. **Command(s) or steps** — from the control worktree:

   ```bash
   uv run aidw prompt 05 G1 G1.1 --require-approval
   uv run aidw runs list
   uv run aidw runs show <run-id printed above>
   ```

   Use the real run's id in place of `<run-id>`. (Marked **unconfirmed as a deterministic
   recipe**: the reviewer is a model, so whether it emits `Kind: spec-gap` cannot be forced
   from a command. The deterministic proof of the same path is A4's
   `tests/test_prompt_workflow.py`.)
3. **Expected observable result** — the run stops after `task-review-1` (no
   `task-review-fixes-*`, no `task-review-reconcile-*` stage); stderr carries a headline
   containing `spec-gap` followed by each offending finding in the reviewer's block format with
   its `Kind: spec-gap` line; the process exits 3. `aidw runs show` prints `status: blocked` and
   `gate approve-task-prompt: denied (spec-gap)`. The prompt file in the task worktree is left
   uncommitted.
4. **How to tell pass from fail** — pass requires all of: exit 3, no fix/reconcile stage in
   the run's stage list, `mechanism` exactly `spec-gap` (not `review-loop`), the finding text
   on stderr, and an uncommitted prompt. A `denied (review-loop)` gate, a fixer stage, or an
   exit 0 means the short-circuit did not fire — a fail.
5. **Cost, permission or destructive warning** — **costs model spend** for the author and
   review stages; needs a clean base-branch control worktree; creates a task branch and a git
   worktree and, if it ever approves, commits the prompt. Do not run it against a task whose
   prompt you are not prepared to have rewritten in its own worktree.

#### B6 — `--resume` refuses a classification block

1. **Prerequisites** — a blocked run produced by B5 whose gate mechanism is `spec-gap` (or
   `unclassified`), still present under the state root. The task worktree must still exist.
2. **Command(s) or steps**:

   ```bash
   uv run aidw prompt 05 G1 G1.1 --resume
   ```

3. **Expected observable result** — the command exits 3 with a recorded reason that names the
   `approve-task-prompt` gate and its classification mechanism (wording of the form "denied by
   the task review's finding classification (mechanism `spec-gap`)"). It offers no fix cycle
   and re-runs no review round.
4. **How to tell pass from fail** — pass is exit 3 **and** a printed reason naming the
   classification mechanism. A resumed fix batch, a new `task-review-fixes-*` stage, or an exit
   0 is a fail: it is the behaviour this task exists to remove.
5. **Cost, permission or destructive warning** — none if it refuses as expected (no model is
   invoked). If it does **not** refuse, stop the run: it would spend tokens and rewrite the
   prompt.

### 2c. Browser UI flows

None. No changed file, build-results row or task-prompt statement in this task names a route, a
screen or a browser-rendered surface, so there is no browser scenario to walk.

### 2d. External actions (cloud provider, deployed stack)

None. The change is confined to the toolkit's prompt-review logic and its prompt/agent files;
no changed file or build-results row names a cloud account, role, bucket, ARN or deployed
endpoint, so there is no external-action scenario to walk.

## 3. Teardown

- **No scenario requires teardown for B1–B4**: they are in-memory checks, read-only gates and a
  `--dry-run` that creates no run and no worktree. If B4 did create a run or a worktree, that is
  the failure signal — remove it deliberately and record it:
  `uv run aidw worktree list` (inspect) and `uv run aidw worktree remove <branch>` (remove only
  the worktree that run created — it refuses a dirty tree or an unmerged branch unless
  `--force`, so read the refusal before overriding it), then delete that run's directory under
  the state root printed by `uv run aidw config show`.
- **B5/B6**: delete the run directory under `<state root>/<repo-slug>/runs/<run-id>/` and remove
  the task worktree the run created **only after** confirming it has no uncommitted work you
  need (the blocked run leaves the prompt uncommitted by design — copy it out first if it is
  worth keeping). Then remove the task branch `05-G1.1` if the run created it and you are not
  delivering from it: `git branch -D 05-G1.1` only from a checkout where it is not current, and
  only when you are certain it holds nothing you need.
- **Do not** `git reset --hard`, `git clean`, or discard the branch's uncommitted implementation
  changes: the build results record that delivery has not happened yet, and those changes are
  the implementation under test.
- **No environment variables, seed data, fixtures, cloud resources or credentials are created
  by any scenario**, so there is nothing else to unset or delete. If you exported anything for
  B5 (for example a state-directory override), unset it.

## 4. Could not be exercised in this environment

- **The full `aidw prompt` loop against a live reviewer (B5).** It needs a Pi installation, an
  authenticated model, model spend, and a clean control worktree on the configured base branch;
  the recorded run was made on branch `05-G1.1` with a dirty tree, where a real run refuses
  (exit 4). The deterministic evidence for the same path is the faked-stage coverage in
  `tests/test_prompt_workflow.py`, recorded in the build results as part of the full suite.
  A machine with Pi credentials and a clean base-branch control worktree would exercise it.
- **The dry-run plan's exact text (B4).** The plan's stage list and predecessor report depend on
  the target repo's config and roadmap state; only the properties in B4's pass test (stages
  named, `Pi not invoked`, no run created) are confirmed against the tree. Run it in the target
  repo whose config you mean to test.
- **Unverified build-results rows carried forward unchanged.** The build results record
  **Lint** as `unverified` — no linter is configured in this repo and `design.md` §15 says pytest
  is the only verification — and **Build** as `unverified` — no build gate is named by
  `AGENTS.md`, though `tests/test_packaging.py` exercises wheel/sdist construction inside the
  suite. Neither is a failure and neither is covered by any scenario here; if you need a
  packaging check, run `uv run --frozen pytest tests/test_packaging.py` and treat its result as
  your own, not as this task's recorded evidence.
- **No browser flow and no cloud/AWS action** could be exercised because this change names
  none; there is no environment that would add one.
