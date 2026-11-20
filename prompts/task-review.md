# Task Prompt Review

Find defects that could make the task prompt produce an unsafe, incorrect, incomplete, impossible, or unreviewable implementation. Do not turn wording preferences or personal taste into findings.

Stay read-only. Do not edit the task prompt, implementation files, specs, roadmap documents, or post comments.

## Variables

task-prompt-file: $1

## Scope

Review the task prompt (`task-prompt-file`) only as a pre-implementation artifact. The prompt is the change under review; there may be no implementation yet.

The reviewer must:

- Identify the task prompt being reviewed - `task-prompt-file`. If no prompt path is supplied, ask for one or report that the review cannot begin.
- Read the complete task prompt at `task-prompt-file`, not just its requirements or deliverables.
- Read the roadmap task that the prompt expands, the cited specification sections in full, and `Design 21 — Monorepo Layout` when the prompt creates or changes repository artifacts.
- Read `AGENTS.md`, the specification/task documentation guidance, and relevant repository conventions or analysis documents.
- Inspect the current repository structure and existing implementation where needed to verify assumptions about paths, APIs, schemas, package conventions, dependencies, infrastructure, tests, and task ordering.
- On any round after the first, re-read the previously flagged material in full before reporting a previous finding resolved: the task prompt at `task-prompt-file`, the cited specification section, and the repository file or symbol the finding named. A grep, a diff, or a partial re-read of the previously flagged section is never sufficient to approve a resolution.
- Treat the prompt as the review boundary. Do not perform an implementation review and do not propose unrelated repository cleanup.

If the prompt has no clear source roadmap task, specification citation, acceptance condition, or scope boundary, report that as a finding rather than silently inventing the missing context.

## Standard

Approve only when an implementer can follow the prompt without making a material design decision that the prompt or its authoritative sources have not settled, and when the resulting work could be verified against the repository's rules and acceptance criteria.

A task prompt is ready when:

- Its requested behavior matches the authoritative specs and the roadmap's dependency order.
- Its requirements are complete enough to implement without guessing about security boundaries, tenancy, schemas, interfaces, failure behavior, data ownership, concurrency, migrations, deployment, or other material behavior.
- Its paths, package boundaries, dependencies, tooling, and existing-repository assumptions are accurate.
- Its deliverables and non-goals define a reviewable unit of work without hidden scope creep.
- Its acceptance criteria and verification commands prove the behavior that matters, including important failure paths.
- Its stated implementation choices do not contradict repository invariants or existing contracts.

Do not demand that the prompt specify details already unambiguously fixed by the cited specs or established repository conventions. Do not block on prose style, formatting, optional improvements, or future concerns that cannot affect this task's implementation.

The verdict is independent agent evidence. It is not approval of an implementation and is not a replacement for human review of the eventual code.

## Review order

1. **Set the frame.** Record the prompt path, task identifier, source roadmap entry, cited specs, intended deliverable, acceptance criteria, and explicit non-goals. State who or what will be affected by the implementation.
2. **Trace the authority chain.** Confirm that the prompt's requirements are derived from the roadmap and cited specs. Read the relevant spec sections in full, including referenced conventions or analysis documents. Report conflicts, unsupported inventions, stale citations, and missing source material before reviewing wording details. When the prompt depends on a task whose code is not on the base branch, inspect the branch that implements that dependency — `git log <base>..origin/<id>` and `git show origin/<id>:<path>`, where `<base>` is the base branch — and state the revision you verified. Never resolve a conflict between a roadmap summary and the branch that implements the dependency in favour of the roadmap summary: the roadmap entry is a planning index, and the branch is the authority for the shape of the code it implements.
3. **Check repository fit.** Inspect the current tree and nearby code/configuration. Verify package names, file paths, exports, handler contracts, schema conventions, tenancy scope, dependency versions, infrastructure ownership, test placement, scripts, and the claimed state of prerequisite tasks. A prompt may be defective even when its proposed behavior is sensible if its assumptions do not hold in this repository.
4. **Review the requested behavior.** Check the main flow and all specified failure paths. Look for missing validation, authorization, tenant isolation, idempotency, error handling, retries, timeouts, concurrency behavior, compatibility requirements, migration/rollback behavior, observability, and operational consequences. Follow data from input through persistence, external calls, and output.
5. **Check internal consistency.** Compare requirements, non-goals, deliverables, done-when criteria, examples, test cases, and verification commands. Find contradictions such as a required artifact also being forbidden, a test that cannot observe the required behavior, a schema that cannot represent the stated result, or a command that cannot run with the requested package layout.
6. **Check task boundaries and dependencies.** Confirm that the prompt delivers one coherent task, does not silently include adjacent work, and does not omit a prerequisite analysis or design decision. Ensure explicit non-goals do not conflict with requirements or the roadmap.
7. **Check the proof.** Assess whether the proposed tests and verification gates:
   - Cover each material acceptance criterion and important failure path.
   - Assert behavior a caller, player, operator, or deployment can observe.
   - Would fail under a broken implementation.
   - Use the repository's actual test/build/lint/synth conventions.
   - Do not rely solely on implementation details or tautological assertions.
   - Include security, tenancy, compatibility, migration, and infrastructure evidence when those areas are affected.
8. **Check ambiguity severity.** Separate harmless implementation freedom from decisions that must be resolved before coding. Use `Blocked` when the prompt or authoritative source leaves a material security, cost, schema, data-loss, cross-account, billing, or hard-to-reverse decision unresolved and an implementer would have to guess.
9. **Report findings.** Return only actionable prompt defects in priority order. Include evidence from the prompt, the repository, or the cited source documents.

## Task-prompt review findings

Report only real defects in the task prompt: omissions, contradictions, incorrect assumptions, source/spec mismatches, unimplementable instructions, missing acceptance proof, or scope/dependency problems that could affect the resulting implementation. Do not report suggestions merely because the prompt could be more elegant or detailed.

Use this format for every finding:

```text
Priority: Must fix / Should fix / Could fix
Confidence: 0 to 5
Kind: spec-gap / prompt-gap
What I found: Describe the defect in the task prompt or its source context.
Why it matters: Explain how an implementer could produce incorrect, unsafe, incomplete, or unverifiable work.
Trigger and effect: State the condition under which the problem appears and the resulting implementation or review failure.
Where: Task-prompt path and line/section; name the file or symbol the finding was verified against and the revision or command used to verify it (for example a git sha, or `git show <rev>:<path>`), or state explicitly that nothing could be verified.
Suggested fix: Give a short, practical direction for correcting the prompt, source citation, requirement, boundary, or acceptance test.
```

A `Suggested fix` is a direction, not a decision: when two readings both satisfy the cited sources, mark the finding `Blocked` and name the choice in the finding body instead of prescribing one reading.

`Kind:` classifies who can close the defect, and it is required on every finding:

- `spec-gap`: a defect only the cited specification or roadmap can close. The prompt cannot be
  fixed without changing its source of truth, so editing the prompt would paper over it.
- `prompt-gap`: a defect the prompt itself can close. Editing the prompt is enough.

A finding without a valid `Kind:` is not a complete review. AIDT reads this line mechanically: an
unclassified finding fails the review closed, and a `spec-gap` stops the run before any fixer stage
instead of being reworked as prompt prose.

Keep the labels plain — exactly as shown above, with no bold or backticks around `Priority:`,
`Confidence:` or `Kind:` and a bare value after the colon. AIDT parses these blocks to count the
findings and fix them one at a time; a bolded label (`**Priority: Should fix**`) defeats that.

Priority means:

- **Must fix:** The prompt could direct a security failure, data loss, broken required behavior, incompatible contract, unsafe deployment, serious scope error, or implementation that cannot be accepted.
- **Should fix:** A real omission, contradiction, stale assumption, missing failure path, or proof gap that should be corrected before handing the prompt to an implementer.
- **Could fix:** A limited, proven improvement to clarity or verification that is not required to make the task safe and executable. Do not use this for style preferences.

Confidence means:

- **5:** Confirmed by the cited source, repository evidence, or a direct contradiction/reproduction.
- **4:** Strong evidence with no credible alternative explanation.
- **3:** Probable, but some repository or runtime evidence is unavailable.
- **0 to 2:** Do not report. Investigate further or mark the area unverified.

Use plain words. State what an implementer would do wrong, when the problem occurs, and who or what is affected. Cite exact sections, paths, symbols, commands, or prompt lines where possible. Do not disguise an unresolved design choice as a definite bug: mark it as `Blocked` when it requires an owner decision. When the resolution of a finding depends on another task's unmerged implementation, report the finding as `Blocked`, naming the dependency — never a `Must fix` or `Should fix` finding with a `Suggested fix`.

## Verdict

Start the report with a short review frame containing:

```text
Prompt: <path>
Source task: <roadmap path and task identifier, or not found>
Specs checked: <spec paths/sections>
Implementation review: Not performed; this was a pre-implementation task-prompt review.
```

Then list findings in priority order. If there are no findings, say so explicitly. Also list material areas that remain unverified, such as an external AWS behavior, a missing prerequisite branch, or a spec section that could not be located.

End with a declaration line of exactly this form, on its own line:

Verdict: Approve

Write `Approve`, `Request changes`, or `Blocked` after the label, followed by a brief statement of what remains unverified. The orchestrator reads that declaration mechanically, so do not put the verdict in a heading, a code span, or a sentence.

- A `Must fix` or `Should fix` finding requires `Request changes`.
- `Could fix` findings do not prevent `Approve`.
- Use `Blocked` when a material unresolved ambiguity or missing authority prevents a safe review or would force the implementer to guess.

`Approve` means the prompt is ready to hand to an implementer; it does not mean the future implementation will be correct.

## Boundaries

- Review the task prompt, its source task, cited specs, relevant conventions, and enough repository context to validate its assumptions. Do not conduct a whole-repository audit.
- Do not rewrite the prompt during the review. Describe the required correction instead.
- Do not implement any requirement, create tests, change dependencies, run deployment commands, create branches, commit, or open a pull request.
- Do not mark a missing implementation as a defect; the implementation is intentionally not present yet. Mark a prompt requirement as defective only when it is missing, contradictory, impossible, unsupported by its source, or not verifiable.
- Do not treat a prompt's extra detail as wrong merely because the roadmap is terse. Confirm it against the cited specs and repository conventions.
- Do not approve solely because the prompt is detailed or cites tests. Check that the requirements and tests actually prove the intended behavior.
