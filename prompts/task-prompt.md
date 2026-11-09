---
description: Author a task prompt from one roadmap entry, for the implementation stage
argument-hint: "<phase> <epic> <task>"
---

# Create a task prompt

The roadmap files in the configured roadmap directory (`paths.roadmap_dir`) are **planning
indexes**, not agent prompts. Each entry is deliberately terse — one line of context, one spec
citation, one done-condition — so the roadmap stays scannable and does not drift out of sync with
the prompts written from it.

Generated prompts must stay lean for the same reason: the implementer (the `/impliment-task`
stage) reads the specs and the repo itself. The prompt's job is scope + traps + acceptance — not
transcription.

## Variables

phase: $1
epic: $2
task: $3

## Instructions

AIDT owns branch setup (EXTRACTION.md §3.2): `aidw prompt` creates the task branch and its worktree before this stage runs. Do not create, switch, or reset branches yourself — write the prompt file and return its path; AIDT commits the reviewed prompt.

- Feasibility check before writing the prompt file: read the roadmap entry and every spec section
  it cites, and check whether what the task depends on exists. When authoring cannot proceed,
  output `blocked: <reason>` as the first line of your final message and change nothing — no
  prompt file, no other edits.
- Report `blocked: <reason>` for any of these reasons: a cited spec section is missing or contradicts the roadmap entry; a prerequisite the entry depends on cannot be found (not merged and no branch carrying it); an acceptance condition cannot be made executable without inventing a contract the cited sources do not fix. A `blocked:` line with an empty reason is still a blocked report.
- Read the roadmap document that holds the entry: the file in `paths.roadmap_dir` whose name
  matches `paths.roadmap_glob` and whose title matches the task's phase.
- Expand Phase {phase} Epic {epic} Task {task} into a full prompt using the `Prompt Format`. Store
  it in `paths.task_prompts_dir` as `<phase>-<task>-prompt.md` — the same `<phase>-<task>` branch
  name the task will run under.
- Replace every <placeholder> in the `Prompt Format` with specific implementation details.
- Obey the `Conciseness budget` below. If the draft exceeds it, cut pasted content first
  (schemas, code, static data, test scripts) and replace with pointers — never cut traps,
  non-goals, or Done-when checks.
- Do not invent a material interface the cited spec omits. If a schema field, keying convention,
  failure contract, or signature this task must implement is not fixed by the spec, stop and report
  it as a spec gap and update the spec first. A prompt-fixed decision is only acceptable when it is
  explicitly labelled as such, with its rationale, and the ambiguity is named in the
  ask-if-ambiguous clause.
- IMPORTANT: when you finish writing the task prompt, return exclusively the path to the prompt
  file created — or, when blocked, `blocked: <reason>` — and nothing else.

## Conciseness budget (mandatory)

- Target: **80–120 lines, <15KB**. Larger tasks may reach ~150 lines; beyond that, stop and cut.
- **Cite, don't paste.** Never paste code, schemas, type unions, static data or configuration
  longer than ~15 lines. Reference them as a spec section plus `path/to/file:Symbol`, and let the
  implementer read the source.
- **No repo snapshots.** Describe the starting state with file+symbol pointers, not pasted
  contents. The implementer has `read`/`bash`.
- **No stale-prone pins.** Never hard-code line numbers, test-file line references, or current
  counts that drift with ordinary work; write "recount and update the size assertion" instead. A
  spec-mandated minimum is different: state the required floor when the authoritative source sets
  it as an acceptance condition.
- **No wrapper duplication.** Branch setup and the implementation belong to the `/impliment-task`
  stage. The repo's full verification gate and the results document belong to the
  `/record-implementation-results` stage. The repo's traceability artefacts and the roadmap
  checkbox belong to the `/update-traceability` stage. Commit, push and the PR belong to the `/pr`
  stage. The task prompt lists only *task-specific* verification. One narrow exception: when the
  task adds a new dependency edge or build path, Done when may name the single build or lint
  command that proves that wiring — never the full gate.
- If in doubt, cut context — keep traps.

## Prompt Format

```
Read the following spec sections before starting, in full:
- <spec section — title>
  Located at: <path to the spec document>
- <repeat for every spec section the task cites — usually 1-2, occasionally more>

Task: <the task's one-line description, copied from the roadmap file>

Requirements:
1. <One behaviour per item, derived from what the cited spec actually says, not
   invented. Name the exact field/threshold/signature by reference
   (e.g. "per <spec §> : pure, the clock is injected"), don't paste the
   definition. If the spec gives a snippet, say "match <spec §> <symbol>"
   and stop.>
2. <... — keep to the behaviours this task owns; 5–9 items max>
   <If this task changes a checker, status vocabulary, catalog reference, or CI gate,
   add a one-line "Gate impact:" naming the checker and the pre-existing entries it
   affects, and confirm against the current repo that the gate stays green.>

Traps / prior review findings (max 5–7 bullets, 1–2 lines each):
- <What the implementer will get wrong if unwarned + why, with a
  file/symbol pointer.>

Explicit non-goals — do NOT do these in this task:
- <Name the next task(s) in the same epic, or an obviously-adjacent task in
  another epic, and say explicitly "that's a separate task, don't start it
  here.">
- <Name any deferred or out-of-scope spec item this task's area touches, if
  there's a real risk of scope creep into it.>

Deliverables:
- <File paths only, one per line. No contents.>

Tests (what to prove, not the literal expects):
- <One hand-calculated example per behaviour path, plus purity and
  fail-closed checks. Say what to assert and which file to put it in; don't
  dictate stub sequences or exact error strings.>

Done when:
- <The roadmap's "Done when" line made executable: 3–6 task-specific checks
  (a test file passing, a call working end-to-end, an assertion on output). No
  build/lint/test gate — the record stage owns the full verification gate. The
  one allowed exception is a single build or lint line proving new dependency or
  build-path wiring when this task introduces one.>

If anything in the cited spec section is ambiguous or underspecified for
this task, stop and ask rather than guessing — especially <2–4 task-specific
risks named here>. Always include the generic guard: security-sensitive,
cost-committing, or hard-to-reverse changes (trust boundaries, schema
changes, billing logic, data deletion).
```

## Section-by-Section Guidance

### Spec citation(s)
Pull directly from the task's own spec reference in the roadmap file. If the task cites a whole
document with no section, read enough of it to find the specific subsection that actually matters
and cite that instead — narrower is better than "read the whole document."

If the task creates files, modules, services or tests, also cite whatever document fixes their
**location and naming**, and use it to choose paths. Do not invent a new top-level directory
unless the task explicitly requires something outside the documented layout.

### Requirements
State behaviours, not transcriptions. The roadmap bullet is a summary; each requirement should name
what the spec *actually specifies* by reference — field/threshold/signature name plus spec section
plus `path:Symbol` — without pasting the definition. Many specs include literal snippets: require
matching the cited symbol, never paraphrasing it, and never pasting it into the prompt unless it is
≤15 lines *and* the implementer cannot proceed without it inline.

If the roadmap and spec already settle something, don't re-decide it. If you must fix an
underspecification for determinism, put the decision in one line *and* flag it in the
ask-if-ambiguous clause so the implementer knows it is prompt-fixed, not spec-fixed.

### Gate and verifier reconciliation (gate-touching tasks)

If the task changes a checker, status vocabulary, or CI gate, the prompt must state the observable
effect on existing data, and the author must verify it against the repo before writing the
requirement. The gate list is the target repo's to declare: read it from that repo's
root `AGENTS.md` plus its optional `aidw/conventions.md` (EXTRACTION.md §3.4/§3.8, D16;
R10/R14), and require the generated prompt to name the exact gate commands from that source rather than any
command inlined here. A repo that has no conventions yet falls back to the gates its own task
prompt names plus the stack's obvious build and test commands. If a gate-touching instruction
cannot be reconciled with the repo, fix the instruction or make the reconciliation an explicit
deliverable — don't paper over it.

### Traps / prior review findings
This is where hard-won correctness lives — keep it, but keep it tight. Max 5–7 bullets, each:
*mistake → consequence → pointer*. Prefer traps that caused real review findings (name collisions,
parser contracts that parse more than they should, wire fields that must not be optional,
fail-closed paths). Anything the agent can discover with one `read`/`grep` is not a trap — cut it.

### Explicit non-goals
This is the single highest-leverage section for keeping tasks bite-sized. Coding agents will often
"helpfully" continue into the next logical piece of work unless told not to. Always name at least
the next task in the same epic. If the task sits inside a phase that borders a deferred decision
the roadmap records, call that out explicitly too, since those are exactly the "seems like the
natural next step" traps.

### Deliverables
File paths only, one per line. "A handler that does X" is weaker than
`src/handlers/action.ts:handleAction (+ test)`. Take locations from the layout document the task
cites, not from guesswork.

### Tests
Say *what to prove*, not the literal `expect()`. Require one hand-calculated example per behaviour
path plus purity (no input mutation, no undeclared I/O) and fail-closed checks (a rejection returns
the documented failure, never a raw exception escaping). Name the test file. Do not dictate stub
sequences, exact assertion text or incidental ordering beyond what the spec normatively requires.
Where the repo has a traceability or coverage artefact, say what evidence it needs and let the
`/update-traceability` stage own the mechanics.

### Done when
The roadmap's own "Done when" line is usually already close to right — make it executable with 3–6
task-specific checks. If it is already concrete, copy it as-is. Never include the repo's
build/lint/test gate or its checker list here — the `/record-implementation-results` and
`/update-traceability` stages own generic verification.

### Ask-if-ambiguous clause
Always include it, but scope it: 2–4 task-specific risks named inline plus the generic guard
(security-sensitive, cost-committing, hard-to-reverse). A bare verbatim clause with no
task-specific risks is a sign the prompt author didn't read the spec. Before returning the prompt, run the pre-submit self-check below; it is where the `prompt-fixed` label defined here is applied.

## Pre-submit self-check

Before you return the prompt, walk the same ground as the reviewer's `## Review order` in
`task-review.md` — read it, do not transcribe it. Each numbered check below shadows one
review-order step. Where the cited spec is silent, make the decision explicit and label it
`prompt-fixed` with its rationale, and name the ambiguity in the ask-if-ambiguous clause — the one
label that clause already defines; do not invent a second. If a check would force bloat, cut
context and keep traps (Conciseness budget).

1. **Set the frame** — task id, cited specs, deliverable, acceptance checks and non-goals, and who or what the change affects.
2. **Trace the authority chain** — every requirement cites the roadmap entry or spec section that fixes it; where new shared code lives is decided from the repository conventions, and labelled `prompt-fixed` if the spec is silent.
3. **Check repository fit** — paths, names and dependencies exist in the current tree; the claimed prerequisite state is true.
4. **Review the requested behavior** — failure-path precedence when two failures are possible, and per-mode output contracts on the failure path, are each decided and labelled `prompt-fixed` if the spec is silent.
5. **Check internal consistency** — the complete label/key vocabulary, why the enumerated set is complete, and exact comparison semantics are all decided; requirements, non-goals, deliverables and Done-when do not contradict.
6. **Check task boundaries and dependencies** — one coherent task, adjacent work named as a non-goal, no missing prerequisite.
7. **Check the proof** — one proof per requirement: every numbered requirement maps to at least one Tests or Done-when assertion that would fail under a broken implementation.
8. **Check ambiguity severity** — every material ambiguity the spec leaves open is visibly labelled `prompt-fixed` with its rationale and named in the ask-if-ambiguous clause, not left implicit.
9. **Report findings** — the ask-if-ambiguous clause names its task-specific risks and the generic guard.
