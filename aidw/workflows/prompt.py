"""``aidw prompt`` — task prompt generation and review (design §8.1).

Stages:

1. ``task-prompt``      — agent ``task-author`` creates ``docs/task-prompts/<phase>-<task>-prompt.md``
                          on branch ``<phase>-<task>`` and commits it.
2. ``task-review-N``    — agent ``task-reviewer`` reviews the prompt (read-only); N starts at 1.
                          Every round receives a pointer to its own evidence bundle
                          (``<run_dir>/stages/<stage>.evidence.md``, L2.4); rounds 2+ also
                          receive a delta brief (``extra=``): a per-finding resolution
                          instruction, the previous review verbatim, and a real ``git diff``
                          of the prompt since that review (L2.3).
3. ``task-review-fixes`` — repeated (bounded) rework when the review requests changes. One
                          stage per blocking (must-fix/should-fix) finding, plus one combined
                          stage for the non-blocking could-fix findings; a single combined stage
                          carrying the whole review when it does not parse into findings. Fix
                          batches run for the first ``MAX_REVISIONS - 1`` review rounds; the
                          ``MAX_REVISIONS``-th round is review-only (the terminal review), so a
                          review is always the last stage for a non-approving prompt. Every fix
                          stage also receives a pointer to its own evidence bundle (L2.4),
                          and its input prompt is snapshotted to
                          ``<run_dir>/stages/<stage>.prompt.md`` before it runs (L3.3).
4. ``task-review-reconcile-N`` — one stage per fix batch, after the batch and before the
                          next review. It uses the ``task-fixer`` agent with
                          ``prompts/task-review-fixes.md`` and an ``extra=`` that carries the
                          whole review plus that batch's combined diff (L3.4).
5. optional gate ``approve-task-prompt``.

A real run requires ``main`` and a clean working tree, because the ``task-prompt`` prompt
requires it. It then refuses (exit 4) when an earlier task in the same ``docs/tasks/*.md``
phase file is unticked, unless ``--allow-incomplete-prereqs`` is given, then fetches
``origin`` and refuses (exit 4) when the base branch is behind or diverged from
``origin/<base>``; ``--no-fetch`` skips both the fetch and the comparison.
A ``--dry-run`` plans the stages without those preconditions, reports the incomplete
predecessors, and never touches the network.
When the author's first output line is ``blocked: <reason>`` the run ends ``blocked``
(exit 3) with the reason in the run log and on stderr; the leftovers the run can see — an
uncommitted change under ``docs/task-prompts/`` and a ``{phase}-{task}`` branch it created
during the run — are reported, never repaired (design §13, L1.3).
The approval gate is off by default; pass ``--require-approval`` to pause for a human decision.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from tempfile import mkdtemp

from aidw import git
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.findings import (
    ParsedFinding,
    findings_summary,
    finding_title,
    parse_review_findings,
    partition_findings,
    render_could_fix_block,
    render_finding_block,
)
from aidw.gates import GateOutcome, decide
from aidw.log import RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.report import print_stage
from aidw.roadmap import DONE_RE, TASK_RE, RoadmapTask, find_task, load_tasks
from aidw.runner import StageSpec, run_stage
from aidw.state import (
    BLOCKED,
    FAILED,
    SUCCEEDED,
    GateRecord,
    create_run,
    run_dir,
    save,
    utcnow_iso,
)
from aidw.verdict import APPROVE, BLOCKED as VERDICT_BLOCKED, parse_verdict

GATE = "approve-task-prompt"

#: Remote the base-branch preflight fetches (L1.1, design §8.1). Full ``git fetch origin``
#: keeps ``refs/remotes/origin/<base>`` current; a partial refspec would not.
REMOTE = "origin"

#: Exit code for a preflight/safety refusal (design §14).
EXIT_REFUSED = 4

#: Number of review rounds, and the number of revision slots. ``MAX_REVISIONS - 1`` fix
#: batches run (one stage per blocking finding, one combined stage for the could-fix
#: findings); the ``MAX_REVISIONS``-th round is review-only so a review is always the last
#: stage for a non-approving prompt. A residual `Request changes` after that terminal review
#: fails closed (``BLOCKED``, exit 3) with the findings on stderr — a reviewer that keeps
#: requesting changes must not have its last fixes accepted unreviewed. A `Blocked` verdict
#: short-circuits earlier and still fails closed, since it means a human must settle a
#: material ambiguity.
MAX_REVISIONS = 3

#: Instruction prepended to every review round after the first (L2.3, design §8.1). The
#: three verdict tokens are literal because the reviewer must emit one of them per prior
#: finding before it may raise a new one. This lives here as toolkit runtime text rather
#: than in ``prompts/task-review.md``: that prompt is bucket (i) generic and ships as-is
#: (EXTRACTION.md §4.2), so the round-specific priming is assembly, not prompt copy.
_DELTA_BRIEF_INSTRUCTION = """\
## Delta brief — resolve the previous review before raising new findings

This is a later review round, not the first. For **each** finding in the previous review
below, state a per-finding resolution verdict of exactly `resolved`, `not resolved`, or
`newly contradicted` before you raise any new finding. Judge `resolved` only from the
current prompt and the diff that follows. New findings must be genuinely new: never
re-litigate a finding you judged `resolved`."""

#: Note used when the prompt diff cannot be produced. The brief must never present a
#: silently empty diff section: the reviewer is told the evidence is missing instead (L2.3).
_DIFF_UNAVAILABLE = (
    "The prompt diff for this round is unavailable (`git diff` could not be produced); "
    "review the prompt file itself for its current state."
)

#: Note used when the two prompt snapshots are byte-identical, so the reviewer is not left
#: wondering whether a diff section went missing.
_DIFF_EMPTY = "The prompt is unchanged since the previous review."

#: Instruction prepended to the single reconcile stage that follows a fix batch (L3.4,
#: design §8.1). A fix batch edits the prompt one finding at a time (or one combined batch
#: of non-blocking findings) and is told to prefer the smallest edit, so the batch can end
#: internally inconsistent: a fix can leave a neighbouring section stale or leave a finding
#: unaddressed. This stage compares the fixed prompt against the full review text and the
#: combined diff and repairs both. It is deliberately *not* :data:`_DELTA_BRIEF_INSTRUCTION`:
#: that orders the *reviewer* to emit a ``resolved``/``not resolved``/``newly contradicted``
#: verdict per prior finding; the fixer must reconcile, not review. Like the delta brief it
#: lives here as toolkit runtime text rather than in ``prompts/task-review-fixes.md``, which
#: is bucket (i) generic and ships as-is (EXTRACTION.md §4.2).
_RECONCILE_INSTRUCTION = """\
## Reconcile the fix batch

One or more fix stages have just edited this prompt in isolation. Compare the fixed
prompt against the full review text and the combined diff below. Repair every
cross-section contradiction the edits introduced and address any finding the batch left
unaddressed. Do not review or re-litigate the findings; make the prompt internally
consistent with the review."""

#: Temp-directory prefix for the two stable-named diff snapshots. The directory is
#: removed in a ``finally`` on every path; it is never the run directory (L3.3 owns
#: ``stages/<stage>.prompt.md`` snapshots).
_DIFF_TMP_PREFIX = "aidw-prompt-diff-"


def _capture_prompt(path: Path) -> str | None:
    """The prompt's current content, or ``None`` when it cannot be read (L2.3).

    The baseline is captured in memory after a review's verdict and before that round's
    fix stages run. ``_commit_reviewed_prompt`` runs only once after the loop, so there
    are no per-round commits and a bare ``git diff -- <path>`` would be cumulative; a
    capture-then-diff makes round N's diff exactly the previous fix batch's net effect.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _no_index_diff(directory: Path, name: str) -> tuple[int, str, str]:
    """Run ``git diff --no-index`` from ``directory`` under stable relative names.

    Running from the temp directory keeps both path arguments deterministic, so the
    ``diff --git a/baseline/<name> b/current/<name>`` header is identical across rounds
    and runs — the brief must never carry a random ``/tmp/...`` path. ``git diff``
    reports differences as exit code 1, so callers must accept ``{0, 1}`` as success; the
    ``code == 0`` guards in :mod:`aidw.git` (``diff_stat``/``changed_files``) would drop
    exactly the diff this brief exists for. ``GIT_DIR``/``GIT_WORK_TREE`` are removed from
    the environment so a caller's repository context cannot redirect the comparison.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
    }
    return git._git_out(
        directory,
        ["diff", "--no-index", f"baseline/{name}", f"current/{name}"],
        env=environment,
    )


def _prompt_diff(baseline: str, current: str, *, name: str) -> str | None:
    """A real unified diff between two prompt snapshots, or ``None`` (L2.3).

    Never hand-builds a summary: both snapshots are written under stable names into a
    ``tempfile`` directory (not the run directory) and compared with ``git diff --no-index``.
    Exit 0 (identical) and exit 1 (differences) are both success; anything else is a failed
    invocation, which warns on stderr and returns ``None`` so the caller degrades the
    brief instead of failing the run. The temp directory is removed in a ``finally`` on
    every path, so a multi-round run leaves no residue.
    """
    directory = Path(mkdtemp(prefix=_DIFF_TMP_PREFIX))
    try:
        for sub, text in (("baseline", baseline), ("current", current)):
            (directory / sub).mkdir()
            (directory / sub / name).write_text(text, encoding="utf-8")
        code, out, err = _no_index_diff(directory, name)
        if code not in (0, 1):
            reason = next(
                (line.strip() for line in err.splitlines() if line.strip()),
                "git diff failed",
            )[:300]
            print(
                f"warning: could not render the prompt diff for this review round "
                f"({reason}); the delta brief names it unavailable.",
                file=sys.stderr,
            )
            return None
        if code == 0:
            return _DIFF_EMPTY
        return out.rstrip("\n")
    except OSError as exc:
        print(
            f"warning: could not stage the prompt diff for this review round "
            f"({exc}); the delta brief names it unavailable.",
            file=sys.stderr,
        )
        return None
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _render_delta_brief(
    *,
    index: int,
    previous_review: str,
    baseline: str | None,
    current: str | None,
    rel: str,
) -> str:
    """Assemble round ``index``'s ``extra=`` (instruction, prior review, diff) (L2.3).

    The previous review is passed verbatim: the roadmap says "pass them the previous
    review", and the finding blocks are already the reviewer's own format. When the
    baseline or the diff cannot be produced the instruction and the review still ship
    plus an explicit unavailable note — never a silently empty diff section.
    """
    if baseline is None or current is None:
        print(
            f"warning: could not read the reviewed prompt `{rel}` to baseline review "
            f"round {index}; the delta brief names the prompt diff unavailable.",
            file=sys.stderr,
        )
        diff_text = _DIFF_UNAVAILABLE
    else:
        diff_text = _prompt_diff(baseline, current, name=Path(rel).name)
        if diff_text is None:
            diff_text = _DIFF_UNAVAILABLE

    return "\n\n".join(
        [
            _DELTA_BRIEF_INSTRUCTION,
            "### Previous review\n\n" + previous_review,
            "### Prompt diff since that review\n\n" + diff_text,
        ]
    )


def _render_reconcile(
    *,
    index: int,
    review_text: str,
    baseline: str | None,
    current: str | None,
    rel: str,
) -> str:
    """Assemble a reconcile stage's ``extra=`` (instruction, whole review, diff) (L3.4).

    Mirrors :func:`_render_delta_brief`: the full review is passed verbatim, and when the
    baseline or the diff cannot be produced the instruction and the review still ship with
    an explicit unavailable note — never a silently empty diff section. The diff is the fix
    batch's net effect: ``baseline`` is the in-memory capture taken before the fix stages
    and ``current`` is captured before this stage edits anything.
    """
    if baseline is None or current is None:
        print(
            f"warning: could not read the reviewed prompt `{rel}` to reconcile review "
            f"round {index}; the reconcile brief names the prompt diff unavailable.",
            file=sys.stderr,
        )
        diff_text = _DIFF_UNAVAILABLE
    else:
        diff_text = _prompt_diff(baseline, current, name=Path(rel).name)
        if diff_text is None:
            diff_text = _DIFF_UNAVAILABLE

    return "\n\n".join(
        [
            _RECONCILE_INSTRUCTION,
            "### Full review\n\n" + review_text,
            "### Combined diff for this fix batch\n\n" + diff_text,
        ]
    )


# ---------------------------------------------------------------------------
# Evidence bundle (L2.4, design §8.1; EXTRACTION.md §3.8 / D16)
# ---------------------------------------------------------------------------

#: Note for a bundle section whose source could not be read. It is a normal degraded
#: state, never an error: the agent is told the evidence is missing rather than the run
#: being marked failed (L2.4, requirement 4).
_EVIDENCE_UNAVAILABLE = "unavailable — could not be read"

#: Heading that opens the target repo's gate list in ``AGENTS.md`` (L2.4). Per D16 the
#: eventual source is root ``AGENTS.md`` plus optional ``aidw/conventions.md``; E7.3 owns
#: that second channel, so this reads ``AGENTS.md`` directly and adds no second source.
_GATES_HEADING = "## Gates"

#: A field bullet inside a roadmap task entry (``  - Tests:``). The full ``Done when:``
#: block ends at the next field bullet, because that bullet introduces a different field.
_FIELD_BULLET_RE = re.compile(r"^  - [A-Za-z][\w ]*:")

#: A markdown filename token inside a task's citation detail (``EXTRACTION.md``).
_DOC_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-]+\.md")

#: A section marker (``§3.8``) and a decision id (``D16``) inside a citation window.
_SECTION_RE = re.compile(r"§\s*(\d+(?:\.\d+)?)")
_DECISION_RE = re.compile(r"\bD\d+\b")

#: A markdown heading's numbering (``### 3.8 Task-prompt format ...``).
_HEADING_NUMBER_RE = re.compile(r"^#+\s+(\d+(?:\.\d+)?)\b")


def _roadmap_lines(repo: TargetRepo, entry: RoadmapTask) -> list[str] | None:
    """Re-read the entry's own roadmap file, or ``None`` when it cannot be read."""
    try:
        return (
            (repo.root / "docs" / "tasks" / entry.file)
            .read_text(encoding="utf-8")
            .splitlines()
        )
    except OSError:
        return None


def _done_when_block(lines: list[str], task_index: int) -> str:
    """The full ``Done when:`` block for the task at ``task_index`` (L2.4).

    ``RoadmapTask.done_when`` is filled from the first physical line only, so a
    multi-line ``Done when:`` (L2.4's own is four lines) truncates to a fragment. This
    re-reads the entry's line and keeps every continuation line up to the first blank
    line, the next ``  - <Word>:`` field bullet, the next task line, or a heading.
    """
    index = task_index
    while index < len(lines):
        if index > task_index and (
            lines[index].startswith("#") or TASK_RE.match(lines[index])
        ):
            return _EVIDENCE_UNAVAILABLE
        if DONE_RE.match(lines[index]):
            break
        index += 1
    if index >= len(lines):
        return _EVIDENCE_UNAVAILABLE

    block = [lines[index].rstrip()]
    index += 1
    while index < len(lines):
        line = lines[index]
        if (
            not line.strip()
            or line.startswith("#")
            or TASK_RE.match(line)
            or _FIELD_BULLET_RE.match(line)
        ):
            break
        block.append(line.rstrip())
        index += 1
    return "\n".join(block)


def _locate_doc(root: Path, name: str) -> Path | None:
    """The unique ``<name>.md`` file under ``root``, or ``None`` when absent/ambiguous.

    A bounded ``os.walk`` prunes version-control and dependency directories so the search
    stays cheap even when it runs once per stage; a documented citation never lives in
    one of those. The citation is only a basename (``EXTRACTION.md``), so an ambiguous
    match is reported as unavailable rather than guessed.
    """
    matches: list[Path] = []
    for directory, children, files in os.walk(root):
        children[:] = [
            entry for entry in children if entry not in (".git", ".venv", "node_modules")
        ]
        if name in files:
            matches.append(Path(directory) / name)
            if len(matches) > 1:
                return None
    return matches[0] if len(matches) == 1 else None


def _decision_section(text: str, decision: str) -> str | None:
    """The section number of the heading naming ``decision`` (``D16`` → ``§3.8``)."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if not re.search(rf"\b{re.escape(decision)}\b", stripped):
            continue
        match = _HEADING_NUMBER_RE.match(stripped)
        if match:
            return f"§{match.group(1)}"
    return None


def _render_cited_specs(
    repo: TargetRepo, entry: RoadmapTask, task_line: str, done_block: str
) -> str:
    """``Design N`` citations plus the ``<NAME>.md`` doc refs ``RoadmapTask`` drops.

    ``CITATION_RE`` captures only ``Design N`` tokens, so the non-``Design`` doc
    references (``EXTRACTION.md D16``) are recovered by re-reading the task line's
    parenthesised detail and the ``Done when:`` line and mapping each ``<NAME>.md``
    token to file+section — ``§n`` directly, ``D<nn>`` via the heading that names it.
    """
    rendered: list[str] = []
    for citation in entry.citations:
        number = citation.split(maxsplit=1)[-1]
        rendered.append(f"- {citation} → design.md §{number}")

    blob = f"{task_line}\n{done_block}"
    tokens = list(_DOC_TOKEN_RE.finditer(blob))
    seen: set[str] = set()
    for position, match in enumerate(tokens):
        token = match.group(0)
        if token == "design.md" or token in seen:
            continue
        seen.add(token)
        window_end = (
            tokens[position + 1].start() if position + 1 < len(tokens) else len(blob)
        )
        window = blob[match.end() : window_end]
        path = _locate_doc(repo.root, token)
        if path is None:
            rendered.append(
                f"- {token} → unavailable — could not locate the file uniquely"
            )
            continue
        relative = path.relative_to(repo.root).as_posix()
        section_match = _SECTION_RE.search(window)
        section: str | None = None
        if section_match:
            section = f"§{section_match.group(1)}"
        else:
            decision_match = _DECISION_RE.search(window)
            if decision_match:
                try:
                    section = _decision_section(
                        path.read_text(encoding="utf-8"), decision_match.group(0)
                    )
                except OSError:
                    section = None
        rendered.append(
            f"- {token} → {relative} {section}" if section else f"- {token} → {relative}"
        )
    return "\n".join(rendered) if rendered else _EVIDENCE_UNAVAILABLE


def _render_prerequisites(entries: list[RoadmapTask], entry: RoadmapTask) -> str:
    """Every earlier task in the same phase file with its tick state (L2.4).

    Ordering matches ``_incomplete_predecessors`` (same file, strictly earlier line), but
    shows *all* predecessors — ticked and unticked — because the reviewer needs the state
    the author acted on, not only the ones that would block the run.
    """
    predecessors = [
        candidate
        for candidate in entries
        if candidate.file == entry.file and candidate.line < entry.line
    ]
    if not predecessors:
        return "- (none — this is the first task in the phase file)"
    return "\n".join(
        f"- [{'x' if predecessor.done else ' '}] {predecessor.task} — "
        f"{predecessor.title}"
        for predecessor in predecessors
    )


def _gate_block(repo: TargetRepo) -> str:
    """The target repo root's ``## Gates`` section, copied verbatim (L2.4, D16).

    Reads ``repo.root / "AGENTS.md"`` — the *target* root, never the toolkit root or a
    cwd-relative path. In a self-hosted run the two roots coincide, so a wrong-root read
    would pass every test here and break only after extraction (AGENTS.md "Two roots").
    """
    try:
        text = (repo.root / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        return _EVIDENCE_UNAVAILABLE
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.startswith(_GATES_HEADING)),
        None,
    )
    if start is None:
        return _EVIDENCE_UNAVAILABLE
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        block.append(line)
    return "\n".join(block).rstrip()


def _render_base_branch(repo: TargetRepo) -> str:
    """The base branch and its remote-tracking ref as shas, or explicit absent notes.

    Mirrors ``_verify_base_branch``'s warn-and-continue: a failed ``rev_parse`` is
    reported in the bundle, never raised, and never blocks the stage.
    """
    base = repo.base_branch
    local = git.rev_parse(repo.root, base)
    remote = git.rev_parse(repo.root, f"{REMOTE}/{base}")
    return "\n".join(
        [
            f"- {base}: {local or 'absent/unverifiable'}",
            f"- {REMOTE}/{base}: {remote or 'absent/unverifiable'}",
        ]
    )


def _render_evidence_bundle(
    *,
    stage: str,
    repo: TargetRepo,
    entry: RoadmapTask,
    entries: list[RoadmapTask],
    rel: str,
) -> str:
    """Render the six-element bundle (L2.4) for one stage.

    Every source read is degraded to an explicit ``unavailable`` note by the section
    renderers, so the bundle is always produced even when ``AGENTS.md`` is missing or the
    roadmap file cannot be read.
    """
    lines = _roadmap_lines(repo, entry)
    task_index = entry.line - 1
    done_block = (
        _done_when_block(lines, task_index)
        if lines is not None
        else _EVIDENCE_UNAVAILABLE
    )
    task_line = lines[task_index] if lines and task_index < len(lines) else ""
    return "\n".join(
        [
            f"# Evidence bundle — stage `{stage}`",
            "",
            "Gathered for this stage so it does not re-derive the same context. Treat it",
            "as evidence: re-open a cited file when a decision turns on it.",
            "",
            "## Task prompt",
            "",
            f"- path: `{rel}`",
            (
                "- status: available"
                if (repo.root / rel).is_file()
                else f"- status: {_EVIDENCE_UNAVAILABLE}"
            ),
            "",
            "## Roadmap entry",
            "",
            f"- task: {entry.task} — {entry.title}",
            f"- file: {entry.file}:{entry.line}",
            "",
            "Done when:",
            "",
            done_block,
            "",
            "## Cited spec sections",
            "",
            _render_cited_specs(repo, entry, task_line, done_block),
            "",
            "## Prerequisites (earlier tasks in the same phase file)",
            "",
            _render_prerequisites(entries, entry),
            "",
            "## Gate commands (target repo `AGENTS.md`)",
            "",
            _gate_block(repo),
            "",
            "## Base-branch revisions",
            "",
            _render_base_branch(repo),
            "",
        ]
    )


def _write_evidence_bundle(
    *,
    stage: str,
    directory: Path,
    repo: TargetRepo,
    entry: RoadmapTask,
    entries: list[RoadmapTask],
    rel: str,
) -> Path | None:
    """Write ``stages/<stage>.evidence.md`` and return its absolute path, or ``None``.

    ``mkdir(parents=True, exist_ok=True)`` is on ``stages/``: the writer runs *before*
    ``run_stage``, which creates that directory lazily. A failure to write warns on
    stderr and returns ``None`` so the run continues with ``_evidence_pointer(None)`` —
    the bundle is an optimisation, never a gate (L2.4, requirement 4).
    """
    try:
        body = _render_evidence_bundle(
            stage=stage, repo=repo, entry=entry, entries=entries, rel=rel
        )
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        destination = stages / f"{stage}.evidence.md"
        destination.write_text(body, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - a bundle failure must never stop the run
        print(
            f"warning: could not write the evidence bundle for stage `{stage}` "
            f"({exc}); the stage runs without it.",
            file=sys.stderr,
        )
        return None
    return destination.resolve()


def _evidence_pointer(path: Path | None) -> str:
    """The pointer prepended to a review or fix stage's ``extra`` (L2.4).

    The path is absolute because the agent's cwd is the repo root while the run directory
    lives under the state root, outside the tree: a relative ``stages/...`` pointer
    resolves nowhere. When the bundle could not be written, an explicit unavailable note
    (with no path) is shipped instead so no dangling pointer remains.
    """
    if path is None:
        return (
            "## Evidence bundle\n\n"
            "The gathered evidence bundle for this stage could not be written; derive the "
            "repository conventions, the cited spec sections, the prerequisite tick "
            "state and the base-branch revisions from the repository yourself."
        )
    return (
        "## Evidence bundle\n\n"
        f"Read `{path}` before working: it is the evidence bundle gathered for this "
        "stage (the prompt path, the roadmap entry with its full `Done when`, the cited "
        "spec sections, the prerequisite tick state, the target repo's gate commands and "
        "the base-branch revisions). Re-open the original sources when a decision turns "
        "on them."
    )


def _stage_evidence_pointer(
    *,
    stage: str,
    directory: Path,
    repo: TargetRepo,
    entry: RoadmapTask,
    entries: list[RoadmapTask],
    rel: str,
) -> str:
    """Write this stage's bundle and return the pointer to prepend to its ``extra``."""
    return _evidence_pointer(
        _write_evidence_bundle(
            stage=stage,
            directory=directory,
            repo=repo,
            entry=entry,
            entries=entries,
            rel=rel,
        )
    )


def _with_evidence(pointer: str, extra: str) -> str:
    """Prepend the evidence pointer to a stage's existing ``extra`` (compose, never replace)."""
    return f"{pointer}\n\n{extra}" if extra else pointer


# ---------------------------------------------------------------------------
# Prompt snapshot (L3.3, design §9.1)
# ---------------------------------------------------------------------------

#: Suffix of a fix stage's prompt snapshot. Distinct from the L2.4 ``.evidence.md``
#: bundle, the stage ``.jsonl``/``.out.txt``/``.meta.json`` files, and the L2.3
#: ``baseline/``/``current/`` diff names, so no two writers share a path (L3.3, req 5).
_SNAPSHOT_SUFFIX = ".prompt.md"


def _write_prompt_snapshot(
    *, stage: str, directory: Path, prompt_path: Path
) -> Path | None:
    """Write ``stages/<stage>.prompt.md`` from the prompt's on-disk content (L3.3).

    Called *before* a fix stage's ``run_stage``, so ``snapshot(i)`` is exactly stage
    ``i``'s input: it already carries every earlier fix stage's mutation and none of
    this stage's. The snapshot lives under the run directory — never the L2.3
    ``_DIFF_TMP_PREFIX`` temp directory, which ``_prompt_diff`` deletes in a
    ``finally`` — and is a plain run-dir artifact, so ``state.json`` gains no field.

    ``stages.mkdir(parents=True, exist_ok=True)`` creates the directory lazily, exactly
    as :func:`_write_evidence_bundle` does. A write failure raises; the caller
    :func:`_snapshot_fix_stage` turns it into the warn-and-continue a fix stage needs.
    """
    text = _capture_prompt(prompt_path)
    if text is None:
        print(
            f"warning: could not read the prompt `{prompt_path}` to snapshot it for "
            f"stage `{stage}`; the stage runs without a snapshot.",
            file=sys.stderr,
        )
        return None
    stages = directory / "stages"
    stages.mkdir(parents=True, exist_ok=True)
    destination = stages / f"{stage}{_SNAPSHOT_SUFFIX}"
    destination.write_text(text, encoding="utf-8")
    return destination.resolve()


def _snapshot_fix_stage(
    *, stage: str, directory: Path, prompt_path: Path
) -> Path | None:
    """Warn-and-continue guard around :func:`_write_prompt_snapshot` (L3.3, req 3).

    Mirrors :func:`_write_evidence_bundle`: a snapshot failure — an unreadable prompt,
    a read-only or odd run directory — is a stderr warning that lets the fix stage run.
    The snapshot is recoverability, never a gate, so it must not fail a run.
    """
    try:
        return _write_prompt_snapshot(
            stage=stage, directory=directory, prompt_path=prompt_path
        )
    except Exception as exc:  # noqa: BLE001 - a snapshot failure must never stop the run
        print(
            f"warning: could not write the prompt snapshot for stage `{stage}` "
            f"({exc}); the stage runs without it.",
            file=sys.stderr,
        )
        return None


def _read_out(record) -> str | None:
    out = record.artifacts.get("out")
    if out and Path(out).is_file():
        return Path(out).read_text(encoding="utf-8")
    return None


def _resolve_prompt_path(
    repo: Path, record, default_rel: str
) -> Path | None:
    """Prefer the path the agent reported; fall back to the conventional location."""
    out = _read_out(record)
    if out:
        first = out.strip().splitlines()[0].strip().strip("`").strip()
        candidate = Path(first)
        if not candidate.is_absolute():
            candidate = repo / candidate
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            pass

    fallback = repo / default_rel
    return fallback if fallback.is_file() else None


#: Directory the author owns. A blocked run reports uncommitted changes here and never
#: commits or removes them (design §13, L1.3).
_PROMPTS_DIR = "docs/task-prompts"

#: First-line marker the author uses to report it cannot author the task (L1.3).
_BLOCKED_MARKER = "blocked:"


def _parse_blocked(out: str | None) -> str | None:
    """Reason when the author's first output line is ``blocked: <reason>`` (L1.3).

    Uses the same strip-then-first-line convention as :func:`_resolve_prompt_path`, so a
    backticked or fenced marker is recognised, and is case-insensitive. Returns ``None``
    when the output is absent/empty or does not start with the marker; an empty string
    means the author reported ``blocked:`` without a reason.
    """
    if not out or not out.strip():
        return None
    lines = out.strip().splitlines()
    first = lines[0].strip().strip("`").strip()
    if not first.lower().startswith(_BLOCKED_MARKER):
        return None
    remainder = [first[len(_BLOCKED_MARKER):].strip(), *lines[1:]]
    return "\n".join(part.strip() for part in remainder if part.strip()).strip()


def _probe_branch(repo: Path, name: str) -> tuple[bool, str | None]:
    """``(answered, sha)`` for ``refs/heads/<name>`` — advisory, never raises (L1.3).

    ``git.probe_ref`` distinguishes "the branch is absent" (rev-parse exit 1) from
    "git could not answer" (any other non-zero exit — a missing git binary, a timeout,
    a fatal plumbing error), so a transient pre-author probe failure reads as
    unanswerable, never as "absent", and cannot yield a spurious "created branch"
    warning for a branch that legitimately pre-existed (review follow-up F1, PR #16).
    """
    try:
        return git.probe_ref(repo, f"refs/heads/{name}")
    except Exception:  # advisory probe: it must never stop the blocked report
        return False, None


def _uncommitted_prompt_paths(repo: Path) -> list[str]:
    """Repo-relative paths under ``docs/task-prompts/`` with uncommitted changes.

    Uncommitted changes are enumerated one file at a time. ``git status --porcelain``
    collapses a wholly-untracked directory to a single ``?? docs/task-prompts/`` line, so
    untracked paths come from :func:`aidw.git.untracked_paths` instead; a blocked run must
    name every file it did not commit, not the directory it sits in.
    """
    prefix = f"{_PROMPTS_DIR}/"
    paths: list[str] = []
    for line in git.status_short(repo, paths=[_PROMPTS_DIR]).splitlines():
        if len(line) < 4 or line[:2] == "??":
            continue
        entry = line[3:].strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip('"')
        if entry not in paths:
            paths.append(entry)
    for rel in git.untracked_paths(repo):
        if rel.startswith(prefix) and rel not in paths:
            paths.append(rel)
    return paths


def _report_blocked_leftovers(
    repo: Path, *, branch: str, branch_before: tuple[bool, str | None]
) -> None:
    """Report — never repair — what a blocked run can see it left behind (design §13).

    AIDT never deletes a branch and never discards work, so a blocked run leaves the tree
    as the author left it and names it instead. The branch is only reported when the
    pre-author probe saw it absent and the post-block probe sees it present, so a branch
    that legitimately pre-existed is never blamed on the run.
    """
    for rel in _uncommitted_prompt_paths(repo):
        print(
            f"warning: blocked run left an uncommitted change under `{_PROMPTS_DIR}/`: "
            f"{rel} (the run neither committed nor removed it).",
            file=sys.stderr,
        )
    answered_before, sha_before = branch_before
    answered_after, sha_after = _probe_branch(repo, branch)
    if (
        answered_before
        and answered_after
        and sha_before is None
        and sha_after is not None
    ):
        print(
            f"warning: blocked run created branch `{branch}`; the run does not delete "
            "it. Remove it manually if it is not wanted.",
            file=sys.stderr,
        )


def _commit_reviewed_prompt(repo: Path, rel: str, phase: str, task: str) -> bool:
    """Commit the reviewed prompt when the review-fix loop changed it."""
    if not git.status_short(repo, paths=[rel]):
        return True
    return git.commit_paths(
        repo, [rel], f"docs: revise task prompt for {phase}-{task} after review"
    )


def _verify_base_branch(repo: TargetRepo, *, no_fetch: bool) -> int | None:
    """Fetch and require the base branch to be current (L1.1, design §8.1).

    Returns :data:`EXIT_REFUSED` when the base branch is provably stale or diverged, else
    ``None``. The fetch outcome is reported as a warning but never decides the verdict on
    its own: the comparison against ``origin/<base>`` (last known refs after a failed
    fetch) is what refuses, so an offline run still catches a stale base. Every message is
    operator-facing on stderr and carries no credential (design §13).
    """
    base = repo.base_branch
    remote_ref = f"{REMOTE}/{base}"

    if no_fetch:
        print(
            f"warning: --no-fetch: base branch `{base}` was not verified against "
            f"`{remote_ref}`.",
            file=sys.stderr,
        )
        return None

    fetched, reason = git.fetch(repo.root, REMOTE)
    if not fetched:
        detail = f" ({reason})" if reason else ""
        print(
            f"warning: could not fetch `{REMOTE}`{detail}; comparing `{base}` against "
            f"the last known `{remote_ref}`.",
            file=sys.stderr,
        )

    local = git.rev_parse(repo.root, base)
    remote = git.rev_parse(repo.root, remote_ref)
    if local is None or remote is None:
        print(
            f"warning: cannot verify base branch `{base}` against `{remote_ref}` "
            f"(no such remote-tracking ref); continuing.",
            file=sys.stderr,
        )
        return None

    if local == remote:
        return None

    behind = git.is_ancestor(repo.root, local, remote)
    if behind is True:
        print(
            f"refusing: base branch `{base}` is behind `{remote_ref}`.\n"
            f"  local  {base}  {local}\n"
            f"  remote {remote_ref}  {remote}\n"
            "Run `git pull --ff-only` in the base worktree, then retry.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    ahead = git.is_ancestor(repo.root, remote, local)
    if ahead is True:
        print(
            f"warning: base branch `{base}` is ahead of `{remote_ref}` "
            f"(unpushed commits); continuing.",
            file=sys.stderr,
        )
        return None

    if behind is False and ahead is False:
        print(
            f"refusing: base branch `{base}` has diverged from `{remote_ref}`.\n"
            f"  local  {base}  {local}\n"
            f"  remote {remote_ref}  {remote}\n"
            "Reconcile the base branch with its remote before authoring.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    # ``is_ancestor`` answered ``None`` (git could not decide): warn, never pass as current.
    print(
        f"warning: could not verify whether base branch `{base}` is current with "
        f"`{remote_ref}`; continuing.",
        file=sys.stderr,
    )
    return None


def _incomplete_predecessors(
    entries: list[RoadmapTask], entry: RoadmapTask
) -> list[RoadmapTask]:
    """Earlier, unticked tasks in the target's own roadmap file (L1.2, design §11).

    Roadmap ordering is the line order within ``RoadmapTask.file``; an epic-id sort is
    not the authority. ``load_tasks`` returns every phase file, so the filter is on the
    file, not the phase id — otherwise an unticked backlog in phase 00 would block every
    other phase.
    """
    return [
        candidate
        for candidate in entries
        if candidate.file == entry.file
        and candidate.line < entry.line
        and not candidate.done
    ]


def _render_predecessors(predecessors: list[RoadmapTask]) -> str:
    """One ``id — title`` line per predecessor, in roadmap order (never a bare count)."""
    return "\n".join(f"  {p.task} — {p.title}" for p in predecessors)


def _refuse_incomplete_predecessors(
    entry: RoadmapTask, predecessors: list[RoadmapTask]
) -> None:
    """Exit-4 refusal naming the target, its phase file and every predecessor."""
    print(
        f"refusing: cannot author `{entry.task}` in phase file `{entry.file}`; "
        "earlier tasks in the same file are incomplete:",
        file=sys.stderr,
    )
    print(_render_predecessors(predecessors), file=sys.stderr)
    print(
        "Tick each predecessor once its work is merged (a merged task may still be "
        "unticked, so the roadmap cannot tell the difference), or re-run with "
        "`--allow-incomplete-prereqs` to author anyway.",
        file=sys.stderr,
    )


def _warn_incomplete_predecessors(
    entry: RoadmapTask, predecessors: list[RoadmapTask]
) -> None:
    print(
        f"warning: --allow-incomplete-prereqs: authoring `{entry.task}` anyway; "
        "skipping incomplete predecessor(s):",
        file=sys.stderr,
    )
    print(_render_predecessors(predecessors), file=sys.stderr)


def run(
    *,
    phase: str,
    epic: str,
    task: str,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    label: str | None = None,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    require_approval: bool = False,
    strict: bool = False,
    dry_run: bool = False,
    no_fetch: bool = False,
    allow_incomplete_prereqs: bool = False,
    stream: bool = False,
) -> int:
    skip = set(skip_gates or [])
    deny = set(deny_gates or [])
    # ``aidt`` locates the toolkit's assets (prompts, agent configs); run state lives
    # under the per-repo state root (EXTRACTION.md §3.10), resolved once by ``_roots``
    # and threaded in as ``workspace`` so no workflow re-resolves it.
    runs_root = workspace.state_root / "runs"

    entries = load_tasks(repo.root / "docs" / "tasks")
    entry = find_task(entries, phase, epic, task)
    if entry is None:
        print(
            f"roadmap task not found: phase={phase} epic={epic} task={task}",
            file=sys.stderr,
        )
        return 2

    # L1.2 (design §8.1, §11): computed once, before the ``dry_run`` split, so the
    # dry-run note and the real-run refusal cannot disagree. ``entries`` already holds
    # every parsed phase file; the filter is on the target's own file and a strictly
    # earlier line, never on epic-id order (a later-sorting epic can sit on an earlier
    # line) and never across files (phase 00's unticked backlog must not block phase 02).
    incomplete = _incomplete_predecessors(entries, entry)

    branch = git.current_branch(repo.root)
    if dry_run:
        if branch != "main":
            print(f"[dry-run] a real run requires `main` (currently `{branch}`).")
        if not git.is_clean(repo.root):
            print("[dry-run] a real run requires a clean working tree.")
        if incomplete:
            print(
                f"[dry-run] incomplete predecessors for `{entry.task}` in "
                f"`{entry.file}`:\n{_render_predecessors(incomplete)}"
            )
        else:
            print(f"[dry-run] no incomplete predecessors in `{entry.file}`.")
        print(
            "[dry-run] a real run will fetch and verify the base branch against "
            f"`{REMOTE}/{repo.base_branch}`."
        )
    else:
        if branch != "main":
            print(
                f"`aidw prompt` must run on `main`; currently on `{branch}`.",
                file=sys.stderr,
            )
            return 4
        if not git.is_clean(repo.root):
            print("working tree is dirty; commit or stash first.", file=sys.stderr)
            return 4
        # Refuse before ``load_all``/``create_run`` so a stale base leaves no run
        # directory, no ``{phase}-{task}`` branch and no prompt file behind. A refusal
        # on roadmap ordering is deliberately checked before the network fetch: it is a
        # purely local, in-memory condition, so an unreachable ``origin`` must not be
        # spent first.
        if incomplete:
            if not allow_incomplete_prereqs:
                _refuse_incomplete_predecessors(entry, incomplete)
                return EXIT_REFUSED
            _warn_incomplete_predecessors(entry, incomplete)
        refusal = _verify_base_branch(repo, no_fetch=no_fetch)
        if refusal is not None:
            return refusal

    agents, issues = load_all(aidt.root, repo.root)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    default_rel = f"docs/task-prompts/{phase}-{task}-prompt.md"
    state = create_run(
        runs_root,
        repo.root,
        "prompt",
        label=label or f"{phase}-{task}",
        task={"phase": phase, "epic": epic, "task": task, "title": entry.title},
        strict=strict,
        branch=branch,
    )
    directory = run_dir(runs_root, state.run_id)
    logger = RunLogger(directory, stream=stream)
    logger.info(f"prompt workflow {phase}/{epic}/{task}: {entry.title}")
    print(f"run:    {state.run_id}")
    print(f"task:   {entry.title}")

    author = StageSpec(
        "task-prompt",
        "task-author",
        aidt.prompts_dir / "task-prompt.md",
        [phase, epic, task],
    )

    # L1.3: probe for the author's branch before it runs, so a blocked run can tell a
    # branch the author created from one that legitimately pre-existed (the author reuses
    # one based on ``main``). ``--dry-run`` plans no branch and does no comparison.
    branch_before: tuple[bool, str | None] | None = None
    if not dry_run:
        branch_before = _probe_branch(repo.root, f"{phase}-{task}")

    rec1 = run_stage(
        author,
        repo_root=repo.root,
        toolkit_root=aidt.root,
        runs_root=runs_root,
        state=state,
        logger=logger,
        agents=agents,
        dry_run=dry_run,
    )
    print_stage(rec1, repo_root=repo.root)

    if dry_run:
        rec2 = run_stage(
            StageSpec(
                "task-review-1",
                "task-reviewer",
                aidt.prompts_dir / "task-review.md",
                [default_rel],
            ),
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
            dry_run=True,
        )
        print(f"stage:  {rec2.name} [{rec2.status}] (planned) model={rec2.model}")
        state.status = SUCCEEDED
        save(directory, state)
        print("dry-run complete; Pi not invoked")
        return 0

    if rec1.status != SUCCEEDED:
        print(f"task-prompt stage failed: {rec1.error}", file=sys.stderr)
        return 1

    # L1.3: detect the blocked report before ``_resolve_prompt_path`` tries the first
    # line as a path and falls back to the conventional location — otherwise a
    # ``blocked:`` line would be silently ignored whenever the author also left a file.
    # The author stage stays ``succeeded`` (it exited 0 with a valid report); the *run* is
    # what is blocked, and no commit, review or fix stage follows.
    blocked_reason = _parse_blocked(_read_out(rec1))
    if blocked_reason is not None:
        reason = blocked_reason or "no reason given"
        logger.error(f"task-prompt author reported blocked: {reason}")
        if branch_before is not None:
            _report_blocked_leftovers(
                repo.root, branch=f"{phase}-{task}", branch_before=branch_before
            )
        state.status = BLOCKED
        save(directory, state)
        print(f"blocked: {reason}", file=sys.stderr)
        return 3

    prompt_path = _resolve_prompt_path(repo.root, rec1, default_rel)
    if prompt_path is None:
        print(
            f"generated task prompt not found at {default_rel}",
            file=sys.stderr,
        )
        state.status = FAILED
        save(directory, state)
        return 1
    rel = prompt_path.relative_to(repo.root).as_posix()
    print(f"prompt: {rel}")
    state.git["branch"] = f"{phase}-{task}"
    save(directory, state)

    verdict: str | None = None
    review_text = ""
    # L2.3: ``previous_review_text`` and ``baseline_prompt`` are set only when the round is
    # followed by fixes. ``review_text`` is reassigned on the next iteration, so the prior
    # review is carried separately; the baseline is the in-memory snapshot (no per-round
    # commits exist) taken after this verdict and before the fix stages mutate the prompt.
    previous_review_text: str | None = None
    baseline_prompt: str | None = None
    review_index = 0
    revisions = 0
    while True:
        review_index += 1
        name = f"task-review-{review_index}"
        # Round 1 is deliberately unprimed (no delta brief): the independent first sample
        # is what keeps the loop from anchoring on the previous review. It still receives
        # its evidence pointer, which is gathered context, not prior findings. Rounds 2+
        # add the delta brief, keyed off the stage counter rather than ``revisions`` (which
        # is incremented later in the same iteration).
        delta = ""
        if review_index >= 2 and previous_review_text is not None:
            delta = _render_delta_brief(
                index=review_index,
                previous_review=previous_review_text,
                baseline=baseline_prompt,
                current=_capture_prompt(prompt_path),
                rel=rel,
            )
        pointer = _stage_evidence_pointer(
            stage=name,
            directory=directory,
            repo=repo,
            entry=entry,
            entries=entries,
            rel=rel,
        )
        rec = run_stage(
            StageSpec(
                name,
                "task-reviewer",
                aidt.prompts_dir / "task-review.md",
                [rel],
                extra=_with_evidence(pointer, delta),
            ),
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(rec, repo_root=repo.root)
        if rec.status != SUCCEEDED:
            state.status = FAILED
            save(directory, state)
            return 1

        review_text = _read_out(rec) or ""
        if not review_text.strip():
            logger.error(f"{rec.name} produced no final message")
            print(
                f"{rec.name} produced no final message; stopping.", file=sys.stderr
            )
            state.status = FAILED
            save(directory, state)
            return 1

        verdict = parse_verdict(review_text)
        findings, problems = parse_review_findings(review_text)
        if verdict == APPROVE:
            print(f"verdict: {verdict}")
        else:
            print(f"verdict: {verdict or 'ambiguous'} — {findings_summary(findings)}")

        if verdict == APPROVE:
            break
        if verdict == VERDICT_BLOCKED:
            # A `Blocked` verdict means a material ambiguity only a human can settle, so
            # it short-circuits before any fix stage and before any ``approve_all`` path
            # can reach the gate or :func:`_commit_reviewed_prompt` — the prompt stays
            # uncommitted and the run fails closed (design §8.1/§8.3, L2.1). This runs
            # before ``revisions += 1`` so a Blocked review never spawns a fixer, with or
            # without parsed findings.
            logger.error("task review returned Blocked; failing closed.")
            state.status = BLOCKED
            save(directory, state)
            print(
                "task review returned Blocked; a human must settle it.",
                file=sys.stderr,
            )
            print(review_text, file=sys.stderr)
            return 3
        if revisions >= MAX_REVISIONS - 1:
            # The fix budget is spent: the terminal review has now run. There is no further
            # revision slot, so a residual `Request changes` fails closed rather than being
            # applied unreviewed — the prompt is left uncommitted for a human to settle, with
            # this review's findings on stderr. `Blocked` short-circuited above, so it keeps
            # its own "a human must settle it" message.
            state.status = BLOCKED
            save(directory, state)
            print(
                "task review did not approve within the revision budget; failing closed.",
                file=sys.stderr,
            )
            print(review_text, file=sys.stderr)
            return 3

        # Capture after the verdict and its Blocked/terminal exits, before the fix
        # stages run, so the next round's diff is exactly this fix batch's net effect and
        # not a cumulative diff across rounds (there is no per-round commit to diff against).
        baseline_prompt = _capture_prompt(prompt_path)
        previous_review_text = review_text
        revisions += 1
        if not findings or problems:
            if problems:
                print(
                    f"         {len(problems)} finding block(s) did not parse cleanly "
                    f"({problems[0]}); reworking with the whole review instead"
                )
            fallback_name = f"task-review-fixes-{revisions}"
            _snapshot_fix_stage(
                stage=fallback_name, directory=directory, prompt_path=prompt_path
            )
            rec_fix = run_stage(
                StageSpec(
                    fallback_name,
                    "task-fixer",
                    aidt.prompts_dir / "task-review-fixes.md",
                    [rel],
                    extra=_with_evidence(
                        _stage_evidence_pointer(
                            stage=fallback_name,
                            directory=directory,
                            repo=repo,
                            entry=entry,
                            entries=entries,
                            rel=rel,
                        ),
                        f"## Review findings to address\n\n{review_text}",
                    ),
                ),
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
            )
            print_stage(rec_fix, repo_root=repo.root)
            if rec_fix.status != SUCCEEDED:
                state.status = FAILED
                save(directory, state)
                return 1
        else:
            # Blocking findings are fixed one at a time so progress is visible per change;
            # the non-blocking could-fix findings share a single stage, so they cost one
            # invocation instead of one each.
            blocking, could_fix = partition_findings(findings)
            steps: list[tuple[str, list[ParsedFinding]]] = [
                ("finding", [finding]) for finding in blocking
            ]
            if could_fix:
                steps.append(("combined", could_fix))
            total = len(steps)

            for index, (kind, group) in enumerate(steps, start=1):
                prefix = f"fix {revisions}.{index}/{total}:"
                if kind == "finding":
                    finding = group[0]
                    print(f"{prefix} {finding_title(finding)} [{finding.priority}]")
                    extra = render_finding_block(finding, index=index, total=total)
                else:
                    noun = "finding" if len(group) == 1 else "findings"
                    print(f"{prefix} {len(group)} could-fix {noun} combined")
                    extra = render_could_fix_block(group)

                fix_name = f"task-review-fixes-{revisions}-{index}"
                _snapshot_fix_stage(
                    stage=fix_name, directory=directory, prompt_path=prompt_path
                )
                rec_fix = run_stage(
                    StageSpec(
                        fix_name,
                        "task-fixer",
                        aidt.prompts_dir / "task-review-fixes.md",
                        [rel],
                        extra=_with_evidence(
                            _stage_evidence_pointer(
                                stage=fix_name,
                                directory=directory,
                                repo=repo,
                                entry=entry,
                                entries=entries,
                                rel=rel,
                            ),
                            extra,
                        ),
                    ),
                    repo_root=repo.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                )
                print_stage(rec_fix, repo_root=repo.root)
                if rec_fix.status != SUCCEEDED:
                    state.status = FAILED
                    save(directory, state)
                    return 1

        # L3.4: one reconcile stage per fix batch, after the batch and before the next
        # review. The fixers work one finding at a time and prefer the smallest edit, so the
        # batch can end internally inconsistent. After L4.1 there is no final fix batch to
        # reconcile: a review is always the last stage for a non-approving prompt, and
        # ``MAX_REVISIONS`` counts review rounds with the last one review-only. ``review_index``
        # is the round number, so the name matches neither ``task-review-N`` nor
        # ``task-review-fixes-*`` — the L3.3 snapshot writer, the ``_fix_round`` regex and
        # the harness's ``fix_status`` branch all leave it alone.
        reconcile_name = f"task-review-reconcile-{review_index}"
        rec_reconcile = run_stage(
            StageSpec(
                reconcile_name,
                "task-fixer",
                aidt.prompts_dir / "task-review-fixes.md",
                [rel],
                extra=_with_evidence(
                    _stage_evidence_pointer(
                        stage=reconcile_name,
                        directory=directory,
                        repo=repo,
                        entry=entry,
                        entries=entries,
                        rel=rel,
                    ),
                    _render_reconcile(
                        index=review_index,
                        review_text=review_text,
                        baseline=baseline_prompt,
                        # Captured here, before run_stage: this is the fix batch's net
                        # effect, not a diff polluted by the reconcile edit itself.
                        current=_capture_prompt(prompt_path),
                        rel=rel,
                    ),
                ),
            ),
            repo_root=repo.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(rec_reconcile, repo_root=repo.root)
        if rec_reconcile.status != SUCCEEDED:
            state.status = FAILED
            save(directory, state)
            return 1

    verdict_line = f"Review verdict: {verdict or 'ambiguous'}"
    summary = "\n".join(
        [
            f"Task: {phase} {epic} {task} — {entry.title}",
            f"Prompt: {prompt_path.relative_to(repo.root)}",
            verdict_line,
        ]
    )
    if require_approval:
        outcome = decide(
            GATE,
            summary,
            approve_all=approve_all,
            skip=skip,
            deny=deny,
            gate_default=gate_default,
        )
    else:
        # The prompt is verified by the reviewer above; the human gate is optional and
        # off by default. Record the auto-decision so state still shows what happened.
        outcome = GateOutcome(GATE, True, "optional (default)")
    state.record_gate(
        GateRecord(
            name=GATE,
            decision=outcome.decision,
            mechanism=outcome.mechanism,
            at=utcnow_iso(),
            detail=f"verdict={verdict}; revisions={revisions}",
        )
    )
    if not outcome.approved:
        state.status = BLOCKED
        save(directory, state)
        print(f"gate {GATE} denied ({outcome.mechanism}); stopping.", file=sys.stderr)
        return 3

    # The initial task-prompt stage commits the prompt, but the review-fix loop runs
    # afterwards. Commit the reviewed prompt so the branch is clean when the
    # implementation workflow starts. Only the owned prompt path is committed.
    if _commit_reviewed_prompt(repo.root, rel, phase, task):
        logger.info(f"reviewed prompt committed or unchanged: {rel}")
    else:
        logger.error(f"failed to commit reviewed prompt {rel}")
        print(
            f"warning: could not commit the reviewed prompt ({rel}); "
            "the branch is dirty",
            file=sys.stderr,
        )

    state.status = SUCCEEDED
    save(directory, state)
    print("prompt workflow complete")
    print(f"branch: {phase}-{task}")
    print(f"prompt: {rel}")
    return 0
