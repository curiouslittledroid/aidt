# Prompt classification — EXTRACTION.md §4.2, after the MF.2 cutover

Execution record for **E7.1 Classify and relocate** and **MF.2 Move the product prompts**.

EXTRACTION.md §4.2 fixed the inventory by naming three buckets over the toolkit's 31 top-level
`prompts/*.md` files — 6 + 5 + 20. The cutover has now run: **17 of the 20 product prompts moved to
Mythical Forge's `aidw/prompts/`** (where they shadow the toolkit default by filename, D14
precedence 2), and **3 stayed here as neutral defaults**, because they are wired into the toolkit's
default workflow chains and a target repo with no `aidw/` folder must still run (§8.3 acceptance).

That deviation from MF.2's literal "none remains in the toolkit" is deliberate and recorded in
`design.md` §17 (M4). The 3 kept files were rewritten to be product-free at cutover; the product
text lives on in Mythical Forge's own copies, which is where it is maintained now.

Membership stays **spec-fixed**, never re-derived by grepping for product tokens: §4.2 deliberately
kept `git-update.md` and `review-findings-to-github.md` in bucket (i) despite their frozen marker
strings, and `task-prompt.md` in bucket (iii) even though it named the toolkit's own directory.
`tests/test_prompt_classification.py` asserts both halves of that partition — the 14 files present
Class `(iv)` is the one post-cutover addition: `update-roadmap.md`, the core `I7` stage H3.1
added so the roadmap tick has an owner independent of the repo-optional traceability stage. It was
not part of §4.2's 31-file inventory, so it carries its own class rather than being back-dated into
one of the three buckets.

here and the 17 that must be absent — so a prompt that is deleted, re-added, or quietly re-bucketed
fails there rather than after the next release.

## In the toolkit (14 files)

| Prompt file | Class | Action | Destination |
|---|---|---|---|
| `approve-review-followups.md` | (i) | ship as-is | toolkit `prompts/` |
| `code-review.md` | (i) | ship as-is | toolkit `prompts/` |
| `git-update.md` | (i) | ship as-is | toolkit `prompts/` |
| `review-findings-to-github.md` | (i) | ship as-is | toolkit `prompts/` |
| `task-review-fixes.md` | (i) | ship as-is | toolkit `prompts/` |
| `task-review.md` | (i) | ship as-is | toolkit `prompts/` |
| `fix-next-review-followup.md` | (ii) | neutralised in E7.2 | toolkit `prompts/` |
| `impliment-task.md` | (ii) | neutralised in E7.2 | toolkit `prompts/` |
| `pr.md` | (ii) | neutralised in E7.2 | toolkit `prompts/` |
| `record-implementation-results.md` | (ii) | neutralised in E7.2 | toolkit `prompts/` |
| `test.md` | (ii) | neutralised in E7.2 | toolkit `prompts/` |
| `task-prompt.md` | (iii) | retained and neutralised in MF.2 | toolkit `prompts/` |
| `update-architecture.md` | (iii) | retained and neutralised in MF.2 | toolkit `prompts/` |
| `update-traceability.md` | (iii) | retained and neutralised in MF.2 | toolkit `prompts/` |
| `update-roadmap.md` | (iv) | added after the cutover (H3.1) | toolkit `prompts/` |

The three retained files are the ones the default registry invokes: `task-prompt.md` is stage
`P1` of the `prompt` workflow, and `update-traceability.md` / `update-architecture.md` are stages
`I3` / `I4` of the default `implement` chain. Every other product prompt was reached only by
`aidw exec --prompt <name>` or by prose in another prompt, so removing it changes no stage: a repo
that wants one supplies a same-named file under its own `aidw/prompts/`.

## Moved to Mythical Forge at MF.2 (17 files)

- `doc-lambdas.md`
- `implement-srd-followup.md`
- `integration-tests.md`
- `manual-test-plan.md`
- `show-updated-integration-tests.md`
- `show-updated-player-actions.md`
- `update-authentication-sequence-diagram.md`
- `update-infrastructure-diagram.md`
- `update-lambda-dataflow-diagram.md`
- `update-player-ws-message-flow-diagram.md`
- `update-rules-engine-diagram.md`
- `update-rules-engine-diagram-combat.md`
- `update-rules-engine-diagram-movement.md`
- `update-rules-engine-diagram-progression.md`
- `update-rules-engine-diagram-skills.md`
- `update-rules-engine-diagram-spells.md`
- `update-rules-engine-diagram-vision-world.md`

They moved with their filenames unchanged, so they still resolve by name in the target repo, and
the toolkit prompts that used to name them in prose now name the **stage** instead (`/test`,
`/record-implementation-results`, `/pr`, …) — a toolkit default must not point at a file it does not
ship. The `destination:` frontmatter marker E7.1 used to track the pending move is gone with them:
no toolkit prompt carries it any more.

## What the guard asserts

`tests/test_prompt_classification.py` pins, in both directions:

- the 14 files present here are exactly the rows of the table above, and the 17 listed as moved are
  absent from the toolkit;
- the four sets partition §4.2's own named lists (6 / 5 / 3 / 17 = 31), read from
  `docs/migration/EXTRACTION.md` rather than re-derived;
- bucket (i) is byte-identical to the pre-E7.1 baseline revision, so "ship as-is" keeps meaning it;
- the three retained defaults render at the positional arity their stages pass (`$1 $2 $3` for the
  author stage, `$1` for traceability, `$1 $2` for architecture), and
  `tests/test_prompt_neutrality.py` asserts their rendered text names no package manager, product
  path or product doc.
