# Prompt classification — EXTRACTION.md §4.2 (E7.1)

Execution record for **E7.1 Classify and relocate**: every top-level prompt in the toolkit's
`prompts/` directory carries one explicit **bucket**, one **action**, and one **destination**.

The inventory is fixed by the spec, not re-derived: EXTRACTION.md §4.2 names the members of all
three buckets — 6 + 5 + 20 = 31 files. That section is the source of truth; this table echoes it.
Do not re-bucket by grepping for product tokens: §4.2 deliberately keeps `git-update.md` and
`review-findings-to-github.md` in bucket (i) despite their frozen marker strings, and keeps
`task-prompt.md` in bucket (iii) even though it names `aidt/prompts`. Grep would misclassify all
three, and the frozen markers are not allowed to move (D5, §3.9).

## Buckets and actions

| Bucket | Meaning | Action | Owner |
|---|---|---|---|
| (i) | Generic — no product coupling | ship as-is | none |
| (ii) | Mixed — path and tooling names, small edits | neutralise in E7.2 | E7.2 |
| (iii) | Wholly Mythical Forge — product prompts | move at cutover in MF.2 | MF.2 |

Until the cutover (§7, MF.2) every file stays exactly where it is. Bucket (iii) files are **marked
only**: they carry their intended destination in YAML frontmatter and are otherwise untouched.

## Classification

| Prompt file | Bucket | Action | Destination |
|---|---|---|---|
| `approve-review-followups.md` | (i) | ship as-is | toolkit `prompts/` |
| `code-review.md` | (i) | ship as-is | toolkit `prompts/` |
| `git-update.md` | (i) | ship as-is | toolkit `prompts/` |
| `review-findings-to-github.md` | (i) | ship as-is | toolkit `prompts/` |
| `task-review-fixes.md` | (i) | ship as-is | toolkit `prompts/` |
| `task-review.md` | (i) | ship as-is | toolkit `prompts/` |
| `fix-next-review-followup.md` | (ii) | neutralise in E7.2 | toolkit `prompts/` |
| `impliment-task.md` | (ii) | neutralise in E7.2 | toolkit `prompts/` |
| `pr.md` | (ii) | neutralise in E7.2 | toolkit `prompts/` |
| `record-implementation-results.md` | (ii) | neutralise in E7.2 | toolkit `prompts/` |
| `test.md` | (ii) | neutralise in E7.2 | toolkit `prompts/` |
| `doc-lambdas.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `implement-srd-followup.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `integration-tests.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `manual-test-plan.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `show-updated-integration-tests.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `show-updated-player-actions.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `task-prompt.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-architecture.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-authentication-sequence-diagram.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-infrastructure-diagram.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-lambda-dataflow-diagram.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-player-ws-message-flow-diagram.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-rules-engine-diagram-combat.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-rules-engine-diagram-movement.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-rules-engine-diagram-progression.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-rules-engine-diagram-skills.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-rules-engine-diagram-spells.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-rules-engine-diagram-vision-world.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-rules-engine-diagram.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |
| `update-traceability.md` | (iii) | move at cutover in MF.2 | Mythical Forge `aidw/prompts/` |

## Bucket (iii) marker contract

Each bucket (iii) file carries exactly one frontmatter field:

```yaml
destination: mythical-forge/aidw/prompts/
```

Three rules make the marker inert:

1. **Frontmatter only.** `aidw/prompts.py:strip_frontmatter` removes the leading `---` block
   before rendering, so the rendered prompt — the text Pi receives — is byte-identical to the
   text before the marker was added. A note in the body would render into the agent message and
   change behaviour.
2. **A minimal block, not a replaced one.** `task-prompt.md`, `integration-tests.md` and
   `manual-test-plan.md` had no frontmatter; each gained a `---` … `---` block carrying the
   destination field and nothing else. The other 17 already had a block and kept every existing
   field.
3. **No foreign prefix.** The value must never contain `.pi/prompts`: `aidw/inventory.py`
   (`FOREIGN_PREFIX`) rejects that reference from every file under `prompts/`, so
   `aidw prompts check` and `tests/test_inventory.py::test_real_inventory_is_complete` would go
   red. `mythical-forge/aidw/prompts/` is the new repo's own folder, not the old mirror.

## What this table does *not* own

- **Bucket (ii) wording.** `test.md`, `pr.md`, `fix-next-review-followup.md`,
  `record-implementation-results.md` and `impliment-task.md` are edited in E7.2. `pr.md` was
  partly edited ahead of E7.2 (§4.2's (ii) table, R17) and is left exactly as found here. The
  five keep toolkit `prompts/` as their destination; at MF.2 Mythical Forge additionally supplies
  same-named overrides through `aidw/prompts/` (D14 precedence 2, §7 MF.2), which is a copy the
  target repo owns, not a move of the toolkit default.
- **The move itself.** MF.2 relocates the 20 files with their filenames unchanged, so stage
  resolution stays by name. Nothing is moved, deleted or renamed here.
- **`prompts/scripts/`.** The bundled streaming-review scripts (`REQUIRED_SCRIPTS` in
  `aidw/inventory.py` — `scripts/review-followup/*.py`) are toolkit-owned helpers, not prompts,
  and never appear in this table.
- **Agents, configs and docs.** §4.3's inventory is E7.4's; §4.1's code inventory is not
  revisited here.

## Guard

`tests/test_prompt_classification.py` is this document's executable half: the table's filename
set equals the set of top-level `prompts/*.md` in **both** directions (no unclassified file, no
stale row), the bucket membership equals §4.2's named lists, and the marker contract above is
asserted against the real files through `strip_frontmatter`.
