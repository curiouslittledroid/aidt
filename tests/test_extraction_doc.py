"""Consistency checks pinning the *historical* status of ``docs/migration/EXTRACTION.md``.

E9.3 ("Move this document to history") finalises the extraction plan **in place**: the file
stays at ``docs/migration/EXTRACTION.md`` — pinned by
``tests/test_design_doc.py::test_contract_links_are_existing_cross_references`` and cited from
``design.md`` §1/§3/§17, ``AGENTS.md`` and ``README.md`` — and only its front-matter changes, so
a reader is redirected to the live artifacts instead of stranded on a plan that says the
extraction has not started (EXTRACTION.md §3.12 "this document, kept as history").

The roadmap's "moved file" deliverable is terse and the failure mode is silent, so this module is
the executable half of it (AGENTS.md: pytest is the only verification). It asserts, against the
file read from the toolkit root:

- the header states the document is historical and the extraction complete, and names the two
  live artifacts by path: ``design.md`` (design of record) and
  ``docs/tasks/00 - Extraction.md`` (the repo's own roadmap, superseding §6's E0–E9 list);
- no live-status claim survives anywhere in the file — the two replaced front-matter lines are
  *replaced*, never appended to ("HISTORICAL" above "not yet started" is a self-contradicting
  header, which is exactly what E9.3 exists to remove);
- the decision trail design.md §17 cites by identifier is intact: §2 (D1–D24), §6 (every
  E0.1–E9.4 entry, with the checkbox tally the historical record was written with — E9.3 must
  not tick anything) and §10 (R1–R18), each row still carrying content. Blanking or renumbering
  one drops the trail §17 exists to keep.

Also deliberately *not* tested: the body's stale wording (§0 instructions, §6 checkboxes as
prose, §8 acceptance criteria, §9 non-goals) — the document is historical as-is and E9.3 owns the
front-matter only; and the roadmap checkbox in ``docs/tasks/00 - Extraction.md``, which
``update-traceability`` owns.

The header checks are proved non-vacuous by doctoring: restoring the old status line, dropping a
pointer, blanking a decision row, deleting §10 and ticking a §6 box must each produce a violation,
while a synthetic compliant header must not — so neither a permanently-failing nor a
permanently-passing check can ship here.
"""

from __future__ import annotations

import re

from aidw.paths import toolkit_root

_RELATIVE_PATH = "docs/migration/EXTRACTION.md"

# §6's per-epic entry counts as written (D1–D24 in §2, R1–R18 in §10, below). Pinned so a
# renumbering or a deleted task fails here rather than after a reader follows a dangling id.
_TASK_COUNTS = {
    "E0": 8,
    "E1": 6,
    "E2": 9,
    "E3": 7,
    "E4": 8,
    "E5": 4,
    "E6": 4,
    "E7": 5,
    "E8": 5,
    "E9": 4,
}

# The historical record was written with E0.1–E0.6 (and later work) ticked and the rest open;
# the tally is part of that record. E9.3 changes the header only — ticking this document's own
# E9.3 box here would rewrite history instead of recording it.
_TASKS_DONE = 8
_TASKS_OPEN = 52

# The two replaced front-matter claims (in any casing), plus the phrase that asserted a *live*
# source of truth. A "Mythical Forge" mention is allowed as provenance; these are not.
_LIVE_STATUS_CLAIMS = (
    "not yet started",
    "no code has moved",
    "source of truth today",
)

_LIVE_ARTIFACTS = ("design.md", "docs/tasks/00 - Extraction.md")


def _extraction_md() -> str:
    return (toolkit_root() / _RELATIVE_PATH).read_text(encoding="utf-8")


def _header(doc: str) -> str:
    """Everything before §0 — the title and the front-matter E9.3 owns."""
    return doc[: doc.index("## 0. How to use this document")]


def _section(doc: str, heading: str, next_heading: str | None) -> str:
    """Return one section, or ``""`` when it is gone.

    Fail closed: a deleted section is the drift these checks exist to report, so it must come
    back as a violation for the caller to list rather than as an exception here.
    """
    start = doc.find(heading)
    if start < 0:
        return ""
    if next_heading is None:
        return doc[start:]
    end = doc.find(next_heading, start)
    return doc[start:] if end < 0 else doc[start:end]


def _header_violations(doc: str) -> list[str]:
    """Header requirements: historical, complete, and a redirect to both live artifacts."""
    header = _header(doc)
    lowered = header.lower()
    violations: list[str] = []
    if "historical" not in lowered:
        violations.append("header does not state the document is historical")
    if "complete" not in lowered:
        violations.append("header does not state the extraction is complete")
    for artifact in _LIVE_ARTIFACTS:
        if artifact not in header:
            violations.append(f"header does not name the live artifact {artifact!r}")
    if not re.search(r"supersed\w*", header, re.IGNORECASE):
        violations.append("header does not state that the roadmap supersedes §6's task list")
    if "§6" not in header:
        violations.append("header names no section (§6) as superseded")
    return violations


def _live_status_violations(doc: str) -> list[str]:
    """No front-matter claim that the extraction is still pending survives anywhere."""
    lowered = doc.lower()
    return [phrase for phrase in _LIVE_STATUS_CLAIMS if phrase in lowered]


def _table_rows(section: str, identifier: str) -> dict[str, str]:
    """The ``| <id> | ... |`` rows of one decision table, keyed by id, with their content."""
    rows: dict[str, str] = {}
    for line in section.splitlines():
        match = re.match(rf"^\|\s*({identifier}\d{{1,2}})\s*\|(.*)$", line)
        if match:
            rows[match.group(1)] = match.group(2).strip()
    return rows


def _decision_rows_violations(
    section: str, prefix: str, count: int, section_name: str
) -> list[str]:
    """Every identifier is present exactly once and its row still says something."""
    rows = _table_rows(section, prefix)
    expected = [f"{prefix}{number}" for number in range(1, count + 1)]
    violations = [
        f"{section_name}: {identifier} missing" for identifier in expected if identifier not in rows
    ]
    violations += [
        f"{section_name}: {identifier} row is blank" for identifier, body in rows.items() if not body
    ]
    unexpected = sorted(set(rows) - set(expected))
    violations += [f"{section_name}: unexpected identifier {identifier}" for identifier in unexpected]
    return violations


def _trail_violations(doc: str) -> list[str]:
    """§2 (D1–D24), §6 (E0.1–E9.4) and §10 (R1–R18) survive the historical header intact."""
    locked = _section(doc, "## 2. Locked decisions", "## 3. Target architecture")
    tasks = _section(doc, "## 6. Tasks", "## 7. Mythical Forge adoption and cutover")
    resolved = _section(doc, "## 10. Decisions resolved while writing", None)

    violations = _decision_rows_violations(locked, "D", 24, "§2")
    violations += _decision_rows_violations(resolved, "R", 18, "§10")

    found = re.findall(r"^-\s*\[([ xX])\]\s*\*\*(E\d+\.\d+)\b", tasks, re.MULTILINE)
    expected = {
        f"{epic}.{number}"
        for epic, count in _TASK_COUNTS.items()
        for number in range(1, count + 1)
    }
    identifiers = [identifier for _mark, identifier in found]
    violations += [
        f"§6: task {identifier} missing" for identifier in sorted(expected - set(identifiers))
    ]
    violations += [
        f"§6: task {identifier} appears {identifiers.count(identifier)} times"
        for identifier in sorted(set(identifiers) & expected)
        if identifiers.count(identifier) != 1
    ]
    done = sum(1 for mark, _identifier in found if mark.lower() == "x")
    open_ = sum(1 for mark, _identifier in found if mark == " ")
    if done != _TASKS_DONE or open_ != _TASKS_OPEN:
        violations.append(
            f"§6: checkbox tally is {done} done / {open_} open, "
            f"expected {_TASKS_DONE} / {_TASKS_OPEN} (the historical record)"
        )
    return violations


def test_document_stays_at_the_historical_path() -> None:
    """E9.3 is an in-place header edit; a relocation breaks the design.md §3 cross-reference.

    The plan's "move to history" is its historical-status step, not a `git mv`: §3.12,
    design.md §3 and ``test_design_doc.py``'s path pin all keep the file at
    ``docs/migration/EXTRACTION.md`` ("kept as history").
    """
    path = toolkit_root() / _RELATIVE_PATH
    assert path.is_file(), f"{_RELATIVE_PATH} must stay at its pinned path"
    assert not (toolkit_root() / "docs/history" / "EXTRACTION.md").exists()


def test_header_marks_the_plan_historical_and_names_the_live_artifacts() -> None:
    """The header redirects a reader instead of stranding them on a superseded plan."""
    violations = _header_violations(_extraction_md())
    assert not violations, "\n".join(violations)


def test_no_live_status_claim_survives_the_header() -> None:
    """The stale status lines are replaced, not merely preceded by a "historical" note."""
    violations = _live_status_violations(_extraction_md())
    assert not violations, f"live-status claims still present: {violations}"


def test_decision_trail_survives_the_historical_header() -> None:
    """design.md §17 cites D1–D24/R1–R18 here; "historical" must not mean "emptied"."""
    violations = _trail_violations(_extraction_md())
    assert not violations, "\n".join(violations)


def test_the_checks_are_not_vacuous() -> None:
    """Every check fires on the edit it exists to catch, and accepts a compliant header.

    The reversions are the ones the task names: put the old status lines back, drop a live
    artifact pointer, blank a decision row, delete §10, and tick a §6 box. A check that passes
    on all of those — or one that rejects a correct header — would let the drift through.
    """
    doc = _extraction_md()

    reverted_status = re.sub(
        r"\*\*Status:.*?(?=\*\*Audience:)",
        "**Status:** approved plan, not yet started. No code has moved.\n"
        "**Source of truth today:** `aidt/` inside the Mythical Forge repo.\n",
        doc,
        count=1,
        flags=re.DOTALL,
    )
    assert reverted_status != doc
    assert _live_status_violations(reverted_status), "reverted status line must be caught"
    assert _header_violations(reverted_status), "reverted status line must fail the header check"

    dropped_pointer = doc.replace("docs/tasks/00 - Extraction.md", "")
    assert dropped_pointer != doc
    assert _header_violations(dropped_pointer), "a dropped roadmap pointer must be caught"

    dropped_design = doc.replace("`design.md` — the design of record", "")
    assert dropped_design != doc
    assert _header_violations(dropped_design), "a dropped design.md pointer must be caught"

    blanked_row = re.sub(r"^\| D5 \|.*$", "| D5 | ", doc, count=1, flags=re.MULTILINE)
    assert blanked_row != doc
    assert _trail_violations(blanked_row), "a blanked §2 row must be caught"

    without_section_10 = doc.split("## 10. Decisions resolved", 1)[0]
    assert without_section_10 != doc
    assert _trail_violations(without_section_10), "a deleted §10 must be caught"

    ticked_task = doc.replace("- [ ] **E9.3", "- [x] **E9.3", 1)
    assert ticked_task != doc
    assert _trail_violations(ticked_task), "ticking a §6 box rewrites the historical record"

    compliant_header = (
        "# AIDT Extraction Plan\n\n"
        "**Status: historical — the extraction is complete.** Not a live source of truth.\n"
        "**Read instead:** `design.md` and `docs/tasks/00 - Extraction.md`, which supersedes\n"
        "§6's task list.\n\n"
        "## 0. How to use this document\n"
    )
    assert _header_violations(compliant_header) == []
    assert _live_status_violations(compliant_header) == []
