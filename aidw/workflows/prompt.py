"""``aidw prompt`` — task prompt generation and review (design §8.1).

Stages:

1. ``task-prompt``      — agent ``task-author`` writes ``docs/task-prompts/<phase>-<task>-prompt.md``
                          in the AIDT-created task worktree; AIDT commits the reviewed
                          prompt after the loop. Immediately after the author, the
                          workflow measures that just-generated file against the
                          conciseness budget (``prompts/task-prompt.md``): every produced
                          prompt gets a ``budget:`` count line, an over-budget prompt warns
                          and names its longest requirement, and ``--strict`` refuses
                          (exit 1, ``FAILED``, no gate) before the review loop (L5.3,
                          design §8.1/§14).
2. ``task-review-N``    — agent ``task-reviewer`` reviews the prompt (read-only); N starts at 1.
                          Every round receives a pointer to its own evidence bundle
                          (``<run_dir>/stages/<stage>.evidence.md``, L2.4); rounds 2+ also
                          receive a delta brief (``extra=``): a per-finding resolution
                          instruction, the previous review verbatim, and a real ``git diff``
                          of the prompt since that review (L2.3).
3. ``task-review-fixes`` — repeated (bounded) rework when the review requests changes. One
                          stage per blocking (must-fix/should-fix) finding, plus one combined
                          stage for the non-blocking could-fix findings; a single combined stage
                          carrying the whole review when it does not parse into findings. The
                          budget is ``max_revisions`` (CLI ``--max-revisions``, default 3);
                          ``max_revisions - 1`` fix batches run and the ``max_revisions``-th
                          review is review-only (the terminal review), so a review is always the
                          last stage for a non-approving prompt. Every fix
                          stage also receives a pointer to its own evidence bundle (L2.4),
                          and its input prompt is snapshotted to
                          ``<run_dir>/stages/<stage>.prompt.md`` before it runs (L3.3).
4. ``task-review-reconcile-N`` — one stage per fix batch, after the batch and before the
                          next review. It uses the ``task-fixer`` agent with
                          ``prompts/task-review-fixes.md`` and an ``extra=`` that carries the
                          whole review plus that batch's combined diff (L3.4).
5. optional gate ``approve-task-prompt``. Every verdict-bearing exit — approve,
                          human-deny, terminal ``Request changes`` and ``Blocked`` —
                          records that gate (``decision`` stays ``approved``/``denied``)
                          with a per-round ``key=value`` summary in ``detail``, writes
                          the same summary to ``run.log`` and stdout, and prints one
                          per-round findings/fixes line (L4.2, design §9.2/§9.3).
                          Verdict-less exits record no gate and no summary.

A real run requires the configured base branch (``repo.base_branch``) checked out in the
control worktree and a clean working tree. It then refuses (exit 4) when an earlier task in
the same roadmap phase file is unticked, unless ``--allow-incomplete-prereqs``
is given, then fetches ``origin`` and refuses (exit 4) when the base branch is behind or
diverged from ``origin/<base>``; ``--no-fetch`` skips both the fetch and the comparison.
It derives the branch/worktree name from ``repo.branch_pattern`` and **locates** the task
worktree before the author stage, creating it only when none exists; a malformed pattern is
a usage error (exit 2) and a git refusal is exit 4, both before any stage or run state
(EXTRACTION.md §3.2/§3.4). A re-run or a resume finds the worktree an earlier run created
(``git.add_worktree`` returns ``None`` for an already-checked-out branch), so a located
worktree is reused: a resume always proceeds in the failed run's own tree, while a fresh
re-run reuses it only when it is clean and otherwise refuses (exit 4) printing the two
commands that clear it (H1.2, design §8.1/§13).
A ``--dry-run`` plans the stages without those preconditions, reports the incomplete
predecessors and the planned ``worktree add``, and never touches the network or creates a
worktree.

Resumability (H1.2, design §9.4) mirrors ``aidw implement``: ``--resume`` reads the latest
**prompt** run for the derived branch, prints its completed stages and confirms before
continuing; ``--from <stage>`` re-runs that stage and everything after it. A failed run
stamps ``state.resume.next_stage`` at every ``return 1`` site and a run that succeeds clears
it; a *blocked* run records none (design §9.3). A resume keeps
the run's single id and appends to the same ``state``: the loop's in-memory counters are
reconstructed from the recorded stage records (``review_index``/``revisions`` from the stage
names, each round's fix batch re-parsed from that round's recorded review ``.out.txt``), so
no author or review stage is re-run to recover them and no ``FixBatch`` or baseline diff is
fabricated. ``--dry-run`` always plans the fresh author + ``task-review-1`` baseline — never
a resumed plan — exactly as ``implement.py`` layers the same flags.

A **blocked** run's forward path is H1.3's, scoped by the shape of the block (design §9.4).
A *review-loop* block — a blocked run holding the loop's own `denied`
``approve-task-prompt`` gate (``mechanism == "review-loop"``: the terminal `Request
changes`, a `Blocked` verdict, or M2's approve-with-blocking-findings) — continues with
``--resume``: the same loop, in the same run id and worktree, under an *extended* budget of
one added review round (``state.task["effective_max_revisions"]``), so the recorded round's
findings finally get their fix batch and reconcile and the added review is terminal (L4.1).
An author-``blocked:`` run and a human-gate denial hold no terminal review whose findings
drive a fix batch, so ``--resume`` keeps H1.2's exit-3 refusal naming the recorded reason.
``--from-prompt <path>`` is either shape's path: it copies the operator's content into the
canonical prompt path (refusing exit 4 when the blocked run left uncommitted edits there,
design §13), records its provenance in ``state.task["from_prompt"]``, and re-runs the review
loop from ``task-review-1`` under the resolved ``max_revisions``. A blocked continuation whose
task worktree is gone refuses exit 4 naming the run, the missing worktree and the re-author
command; it never re-authors silently.
Before any of that — and regardless of ``--dry-run`` — the target repo's
``<target>/aidw/config.yaml`` is loaded and resolved (E3.2): its ``max_revisions`` is the
budget under the CLI flag, and a config carrying validation ERRORs refuses with
``format_issues`` on stderr and exit 2 rather than silently resolving to
``DEFAULT_MAX_REVISIONS`` (design §12, H8; EXTRACTION.md §3.4). A config this toolkit
cannot *understand* refuses at the same site and with the same contract (E3.3, D10):
:func:`aidw.target_config.check_compatibility` reports a ``schema_version`` newer than
``SUPPORTED_SCHEMA_VERSION`` or an unsatisfied ``requires_toolkit`` pin, and the issues go
to stderr with exit 2 before ``load_tasks``/``derive_branch_name``, so the run leaves no
state, branch or worktree (EXTRACTION.md §3.11 "refuses to run"). Both of those refusals
live once, in :func:`aidw.target_config.resolve_workflow_config`, which all five workflows
share so they cannot drift (E4.3).

Every stage of every round — the author, each review, each fix stage and each reconcile —
comes from :func:`aidw.runner.plan_stages` over the ``aidw.stage_registry`` defaults, with
the target repo's ``prompt:`` overlay applied (E4.3, EXTRACTION.md §3.5). The loop
re-expands per round as real verdicts accumulate, so there is no hand-built stage list here;
the runtime-only parts (the L2.4 evidence pointer, the brief payloads, the L3.3 snapshots)
stay workflow-side and are composed in front of the registry's body text.
The same preflight then refuses (exit 2, stderr) when a resolved ``paths:`` read-path does
not exist in the target — by default or by config, since D17's defaults are Mythical
Forge's layout (E3.7, §3.4 "Configured read-paths must exist"). Every issue names the
field and the resolved path, so the operator sees what to create or override; there is no
fallback and no agent-side improvisation.
When the author's first output line is ``blocked: <reason>`` the run ends ``blocked``
(exit 3) with the reason in the run log and on stderr; the created task worktree and any
uncommitted change under ``docs/task-prompts/`` in it are reported, never repaired
(design §13, L1.3).
The approval gate is off by default; pass ``--require-approval`` to pause for a human decision.

The run lock (``aidw.lock``, EXTRACTION.md §3.2/§3.10) is keyed on the **task worktree**
(``target.root``), acquired after branch setup — located or created first — and released on
every exit path. A resume reuses the failed run's worktree, so its lock key is the same one
the failed invocation held. It is therefore the same key a concurrent
``implement``/``fix``/``review``/``approve`` started in that worktree takes. A dry run
locates and creates no worktree, so it locks the control worktree it plans against.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import mkdtemp

from aidw import __version__, git, lock
from aidw import stage_registry
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.findings import (
    ParsedFinding,
    findings_summary,
    finding_title,
    parse_review_findings,
    partition_findings,
)
from aidw.gates import GateOutcome, decide
from aidw.log import NullLogger, RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
# ``_GATES_HEADING`` is the shared recognised-heading tuple from its single definition in
# ``aidw.prompts`` (C1.2, design §7.3 step 4), so this reader and ``aidw doctor`` cannot
# drift on the heading set or the comparison.
from aidw.prompts import (
    GATES_HEADINGS as _GATES_HEADING,
    is_recognised_gates_heading,
    read_conventions_sources,
)
from aidw.report import empty_final_message_error, print_stage
from aidw.roadmap import DONE_RE, TASK_RE, RoadmapTask, find_task, load_tasks
from aidw.runner import (
    StageSpec,
    declared_stage_issues,
    plan_stages,
    run_stage,
)
# ``DEFAULT_MAX_REVISIONS`` lives in ``aidw.target_config``, its single home (design
# §12/H8). The direction must not be reversed: ``target_config`` is the low-level config
# module, and importing this workflow module from it would be an import cycle.
from aidw.target_config import (
    DEFAULT_MAX_REVISIONS,
    SOURCE_CONFIG,
    ConfigOverrides,
    ResolvedConfig,
    agent_configs_override,
    config_identity,
    load_target_config,
    resolve_workflow_config,
    validate_paths,
)
from aidw.state import (
    BLOCKED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    GateRecord,
    RunState,
    PLANNED_RUN_DIR_TEXT,
    create_run,
    list_runs,
    planned_run,
    run_dir,
    save,
    utcnow_iso,
)
from aidw.verdict import APPROVE, BLOCKED as VERDICT_BLOCKED, parse_verdict
from aidw.workflows.implement import derive_branch_name

GATE = "approve-task-prompt"

#: Remote the base-branch preflight fetches (L1.1, design §8.1). Full ``git fetch origin``
#: keeps ``refs/remotes/origin/<base>`` current; a partial refspec would not.
REMOTE = "origin"

#: Exit code for a preflight/safety refusal (design §14).
EXIT_REFUSED = 4

#: The revision budget, and the number of revision slots (design §12).
#: ``max_revisions`` (CLI ``--max-revisions``, default 3): ``max_revisions - 1`` fix batches
#: run (one stage per blocking finding, one combined stage for the could-fix findings) and
#: the ``max_revisions``-th review is review-only (the terminal review), so a review is always
#: the last stage for a non-approving prompt. A residual `Request changes` after that terminal
#: review fails closed (``BLOCKED``, exit 3) with the findings on stderr — a reviewer that
#: keeps requesting changes must not have its last fixes accepted unreviewed. A `Blocked`
#: verdict short-circuits earlier and still fails closed, since it means a human must settle
#: a material ambiguity. The floor default is ``DEFAULT_MAX_REVISIONS``, imported above from
#: its single home; the effective value is resolved in :func:`run` via ``resolve_config``:
#: CLI flag > target config > ``DEFAULT_MAX_REVISIONS``.

#: Note used when the two prompt snapshots are byte-identical, so the reviewer is not left
#: wondering whether a diff section went missing.
#: The delta-brief and reconcile wording itself lives in ``aidw.stage_registry`` since E4.3
#: (``DELTA_BRIEF_INSTRUCTION``/``RECONCILE_INSTRUCTION``/``DIFF_UNAVAILABLE`` and the pure
#: ``render_delta_brief``/``render_reconcile``); this workflow now only produces the diff
#: that those renderers embed, so the text has exactly one home.
_DIFF_EMPTY = "The prompt is unchanged since the previous review."

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


def _brief_diff(
    *,
    index: int,
    baseline: str | None,
    current: str | None,
    rel: str,
    verb: str,
    brief_name: str,
) -> str | None:
    """The diff payload a delta/reconcile brief embeds, or ``None`` when unavailable (L2.3/L3.4).

    Only the workflow has the two prompt snapshots (a captured baseline plus the prompt as
    it stands now), so producing the diff is its job; the *wording* around it is the
    registry's (:func:`aidw.stage_registry.render_delta_brief`/
    :func:`~aidw.stage_registry.render_reconcile`). ``None`` is passed through as-is, which
    those renderers turn into an explicit unavailable note — never a silently empty diff
    section. ``verb``/``brief_name`` only shape this warning.
    """
    if baseline is None or current is None:
        print(
            f"warning: could not read the reviewed prompt `{rel}` to {verb} review "
            f"round {index}; the {brief_name} names the prompt diff unavailable.",
            file=sys.stderr,
        )
        return None
    return _prompt_diff(baseline, current, name=Path(rel).name)


# ---------------------------------------------------------------------------
# Evidence bundle (L2.4, design §8.1; EXTRACTION.md §3.8 / D16)
# ---------------------------------------------------------------------------

#: Note for a bundle section whose source could not be read. It is a normal degraded
#: state, never an error: the agent is told the evidence is missing rather than the run
#: being marked failed (L2.4, requirement 4).
_EVIDENCE_UNAVAILABLE = "unavailable — could not be read"

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


def _roadmap_lines(
    repo: TargetRepo, entry: RoadmapTask, *, roadmap_dir: str
) -> list[str] | None:
    """Re-read the entry's own roadmap file, or ``None`` when it cannot be read.

    ``roadmap_dir`` is the resolved ``paths.roadmap_dir`` (D15/D17): the second consumer
    of the roadmap directory (roadmap-format.md §6, "two readers"), so it must follow the
    same configured location the entry was parsed from rather than a fixed path. It is
    joined against ``repo`` — the tree the stage runs in — and an absolute value wins.
    """
    try:
        return (
            (repo.root / roadmap_dir / entry.file)
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


def _gates_section(text: str, extra_heading: str | None = None) -> str | None:
    """One conventions source's gate-commands section verbatim, or ``None`` (C1.2).

    Recognises either heading in :data:`_GATES_HEADING` (``## Gates`` or
    ``## Gate commands``) plus ``extra_heading``, the target's configured ``gates_heading``
    passed in verbatim as a full ``## ``-prefixed line (design §7.3 step 4). Recognition is
    :func:`aidw.prompts.is_recognised_gates_heading`'s ``startswith`` rule — the same one
    ``aidw doctor`` uses — so a suffixed canonical heading still matches and the heading
    set has exactly one definition. The extra heading is passed in, never loaded here:
    this function stays pure.

    The section runs from the heading to the next ``## `` heading, so a later section
    (``## Tests``) is never copied into the gate list. Pure — no I/O, and the input text is
    only read.
    """
    lines = text.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if is_recognised_gates_heading(line, extra_heading)
        ),
        None,
    )
    if start is None:
        return None
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        block.append(line)
    return "\n".join(block).rstrip()


def _gate_block(repo: TargetRepo) -> str:
    """The target repo's gate commands, from every conventions source (L2.4, D16/E7.3).

    Sources are read through :func:`aidw.prompts.read_conventions_sources` — the same
    single conventions channel the five-prompt injection uses — in D16 order: the root
    ``AGENTS.md``, then the optional ``aidw/conventions.md``. Each source is passed through
    :func:`_gates_section` unchanged, contributing its ``## Gates``/``## Gate commands``
    section verbatim, joined in that order, so a repo that publishes its gates in either
    file is honoured rather than silently ignoring the one R14 names for new commands.

    The target's optional ``gates_heading`` is loaded from **this target's**
    ``<repo.root>/aidw/config.yaml`` (never the toolkit root) and passed to
    :func:`_gates_section` as the additional recognised heading. A config-less repo gets
    ``None``; a malformed or unreadable config degrades the same way, so the bundle never
    fails on it (L2.4 requirement 4).

    When no source exists, or none carries a recognised heading, the section degrades to
    ``_EVIDENCE_UNAVAILABLE`` — a normal state, never an error (L2.4 requirement 4). The
    ``gates heading`` doctor WARN (design §8.1) is the diagnosis, not a run failure.

    ``repo.root`` is the *target* root, never the toolkit root or a cwd-relative path. In
    a self-hosted run the two roots coincide, so a wrong-root read would pass every test
    here and break only after extraction (AGENTS.md "Two roots").
    """
    declared = load_target_config(repo.root / "aidw" / "config.yaml")
    extra_heading = declared.gates_heading
    blocks = [
        block
        for block in (
            _gates_section(text, extra_heading)
            for _, text in read_conventions_sources(repo.root)
        )
        if block is not None
    ]
    if not blocks:
        return _EVIDENCE_UNAVAILABLE
    return "\n\n".join(blocks)


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
    roadmap_dir: str,
) -> str:
    """Render the six-element bundle (L2.4) for one stage.

    Every source read is degraded to an explicit ``unavailable`` note by the section
    renderers, so the bundle is always produced even when ``AGENTS.md`` is missing or the
    roadmap file cannot be read.
    """
    lines = _roadmap_lines(repo, entry, roadmap_dir=roadmap_dir)
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
            "## Gate commands (target repo `AGENTS.md` + `aidw/conventions.md`)",
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
    roadmap_dir: str,
) -> Path | None:
    """Write ``stages/<stage>.evidence.md`` and return its absolute path, or ``None``.

    ``mkdir(parents=True, exist_ok=True)`` is on ``stages/``: the writer runs *before*
    ``run_stage``, which creates that directory lazily. A failure to write warns on
    stderr and returns ``None`` so the run continues with ``_evidence_pointer(None)`` —
    the bundle is an optimisation, never a gate (L2.4, requirement 4).
    """
    try:
        body = _render_evidence_bundle(
            stage=stage,
            repo=repo,
            entry=entry,
            entries=entries,
            rel=rel,
            roadmap_dir=roadmap_dir,
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
    roadmap_dir: str,
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
            roadmap_dir=roadmap_dir,
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


# ---------------------------------------------------------------------------
# Conciseness budget (L5.3, design §8.1; prompts/task-prompt.md §Conciseness budget)
# ---------------------------------------------------------------------------

#: A generated task prompt's byte budget. Decimal 15KB = 15000 bytes, matching the
#: roadmap's own decimal KB (L5.3: "17.9KB" = 17855 bytes); a binary 15360 budget would
#: shift every boundary by 360 bytes.
PROMPT_BYTE_BUDGET = 15000

#: A generated task prompt's line budget — the larger-task ceiling in the budget text.
PROMPT_LINE_BUDGET = 150

#: Heading that opens the numbered requirement list the over-budget message attributes
#: the size to (``Requirements:`` or a ``#### Requirements`` variant).
_REQUIREMENTS_HEADING_RE = re.compile(r"^#{0,6}\s*Requirements\s*:?\s*$")

#: A numbered requirement item (``1. ...`` / ``12) ...``). A nested ordered list reads
#: as further items, which is harmless because the check only names the longest one(s).
_NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")


def _budget_counts(text: str) -> tuple[int, int]:
    """``(bytes, lines)`` of the prompt text — UTF-8 bytes and physical lines (L5.3)."""
    return len(text.encode("utf-8")), len(text.splitlines())


def _requirement_items(text: str) -> list[tuple[int, str]]:
    """The numbered items under ``Requirements:`` as ``(number, body)`` (L5.3).

    Reads the section that starts at a ``Requirements:`` heading and ends at the
    next heading or at the first column-0 line that is not a numbered item: the
    task-prompt format's trailing sections (``Traps / prior review findings:``,
    ``Explicit non-goals``, ``Deliverables:``, ``Tests``, ``Done when:``) are
    plain-text labels and bullets, never ``#`` headings, so folding them into the
    last item would misattribute the over-budget message (review follow-up #38,
    PR #36 finding F1). Only an indented line continues the item above it; a
    blank line separates entries without ending the list. An empty list means the
    section is absent or holds no numbered item, so the caller degrades to a
    totals-only message. Never raises: a parse failure is a warning, never a
    failed run or check.
    """
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if _REQUIREMENTS_HEADING_RE.match(line.strip()):
            start = index + 1
            break
    if start is None:
        return []

    items: list[tuple[int, list[str]]] = []
    for line in lines[start:]:
        if line.lstrip().startswith("#"):
            break
        match = _NUMBERED_ITEM_RE.match(line)
        if match:
            items.append((int(match.group(1)), [match.group(2).strip()]))
        elif not line.strip():
            # A blank line separates entries; it does not end the section, so a
            # blank-separated numbered item below still parses.
            continue
        elif line.startswith((" ", "\t")):
            # Only an indented line continues the item above it: wrapped item
            # text is indented, trailing-section labels and bullets are not.
            if items:
                items[-1][1].append(line.strip())
        else:
            # Column-0 prose that is neither a heading nor a numbered item opens
            # a trailing section, so the Requirements list ends here.
            break
    return [(number, " ".join(parts)) for number, parts in items]


def _longest_requirements(items: list[tuple[int, str]]) -> list[tuple[int, int]]:
    """The ``(number, word count)`` for the longest requirement item(s) (L5.3).

    Ties are all returned so the message names every equally long offender. The word
    count is whitespace-separated tokens, the same reading the budget text uses.
    """
    if not items:
        return []
    counted = [(number, len(body.split())) for number, body in items]
    longest = max(words for _, words in counted)
    return [entry for entry in counted if entry[1] == longest]


def _budget_reason(
    rel: str,
    *,
    byte_count: int,
    line_count: int,
    items: list[tuple[int, str]],
) -> str:
    """The one-line over-budget reason, with the longest requirement when parseable (L5.3).

    The totals are always named; the attribution is appended only when the requirements
    parsed, so a prompt without a parseable ``Requirements:`` section still warns with
    totals only instead of crashing or staying silent.
    """
    reason = (
        f"task prompt {rel} is over the conciseness budget: "
        f"{byte_count / 1000:.1f}KB, {line_count} lines "
        f"(limits {PROMPT_BYTE_BUDGET / 1000:.1f}KB / {PROMPT_LINE_BUDGET})"
    )
    longest = _longest_requirements(items)
    if longest:
        named = ", ".join(
            f"requirement {number} ({words} words)" for number, words in longest
        )
        reason = f"{reason}; longest: {named}"
    return reason


def _check_conciseness(prompt_path: Path, rel: str) -> str | None:
    """Count the just-generated prompt, warn when over budget, return the reason (L5.3).

    Reads exactly ``prompt_path`` — never a scan of ``docs/task-prompts/``. Prints the
    ``budget:`` count line on stdout for every produced prompt, independently of the
    outcome. Returns ``None`` when within budget, else the one-line reason for the
    ``--strict`` refusal (the default caller instead prints it as a warning and reviews).
    A read failure degrades to a warning and ``None``: a measurement failure cannot fail
    a run.
    """
    try:
        text = prompt_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"warning: could not read the task prompt `{rel}` to check the conciseness "
            f"budget ({exc}); skipping the check.",
            file=sys.stderr,
        )
        return None

    byte_count, line_count = _budget_counts(text)
    print(f"budget: {line_count} lines / {byte_count / 1000:.1f}KB")
    if byte_count <= PROMPT_BYTE_BUDGET and line_count <= PROMPT_LINE_BUDGET:
        return None
    return _budget_reason(
        rel,
        byte_count=byte_count,
        line_count=line_count,
        items=_requirement_items(text),
    )


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


def _uncommitted_prompt_paths(repo: Path) -> list[str]:
    """Repo-relative paths under ``docs/task-prompts/`` with uncommitted changes.

    ``repo`` is the task worktree (where the author writes), never the control root: the
    clean-tree preflight already guaranteed the control tree had no prompt changes.
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


def _report_blocked_leftovers(repo: Path, *, branch: str) -> None:
    """Report — never repair — what a blocked run left behind (design §13, L1.3).

    Branch setup is deterministic Python, so the task worktree always exists on a blocked
    run and is reported unconditionally; the old before/after branch probe is superseded.
    AIDT never deletes a worktree or discards work, so the report names it instead and the
    caller leaves it in place for a human to decide. ``repo`` is the task worktree, where
    the author's uncommitted changes live.
    """
    for rel in _uncommitted_prompt_paths(repo):
        print(
            f"warning: blocked run left an uncommitted change under `{_PROMPTS_DIR}/`: "
            f"{rel} (the run neither committed nor removed it).",
            file=sys.stderr,
        )
    print(
        f"warning: blocked run left the task worktree `{repo}` on branch `{branch}`; the "
        "run does not delete it. Remove it manually if it is not wanted.",
        file=sys.stderr,
    )


def _commit_reviewed_prompt(repo: Path, rel: str, phase: str, task: str) -> bool:
    """Commit the authored (initial or reviewed) prompt — the single commit point.

    The author no longer commits, so this runs once after the review loop, in the task
    worktree, on the branch it already has checked out. It skips when ``rel`` is clean.
    Only the owned prompt path is committed (design §13).
    """
    if not git.status_short(repo, paths=[rel]):
        return True
    return git.commit_paths(
        repo, [rel], f"docs: add task prompt for {phase}-{task}"
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


#: One review round's telemetry (L4.2, design §9.2):
#: ``(review_index, findings_count, fix_stage_count)``.
ReviewRound = tuple[int, int, int]


def _record_round(
    rounds: list[ReviewRound],
    review_index: int,
    findings_count: int,
    fix_stage_count: int,
) -> None:
    """Append one round's telemetry and print its stdout stage-report line (L4.2).

    ``fix_stage_count`` is the number of ``task-review-fixes-*`` stages the round
    actually ran: ``0`` for the approve, ``Blocked`` and terminal-review exits, and the
    in-loop count for a fixing round (the authoritative source — counting the stage
    names after the fact would undercount the fallback round, which runs one stage for
    the whole review). A fixing round is recorded only after its fix batch and
    reconcile succeeded (review follow-up #31): the count is a prediction made before
    the batch, so printing it there would overstate a run that dies mid-batch —
    stdout would claim more fix stages than the stage list in ``state.json`` holds.
    """
    rounds.append((review_index, findings_count, fix_stage_count))
    print(f"round {review_index}: findings={findings_count} fixes={fix_stage_count}")


def _loop_summary(
    *,
    verdict: str | None,
    revisions: int,
    max_revisions: int,
    rounds: list[ReviewRound],
) -> str:
    """One named ``key=value`` summary of the review loop (L4.2, design §9.2, §9.3).

    The single source for the gate ``detail``, the ``run.log`` line and the stdout line,
    so the three cannot drift. ``findings``/``fixes`` are the per-round counts joined by
    ``/``; ``approved=yes`` iff the final verdict is ``Approve`` (a human denial still
    reports the reviewer's verdict here, and its refusal in the gate ``decision``); and
    ``fixes_after_last_review`` is derived from the last round's fix-stage count, never a
    constant — after L4.1 the terminal review runs no fix stage, so a ``yes`` would prove
    an unreviewed fix shipped.
    """
    findings = "/".join(str(count) for _, count, _ in rounds)
    fixes = "/".join(str(count) for _, _, count in rounds)
    approved = "yes" if verdict == APPROVE else "no"
    fixes_after = "yes" if rounds and rounds[-1][2] > 0 else "no"
    return (
        f"verdict={verdict or 'ambiguous'}; revisions={revisions}; "
        f"max_revisions={max_revisions}; rounds={len(rounds)}; "
        f"findings={findings}; fixes={fixes}; "
        f"approved={approved}; fixes_after_last_review={fixes_after}"
    )


def _record_review_outcome(
    state: RunState,
    logger: RunLogger,
    *,
    verdict: str | None,
    revisions: int,
    max_revisions: int,
    rounds: list[ReviewRound],
    decision: str,
    mechanism: str,
) -> str:
    """Record and log one verdict-bearing review-loop exit (L4.2).

    Writes the ``approve-task-prompt`` gate record (``detail`` is the summary), a
    ``run.log`` line carrying the same summary, and the stdout line. ``decision`` stays
    ``approved``/``denied`` — the verdict travels in the summary, never as new gate
    vocabulary. Verdict-less exits must not call this: a ``denied`` would claim a review
    outcome that never happened.
    """
    summary = _loop_summary(
        verdict=verdict,
        revisions=revisions,
        max_revisions=max_revisions,
        rounds=rounds,
    )
    state.record_gate(
        GateRecord(
            name=GATE,
            decision=decision,
            mechanism=mechanism,
            at=utcnow_iso(),
            detail=summary,
        )
    )
    if decision == "denied":
        # A denied gate ends the run BLOCKED, so run.log says so explicitly; the terminal
        # `Request changes` branch used to print to stderr only (L4.2).
        logger.error(f"{GATE} denied; run BLOCKED: {summary}")
    else:
        logger.info(f"{GATE} approved: {summary}")
    print(f"{GATE}: {summary}")
    return summary


def _prompt_plan(
    *,
    config: ResolvedConfig,
    toolkit_root: Path,
    target_root: Path,
    phase: str,
    epic: str,
    task: str,
    rel: str,
    max_revisions: int,
    rounds: list[stage_registry.FixBatch],
) -> tuple[dict[str, StageSpec], dict[str, str]]:
    """This round's stage specs plus the registry's ``brief`` markers, by stage name (E4.3).

    The loop is driven by real verdicts, so it cannot plan the whole chain up front: each
    round re-expands through :func:`aidw.runner.plan_stages` as the returned reviews'
    :class:`~aidw.stage_registry.FixBatch` values accumulate in ``rounds``, and the stages
    it has not reached yet are simply ignored. That is the registry expanding the chain,
    not a hand-built list (EXTRACTION.md §3.5).

    Two results because :class:`aidw.runner.StageSpec` deliberately has no ``brief`` field:
    the marker (``BRIEF_DELTA``/``BRIEF_RECONCILE``, already unprimed on round 1 by the
    registry) says *which* runtime text to render, and the workflow renders it with the
    registry's pure helpers once it has the payload only the loop has — the previous
    review and the batch's diff.
    """
    fields = {
        "phase": phase,
        "epic": epic,
        "task": task,
        "rel": rel,
        "max_revisions": max_revisions,
        "rounds": tuple(rounds),
    }
    specs = {
        spec.name: spec
        for spec in plan_stages(
            "prompt",
            config=config,
            toolkit_root=toolkit_root,
            target_root=target_root,
            **fields,
        )
    }
    briefs = {
        planned.name: planned.brief
        for planned in stage_registry.expand("prompt", **fields)
    }
    return specs, briefs


def _with_pointer(spec: StageSpec, pointer: str, rendered: str = "") -> StageSpec:
    """The stage spec with the L2.4 evidence pointer composed in front of its body.

    The body is the registry-rendered :attr:`StageSpec.extra`, plus the runtime text the
    registry's ``brief`` marker asked for (a delta brief or a reconcile brief). The pointer
    is **prepended**, never substituted, so no run path clears or rewrites a
    registry-rendered extra (E4.3 req 5).
    """
    body = spec.extra
    if rendered:
        body = f"{body}\n\n{rendered}" if body else rendered
    return replace(spec, extra=_with_evidence(pointer, body))


# ---------------------------------------------------------------------------
# Resumability (H1.2, design §9.3/§9.4)
# ---------------------------------------------------------------------------

#: The prompt loop's stage-name grammar (H1.2 req 5), derived from
#: :func:`aidw.stage_registry._expand_prompt_loop`'s expansion: one review per round, then
#: that round's fix stages and its single reconcile, and the final round review-only.
_REVIEW_STAGE_RE = re.compile(r"task-review-(\d+)")
_FIXES_STAGE_RE = re.compile(r"task-review-fixes-(\d+)(?:-(\d+))?")
_RECONCILE_STAGE_RE = re.compile(r"task-review-reconcile-(\d+)")


def prompt_stage_position(name: str) -> tuple[int, int, int] | None:
    """The canonical loop position of a prompt stage name, or ``None`` when unknown (H1.2).

    Pure. ``task-prompt`` sorts before every round (position ``0``); within round ``r``
    (position ``r + 1``) the review comes first, then the round's fix stages in finding
    order, then its reconcile. The tuple is what ``--from``/``resume.next_stage`` compare
    with, so "re-run from here" is one ordering rule rather than a second stage list.
    """
    if name == "task-prompt":
        return (0, 0, 0)
    match = _REVIEW_STAGE_RE.fullmatch(name)
    if match:
        return (int(match.group(1)) + 1, 0, 0)
    match = _FIXES_STAGE_RE.fullmatch(name)
    if match:
        # The fallback stage carries no finding index; it sorts where the first would.
        return (int(match.group(1)) + 1, 1, int(match.group(2) or 1))
    match = _RECONCILE_STAGE_RE.fullmatch(name)
    if match:
        return (int(match.group(1)) + 1, 2, 0)
    return None


def is_from_stage(name: str, max_revisions: int) -> bool:
    """Whether ``name`` is a grammar-valid prompt stage under this budget (H1.2 req 5).

    Pure, and consulted *before* any side effect. The bounds are the loop's own: reviews
    run ``1..max_revisions``; fix batches and reconciles run only for rounds
    ``1..max_revisions - 1`` because ``terminal_last`` breaks before the final round's
    body; and a fix stage's finding index has no upper bound because a review's finding
    count is not budgeted. Every name the loop records is grammar-valid within budget, so
    validation needs no run record — ``task-review-5`` under ``--max-revisions 3`` is
    simply unknown.
    """
    position = prompt_stage_position(name)
    if position is None:
        return False
    round_index, kind, index = position
    if round_index == 0:
        return True  # task-prompt
    budgeted_round = round_index - 1
    if kind == 0:
        return 1 <= budgeted_round <= max_revisions
    if not 1 <= budgeted_round <= max_revisions - 1:
        return False
    # A fix stage's finding index starts at 1 and is otherwise unbudgeted; a reconcile
    # stage carries no index at all.
    return kind != 1 or index >= 1


def _unknown_from_stage_message(name: str, max_revisions: int) -> str:
    """The exit-2 message for an unknown or out-of-budget ``--from`` name (H1.2 req 5).

    The grammar has no finite name list (a fix stage's finding index is unbounded), so the
    message states the bounded shape under the resolved budget instead of enumerating it.
    """
    fix_last = max_revisions - 1
    fixes = (
        f"`task-review-fixes-1..{fix_last}[-<n>]` and "
        f"`task-review-reconcile-1..{fix_last}`"
        if fix_last >= 1
        else "no fix or reconcile stage (max_revisions=1)"
    )
    return (
        f"unknown stage `{name}` for the prompt loop with max_revisions={max_revisions}: "
        f"expected `task-prompt`, `task-review-1..{max_revisions}`, {fixes}"
    )


def _latest_prompt_run(runs_root: Path, branch: str) -> RunState | None:
    """The newest **prompt** run recorded for ``branch``, or ``None`` (H1.2 req 1).

    Mirrors :func:`aidw.workflows.implement._latest_implement_run`: filtered on the
    workflow *and* the recorded branch, so an ``implement`` run for the same branch is
    never mistaken for the run this invocation continues.
    """
    matches = [
        state
        for state in list_runs(runs_root)
        if state.workflow == "prompt" and state.git.get("branch") == branch
    ]
    return matches[-1] if matches else None


def _confirm_resume(assume_yes: bool) -> bool:
    """Ask before a resume continues, mirroring ``implement._confirm_resume`` (H1.2 req 1).

    ``--yes`` skips the question. A non-interactive session (and EOF) confirms: the
    operator already passed ``--resume`` explicitly and a piped run has nobody to ask, the
    same trade-off the implement workflow records.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return True
    try:
        answer = input("Resume this prompt run? [y/N] ").strip().lower()
    except EOFError:
        return True
    return answer in ("y", "yes")


def _print_completed(state: RunState) -> None:
    for record in state.stages:
        print(f"  {record.name}: {record.status}")


def worktree_clear_commands(
    workspace: WorkspacePaths, branch: str, base_branch: str
) -> tuple[str, str]:
    """The two copy-pasteable commands that clear a stale task worktree and branch (H1.2).

    Derived from the ``aidw worktree`` surface and
    :func:`aidw.workflows.implement.worktree_add_command`'s base-worktree ``-C`` form —
    never a hand-rolled ``rm -rf``, ``git reset --hard`` or ``git clean``, because design
    §13 makes the discard an explicit operator action and ``--force`` the only override.
    """
    base_worktree = workspace.workspace_root / base_branch
    return (
        f"aidw worktree remove {branch} --force",
        f"git -C {base_worktree} branch -D {branch}",
    )


def _recorded_fix_rounds(state: RunState) -> int:
    """How many fix rounds a recorded run spent, from its stage names (H1.2 req 4)."""
    rounds = {
        int(match.group(1))
        for record in state.stages
        if (match := _FIXES_STAGE_RE.fullmatch(record.name))
    }
    return len(rounds)


def _recorded_fix_names(state: RunState, round_index: int) -> list[str]:
    """The recorded fix stage names for one review round, in record order (H1.2 req 4)."""
    names: list[str] = []
    for record in state.stages:
        match = _FIXES_STAGE_RE.fullmatch(record.name)
        if match and int(match.group(1)) == round_index:
            names.append(record.name)
    return names


def _reconcile_recorded_fixes(recorded: list[str], rebuilt: list[str]) -> str | None:
    """Why a rebuilt fix batch cannot stand in for the recorded stages, or ``None`` (H1.2).

    Pure. The stage names carry only counts, so the rebuilt :class:`FixBatch` (re-parsed
    from the round's recorded review text) is the authority for what will run, and the
    recorded names are the inventory it must be able to account for. A recorded name the
    rebuilt plan lacks means the batch cannot be reconstructed faithfully — a parser or
    budget change between invocations — so the caller fails closed rather than silently
    dropping a stage. A recorded prefix shorter than the rebuilt plan is normal: that is
    the in-flight batch a failed fix stage or a crash left half-run.
    """
    missing = [name for name in recorded if name not in rebuilt]
    if not missing:
        return None
    return (
        f"recorded fix stage(s) {', '.join(missing)} are not in the rebuilt batch "
        f"({', '.join(rebuilt) or 'none'})"
    )


def _recorded_later_stage(
    state: RunState, position: tuple[int, int, int]
) -> str | None:
    """The first recorded stage positioned after ``position``, or ``None`` (H1.2 req 4).

    Pure read of the recorded stage names. A resume walks the rounds in canonical order, so
    a recorded stage this walk never reaches means the reconstruction disagrees with what
    the run recorded.
    """
    for record in state.stages:
        recorded_position = prompt_stage_position(record.name)
        if recorded_position is not None and recorded_position > position:
            return record.name
    return None


def _last_review_record(state: RunState):
    """The last recorded ``task-review-N`` record, or ``None`` (H1.2 req 6)."""
    for record in reversed(state.stages):
        if _REVIEW_STAGE_RE.fullmatch(record.name):
            return record
    return None


def _recorded_review_count(state: RunState) -> int:
    """How many review rounds a recorded run ran, from its stage names (H1.3 req 2).

    Pure read of ``state.stages``. The count is the run's *review* rounds, which is what the
    revision budget counts (the ``max_revisions``-th review is review-only), so it is also
    the budget the run actually consumed.
    """
    return sum(
        1 for record in state.stages if _REVIEW_STAGE_RE.fullmatch(record.name)
    )


def effective_max_revisions(state: RunState) -> int:
    """The budget a blocked-run continuation runs under: recorded reviews + 1 (H1.3 req 2).

    Pure. The continuation grants exactly **one** added review round, never a larger default
    budget (roadmap H1.3 Notes): with ``N`` recorded reviews the loop's own expansion then
    plans the recorded rounds' fix batches (all recorded but the last, so they are skipped),
    the last recorded round's ``FixBatch`` — which the original run never appended, because
    ``terminal_last`` broke before it — its reconcile, and ``task-review-{N+1}``, which is
    the ``max_revisions``-th review and therefore review-only (L4.1). Each further
    ``--resume`` is its own explicit operator decision and adds one more round.
    """
    return _recorded_review_count(state) + 1


def review_loop_block(state: RunState) -> bool:
    """Whether a blocked run's latest review gate is the loop's own `denied` one (H1.3 req 1).

    Pure. The marker is ``_record_review_outcome``'s ``mechanism == "review-loop"``: the
    terminal `Request changes`, a `Blocked` verdict, and M2's approve-with-blocking-findings
    exit. An author-``blocked:`` run recorded no gate, and a human-gate denial recorded
    ``decide``'s own mechanism; neither has terminal findings that could drive a fix batch,
    so neither is a fix-cycle continuation. Branching on the ``mechanism`` rather than on
    ``status == BLOCKED`` alone is what keeps a human-gate-denied run (review already
    approved) out of the fix cycle, which would re-commit an approved prompt.

    The **latest** ``approve-task-prompt`` record decides, not "any": a continuation appends
    its own gate after the block it continues, so a fix cycle re-blocked by a human denial
    holds *both* a `review-loop` denial and that human one, and its next `--resume` must meet
    the human-gate denial's refusal (req 1/3). The earlier records stay in ``state.gates`` as
    history, which is what makes the original decision reviewable.
    """
    latest = None
    for gate in state.gates:
        if gate.name == GATE:
            latest = gate
    return (
        latest is not None
        and latest.decision == "denied"
        and latest.mechanism == "review-loop"
    )


def _apply_from_prompt(
    worktree: Path,
    rel: str,
    supplied: Path,
    *,
    run_id: str,
    workspace: WorkspacePaths,
    branch: str,
    base_branch: str,
) -> tuple[int | None, dict[str, str]]:
    """Copy an operator-supplied prompt onto the canonical path (H1.3 req 4).

    Returns ``(refusal, provenance)``: a design §14 exit code when the copy must not happen,
    otherwise ``None`` plus the ``state.task["from_prompt"]`` mapping — the *supplied* path
    and a ``sha256:<hex>`` over the very bytes written (design §9.2's ``config_hash``
    convention, so the fingerprint can be reproduced with any sha256 tool).

    The supplied file **is** the prompt being reviewed, but the review loop, the evidence
    bundle and :func:`_commit_reviewed_prompt` all key off the worktree-relative canonical
    ``docs/task-prompts/<phase>-<task>-prompt.md``; copying the content in keeps those three
    working without inventing a second path, and the committed version stays in git history.

    Design §13: a blocked run may itself have left uncommitted edits on that path — exactly
    what :func:`_report_blocked_leftovers` reports and never repairs — so a dirty path
    refuses (exit 4) before the copy rather than silently discarding the operator's work. A
    clean path destroys nothing. The refusal prints the same two copy-pasteable clear
    commands the fresh-path dirty-tree refusal does.
    """
    if git.status_short(worktree, paths=[rel]):
        remove_command, branch_command = worktree_clear_commands(
            workspace, branch, base_branch
        )
        print(
            f"--from-prompt refused: run {run_id} left uncommitted changes on the "
            f"canonical prompt path `{rel}` in {worktree}; copying the supplied file over "
            "them would discard that work, which AIDT never does. The path was left "
            "untouched. Commit or stash it, or clear the worktree and branch and start a "
            "fresh run:",
            file=sys.stderr,
        )
        print(f"  {remove_command}", file=sys.stderr)
        print(f"  {branch_command}", file=sys.stderr)
        return EXIT_REFUSED, {}
    try:
        content = supplied.read_bytes()
    except OSError as exc:
        print(f"--from-prompt: cannot read {supplied}: {exc}", file=sys.stderr)
        return 2, {}
    destination = worktree / rel
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    except OSError as exc:
        print(f"--from-prompt: cannot write {destination}: {exc}", file=sys.stderr)
        return EXIT_REFUSED, {}
    return None, {
        "path": str(supplied),
        "hash": f"sha256:{hashlib.sha256(content).hexdigest()}",
    }


def blocked_resume_reason(state: RunState) -> str:
    """A blocked run's recorded reason, re-read from its own records (H1.2 req 6).

    Three shapes, in the order the loop records them: the author's ``blocked:`` line; the
    last recorded review's verdict plus findings summary (the loop's own
    :func:`aidw.verdict.parse_verdict`/:func:`aidw.findings.parse_review_findings`, the
    same re-read a resume rebuild uses); and a denied ``approve-task-prompt`` gate, whose
    mechanism ``review-loop`` marks the loop's own verdict shapes while anything else is a
    gate decision. Never raises: artifacts that are gone degrade to
    ``the run recorded no reason`` rather than a traceback.
    """
    parts: list[str] = []
    author = state.stage("task-prompt")
    author_reason = _parse_blocked(_read_out(author)) if author is not None else None
    if author_reason is not None:
        parts.append(
            "the task-prompt author reported `blocked:` "
            f"{author_reason or '(no reason given)'}"
        )
    review = _last_review_record(state)
    if review is not None:
        text = _read_out(review) or ""
        verdict = parse_verdict(text)
        findings, _problems = parse_review_findings(text)
        parts.append(
            f"the last recorded review ({review.name}) returned "
            f"{verdict or 'an ambiguous verdict'} — {findings_summary(findings)}"
        )
    gate = next(
        (
            gate
            for gate in reversed(state.gates)
            if gate.name == GATE and gate.decision == "denied"
        ),
        None,
    )
    if gate is not None:
        if gate.mechanism == "review-loop":
            parts.append(f"the `{GATE}` gate was denied by the review loop")
        else:
            parts.append(
                f"the `{GATE}` gate was denied by a human decision "
                f"(mechanism `{gate.mechanism}`)"
            )
    return "; ".join(parts) if parts else "the run recorded no reason"


def _refuse_blocked_resume(state: RunState, branch: str) -> None:
    """Print the exit-3 refusal for a blocked run with no fix-cycle path (H1.2/H1.3).

    Mutates nothing. A blocked run is not a failed one: design §9.3 sets
    ``resume.next_stage`` only when a stage fails, so there is no stage to continue from,
    and re-authoring would discard the reviewed prompt silently. H1.3 scopes the refusal to
    the shapes a fix cycle cannot help — an author ``blocked:`` report (no recorded review)
    and a human-gate denial (the review already approved) — because neither holds terminal
    findings to batch; ``--from-prompt`` is their forward path. Exit 3 is design §14's
    "workflow blocked (needs human)" — not a usage error (2) and not a preflight refusal
    (4), which stay reserved for the no-matching-run, still-running and worktree cases.
    """
    print(
        f"resume refused: run {state.run_id} for `{branch}` is blocked, not failed — a "
        "blocked run records no `resume.next_stage` (design §9.3), so there is no stage "
        "to continue from, and this block shape has no terminal review whose findings a "
        f"fix cycle could take. Recorded reason: {blocked_resume_reason(state)}. Fix the "
        "cause and start a fresh run, or continue the review loop from a prompt file you "
        "supply with `--from-prompt <path>`.",
        file=sys.stderr,
    )


def _mark_failed(state: RunState, directory: Path, stage_name: str) -> None:
    """Record a failed stop and the stage a ``--resume`` continues at (H1.2 req 3).

    One helper for every ``return 1`` site in :func:`run`, because the key the resume
    read-back keys on must not be missed at any of them.
    """
    state.status = FAILED
    state.resume = {"next_stage": stage_name}
    save(directory, state)


def _mark_blocked(state: RunState, directory: Path) -> None:
    """Record a blocked stop with **no** ``next_stage`` (H1.2 req 3, design §9.3).

    Clearing rather than leaving the resumed run's previous ``next_stage`` in place is
    load-bearing: a resumed failed run that ends blocked must not look resumable.
    """
    state.status = BLOCKED
    state.resume = {}
    save(directory, state)


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
    max_revisions: int | None = None,
    resume: bool = False,
    from_stage: str | None = None,
    from_prompt: Path | None = None,
    stream: bool = False,
) -> int:
    skip = set(skip_gates or [])
    deny = set(deny_gates or [])
    # Resolution precedence (design §12, H8): CLI `--max-revisions` > target config
    # `<target>/aidw/config.yaml:max_revisions` > `DEFAULT_MAX_REVISIONS`, implemented in
    # exactly one place — `resolve_config`. A malformed config must never hide behind the
    # default, so its ERROR issues refuse here (exit 2, the same code and stderr contract
    # as the `load_all` refusal below) before any run record, branch or worktree exists and
    # regardless of `--dry-run`. The loader emits only ERROR issues today, so there is no
    # WARNING path to gate behind `--strict`.
    # Version/compatibility refusal (E3.3, D10, EXTRACTION.md §3.11) at the *same* site and
    # with the same contract: stderr + exit 2 (a usage/config error, design §14), before
    # `load_tasks`/`derive_branch_name`, any run record, branch or worktree, and regardless
    # of `--dry-run`. `EXIT_REFUSED` (4) stays reserved for git/worktree/layout refusals,
    # so both config refusals share one exit code. The toolkit version is this package's
    # (`aidw.__version__`); the import direction stays one-way (`target_config` never
    # imports a workflow module). Both refusals — and only these two — live in
    # :func:`aidw.target_config.resolve_workflow_config`, which the other four workflows
    # share since E4.3 so they cannot drift from this contract.
    resolved_config, config_issues = resolve_workflow_config(
        repo.root,
        toolkit_version=__version__,
        overrides=ConfigOverrides(max_revisions=max_revisions),
    )
    if config_issues:
        print(format_issues(config_issues), file=sys.stderr)
        return 2
    # Core vs repo-optional stages (E4.5a, D12/D13, EXTRACTION.md §3.5): only a *declared*
    # `workflows.prompt.stages` list is validated. It replaces the toolkit's list wholesale
    # (§3.4), so a missing core id is a removal, while an undeclared list is absent from the
    # resolved config and the registry defaults plan unchanged. Runs at the same site and
    # with the same stderr + exit 2 contract as the config refusal above: before
    # `validate_paths`, `load_tasks`, any run record or worktree, and in `--dry-run`.
    stages_entry = resolved_config.get("workflows.prompt.stages")
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        stage_issues = stage_registry.validate_stage_list(
            "prompt", stages_entry.value or []
        )
        if stage_issues:
            print(format_issues(stage_issues), file=sys.stderr)
            return 2
    # Path preflight (E3.7, EXTRACTION.md §3.4/§3.11) at the *same* site and with the same
    # contract as the two refusals above: stderr + exit 2, before `load_tasks`,
    # `derive_branch_name`, any run record, branch or worktree, and regardless of
    # `--dry-run`. A read-path this repo does not have is exactly the "stage preflight
    # that first needs it" §3.4 names — the prompt workflow reads the roadmap and writes
    # into the task-prompts directory — and failing here is what stops an agent from
    # improvising around a missing directory. Resolved once: `max_revisions` comes from
    # the same resolution the check validated.
    path_issues = validate_paths(resolved_config, repo.root)
    if path_issues:
        print(format_issues(path_issues), file=sys.stderr)
        return 2
    max_revisions = resolved_config["max_revisions"].value
    # ``aidt`` locates the toolkit's assets (prompts, agent configs); run state lives
    # under the per-repo state root (EXTRACTION.md §3.10), resolved once by ``_roots``
    # and threaded in as ``workspace`` so no workflow re-resolves it.
    runs_root = workspace.state_root / "runs"

    # D15/D17: the roadmap location is target-repo configuration — the whole per-repo
    # surface is ``paths.roadmap_dir`` plus ``paths.roadmap_glob`` (no parser dialect).
    # Both resolve from the config already resolved above; the glob only pre-selects files
    # and ``roadmap.py``'s ``_FILENAME_RE`` stays the phase authority. ``roadmap_dir`` is
    # threaded on to the evidence bundle, whose re-read is the second consumer of the same
    # directory (roadmap-format.md §6).
    roadmap_dir = str(resolved_config["paths.roadmap_dir"].value)
    entries = load_tasks(
        repo.root / roadmap_dir, str(resolved_config["paths.roadmap_glob"].value)
    )
    entry = find_task(entries, phase, epic, task)
    if entry is None:
        print(
            f"roadmap task not found: phase={phase} epic={epic} task={task}",
            file=sys.stderr,
        )
        return 2

    # EXTRACTION.md §3.4: the branch/worktree name comes from `repo.branch_pattern`, not
    # the task id. A malformed pattern is a usage error (design §14, exit 2) before any
    # worktree or stage. `derive_branch_name` is reused from the implement workflow so
    # both workflows share one formatter contract.
    branch_name = derive_branch_name(repo.branch_pattern, phase=phase, task=task)
    if branch_name is None:
        print(
            f"malformed repo.branch_pattern {repo.branch_pattern!r}: it must be a "
            "format string referencing both `{phase}` and `{task}` "
            '(e.g. "{phase}-{task}").',
            file=sys.stderr,
        )
        return 2

    # L1.2 (design §8.1, §11): computed once, before the ``dry_run`` split, so the
    # dry-run note and the real-run refusal cannot disagree. ``entries`` already holds
    # every parsed phase file; the filter is on the target's own file and a strictly
    # earlier line, never on epic-id order (a later-sorting epic can sit on an earlier
    # line) and never across files (phase 00's unticked backlog must not block phase 02).
    incomplete = _incomplete_predecessors(entries, entry)

    # --- the run this invocation continues or replaces (H1.2 req 1/6) ------------- #
    # The lookup runs on a fresh invocation too, mirroring `implement.run`: a crashed run
    # releases its worktree lock but keeps a stale `running` record, and a fresh run that
    # ignored it would mint a second run id over the same worktree. `takeover` is what the
    # rest of this function means by "this invocation resumes": `--dry-run` never takes a
    # run over (req 8) — it always plans the fresh author + task-review-1 baseline.
    existing = _latest_prompt_run(runs_root, branch_name)
    # H1.3 req 4/7: `--from-prompt` **alone** is a takeover — locate, lock and run-id reuse
    # happen with or without `--resume` — so the H1.2 gate widens from `resume` to either
    # flag, while `--dry-run` still never takes over any run (it plans the fresh baseline).
    takeover = (resume or from_prompt is not None) and not dry_run

    if existing is not None and existing.status == RUNNING and not resume and not takeover:
        # Not `--dry-run`-gated: a dry run must not plan a second author over a run that a
        # live-or-crashed process still owns. `--resume` (real or dry-run) takes the record
        # over below, and a real `--from-prompt` takeover reaches its blocked-run-only
        # usage error instead — a running record is not a blocked one.
        print(
            f"another prompt run for `{branch_name}` is still marked running: "
            f"{existing.run_id}. Use --resume or finish it.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    # --- `--from-prompt` validation (before any side effect, H1.3 req 4/7) ------- #
    # Two usage errors, both before the confirmation, the base-branch preflights, the
    # locate, the lock and any state write: a contradictory `--from` (the route fixes its
    # own start stage at `task-review-1`, so a stage name there is not an ordering but a
    # contradiction) and a supplied file that does not exist. Neither is `--dry-run`-gated
    # — a dry run validates the flags exactly as it validates `--from`. Only the
    # missing/non-blocked-run error below is suppressed under `--dry-run` (H1.2 req 8: a dry
    # run over a missing run plans fresh).
    if from_prompt is not None:
        if from_stage is not None:
            print(
                "--from and --from-prompt cannot be combined: `--from-prompt` starts the "
                "continuation's review loop at `task-review-1` over the supplied content, "
                "so a `--from` stage name would contradict the route.",
                file=sys.stderr,
            )
            return 2
        if not from_prompt.is_file():
            print(f"--from-prompt: no such file: {from_prompt}", file=sys.stderr)
            return 2
        if not dry_run and (existing is None or existing.status != BLOCKED):
            detail = (
                "no earlier prompt run exists for it"
                if existing is None
                else f"run {existing.run_id} is `{existing.status}`, not `blocked`"
            )
            print(
                "--from-prompt continues a *blocked* prompt run for "
                f"`{branch_name}`: {detail}. A failed run uses --resume/--from.",
                file=sys.stderr,
            )
            return 2

    # H1.2 req 6 / H1.3 req 1: a blocked run's forward path is scoped by the shape of the
    # block. A review-loop block (the loop recorded its own `denied` gate) continues, and
    # `--from-prompt` continues either shape; an author-`blocked:` run and a human-gate
    # denial keep the exit-3 refusal, naming the recorded reason, *before* the
    # completed-stages print, the confirmation, the locate and the lock — nothing is
    # mutated. Exit 3 is design §14's "workflow blocked (needs human)", keeping 2 (usage)
    # and 4 (preflight refusal) for the no-run, still-running and worktree cases.
    # Deliberately not `--dry-run`-gated: a dry run must not plan an author over a blocked
    # run through a route that is no forward path for that shape.
    block_continuation = False
    if (
        existing is not None
        and existing.status == BLOCKED
        and (resume or from_prompt is not None)
    ):
        if from_prompt is None and not review_loop_block(existing):
            _refuse_blocked_resume(existing, branch_name)
            return 3
        # A dry run never takes the run over (req 7), so the located/copied part of the
        # route is unreachable there and only the fresh plan runs.
        block_continuation = not dry_run

    # H1.2 req 1: no run to resume is a usage error, matching implement. Suppressed under
    # `--dry-run` (implement's `resume and not dry_run` guard): no matching run simply
    # plans a fresh run, which is the dry run's only mode.
    if resume and not dry_run and existing is None:
        print(f"no prompt run to resume for `{branch_name}`.", file=sys.stderr)
        return 2

    # --- --from validation (grammar only; before any side effect) ---------------- #
    # H1.2 req 5, mirroring implement's F1 position: a typo'd or out-of-budget stage name
    # refuses with exit 2 before the base-branch fetch, the locate and any run state — and
    # in `--dry-run`, which validates the flag but never applies it to the plan. Validation
    # consults only the loop's grammar under the resolved `max_revisions`, never a run
    # record: every stage the loop records is grammar-valid within budget, so a run record
    # would add no accepted names.
    if from_stage is not None and not is_from_stage(from_stage, max_revisions):
        print(
            _unknown_from_stage_message(from_stage, max_revisions), file=sys.stderr
        )
        return 2

    # --- the budget this invocation's loop runs under (H1.3 req 2/4/6) ---------- #
    # A `--resume` fix cycle continues the *existing* loop one round past the reviews the
    # run recorded (`effective_max_revisions`), so the terminal review's findings finally
    # get their fix batch and reconcile and the added review is itself terminal (L4.1).
    # `--from-prompt` reviews new content, so it runs under a fresh budget — the resolved
    # `max_revisions`, never a stale `effective_max_revisions` an earlier fix cycle left on
    # the same run. `max_revisions` itself stays the resolved config value everywhere the
    # grammar is consulted (`--from` validation above, the CLI/config precedence), because a
    # per-run extension must never leak into the loop's bounded name grammar.
    fix_cycle = block_continuation and from_prompt is None
    loop_max_revisions = max_revisions
    if fix_cycle and existing is not None:
        loop_max_revisions = effective_max_revisions(existing)

    # R4: the control worktree is whichever worktree has `repo.base_branch` checked out;
    # never a fixed name. The literal "main" stays out of the code.
    control_branch = git.current_branch(repo.root)
    if dry_run:
        if control_branch != repo.base_branch:
            print(
                "[dry-run] a real run requires the base branch "
                f"`{repo.base_branch}` (currently `{control_branch}`)."
            )
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
        if control_branch != repo.base_branch:
            print(
                f"`aidw prompt` must run on the base branch `{repo.base_branch}`; "
                f"currently on `{control_branch}`.",
                file=sys.stderr,
            )
            return 4
        if not git.is_clean(repo.root):
            print("working tree is dirty; commit or stash first.", file=sys.stderr)
            return 4
        # Refuse before ``load_all``/``create_run`` so a stale base leaves no run
        # directory, no branch/worktree and no prompt file behind. A refusal
        # on roadmap ordering is deliberately checked before the network fetch: it is a
        # purely local, in-memory condition, so an unreachable ``origin`` must not be
        # spent first.
        #
        # H1.2: the two *run-scoped* preflights — L1.2's predecessor check and L1.1's
        # base-branch fetch — belong to the run being resumed and are not repeated
        # (roadmap Notes). The worktree identity and the one-run-per-worktree lock below
        # are repeated. Skipping them is what keeps a resume from re-spending the fetch
        # and from being refused by a roadmap tick that changed after the run started.
        if not takeover:
            if incomplete:
                if not allow_incomplete_prereqs:
                    _refuse_incomplete_predecessors(entry, incomplete)
                    return EXIT_REFUSED
                _warn_incomplete_predecessors(entry, incomplete)
            refusal = _verify_base_branch(repo, no_fetch=no_fetch)
            if refusal is not None:
                return refusal

    # E4.6: a declared `paths.agent_configs_dir` shadows the toolkit's agent configs by
    # id; unset passes `None` (toolkit defaults). It is a §3.4 read-path, so the
    # `validate_paths` refusal above already refused a named-but-missing directory; the
    # worktree reload below re-resolves it against the tree P1 runs in.
    agents, issues = load_all(
        aidt.root,
        repo.root,
        override_dir=agent_configs_override(resolved_config, repo.root),
    )
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    # --- declared stage settings (E4.5b, EXTRACTION.md §3.5/§3.6) --------------- #
    # After `load_all`, because the agents dict is what a repo-added stage's `agent` is
    # checked against — the validator above runs before it. `validate_stage_list` stays
    # the first stage-list refusal; this one covers the two settings the plan needs and
    # turns them into config ERRORs (stderr + exit 2) before branch setup, any run record
    # or worktree, so a missing declared prompt or an unknown repo-added agent never
    # escapes `run()` as a traceback. This workflow runs no repo-added stage (its consumer
    # is name-keyed, E4.5b's non-goal), but the declaration is still checked here and
    # warned about by `plan_stages` — accepted, never a silent drop.
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        declaration_issues = declared_stage_issues(
            "prompt",
            stages_entry.value or [],
            toolkit_root=aidt.root,
            target_root=repo.root,
            agents=agents,
        )
        if declaration_issues:
            print(format_issues(declaration_issues), file=sys.stderr)
            return 2

    default_rel = f"docs/task-prompts/{phase}-{task}-prompt.md"

    # --- resume confirmation (before the locate, the lock and any write) -------- #
    # implement's F2 position (PR #49 review follow-up): print the completed stages and
    # ask *before* the worktree locate, the lock and `create_run`, so a declined resume
    # exits 4 with no side effect at all — no locate, no lock, no run state, `state.json`
    # unchanged. `--yes` skips the question; a non-interactive session confirms.
    if takeover and existing is not None:
        print(f"resume: {existing.run_id}")
        print("completed stages:")
        _print_completed(existing)
        if not _confirm_resume(approve_all):
            print("resume declined.", file=sys.stderr)
            return EXIT_REFUSED
        # H1.2 req 4: the rebuilt batches are expanded under *this* invocation's budget,
        # and `_expand_prompt_loop` raises for more batches than it allows. Fail closed as
        # a usage/config error before the locate and the lock instead of crashing inside
        # the loop. H1.3 req 2: the guard must consult the budget the loop will actually run
        # under — `loop_max_revisions`, which is the *effective* value for a fix-cycle
        # continuation and the resolved one for a failed-run resume — because a continuation
        # legitimately recorded more fix rounds than the resolved budget allows (left on the
        # resolved value it refuses the second `--resume` on a re-blocked run as exit 2,
        # before the route is ever reached). A `--from-prompt` continuation rebuilds none of
        # the recorded rounds, so it counts none (req 4).
        recorded_fix_rounds = (
            0 if from_prompt is not None else _recorded_fix_rounds(existing)
        )
        if recorded_fix_rounds > loop_max_revisions - 1:
            print(
                f"cannot resume run {existing.run_id}: it recorded "
                f"{recorded_fix_rounds} fix round(s), but max_revisions="
                f"{loop_max_revisions} allows at most {loop_max_revisions - 1}. Re-run "
                "with a budget at least as large as the run used, or start a fresh run.",
                file=sys.stderr,
            )
            return 2

    # --- branch setup: reuse or create the task worktree (EXTRACTION.md §3.2) --- #
    # Inline Python, before the author stage: P1 must run in the task worktree, and a
    # refusal must leave no stage record or run state behind. `--dry-run` prints the plan
    # and creates nothing.
    #
    # H1.2: locate first and create only when none exists. `git.add_worktree` returns None
    # (discarding git's stderr) for an already-checked-out branch, which is exactly what an
    # earlier prompt/implement run leaves behind — so calling it unconditionally refused
    # every re-run and every resume. A resume proceeds in the failed run's own worktree: its
    # partial edits are the state it continues from (H1.1's accepted precedent) and its
    # reconcile/next review still verify the result. A fresh re-run reuses a located
    # worktree only when it is clean; a truncated fixer can leave partial prompt edits, so a
    # dirty tree is refused rather than reused or discarded (design §13 — the discard stays
    # operator-owned and `--force`-explicit). Both fresh-path refusals sit here: after the
    # L1.1/L1.2 preflights, before the lock, `create_run` and any stage.
    target = repo
    if dry_run:
        planned_worktree = workspace.workspace_root / branch_name
        print(
            f"branch-setup (planned): worktree add -b {branch_name} "
            f"{planned_worktree} {repo.base_branch}"
        )
    else:
        planned_worktree = (workspace.workspace_root / branch_name).resolve()
        worktree = git.worktree_for_branch(repo.root, branch_name)
        if worktree is not None:
            if not takeover and not git.is_clean(worktree):
                remove_command, branch_command = worktree_clear_commands(
                    workspace, branch_name, repo.base_branch
                )
                print(
                    f"branch-setup refused: the existing worktree for `{branch_name}` "
                    f"at {worktree} has uncommitted changes (a truncated fixer can leave "
                    "partial prompt edits), so a fresh run will neither reuse nor discard "
                    "them. Inspect or commit them, or clear the worktree and branch and "
                    "start again:",
                    file=sys.stderr,
                )
                print(f"  {remove_command}", file=sys.stderr)
                print(f"  {branch_command}", file=sys.stderr)
                return EXIT_REFUSED
        elif takeover and existing is not None:
            if block_continuation:
                # H1.3 req 5: a blocked continuation continues in the run's own worktree and
                # never silently re-creates it or re-authors the prompt. Name the run, the
                # missing worktree and the re-author command; plain `git worktree add` is
                # not offered because the branch's commits are not where the reviewed prompt
                # was (a block commits nothing).
                print(
                    f"continuation refused: run {existing.run_id} has no worktree for "
                    f"`{branch_name}` (missing: {planned_worktree}). A blocked-run "
                    "continuation runs in the run's own worktree and never re-creates or "
                    "re-authors it; re-author the task prompt with:",
                    file=sys.stderr,
                )
                print(f"  aidw prompt {phase} {epic} {task}", file=sys.stderr)
                return EXIT_REFUSED
            base_worktree = workspace.workspace_root / repo.base_branch
            print(
                f"resume refused: run {existing.run_id} has no worktree for "
                f"`{branch_name}` (expected at {planned_worktree}). A resume continues in "
                "the run's own worktree and never re-creates or re-authors it; re-create "
                "the worktree for the existing branch first:",
                file=sys.stderr,
            )
            print(
                f"  git -C {base_worktree} worktree add {planned_worktree} {branch_name}",
                file=sys.stderr,
            )
            return EXIT_REFUSED
        else:
            worktree = git.add_worktree(
                repo.root, branch_name, base_branch=repo.base_branch
            )
            if worktree is None:
                remove_command, branch_command = worktree_clear_commands(
                    workspace, branch_name, repo.base_branch
                )
                print(
                    f"branch-setup refused: git could not create a worktree for "
                    f"`{branch_name}` from `{repo.base_branch}` at "
                    f"{planned_worktree}. The branch is probably left over from an "
                    "earlier failed run (one branch, one worktree) or git refused for "
                    "another reason; clear it and re-run:",
                    file=sys.stderr,
                )
                print(f"  {remove_command}", file=sys.stderr)
                print(f"  {branch_command}", file=sys.stderr)
                return EXIT_REFUSED
        # Re-resolve the target and agents against the worktree: `agent.cwd` was
        # resolved against the control root and would silently keep P1 and every review
        # or fix stage in the wrong worktree (§3.2, E2.4's branch-setup order).
        resolved = TargetRepo.resolve(worktree)
        target = replace(
            resolved,
            base_branch=repo.base_branch,
            branch_pattern=repo.branch_pattern,
        )
        agents, _ = load_all(
            aidt.root,
            target.root,
            override_dir=agent_configs_override(resolved_config, target.root),
        )

    # --- one run per worktree (EXTRACTION.md §3.2/§3.10, E2.7) ---------------- #
    # The key is the *resolved* worktree path -- ``target.root``, the same value
    # ``create_run`` records as ``repo_root`` -- never the branch: a detached-HEAD
    # worktree has no branch, and §3.2 says "keyed by worktree path". Acquired
    # immediately before ``create_run`` (the point where the key is final) and released
    # on every exit path below, refusals and failures included, so the worktree cannot
    # stay locked until process exit. It lives in the state root, never in a target
    # repo or worktree (§3.1), and it is neither ``_STATE_LOCK`` (in-process, per
    # ``state.json`` write) nor ``--parallel`` (concurrent stages inside one run).
    # A dry run acquires the same lock (against the control worktree, the only tree a dry
    # run has), so a peer run is refused here (exit 4, §19 item 8) before any plan output;
    # the lock is released on every exit path.
    try:
        run_lock = lock.acquire(workspace.state_root, target.root)
    except lock.LockHeldError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    try:
        if takeover and existing is not None:
            # H1.2 req 4/7: one run id. Reuse the recorded object and its run directory
            # exactly as `implement.py` does — no `create_run`, so later stages append to
            # the same `state.stages` and the recorded gate outcomes survive `save()`
            # (H0.1's merge-on-write). A record still marked `running` (a crashed run) is
            # taken over the same way: its in-flight stage is not `succeeded`, so it re-runs
            # below and no `next_stage` is needed to find it.
            state = existing
            directory = run_dir(runs_root, state.run_id)
            logger = RunLogger(directory, stream=stream)
            if fix_cycle:
                # H1.3 req 2/6: record the budget this continuation runs under, so the
                # extension is visible in `state.json` rather than inferred from two gates.
                # Additive in the free-form `task` dict (design §9.2), so a pre-H1.3
                # `state.json` still loads and no schema field moves.
                state.task["effective_max_revisions"] = loop_max_revisions
            if from_prompt is not None:
                # H1.3 req 4: copy the supplied content onto the canonical path and record
                # its provenance. A dirty canonical path refuses exit 4 before the copy
                # (design §13), so a blocked run's own uncommitted prompt edits are never
                # discarded.
                refusal, provenance = _apply_from_prompt(
                    target.root,
                    default_rel,
                    from_prompt,
                    run_id=state.run_id,
                    workspace=workspace,
                    branch=branch_name,
                    base_branch=repo.base_branch,
                )
                if refusal is not None:
                    return refusal
                state.task["from_prompt"] = provenance
        else:
            # EXTRACTION.md §3.11 (E8.2): what produced this run. One helper so the five
            # workflows cannot record different values for one config.
            config_schema_version, config_hash = config_identity(resolved_config)
            # W1.2: a plan creates no run — `planned_run` is `create_run` under the
            # never-saved PLANNED_RUN_ID (identical signature, no write), and the plan's
            # directory is the `<run dir>` placeholder a real run replaces with run_dir().
            state = (planned_run if dry_run else create_run)(
                runs_root,
                target.root,
                "prompt",
                label=label or f"{phase}-{task}",
                task={"phase": phase, "epic": epic, "task": task, "title": entry.title},
                strict=strict,
                branch=branch_name,
                toolkit_version=__version__,
                config_schema_version=config_schema_version,
                config_hash=config_hash,
            )
            if dry_run:
                directory = Path(PLANNED_RUN_DIR_TEXT)
                logger = NullLogger(stream=stream)
            else:
                directory = run_dir(runs_root, state.run_id)
                logger = RunLogger(directory, stream=stream)
        logger.info(f"prompt workflow {phase}/{epic}/{task}: {entry.title}")
        if not dry_run:
            print(f"run:    {state.run_id}")
        print(f"task:   {entry.title}")

        # --- stage selection (H1.2 req 4/5) --------------------------------------- #
        # Two *forcing* positions: `resume.next_stage` (where the failed run stopped) and
        # `--from` (the explicit override, applied when the loop reaches the named stage).
        # A stage at or after a position runs even when its record says `succeeded`:
        # "completed stages are never re-run implicitly" (design §9.4) — both flags are the
        # explicit override. Everything else keeps its own skip decision, which is exactly
        # `record is not succeeded`, so a stage that never ran or failed re-runs.
        # `--from` is applied on *encounter* rather than from an up-front name list, so a
        # grammar-valid name absent from this run's plan (a fix index that round never had)
        # degrades as `implement.py` does: no position override, no crash.
        resume_position: tuple[int, int, int] | None = None
        forced_position: tuple[int, int, int] | None = None
        if takeover and existing is not None:
            next_stage = (existing.resume or {}).get("next_stage")
            if isinstance(next_stage, str):
                resume_position = prompt_stage_position(next_stage)
                if resume_position is not None:
                    logger.info(f"resume: continuing at {next_stage}")
        if from_prompt is not None and not dry_run:
            # H1.3 req 4: the route's own position bound, set by the route itself (the flag
            # is refused alongside `--from`). Position 2 is `task-review-1`; `task-prompt`
            # sorts before it, so the author record is still reused and the run never
            # re-authors. A bound rather than skipping the old reviews is load-bearing: their
            # recorded `succeeded` text would otherwise re-parse as stale findings.
            forced_position = prompt_stage_position("task-review-1")
            logger.info("--from-prompt: re-running the review loop from task-review-1")

        def note_from(name: str) -> None:
            """Apply the `--from` override when the loop reaches the named stage."""
            nonlocal forced_position
            if not dry_run and from_stage is not None and name == from_stage:
                forced_position = prompt_stage_position(name)
                logger.info(f"--from {name}: re-running from {name}")

        def should_run(name: str) -> bool:
            """Whether this invocation runs ``name`` (a resume reuses what succeeded)."""
            position = prompt_stage_position(name)
            if position is not None:
                for bound in (resume_position, forced_position):
                    if bound is not None and position >= bound:
                        return True
            record = state.stage(name)
            return not (record is not None and record.status == SUCCEEDED)

        # P1 and the first review come from the registry (E4.3). The dry run plans exactly
        # what it can: `rounds=()` expands to the author plus one review (`task-review-1`),
        # which is the unchanged dry-run baseline; the full post-phase-02 chain (a review per
        # round, a reconcile per batch, a review-only terminal review) is what the loop
        # re-expands above as real verdicts accumulate.
        dry_specs, _dry_briefs = _prompt_plan(
            config=resolved_config,
            toolkit_root=aidt.root,
            target_root=target.root,
            phase=phase,
            epic=epic,
            task=task,
            rel=default_rel,
            max_revisions=loop_max_revisions,
            rounds=[],
        )
        author = dry_specs["task-prompt"]

        # H1.2 req 4: a resume that already has a succeeded author never re-authors — the
        # recorded stage is the review loop's input, so its record (and `out.txt`) is read
        # instead. `--from task-prompt` forces it back on, and a failed author re-runs
        # because its record is not `succeeded`.
        note_from(author.name)
        author_record = state.stage(author.name)
        reuse_author = (
            not dry_run
            and author_record is not None
            and author_record.status == SUCCEEDED
            and not should_run(author.name)
        )
        if reuse_author:
            print(f"stage:  {author.name} [skipped]")
            rec1 = author_record
        else:
            # L1.3: the task worktree is deterministic, so the blocked report names it
            # unconditionally and the old before/after branch probe is gone.
            rec1 = run_stage(
                author,
                repo_root=target.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                dry_run=dry_run,
                config=resolved_config,
            )
            print_stage(rec1, repo_root=target.root)

        if dry_run:
            rec2 = run_stage(
                dry_specs["task-review-1"],
                repo_root=target.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                dry_run=True,
                config=resolved_config,
            )
            print(f"stage:  {rec2.name} [{rec2.status}] (planned) model={rec2.model}")
            print("dry-run complete; Pi not invoked")
            return 0

        if rec1.status != SUCCEEDED:
            print(f"task-prompt stage failed: {rec1.error}", file=sys.stderr)
            _mark_failed(state, directory, rec1.name)
            return 1

        # L1.3: detect the blocked report before ``_resolve_prompt_path`` tries the first
        # line as a path and falls back to the conventional location — otherwise a
        # ``blocked:`` line would be silently ignored whenever the author also left a file.
        # The author stage stays ``succeeded`` (it exited 0 with a valid report); the *run* is
        # what is blocked, and no commit, review or fix stage follows.
        # H1.3 req 4: a `--from-prompt` continuation reviews the operator's content, so the
        # author's recorded marker no longer governs the run — `--from-prompt` is exactly an
        # author-``blocked:`` run's forward path, and re-reading the old line would re-block
        # it before the supplied prompt was ever reviewed.
        blocked_reason = (
            None if from_prompt is not None else _parse_blocked(_read_out(rec1))
        )
        if blocked_reason is not None:
            reason = blocked_reason or "no reason given"
            logger.error(f"task-prompt author reported blocked: {reason}")
            _report_blocked_leftovers(target.root, branch=branch_name)
            _mark_blocked(state, directory)
            print(f"blocked: {reason}", file=sys.stderr)
            return 3

        # H1.3 req 4: a `--from-prompt` route wrote the supplied content onto the canonical
        # path, so that is the file `rel`, the evidence bundle and `_commit_reviewed_prompt`
        # are about; resolving it from the author's old output would review a stale path.
        prompt_path = (
            target.root / default_rel
            if from_prompt is not None
            else _resolve_prompt_path(target.root, rec1, default_rel)
        )
        if prompt_path is None:
            print(
                f"generated task prompt not found at {default_rel}",
                file=sys.stderr,
            )
            # H1.2 req 3: name the author. Its record is `succeeded`, but a resume forces
            # from `next_stage`, so re-authoring is exactly the recovery — the alternative
            # is a resume that fails again at this line.
            _mark_failed(state, directory, author.name)
            return 1
        rel = prompt_path.relative_to(target.root).as_posix()
        print(f"prompt: {rel}")
        # The conciseness budget is the author's postcondition (L5.3), so it is not
        # re-measured on a resume: a prompt a later stage's failure left behind is not
        # re-judged by a check the run already passed (and `--strict` must not turn a
        # resume into a fresh failure).
        if not reuse_author:
            budget_reason = _check_conciseness(prompt_path, rel)
            if budget_reason is not None:
                # L5.3: a workflow-level quality bound, not a gate. At the default it warns
                # and the review loop still runs; `--strict` refuses with the stage-failure
                # exit 1, records FAILED and no gate, and leaves the committed
                # prompt/branch as-is (design §13/§14; no new gate-decision vocabulary,
                # L4.2). `next_stage` names the author: re-authoring is the only way a
                # resume can clear an over-budget prompt.
                if strict:
                    print(f"refusing (--strict): {budget_reason}", file=sys.stderr)
                    _mark_failed(state, directory, author.name)
                    return 1
                print(f"warning: {budget_reason}", file=sys.stderr)
        state.git["branch"] = branch_name
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
        # L4.2: per-round ``(review_index, findings_count, fix_stage_count)`` telemetry,
        # accumulated in the loop so the gate detail and run.log carry the real per-round
        # counts rather than a number reconstructed from stage names.
        rounds: list[ReviewRound] = []
        #: The fix batches this run has accumulated, one per fixing round. They are the
        #: ``prompt`` loop's expansion input (E4.3 req 1/5): each round re-expands the chain
        #: with the batches known so far, so the stages that have not been reached yet are
        #: planned but ignored.
        fix_batches: list[stage_registry.FixBatch] = []
        while True:
            review_index += 1
            name = f"task-review-{review_index}"
            # This round's stages, expanded by the registry from the batches known so far.
            # The review stage's prompt, variables and name come from there; so does the
            # `brief` marker that decides whether this round gets a delta brief.
            specs, briefs = _prompt_plan(
                config=resolved_config,
                toolkit_root=aidt.root,
                target_root=target.root,
                phase=phase,
                epic=epic,
                task=task,
                rel=rel,
                max_revisions=loop_max_revisions,
                rounds=fix_batches,
            )
            spec = specs[name]
            note_from(name)
            # H1.2 req 4: a resume reconstructs the loop by walking the *recorded* rounds,
            # never by re-running them. A round whose record says `succeeded` is skipped and
            # its text re-read, exactly as if it had just run — that is what keeps the
            # verdict, the findings and the round's fix batch real rather than inferred from
            # stage names (which carry only counts). `--from`/`next_stage` force a re-run at
            # or after their position; a failed or missing record re-runs by default.
            record = state.stage(name)
            review_ran = True
            if not should_run(name):
                recorded_text = _read_out(record) or ""
                if recorded_text.strip():
                    print(f"stage:  {name} [skipped]")
                    review_text = recorded_text
                    review_ran = False
                else:
                    # A recorded review whose output is gone cannot drive the loop; re-run
                    # it instead of fabricating a verdict from a name.
                    print(
                        f"warning: the recorded review `{name}` has no saved output; "
                        "re-running it.",
                        file=sys.stderr,
                    )
            if review_ran:
                # Round 1 is deliberately unprimed: the registry zeroes the marker on the
                # first round (L2.3), so the independent first sample cannot anchor on a
                # previous review. Every round still receives its evidence pointer —
                # gathered context, not prior findings.
                delta = ""
                if briefs.get(name) == stage_registry.BRIEF_DELTA:
                    delta = stage_registry.render_delta_brief(
                        previous_review=previous_review_text or "",
                        diff=_brief_diff(
                            index=review_index,
                            baseline=baseline_prompt,
                            current=_capture_prompt(prompt_path),
                            rel=rel,
                            verb="baseline",
                            brief_name="delta brief",
                        ),
                    )
                pointer = _stage_evidence_pointer(
                    stage=name,
                    directory=directory,
                    repo=target,
                    entry=entry,
                    entries=entries,
                    rel=rel,
                    roadmap_dir=roadmap_dir,
                )
                rec = run_stage(
                    _with_pointer(spec, pointer, delta),
                    repo_root=target.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    config=resolved_config,
                )
                print_stage(rec, repo_root=target.root)
                if rec.status != SUCCEEDED:
                    print(f"stage {name} failed: {rec.error}", file=sys.stderr)
                    _mark_failed(state, directory, name)
                    return 1

                review_text = _read_out(rec) or ""
                if not review_text.strip():
                    message = empty_final_message_error(rec)
                    logger.error(message)
                    print(f"{message}; stopping.", file=sys.stderr)
                    _mark_failed(state, directory, name)
                    return 1

            verdict = parse_verdict(review_text)
            findings, problems = parse_review_findings(review_text)
            findings_count = len(findings)
            if verdict == APPROVE:
                print(f"verdict: {verdict}")
            else:
                print(f"verdict: {verdict or 'ambiguous'} — {findings_summary(findings)}")

            # H1.3 req 2/3: a *fix-cycle* continuation re-opens the recorded rounds. Their
            # verdicts already decided the blocked run — replaying an `Approve` (M2) or a
            # `Blocked` here would re-block without a forward path, since the original run
            # already recorded that decision. A replayed round therefore contributes only
            # its re-parsed fix batch (and, for the last recorded round, the fix stages and
            # reconcile the terminal break never let it plan); the continuation's own added
            # review is what decides this invocation, and it is the `max_revisions`-th
            # review under `loop_max_revisions`, so L4.1 holds in the continuation too.
            replay_only = fix_cycle and not review_ran

            # H1.2 req 4: a *skipped* review is the record of what this run decided. If its
            # re-parsed verdict is now an exit (approve, Blocked, or the terminal budget)
            # while the run recorded later stages, the loop cannot be rebuilt from its
            # records — the toolkit's parsers changed between invocations. Fail closed
            # (exit 4, nothing written by this invocation) rather than "finishing" a run
            # that still holds a failed stage. A continuation replays deliberately, so the
            # drift guard does not apply to it.
            if not review_ran and not replay_only and (
                verdict in (APPROVE, VERDICT_BLOCKED)
                or revisions >= loop_max_revisions - 1
            ):
                later = _recorded_later_stage(
                    state, prompt_stage_position(name) or (0, 0, 0)
                )
                if later is not None:
                    print(
                        f"cannot resume: the recorded review `{name}` now reads "
                        f"`{verdict or 'ambiguous'}` and would end the run, but the run "
                        f"recorded `{later}` after it. The loop cannot be rebuilt "
                        "faithfully from its records; nothing was changed.",
                        file=sys.stderr,
                    )
                    return EXIT_REFUSED

            blocking, could_fix = partition_findings(findings)
            if verdict == APPROVE and blocking and not replay_only:
                # M2: `Approve` while reporting must-fix/should-fix findings is a
                # self-contradicting review — the mirror image of `review`'s "requires
                # changes but no findings could be extracted" refusal. The evidence is not
                # silently dropped and the verdict is not silently overridden: the run
                # stops so a human can decide which half of the report to trust. Without
                # this, E4.5b approved a prompt whose first finding made its central
                # construction requirement a `TypeError` (2026-11-04).
                _record_round(rounds, review_index, findings_count, 0)
                logger.error(
                    f"task review approved but reported {len(blocking)} blocking "
                    "finding(s); failing closed."
                )
                _record_review_outcome(
                    state,
                    logger,
                    verdict=verdict,
                    revisions=revisions,
                    max_revisions=loop_max_revisions,
                    rounds=rounds,
                    decision="denied",
                    mechanism="review-loop",
                )
                _mark_blocked(state, directory)
                print(
                    f"task review approved but reported {len(blocking)} blocking "
                    f"finding(s) ({findings_summary(blocking)}); a human must settle it.",
                    file=sys.stderr,
                )
                print(review_text, file=sys.stderr)
                return 3
            if verdict == APPROVE and not replay_only:
                # L4.2: an approving round ran no fix stage, so its fix count is 0.
                _record_round(rounds, review_index, findings_count, 0)
                break
            if verdict == VERDICT_BLOCKED and not replay_only:
                # A `Blocked` verdict means a material ambiguity only a human can settle, so
                # it short-circuits before any fix stage and before any ``approve_all`` path
                # can reach the gate or :func:`_commit_reviewed_prompt` — the prompt stays
                # uncommitted and the run fails closed (design §8.1/§8.3, L2.1). This runs
                # before ``revisions += 1`` so a Blocked review never spawns a fixer, with or
                # without parsed findings.
                _record_round(rounds, review_index, findings_count, 0)
                logger.error("task review returned Blocked; failing closed.")
                _record_review_outcome(
                    state,
                    logger,
                    verdict=verdict,
                    revisions=revisions,
                    max_revisions=loop_max_revisions,
                    rounds=rounds,
                    decision="denied",
                    mechanism="review-loop",
                )
                _mark_blocked(state, directory)
                print(
                    "task review returned Blocked; a human must settle it.",
                    file=sys.stderr,
                )
                print(review_text, file=sys.stderr)
                return 3
            if not replay_only and revisions >= loop_max_revisions - 1:
                # The fix budget is spent: the terminal review has now run. There is no further
                # revision slot, so a residual `Request changes` fails closed rather than being
                # applied unreviewed — the prompt is left uncommitted for a human to settle, with
                # this review's findings on stderr. `Blocked` short-circuited above, so it keeps
                # its own "a human must settle it" message. L4.2 records the gate and the
                # summary here too: run.log used to stay silent on exactly this symptom.
                _record_round(rounds, review_index, findings_count, 0)
                logger.error(
                    "task review did not approve within the revision budget; run BLOCKED"
                )
                _record_review_outcome(
                    state,
                    logger,
                    verdict=verdict,
                    revisions=revisions,
                    max_revisions=loop_max_revisions,
                    rounds=rounds,
                    decision="denied",
                    mechanism="review-loop",
                )
                _mark_blocked(state, directory)
                print(
                    "task review did not approve within the revision budget; failing closed.",
                    file=sys.stderr,
                )
                print(review_text, file=sys.stderr)
                return 3

            # Capture after the verdict and its Blocked/terminal exits, before the fix
            # stages run, so the next round's diff is exactly this fix batch's net effect and
            # not a cumulative diff across rounds (there is no per-round commit to diff against).
            # H1.2 req 4: only a round that ran *here* has a real pre-fix snapshot. On a
            # resume the prompt already carries this round's recorded fixes, so capturing
            # it now would fabricate a baseline — the brief degrades via `_brief_diff(...
            # baseline=None)` instead.
            baseline_prompt = _capture_prompt(prompt_path) if review_ran else None
            previous_review_text = review_text
            revisions += 1
            # The round's fix work as registry input (E4.3): one batch, whose partition
            # (computed above, before the approve/ambiguous exits) selects one stage per
            # blocking finding, one combined could-fix stage, or the single whole-review
            # fallback when nothing parsed cleanly.
            unparseable = not findings or bool(problems)
            fix_batches.append(
                stage_registry.FixBatch(
                    review_text=review_text,
                    blocking=tuple(blocking),
                    could_fix=tuple(could_fix),
                    unparseable=unparseable,
                )
            )
            specs, briefs = _prompt_plan(
                config=resolved_config,
                toolkit_root=aidt.root,
                target_root=target.root,
                phase=phase,
                epic=epic,
                task=task,
                rel=rel,
                max_revisions=loop_max_revisions,
                rounds=fix_batches,
            )
            # This batch's stages: everything the expansion put after this round's review and
            # before the next one — its fix stages plus its single reconcile stage (L3.4).
            ordered = list(specs)
            next_review = f"task-review-{review_index + 1}"
            batch_specs = [
                specs[stage_name]
                for stage_name in ordered[
                    ordered.index(name) + 1 : ordered.index(next_review)
                ]
            ]
            fix_specs = [
                spec
                for spec in batch_specs
                if spec.id != stage_registry.PROMPT_RECONCILE
            ]
            (reconcile_spec,) = [
                spec
                for spec in batch_specs
                if spec.id == stage_registry.PROMPT_RECONCILE
            ]
            # L4.2: a fixing round's fix count comes from the expansion, so it cannot drift
            # from the stages that actually run: the fallback is one stage, a parsed review
            # one per blocking finding plus one combined could-fix stage.
            fix_stage_count = len(fix_specs)

            # H1.2 req 4: a *skipped* round's rebuilt batch must account for every fix stage
            # the run recorded for it. The names carry only counts, so the re-parsed batch is
            # the authority for what runs; a recorded name it cannot reproduce means the loop
            # cannot be rebuilt faithfully (a parser or budget change between invocations) and
            # the run refuses instead of silently dropping a stage. Nothing has been written
            # in this invocation, so the refusal leaves the recorded run untouched.
            if not review_ran:
                rebuilt_names = [entry.name for entry in fix_specs]
                problem = _reconcile_recorded_fixes(
                    _recorded_fix_names(state, review_index), rebuilt_names
                )
                if problem is not None:
                    print(
                        f"cannot resume: {problem} for review round {review_index} "
                        f"({name}); the run's fix batch cannot be rebuilt from its recorded "
                        "review. Nothing was changed.",
                        file=sys.stderr,
                    )
                    return EXIT_REFUSED

            def execute_fix(spec: StageSpec, banner: str = "") -> bool:
                """Run one fix stage unless it already succeeded; return its success (H1.2)."""
                note_from(spec.name)
                if not should_run(spec.name):
                    print(f"stage:  {spec.name} [skipped]")
                    return True
                if banner:
                    print(banner)
                _snapshot_fix_stage(
                    stage=spec.name, directory=directory, prompt_path=prompt_path
                )
                pointer = _stage_evidence_pointer(
                    stage=spec.name,
                    directory=directory,
                    repo=target,
                    entry=entry,
                    entries=entries,
                    rel=rel,
                    roadmap_dir=roadmap_dir,
                )
                rec_fix = run_stage(
                    _with_pointer(spec, pointer),
                    repo_root=target.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    config=resolved_config,
                )
                print_stage(rec_fix, repo_root=target.root)
                if rec_fix.status != SUCCEEDED:
                    print(f"stage {spec.name} failed: {rec_fix.error}", file=sys.stderr)
                    _mark_failed(state, directory, spec.name)
                    return False
                return True

            if unparseable:
                if problems:
                    print(
                        f"         {len(problems)} finding block(s) did not parse cleanly "
                        f"({problems[0]}); reworking with the whole review instead"
                    )
                for spec in fix_specs:
                    if not execute_fix(spec):
                        return 1
            else:
                # Blocking findings are fixed one at a time so progress is visible per change;
                # the non-blocking could-fix findings share a single stage, so they cost one
                # invocation instead of one each. The registry renders each stage's finding
                # block into `extra` from the same partition; the loop only reports on it.
                steps: list[tuple[str, list[ParsedFinding]]] = [
                    ("finding", [finding]) for finding in blocking
                ]
                if could_fix:
                    steps.append(("combined", could_fix))
                total = len(steps)

                for index, (spec, (kind, group)) in enumerate(
                    zip(fix_specs, steps, strict=True), start=1
                ):
                    prefix = f"fix {revisions}.{index}/{total}:"
                    if kind == "finding":
                        banner = (
                            f"{prefix} {finding_title(group[0])} "
                            f"[{group[0].priority}]"
                        )
                    else:
                        noun = "finding" if len(group) == 1 else "findings"
                        banner = f"{prefix} {len(group)} could-fix {noun} combined"
                    if not execute_fix(spec, banner):
                        return 1

            # L3.4: one reconcile stage per fix batch, after the batch and before the next
            # review. The fixers work one finding at a time and prefer the smallest edit, so the
            # batch can end internally inconsistent. After L4.1 there is no final fix batch to
            # reconcile: a review is always the last stage for a non-approving prompt, and
            # ``max_revisions`` counts review rounds with the last one review-only. Its name
            # matches neither ``task-review-N`` nor ``task-review-fixes-*`` — the L3.3 snapshot
            # writer, the ``_fix_round`` regex and the harness's ``fix_status`` branch all
            # leave it alone.
            # H1.2 req 4: a resume skips a reconcile that already succeeded, and renders the
            # brief only when the stage actually runs (a skipped stage's diff is both wasted
            # work and a warning the operator cannot act on).
            note_from(reconcile_spec.name)
            if should_run(reconcile_spec.name):
                reconcile_render = ""
                if briefs.get(reconcile_spec.name) == stage_registry.BRIEF_RECONCILE:
                    reconcile_render = stage_registry.render_reconcile(
                        review=review_text,
                        diff=_brief_diff(
                            index=review_index,
                            baseline=baseline_prompt,
                            # Captured here, before run_stage: this is the fix batch's net
                            # effect, not a diff polluted by the reconcile edit itself.
                            current=_capture_prompt(prompt_path),
                            rel=rel,
                            verb="reconcile",
                            brief_name="reconcile brief",
                        ),
                    )
                pointer = _stage_evidence_pointer(
                    stage=reconcile_spec.name,
                    directory=directory,
                    repo=target,
                    entry=entry,
                    entries=entries,
                    rel=rel,
                    roadmap_dir=roadmap_dir,
                )
                rec_reconcile = run_stage(
                    _with_pointer(reconcile_spec, pointer, reconcile_render),
                    repo_root=target.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    config=resolved_config,
                )
                print_stage(rec_reconcile, repo_root=target.root)
                if rec_reconcile.status != SUCCEEDED:
                    print(
                        f"stage {reconcile_spec.name} failed: {rec_reconcile.error}",
                        file=sys.stderr,
                    )
                    _mark_failed(state, directory, reconcile_spec.name)
                    return 1
            else:
                print(f"stage:  {reconcile_spec.name} [skipped]")

            # L4.2 (review follow-up #31): recorded only now that the whole fix batch and
            # its reconcile ran — ``fix_stage_count`` is predicted above, and a round line
            # printed before the batch would outlive a mid-batch ``return 1`` above and
            # overstate the stages the run actually completed.
            _record_round(rounds, review_index, findings_count, fix_stage_count)

        verdict_line = f"Review verdict: {verdict or 'ambiguous'}"
        summary = "\n".join(
            [
                f"Task: {phase} {epic} {task} — {entry.title}",
                f"Prompt: {prompt_path.relative_to(target.root)}",
                verdict_line,
            ]
        )
        # design §9.4: gates already approved are not re-asked, so a resume that reaches a
        # run whose `approve-task-prompt` gate is recorded `approved` does not prompt again.
        already_approved = any(
            gate.name == GATE and gate.decision == "approved" for gate in state.gates
        )
        if already_approved:
            print(f"gate:   {GATE} [already approved]")
            outcome = GateOutcome(GATE, True, "already approved")
        elif require_approval:
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
        # H1.3 req 6: report the budget this loop actually ran under — the effective one
        # for a `--resume` fix-cycle continuation, the resolved `max_revisions` for a fresh
        # run and for `--from-prompt` (which never claims an extension it did not use), so a
        # continuation's gate is distinguishable from the blocked run's by its `detail`.
        _record_review_outcome(
            state,
            logger,
            verdict=verdict,
            revisions=revisions,
            max_revisions=loop_max_revisions,
            rounds=rounds,
            decision=outcome.decision,
            mechanism=outcome.mechanism,
        )
        if not outcome.approved:
            _mark_blocked(state, directory)
            print(f"gate {GATE} denied ({outcome.mechanism}); stopping.", file=sys.stderr)
            return 3

        # The author no longer commits: this is the single commit point for the authored
        # (initial or reviewed) prompt, in the task worktree on the branch it already has
        # checked out. Only the owned prompt path is committed.
        if _commit_reviewed_prompt(target.root, rel, phase, task):
            logger.info(f"reviewed prompt committed or unchanged: {rel}")
        else:
            logger.error(f"failed to commit reviewed prompt {rel}")
            print(
                f"warning: could not commit the reviewed prompt ({rel}); "
                "the branch is dirty",
                file=sys.stderr,
            )

        # H1.2 req 3: a successful run clears the resume key, so a later `--resume` cannot
        # continue past a run that already finished.
        state.status = SUCCEEDED
        state.resume = {"next_stage": None}
        save(directory, state)
        print("prompt workflow complete")
        print(f"branch: {branch_name}")
        print(f"prompt: {rel}")
        return 0
    finally:
        run_lock.release()
