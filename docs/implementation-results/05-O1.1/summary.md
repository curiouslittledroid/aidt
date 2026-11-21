# Summary — 05-O1.1: Teach agents to handle blocked bash commands

## The problem it was solving

A live implement stage was observed receiving Pi's `Blocked bash command with unapproved
operations` tool result and then retrying the same command four times in a single run. That is a
blind-retry loop: the tool had already refused the operation, but the agent treated the refusal as
something retryable — something to get around by reordering, re-quoting, splitting, or renaming the
command — instead of as a stop-and-surface signal. The build results record this as the motivating
observation, and the task prompt names the consequence: a real Pi implementer keeps retrying, so the
run burns turns on a command that will never be approved.

The reason prompt text alone could not fix it is already settled in the decision log. Per
`design.md` §17 Z9 and Z20, prompt text does not reliably override an agent file's hard rules. Each
`agent-configs/<id>.yaml` points its `agents_md:` key at that agent's own `agents/*/AGENTS.md` file
and `design.md` §5.5 appends those bytes verbatim in every `system_prompt.mode`. So the durable place
for the rule was the shipped agent context files themselves — “the shared context they assemble from”
named in the roadmap entry had no mechanism behind it to edit.

## The core idea

Teach every shipped agent context file one identical, self-contained contract: a bash result reading
`Blocked bash command with unapproved operations` is a **hard deny**, it must not be retried in any
cosmetic variant, and it must be reported as a blocker naming the denied command. The guidance is
duplicated into all eleven `agents/*/AGENTS.md` files rather than centralised, because no shared
fragment or assembly mechanism exists to centralise it into. That is the smallest change that reaches
every agent, and it works because every agent's allowlist grants `bash`. Two further choices made the
rest of the work follow: quoting Pi's real tool-result string **verbatim** so the agent can match the
block when it sees it, and keeping the edit strictly content-only — no file moved or renamed, no
`agents_md:` path changed.

## What was built, piece by piece

The heart of the change is the new `## Blocked bash commands` section added to each of the eleven
`agents/*/AGENTS.md` files. It opens by naming the tool result as a hard deny — “the operation was
refused, not interrupted, so it is not retryable” — then states the three behaviours the roadmap
requires: do not retry the command; do not retry a cosmetic variant of it either, with reordering,
re-quoting, splitting, alternative syntax and renaming explicitly called out as the same denied
operation; and report it as a blocker naming the denied command, then stop. Deliberately, the section
teaches no workaround, because framing the block as a puzzle to solve is exactly what reopens the
retry loop. It also carries no example command, no product, package-manager or product-path token, no
slash-command, and no numbered `AGENTS.md` section reference — each of those would trip the neutrality
sweep that greps this glob.

Because `aidw agents validate --strict` only checks that each `agents_md:` file exists and reads, and
never inspects content, reachability alone would have left the new contract unpinned. The content
coverage therefore lives in `tests/test_agent_guidance_neutrality.py`: a parameterized test over the
whole `agents/*/AGENTS.md` glob asserting, on whitespace-flattened text via the module's existing
`_flat` helper, that the verbatim phrase and every behaviour clause are present. Two live-guard tests
prove the check is not vacuous — one rejects a file that drops the phrase and one a file that drops
the “cosmetic variants” clause — and a pinned property seed keeps the generated clause variants from
silently drifting. This sits alongside the existing reachability test, which stays green precisely
because no file was moved or renamed.

The contract was then recorded in `design.md`, which the task treated as part of the deliverable
rather than documentation after the fact: a new §5.5 bullet states the blocked-bash rule for shipped
agent context files, and one row is appended to the §17 decision log as `Z21`. The id is the next free
one because `aidw/conventions.md` forbids reusing or renumbering ids, so the stale reference pattern
seen in earlier rows (Z18, Z20) is avoided. The row names task O1.1, the files changed, and the
prompt-fixed decisions. `tests/test_design_doc.py` pins both halves — matching the §17 row by task id
`O1.1` and wording, never by its `Z` number, mirroring the existing C1.x/S1.x pin style.

Around those pieces, the branch also carries the task prompt at `paths.task_prompts_dir`
(`05-O1.1-prompt.md`), committed as the first commit on the branch and left in place as the record of
what was asked.

## What it deliberately did not do

No shared context fragment or assembly mechanism was introduced. The roadmap's “or the shared context
they assemble from” alternative describes something that does not exist today; building it is a
larger change than this entry, and the eleven-file edit reaches every agent without it.

No tool allowlist, `agent-configs/*.yaml`, prompt file, or stage-registry entry was touched. The change
is guidance text only, which is why `agents validate` and `prompts check` remain meaningful gates on
it rather than being edited around.

The remaining epic O1 tasks were left alone; each is a separate roadmap entry. And as far as this
stage is concerned, no PR was opened and nothing was committed or pushed — delivery belongs to the
`/pr` stage, which will record the PR in the build results.

One deviation the build results record is worth restating so an omission is not mistaken for an
oversight: the roadmap entry names `tests/test_agent_configs.py`, which does not exist. The equivalent
test that reads the whole glob is `tests/test_agent_guidance_neutrality.py`; the task prompt fixed that
up front, the implementation followed the prompt, and the roadmap entry itself was left untouched per
`aidw/conventions.md`.

## Verification

Every gate the build results record passed; nothing failed and nothing was left unverified. Under
top-level verification, `uv sync --frozen` reported `Checked 19 packages in 1ms`; a build gate
(`uv build --out-dir $(mktemp -d)`) produced `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl`, and
the suite gate (`uv run --frozen pytest`) reported `2532 passed in 52.46s`. `uv run --frozen aidw
doctor` reported `23 checks: 0 failed, 2 warning(s)` — warnings for the dirty `05-O1.1` working tree and
a missing `.mcp.json`, neither of which is a failure. `uv run --frozen aidw agents validate --strict`
reported `11 agent config(s): 0 error(s), 0 warning(s)`, confirming the guidance remains reachable with
configs unchanged, and `uv run --frozen aidw prompts check` reported `resolved repo prompts: 0 error(s),
0 warning(s)`. `git diff --check` produced no output and exited 0. The build results also record that
this repository configures no linter, formatter or type-checker, so there is no lint row to report —
the absence is a property of the repository, not a skipped check.

The focused gate named by the task prompt's Done-when also passed: `tests/test_agent_guidance_neutrality.py`
and `tests/test_design_doc.py` together ran 143 tests in 0.79s. At the task-specific level, the build
results record each required proof as passing: the whole-glob sweep for the verbatim phrase and the
three behaviour clauses; the live-guard and property tests that keep that sweep non-vacuous; the
neutrality sweep remaining green; `agents validate --strict` exiting 0 with unchanged configs; and the
`design.md` §5.5 bullet plus exactly one new §17 row. The build results record no failing or unverified
row, so this summary carries none.
