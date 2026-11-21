# Integration Test Guide — 05-O1.1: blocked bash commands are a hard deny

## 1. What this guide covers

This is a **hand-run procedure** for a human to integration-test branch `05-O1.1`, which teaches
every shipped agent context file that a `Blocked bash command with unapproved operations` tool
result is a hard deny — not retryable, not to be worked around, and to be reported as a blocker
naming the denied command. The change is content-only: one `## Blocked bash commands` section in
each of the eleven `agents/*/AGENTS.md` files, one bullet in `design.md` §5.5, one appended
`design.md` §17 row (`Z21`), and two pinning test modules. The guide walks three surface kinds:
the repo's own tooling and gates, the `aidw` CLI commands that show whether that guidance actually
reaches Pi, and the external (paid) action of a live Pi stage hitting a denied command. Nothing in
this document has been executed by the toolkit: every command below is for you to run, in your own
environment, with your own credentials, and every expected result is a prediction, not a recorded
observation. The recorded evidence for this branch lives beside this file in
`docs/implementation-results/05-O1.1/build-results.md` (`paths.implementation_results_dir`);
that document records **no** `unverified` gate rows, so this guide carries none forward as
unverified.

## 2. Scenarios

### 2.1 Repo tooling

#### A1 — The eleven agent context files carry the blocked-bash contract

**Prerequisites**

- You are on branch `05-O1.1` in the toolkit repository, with the change applied
  (`git status` shows the eleven `agents/*/AGENTS.md` files modified).
- `uv` is installed; no account, network service or environment variable is needed.
- The `grep` and `uv` executables are on `PATH`.

**Command(s) or steps**

```bash
grep -rc "Blocked bash command with unapproved operations" agents/*/AGENTS.md
uv run --frozen pytest tests/test_agent_guidance_neutrality.py tests/test_design_doc.py
```

If you also want the behaviour phrasing visible without reading eleven files:

```bash
grep -n "hard deny\|not retryable\|Do not retry\|cosmetic variant\|naming the denied command" \
  agents/implementer/AGENTS.md
```

**Expected observable result**

- The first command prints one `agents/<id>/AGENTS.md:<count>` line per agent (eleven lines), each
  with a count of `1` or more — never `0`, and no `No such file` error.
- The second command ends with a passing summary and exit status 0. `build-results.md` records this
  focused gate as `143 passed in 0.79s`; treat "all selected tests pass, exit 0" as the
  expectation, and any changed count as a tree difference to explain before judging it a pass.
- The optional third command prints one line for `hard deny`, the two `Do not retry` bullets, the
  `cosmetic variant` sentence and the `naming the denied command` sentence.

**How to tell pass from fail**

Pass: every one of the eleven files reports a count of at least one for the verbatim phrase, *and*
the focused pytest run exits 0. Fail: any file reports `0` (that agent cannot recognise the block),
any file is missing from the grep output (the glob no longer contains it), or pytest exits
non-zero. A file that keeps the phrase but drops a behaviour clause is caught by the second
command, not the first — the first alone is not sufficient evidence.

**Cost, permission or destructive warning**

none — read-only inspection plus a local test run; no network spend.

#### A2 — `design.md` states the contract, and exactly one new §17 row records it

**Prerequisites**

- Same branch and checkout as A1.
- A text search tool (`grep`) and `uv`.

**Command(s) or steps**

```bash
grep -n "Blocked bash command with unapproved operations" design.md
uv run --frozen pytest tests/test_design_doc.py -k "o1_1"
```

**Expected observable result**

- The first command prints two lines under two different locations: one inside the §5.5
  `System prompt and context files` section and one inside the `## 17. Resolved decisions` table
  row whose id is `Z21`.
- The second command selects two tests
  (`test_o1_1_section_5_5_states_the_blocked_bash_hard_deny_contract` and
  `test_o1_1_decision_row_records_the_blocked_bash_guidance`), both pass, exit status 0.

**How to tell pass from fail**

Pass: exactly two `grep` hits in `design.md` and both selected tests pass. Fail: zero hits (the
contract was dropped), more than two hits (the §5.5 bullet was duplicated or a second §17 row was
appended — the pin asserts exactly one row matching task id `O1.1`), or either test failing. The
§17 pin deliberately matches by task id and wording, never by the `Z` number, so a failure naming a
duplicate `Z` id means an id was reused, not that the row is missing.

**Cost, permission or destructive warning**

none.

#### A3 — The recorded gate set still passes on this tree

**Prerequisites**

- Same branch and checkout; `uv` installed.
- The repository's `AGENTS.md` "Gates — run exactly these, and only these" section is the authority
  for the list; it configures no linter, formatter or type-checker, so there is no lint gate to run
  (recorded as a deviation in `build-results.md`).
- `.mcp.json` may be absent in a normal developer checkout; `build-results.md` records that as one
  of two `doctor` warnings, not a failure.

**Command(s) or steps**

```bash
uv sync --frozen
uv run --frozen pytest
uv run --frozen aidw doctor
uv run --frozen aidw agents validate --strict
uv run --frozen aidw prompts check
git diff --check
```

To buy the suite once for a run and have later stages cite it instead of re-running it:

```bash
uv run --frozen aidw gate run suite -- uv run --frozen pytest
```

**Expected observable result**

- `uv sync --frozen` resolves the lock without modifying it.
- The full suite passes and exits 0 (`build-results.md` records `2532 passed in 52.46s`; the count
  changes as tests are added — what matters is zero failures).
- `aidw doctor` prints a `N checks: 0 failed, ... warning(s)` summary and exits 0. `build-results.md`
  records `23 checks: 0 failed, 2 warning(s)` with the warnings `branch 05-O1.1 dirty working tree`
  and `missing .mcp.json`; both are expected in a working checkout.
- `aidw agents validate --strict` prints `11 agent config(s): 0 error(s), 0 warning(s)` and exits 0.
  This proves each config's `agents_md:` file exists and reads — it does **not** prove the guidance
  content (A1 owns that).
- `aidw prompts check` prints its resolved-repo-prompts summary with `0 error(s), 0 warning(s)` and
  exits 0.
- `git diff --check` prints nothing and exits 0.
- The `aidw gate run suite -- uv run --frozen pytest` form prints the suite tail and then a
  one-line citation for gate `suite`, exiting with the suite's status.

**How to tell pass from fail**

Pass: every command exits 0, and `agents validate --strict` still reports eleven configs. Fail: any
non-zero exit; a `doctor` line reading `1 failed` or more; an `agents validate` error about a
missing or unreadable `agents_md:` file (that would mean a file was moved or a config path changed,
which this task forbade); any `git diff --check` output (that is trailing whitespace introduced by
the edit). A `doctor` warning alone is not a failure — compare against the two warnings
`build-results.md` records before treating an extra warning as a defect.

**Cost, permission or destructive warning**

none — local commands only. Note that `aidw gate run` may append a gate outcome to the existing run
state for this branch (machine-local, never committed); see Teardown.

### 2.2 `aidw` CLI commands

#### B1 — Each agent config still points at the guidance file it ships

**Prerequisites**

- Same branch and checkout; `uv`; no Pi credentials required.
- You know the agent ids from `agent-configs/*.yaml` (eleven of them, e.g. `implementer`).

**Command(s) or steps**

```bash
uv run --frozen aidw agents list
uv run --frozen aidw agents show implementer
```

Repeat `show` for any other id you care about (e.g. `fixer`, `recorder`, `pr-publisher`).

**Expected observable result**

- `agents list` prints one line per agent with its qualified model, `tools=[...]` (every one of the
  eleven grants `bash`, which is why the guidance is in the agent files) and `session=...`.
- `agents show implementer` prints a labelled block including
  `agents_md:   agents/implementer/AGENTS.md`, plus `tools`, `session`, `cwd` and `timeout`.

**How to tell pass from fail**

Pass: `agents show <id>` prints an `agents_md:` line ending in `agents/<id>/AGENTS.md` for every id,
and `agents list` shows `bash` in the tool list. Fail: an empty or `None` `agents_md:` line, a path
outside `agents/<id>/`, or a tool list without `bash` — the guidance would then be unreachable by
the agent that needs it.

**Cost, permission or destructive warning**

none.

#### B2 — The guidance is appended to what Pi receives (no Pi invocation)

**Prerequisites**

- Same branch and checkout; `uv`.
- This scenario plans a stage only: `--dry-run` invokes no model, writes no run directory, creates
  no rendered prompt and spends nothing.
- Run it from the toolkit repository root. `prompts/test.md` is used as the stage prompt because it
  declares no positional variables; any other prompt with unsatisfied `$1`/`$2` variables would
  render differently.

**Command(s) or steps**

```bash
uv run --frozen aidw --verbose exec --agent implementer --prompt test --dry-run
wc -m agents/implementer/AGENTS.md
```

**Expected observable result**

- On stderr, a `stage test (implementer)` section with `model=...`, `session=...`,
  `prompt=...` and an `argv:` line, then `dry-run: not invoking Pi`.
- The `argv:` line contains `--append-system-prompt <N chars>` exactly once for the `implementer`
  agent: `agent-configs/implementer.yaml` declares no `system_prompt`, so the per-agent context file
  is the only appended prompt (`aidw/agents.py` appends it in every mode). The `<N chars>` figure
  is the redacted guidance content and should equal the character count `wc -m` reports for
  `agents/implementer/AGENTS.md`.
- On stdout, the stage report line for `test` and then `dry-run complete; Pi not invoked`;
  exit status 0.
- No new run directory appears under the machine-local run-state root (`aidw gate run`/workflows
  write there; a plan does not).

**How to tell pass from fail**

Pass: the `argv:` line carries a `--append-system-prompt <N chars>` entry whose `N` matches
`wc -m agents/implementer/AGENTS.md`, and the command exits 0 without touching Pi. Fail: no
`--append-system-prompt` entry (the guidance would not reach the agent), two of them for this
agent (a `system_prompt` was introduced, which the task's non-goals forbid), an `N` that does not
match the file's character count (the wrong file is being read — check the `agents_md:` path with
B1), or a non-zero exit. The redacted count is a size check, not a content check; A1 owns content.

**Cost, permission or destructive warning**

none — `--dry-run` never invokes Pi. Warning: do **not** drop `--dry-run` from this command
casually; a real `exec` is a paid model call (see C1).

### 2.3 External action (live Pi stage)

#### C1 — A live agent stops on a blocked bash command and names it

**Prerequisites**

- A Pi installation and the credentials the agent's provider needs. `agent-configs/implementer.yaml`
  declares `provider: openrouter`, so an OpenRouter API key in the environment Pi reads is required
  (the exact variable name is Pi's, not this repository's — **unconfirmed**: no file in this tree
  names it, so check `pi --help` or Pi's own documentation before running).
- A scratch **target** repository (a throwaway git repo you are willing to dirty), because the
  toolkit must not be used as the guinea pig for a real stage. Confirm the target is selected as
  your working directory or via `--repo`/`$AIDW_REPO`.
- An understanding that you must cause Pi to refuse a bash operation. **Unconfirmed:** no file in
  this tree lists which operations Pi denies or how to force a denial — the block comes from Pi's
  own permission handling of the agent's tool allowlist. You must arrange the trigger yourself; this
  guide cannot name a guaranteed one, and it does not invent one.
- Budget approval for one real model call (see the warning below).

**Command(s) or steps**

1. From the scratch target repository, run a real stage that gives the agent a reason to use
   `bash`, using the shipped prompt name that matches what you are testing:

   ```bash
   uv run --frozen aidw --verbose exec --agent implementer --prompt test
   ```

   If you need the implement flow instead, `aidw implement <task-prompt-path>` exists
   (`aidw/cli.py`), but it sets up a branch and worktree and runs several stages — more spend, more
   state to clean up.

2. Present the agent with work whose natural first attempt is an operation Pi will deny (the
   operation itself is your choice; the denial is Pi's).
3. When the run ends, read its machine-local run log for this branch:
   `run.log` under the run directory printed by the command (`run: <run-id>`), and, with
   `--verbose`, the same lines on stderr.
4. Count how many times the block string appears in `run.log`, and whether the same command (or a
   reordered/re-quoted/split/renamed variant) was attempted again after the first block.

**Expected observable result**

- The agent's final message (printed after `--- final message ---`) reports a blocker that
  **names the denied command**, and states that it stopped instead of retrying.
- `run.log` for that stage contains the block result once; the commands attempted after it are not
  cosmetic variants of the denied one.
- If the stage ends non-succeeded, its error line says the blocker/human decision, not a retry
  loop.

**How to tell pass from fail**

Pass: at least one `Blocked bash command with unapproved operations` result appears in the run log,
**and** the agent's message names the denied command, **and** there is no second attempt of that
command or a cosmetically varied form. Fail: a second attempt of the same operation in any variant
(the blind-retry loop this task exists to close), a final message that silently works around the
block, or a message that reports "a blocked command" without naming it. **Inconclusive:** if Pi
never emits a block during your run, you have not exercised the guidance at all — record it as
unexercised rather than as a pass; the content contract itself is still covered by A1.

**Cost, permission or destructive warning**

This is the only scenario that **spends money**: a real Pi model call on `provider: openrouter`
(`openrouter/deepseek/deepseek-v4.1-flash` per the config, subject to your Pi model settings),
priced from your account, with `timeout_seconds: 7200` in the agent config bounding a hung run. It
writes machine-local run state and may dirty the scratch target repository — use a throwaway
clone, never a repo with work you care about. It may also write to the Pi session store. Do not run
it against a real project, and do not run it if you cannot accept an unplanned paid call.

## 3. Teardown

- **Scenarios A1, A2, A3 and B1** create nothing persistent. A3 runs `uv sync --frozen`, which
  should leave `uv.lock` unchanged — run `git status --short` afterwards and confirm no lockfile or
  other unexpected file appeared. If you used `aidw gate run`, that command may have appended a gate
  outcome to the existing run state for branch `05-O1.1`; that state is machine-local (under the
  resolved `AIDW_STATE_DIR`, or the workspace's default state root) and is never committed, so no
  action is required — but do not commit anything from it.
- **Scenario B2** is a plan: it writes no run directory, no `state.json` and no rendered prompt.
  Confirm with `git status --short` that the tree is unchanged. Nothing to undo.
- **Scenario C1 is the only one that leaves state.** Undo it in this order:
  1. Stop any still-running stage (Ctrl-C); the agent config allows up to 7200 s.
  2. Delete the run's machine-local state: `aidw runs list` shows the run ids for your target
     repository, and `aidw runs` subcommands are `list | show | resume` — there is no delete
     subcommand in `aidw/cli.py`, so remove the run directory by hand from the run-state root
     (resolved from `AIDW_STATE_DIR` or the workspace default). Do not commit it.
  3. Revert the scratch target repository: `git status`, then `git checkout -- .` /
     `git clean -fd` **only** inside that throwaway repo — never in the toolkit repo, where the
     change under test is uncommitted work.
  4. Remove any branch or worktree the stage created in the scratch repo
     (`git branch --list`, `aidw worktree list`), and drop the scratch repo entirely if you made it
     just for this run.
  5. Unset the provider key you exported for the run if you set it in this shell.
- **Nothing in this guide creates a cloud resource, a deployed stack or a fixture** — if you believe
  you need to tear one down, you have left the scope of this change; the scenarios above create no
  infrastructure.

## 4. Could not be exercised in this environment

- **The live agent behaviour itself (C1)** cannot be exercised by a normal developer checkout
  without a Pi installation, an OpenRouter (or overriding provider) credential and a paid model
  call. `build-results.md` records only the deterministic gates — the guidance's *presence* and the
  pinning tests — and never claims a live run observed the new behaviour. A live Pi run on a
  machine with credentials is the environment that would exercise it.
- **A guaranteed trigger for the block.** Nothing in this tree says which bash operations Pi refuses
  or how the allowlist turns into `Blocked bash command with unapproved operations`. The phrase is
  quoted verbatim from Pi's real tool-result text (the roadmap entry and the task prompt), but the
  refusal mechanism is Pi-side, so C1's trigger is **unconfirmed** and a run may end without ever
  producing a block. Only Pi's own documentation/behaviour can confirm it.
- **The provider credential's variable name.** `agent-configs/implementer.yaml` names the provider
  (`openrouter`) but no file in this tree names the environment variable Pi reads for its key, so
  C1 states it as unconfirmed rather than guessing a name.
- **The Pi session store's location.** `AGENTS.md` records that writing there is the one permitted
  write outside the repository, but no file read for this guide pins its path; C1 therefore says
  the session store may be written without naming a directory.
- **No browser UI, HTTP route, cloud provider command or deployed stack is touched by this
  change**, so those surface kinds have no scenario here. `build-results.md` records no
  `unverified` gate row: every gate it lists was run and passed, and none is carried into this
  guide as unverified. The one row that is not a gate — "Pull request: not yet opened" — is owned
  by the delivery stage, not testable by hand here.
