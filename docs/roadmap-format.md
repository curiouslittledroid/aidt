# The AIDT roadmap format

**Status.** Written by E5.1. This document is the format *contract*: the structure
`aidw/roadmap.py` accepts and the structure `aidw tasks` / `aidw prompt` therefore require.
It deliberately documents behaviour the shipped parser already has; it introduces none.

| Activity | Owner |
|---|---|
| This doc | E5.1 (done) |
| Driving the parser from `paths.roadmap_dir` + `paths.roadmap_glob` | E5.2 (done — see §3) |
| Format *validation* with file/line/rule errors | E5.3 (done — `aidw/roadmap.py:validate_tasks`, surfaced by `aidw tasks --validate`; see §10) |
| Promoting this doc's example to the single source the parser tests read | E5.4 (done — `tests/conftest.py:roadmap_example`; see §9) |

**The code wins.** `aidw/roadmap.py` is normative. Every structural claim below is derived
from the five compiled patterns in that module (`TASK_RE`, `EPIC_RE`, `PHASE_RE`, `DONE_RE`)
and `_FILENAME_RE`, plus `derive_epic`. If this document and the code ever disagree, the code
is correct and this document is a bug.

---

## 1. One format, one owner (D6/D15)

The roadmap/task concept lives in AIDT, not in the target repo (**D6**). AIDT documents and
owns **one** roadmap format; a target repo supplies only the directory and the filename
pattern (**D15**). Concretely, the whole per-repo surface is:

| Config key | Toolkit default | Effect |
|---|---|---|
| `paths.roadmap_dir` | `docs/tasks` | the directory the phase files live in |
| `paths.roadmap_glob` | `[0-9]* - *.md` | the filename pattern selecting phase files |

Both come from `<target>/aidw/config.yaml` and resolve through the normal config layering
(EXTRACTION.md §3.4/D17). `roadmap_glob` is a glob, and `*` matches spaces too — so the
default's spacing is the naming convention, not a strictness guarantee: a spaceless
`[0-9]*-*.md` matches `00 - Extraction.md` as well. The default `[0-9]* - *.md` (a space on
**each** side of the dash) is the canonical convention the phase files are named by
(`00 - Extraction.md`; the worked example in §3 is `07 - Example Roadmap.md`). What it does
not select is a name outside its scope: `example-roadmap.md` (no two-digit prefix) or
`00 - Extraction.txt` (not `.md`).

There is **no per-repo dialect** — no configurable regexes, no alternate heading syntax, no
repo-specific parser. A second dialect defeats the point of the toolkit owning the concept
(D15), and EXTRACTION.md §9 lists it as a non-goal.

Where the roadmap is read:

- `aidw tasks` — lists entries, `--todo`, `--phase`, `--epic`, `--show`, `--next`, `--validate`
  (design §11).
- `aidw prompt` — resolves `<phase> <epic> <task>` to an entry; a missing entry exits `2`
  ("roadmap task not found"), and the entry feeds the stage evidence bundle (design §8.1,
  L2.4). The prompt stage re-reads the entry's own file for the full `Done when` block and the
  citations, so the file layout in this document matters twice.
- `aidw implement` does **not** read the roadmap: it derives `(phase, task, branch)` from the
  task-prompt *filename*.

---

## 2. The contract is five regexes

These are the shipped patterns, character for character. A line that matches none of them is
ignored — the parser never guesses, never repairs and never reports (validation is the separate
`validate_tasks` pass, §10).

| Name | Pattern | What it produces |
|---|---|---|
| `_FILENAME_RE` | `^(\d{2}(?:\.\d+)?)\s*-\s*(.*)\.md$` | the **phase id** (group 1) and the human name (group 2) |
| `PHASE_RE` | `^#\s+Phase\s+([0-9.]+):?\s*(.*)$` | `RoadmapTask.phase_title` (cosmetic) |
| `EPIC_RE` | `^##\s+Epic\s+([A-Za-z0-9]+):\s*(.*)$` | `RoadmapTask.epic_title` (cosmetic) |
| `TASK_RE` | `^\s*-\s*\[([ xX])\]\s*\*\*([A-Za-z0-9.]+)\.\s*(.*?)\*\*(.*)$` | the entry: checkbox, id, title, detail |
| `DONE_RE` | `^\s*(?:-\s*)?\**Done when:?\**\s*(.*)$` (IGNORECASE) | the `Done when` line |

The entries themselves are Python constants, so `TASK_RE.pattern` and the row above are the
same string:

```python
TASK_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s*\*\*([A-Za-z0-9.]+)\.\s*(.*?)\*\*(.*)$")
EPIC_RE = re.compile(r"^##\s+Epic\s+([A-Za-z0-9]+):\s*(.*)$")
PHASE_RE = re.compile(r"^#\s+Phase\s+([0-9.]+):?\s*(.*)$")
DONE_RE = re.compile(r"^\s*(?:-\s*)?\**Done when:?\**\s*(.*)$", re.IGNORECASE)
_FILENAME_RE = re.compile(r"^(\d{2}(?:\.\d+)?)\s*-\s*(.*)\.md$")
```

Two structural consequences follow from the anchors alone and are worth stating once:

- `PHASE_RE` and `EPIC_RE` start at `^#`, with **no** leading `\s*`, so a phase/epic heading
  must begin in column 0. (Extra spaces *after* the `#` are fine: `#  Phase 07:` matches.)
- `TASK_RE` and `DONE_RE` do allow leading whitespace (`^\s*`), so entries may be indented.

---

## 3. Directory and filename

A roadmap file is `<phase> - <name>.md` where `<phase>` is **exactly two digits**, optionally
followed by `.` and more digits for a sub-phase. `roadmap.py`'s own docstring states the same
rule generically (a two-digit phase id, optionally `.` plus digits) and names no repository.

| Filename | Result |
|---|---|
| `07 - Example Roadmap.md` | phase `07`, name `Example Roadmap` |
| `02.5 - Extraction II.md` | phase `02.5` |
| `7 - Example Roadmap.md` | **ignored** — `_FILENAME_RE` requires two digits |
| `000 - Extraction.md` | **ignored** |
| `example-roadmap.md` | **ignored** (and the default glob would not select it either) |

`load_tasks(<dir>, <glob>)` parses the files in `<dir>` that `<glob>` selects;
`parse_file(path, phase)` parses one file for a phase id the caller supplies. Both take the
phase from the **filename prefix**, never from the `# Phase` heading, because the
`/task-prompt` workflow needs the zero-padded form that the task-prompt filename and the
branch name are built from. The phase is what `aidw prompt 00 E0 E0.1` must be given — `0`
does not match `find_task`.

Since E5.2 the two calls are wired to the config: `<dir>` is `paths.roadmap_dir` and `<glob>`
is `paths.roadmap_glob`, both resolved through the normal layering (§1) and joined against
the target root (an absolute value wins). The glob only **pre-selects** candidates;
`_FILENAME_RE` stays the phase authority, so a name the glob admits but the pattern rejects
(`0 - x.md`, `0123 - x.md`) is still ignored. The parser itself carries neither a directory
nor a default pattern. The *format* rules below are unaffected by either config key.

---

## 4. Headings (`PHASE_RE`, `EPIC_RE`)

```text
# Phase 07: Example phase
## Epic E5: Roadmap contracts
```

Both headings are **cosmetic**. They set `phase_title` / `epic_title` on the entries that
follow and nothing else:

- `RoadmapTask.phase` always comes from the filename (§3).
- `RoadmapTask.epic` always comes from `derive_epic(task_id)` (§5), never from the nearest
  `## Epic` heading.

Details that follow from the patterns:

- The colon after the phase number is optional (`# Phase 07 Example phase` still matches);
  the colon after the epic id is required.
- `# Phase` accepts only digits and dots (`[0-9.]+`); the epic id accepts only letters and
  digits (`[A-Za-z0-9]+`) — a dotted epic heading like `## Epic E5.1:` does **not** match.
- `parse_file` sets `phase_title` only when the heading's number equals the filename phase
  (`group(1) in (phase, phase.lstrip("0"))`), so `# Phase 07:` and `# Phase 7:` both work for
  `07 - …`, but `# Phase 0:` does not set anything for `00 - …`. A mismatch is silent:
  `phase_title` stays `None`.
- `epic_title` is simply the most recent `## Epic` heading seen before the entry, so a task
  whose derived epic differs from that heading keeps the stale title. Write the heading to
  match the entries under it; nothing enforces the pairing.
- An entry before any `## Epic` heading parses normally with `epic_title is None`.

---

## 5. Task entries (`TASK_RE`)

The canonical entry is one line:

```text
- [ ] **E5.3. Format validation with actionable errors** <detail: punctuation, prose, citations>
```

Decoded against `TASK_RE`'s four capture groups plus the literal separator:

| Group | Pattern | Meaning |
|---|---|---|
| 1 | `[ xX]` | checkbox state: `x`/`X` = done, a space = todo |
| 2 | `[A-Za-z0-9.]+` | the **task id** |
| 3 | `(.*?)` | the **title**, everything up to the closing `**` |
| 4 | `(.*)` | the **detail**: the rest of the physical line |
| — | `\.` | a literal period between the id and the title |

Rules that matter:

- **The bold and the period are both mandatory.** The id must be followed by `.` *inside* the
  bold, then optional spaces, then the title, then `**`.
- **The id charset is `[A-Za-z0-9.]+`** — letters, digits and dots. `E5.1`, `E5`, `A1` and
  `MF.1` are all valid ids. Nothing requires the id *itself* to contain a dot (`E2` is a valid
  id); the period that follows it is the separator between id and title, not part of the id.
- The checkbox may be `- [ ]` or `- [x]`/`- [X]`; the leading `-` may be followed by any
  amount of whitespace, and the whole line may be indented.
- Anything after the closing `**` is the *detail*; it is where citations live (§8). The
  detail may be empty.

### The collapsed-id trap (E0.7 rule 1)

`- [x] **E0.1 Create the new repository**` — no period after `E0` — parses as **task id `E0`**
with **title `1 Create the new repository`**. It does not fail: it silently makes every entry
in the file collapse to the epic-level id with a stray leading digit in the title, so
`find_task` finds nothing and `aidw prompt` exits `2`. Always write `**E0.1. Create …**`.

The one-line guard from E0.7 exists for exactly this, and reports any id that lost its dot:

```bash
uv run python -c 'import pathlib; from aidw.roadmap import load_tasks; t=load_tasks(pathlib.Path("docs/tasks"), "[0-9]* - *.md"); assert t, "no tasks parsed"; bad=[x.task for x in t if "." not in x.task]; assert not bad, f"MISPARSE: {bad}"; print(f"{len(t)} tasks, none collapsed")'
```

### `derive_epic`

`epic` is computed from the id, never read from a heading:

| Task id | `epic` | Rule |
|---|---|---|
| `E2.9` | `E2` | text before the first `.` |
| `E1.1` | `E1` | text before the first `.` |
| `A1` | `A` | no dot → the leading run of letters |
| `E2` | `E` | no dot → the leading run of letters |
| `E5.1` | `E5` | text before the first `.` |

The lookup follows the same derivation, which is why `aidw prompt 00 E0 E0.1` needs the epic
to match the id's prefix: `find_task` matches on phase + task first, and phase + epic + task
second.

---

## 6. The `Done when` block (`DONE_RE`)

`Done when` is the acceptance check for the entry and is **required** for a well-formed
roadmap. The parser accepts an entry without one and stays silent (it never reports, §10); the
requirement is checked by the separate `validate_tasks` pass, whose first rule is
`missing Done when`.

The canonical form is a two-space bullet directly under the entry:

```text
- [ ] **E5.2. Generalise the parser** (Design 11)
  - Done when: the fixture repo's roadmap parses with no code change, and
    `uv run --frozen pytest` is green.
```

What `DONE_RE` tolerates:

- any casing (`Done when`, `DONE WHEN`, `done when`) — the pattern is `IGNORECASE`;
- an optional leading `- ` bullet, and any leading whitespace;
- optional `**` emphasis around the label (`**Done when:** …`);
- an **optional colon** (`Done when x` matches too — write the colon);
- any text after it, which becomes the done-when text.

What is fixed: the words `Done when` must appear, in that order, on one physical line.

### Two readers, two rules

The block has **two** consumers, and they read different amounts of it:

1. `RoadmapTask.done_when` is filled from the **first physical line only** — the text after the
   label on that line. That is what `aidw tasks --show` prints.
2. `aidw/workflows/prompt.py:_done_when_block` re-reads the entry's file and keeps **every
   continuation line** so the stage evidence bundle can show the whole check. It starts at the
   task line, scans forward to the `Done when` line (blank lines before it are skipped, a
   heading or the next task entry aborts with `unavailable`), then keeps every following line
   until the first of:
   - a blank line,
   - a heading (`#` in column 0),
   - the next task entry (a line matching `TASK_RE`),
   - the next field bullet — a line matching `^  - [A-Za-z][\w ]*:` (§7).

Consequences for writers:

- **Continuation lines must be contiguous** with the `Done when:` line. A blank line directly
  after the `Done when:` line ends the block with no continuation at all; a blank line after a
  continuation line truncates it there. `RoadmapTask.done_when` is a one-line fragment by
  design, so the full block only survives if it is unbroken.
- **Blank lines *between* the entry and its `Done when:` line are harmless**: `parse_file`'s
  scan skips them until the label appears, and `_done_when_block` does the same. (E0.7 rule 5
  claims this breaks; that claim is stale against the shipped parser. Follow the code.)
- Continuation indentation is free-form — there is no pattern for it — but a continuation line
  must not be blank, must not start with `#`, must not look like a task entry, and must not be
  shaped like a field bullet (two spaces, `- `, a letter, a label, a colon; §7).
- Write one `Done when` per entry. A second one is never merged: `parse_file` keeps the
  first in every form. What `_done_when_block` does with the second line depends on its
  shape — a bulleted `  - Done when: …` is itself a field bullet (§7) and so **truncates the
  block** before it, dropping the second line from the stage evidence bundle; a bare
  `Done when: …` (no bullet) is not a field bullet and is carried into the block as an
  ordinary continuation line.

---

## 7. Optional field bullets (`  - Tests:`, `  - Deliverable:`, `  - Notes:`)

Below the entry (conventionally after the `Done when` block) a task may carry field bullets:

```text
- [ ] **E6.1. Move markers into resolved config** (EXTRACTION.md §3.9)
  - Done when: the bundled scripts still run standalone with no config present.
  - Tests: `tests/test_review_followup.py`
  - Deliverable: config plumbing plus tests.
  - Notes: keep the bundled scripts stdlib-only.
```

Recognition is `_FIELD_BULLET_RE = ^  - [A-Za-z][\w ]*:` — **exactly two spaces**, then `- `,
then a label starting with a letter and containing only word characters or spaces, then a
colon. So `  - Tests:` matches, and all of these do **not**:

| Line | Recognised? | Why |
|---|---|---|
| `  - Tests: …` | yes | canonical |
| `   - Tests: …` | no | three spaces before the dash |
| ` - Tests: …` | no | one space |
| `    - Tests: …` | no | four spaces |
| `  -Tests: …` | no | no space after the dash |
| `\t- Tests: …` | no | a tab is not two spaces |

Two important properties:

- **Field bullets are not stored.** `RoadmapTask` has no `tests`/`deliverable`/`notes` field;
  the parser ignores these lines. They exist because a human (and the prompt stage) reads them.
- **Their only machine role is bounding the `Done when` block.** That is why the exact
  two-space indent matters: a four-space or unbulleted `Tests:` line is *not* a boundary, so
  `_done_when_block` swallows it into the `Done when` block and the stage evidence shows the
  `Tests:` text as if it were part of the acceptance check. Indent field bullets with exactly
  two spaces.

`  - Done when:` is itself an instance of this bullet form — `Done when` matches
`[A-Za-z][\w ]*` — which is why the canonical form reads as a field bullet. The bare
`Done when: …` form is tolerated by `DONE_RE`, but the bulleted form is canonical and the only
one whose shape is consistent with the other fields.

---

## 8. Optional citations

There are **two independent citation channels**. They do not merge, and only one of them
reaches `RoadmapTask.citations`.

### 8.1 `Design N` / `Design N.M` → `RoadmapTask.citations`

`CITATION_RE = Design\s+\d+(?:\.\d+)?` scans the entry's **detail** (the text after the bold)
and the first physical `Done when` line. Matches are collected into a set and sorted, so
`RoadmapTask.citations` is de-duplicated and order-independent.

`aidw tasks --show` prints them as `Specs:     Design 8.1`; the stage evidence bundle
renders each as `Design 8.1 → design.md §8.1`.

This channel captures **only** `Design N` tokens. It never captures a filename.

### 8.2 `<NAME>.md` doc refs → the prompt stage's cited-specs section

`aidw/workflows/prompt.py:_render_cited_specs` re-reads the entry's task line and the full
`Done when` block (`_done_when_block`, §6) and recovers markdown filename tokens
(`[A-Za-z0-9_.\-]+\.md`). Each is rendered with the resolved path and a section when one can be
determined:

- a literal `§N`/`§N.M` after the token is used as the section;
- otherwise a `D<nn>` decision id after the token is mapped to the section number of the
  located file's own heading that names that decision;
- a token that cannot be located uniquely under the target root renders as `unavailable — could
  not locate the file uniquely` rather than being guessed;
- the literal token `design.md` is skipped (the `Design N` channel already covers it).

So the reference style is one parenthesised detail on the task line, naming both channels:

```text
- [ ] **E1.1. TargetRepo resolution (D19)** (Design 12, EXTRACTION.md §3.1)
```

`RoadmapTask.citations` for that entry is `["Design 12"]` — the `EXTRACTION.md` ref lives only
in the rendered cited-specs section. A doc-ref-only entry is valid:

```text
- [ ] **E6.1. Move markers into resolved config** (EXTRACTION.md §3.9)
```

That entry's `.citations` is empty, and `_render_cited_specs` still renders the doc ref.

---

## 9. Complete worked example

The whole file, `07 - Example Roadmap.md`. A filename prefix of `07` means the invocation is
`aidw prompt 07 E5 E5.1`, and the `# Phase 07:` heading matches it (it must, or `phase_title`
silently stays `None`).

```markdown
# Phase 07: Example phase

Any prose outside an entry is ignored. This paragraph is here to show that a roadmap file may
carry narrative; the parser only reads headings and task entries.

## Epic E5: Roadmap contracts

- [x] **E5.1. Write the format contract** (Design 11, EXTRACTION.md §3.7)
  - Done when: the format doc states the five-regex contract and the worked example in it
    parses with the shipped parser, and the full pytest suite is green.
  - Tests: `tests/test_roadmap_format.py`
  - Deliverable: the format document plus its contract tests.
- [ ] **E5.2. Generalise the parser** (Design 11.1)
  Done when: the fixture repo's roadmap parses without any code change.

## Epic E6: Frozen GitHub contracts

- [ ] **E6.1. Move markers into resolved config** (EXTRACTION.md §3.9)
  - Done when: the bundled scripts still run standalone with no config present.
  - Notes: keep the bundled scripts stdlib-only.
```

What the shipped parser produces from it (`aidw tasks --phase 07`):

| task | title | done | epic | `done_when` (first line only) | `.citations` |
|---|---|---|---|---|---|
| `E5.1` | `Write the format contract` | yes | `E5` | `the format doc states the five-regex contract and the worked example in it` | `["Design 11"]` |
| `E5.2` | `Generalise the parser` | no | `E5` | `the fixture repo's roadmap parses without any code change.` | `["Design 11.1"]` |
| `E6.1` | `Move markers into resolved config` | no | `E6` | `the bundled scripts still run standalone with no config present.` | `[]` |

`next_todo(tasks)` is `E5.2`; `filter_tasks(tasks, epic="E5")` is `[E5.1, E5.2]`;
`find_task(tasks, "07", "E5", "E5.2")` is the second entry. `_done_when_block` for `E5.1`
returns both of its lines and stops at the `Tests:` bullet, so the evidence bundle shows the
whole check without the field bullet; `_render_cited_specs` renders
`- Design 11 → design.md §11` and `- EXTRACTION.md → docs/migration/EXTRACTION.md §3.7`.

Note the three deliberate details: `E5.2` uses the bare `Done when:` form to show it is
tolerated (the bulleted form is canonical), `E6.1` carries only a doc ref, and every id carries
its period.

---

## 10. What the parser does not do (v1)

Deliberately out of scope, so a format problem is not mistaken for a parser bug:

- **The parser never reports.** `parse_file` and `load_tasks` are silent: a malformed entry is
  skipped, not reported, and a missing `Done when`, a duplicate id and an entry outside an epic
  all parse. They never repair a file either — the parsed fields are a function of the bytes.
- **Validation is a separate, pure pass.** `aidw/roadmap.py:validate_tasks` takes the parsed
  list, reads it without mutating it and without re-reading any file, and reports exactly three
  rules, each under the module's own rule token (`RULE_MISSING_DONE_WHEN`,
  `RULE_DUPLICATE_ID`, `RULE_OUTSIDE_EPIC`):
  - `missing Done when` — the entry's `done_when` is empty (§6).
  - `duplicate id` — a repeated `(phase, task)` pair. The key is the pair, not the id alone: the
    branch is `{phase}-{task}` and `find_task` matches phase+task, so the same id in another
    phase file is a different task. The later entry is the issue, and its message names the
    earlier `file:line`. Both entries still parse; `find_task` returns the first.
  - `entry outside an epic` — `epic_title is None`, i.e. the entry appears before any
    `## Epic` heading (§4). Deliberately **not** `epic`: `derive_epic` derives it from the id
    and never returns `None`.

  `aidw tasks --validate` is the only caller: it surfaces the report as
  `{file}:{line}: {rule} — {message}`, one line per issue, over the whole roadmap, so the
  filters `--todo`/`--phase`/`--epic` never narrow what is validated. A malformed roadmap exits
  non-zero. `parse_file`/`load_tasks` and their other callers are unchanged.
- **No dependency graph.** `--next` is the first unchecked entry in file order, and
  prerequisite ordering is the operator's responsibility (design §11).
- **No field storage.** `Tests:`/`Deliverable:`/`Notes:` are not parsed into fields (§7).
- **No cross-entry state.** A heading applies from where it appears until the next one; the
  parser never goes back and re-titles earlier entries.
- **No per-repo dialect.** Nothing here is configurable except `paths.roadmap_dir` and
  `paths.roadmap_glob` (§1, D15).

---

## 11. Produced fields (`RoadmapTask`)

| Field | Source |
|---|---|
| `phase` | filename prefix (`_FILENAME_RE` group 1) |
| `task` | `TASK_RE` group 2 — the id, dots included |
| `epic` | `derive_epic(task)` |
| `title` | `TASK_RE` group 3, stripped |
| `done` | `TASK_RE` group 1 |
| `done_when` | `DONE_RE` group 1 of the **first** `Done when` line |
| `citations` | `CITATION_RE` over the detail + first `Done when` line, sorted and de-duplicated |
| `epic_title` | the most recent `EPIC_RE` heading, or `None` |
| `phase_title` | `PHASE_RE` heading whose number matches the filename phase, or `None` |
| `file` | the file's basename |
| `line` | 1-based line number of the entry |
| `key` / `branch` | `"<phase>-<task>"`, e.g. `07-E5.1` |
