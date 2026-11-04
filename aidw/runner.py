"""Stage runner: the primitive that executes one agent stage (design §4, §8).

A stage is one Pi invocation with one prompt and one agent. Workflows orchestrate
stages; this module performs the mechanics: resolve the prompt, render variables,
compute the session id, run Pi, and record the stage in run state.

It also owns :func:`plan_stages`, the single run-path plan builder: every workflow's stage
list comes from the ``aidw.stage_registry`` defaults mapped through :func:`resolve_prompt`
plus the target repo's ``prompt:`` overlay, never from a hand-built list (EXTRACTION.md
§3.5, D2/D14, task E4.3).

``aidw exec`` exposes the runner directly for manual/dry-run use and for Phase 2 validation.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from aidw import stage_registry
from aidw.agents import build_argv, build_env, prompt_template_dirs
from aidw.config import ERROR, AgentConfig, Issue, format_issues, load_all
from aidw.log import RunLogger
from aidw.pi import PiResult, execute, write_meta
from aidw.paths import RUN_ID_ENV_VAR, SCRIPTS_DIR_ENV_VAR, STAGE_ENV_VAR
from aidw.progress import ProgressIndicator, resolve_enabled
from aidw.prompts import render_prompt_file
from aidw.report import cost_note
from aidw.target_config import SOURCE_CONFIG, ResolvedConfig
from aidw.state import (
    FAILED,
    PLANNED,
    RUNNING,
    SUCCEEDED,
    RunState,
    StageRecord,
    run_dir,
    save,
    session_id,
    utcnow_iso,
)


@dataclass
class StageSpec:
    name: str
    agent_id: str
    prompt: Path
    variables: list[str]
    workflow: str = "stage"
    extra: str = ""
    #: The stage config's declared ``prompt:`` value as a plain string, or ``None`` when
    #: the stage named its prompt by filename (D14). It rides on the spec next to the
    #: *resolved* :attr:`prompt` so ``run_stage`` can hand Pi the same file as an
    #: explicit ``--prompt-template`` root (EXTRACTION.md §3.6). Only the caller that
    #: resolves the prompt can set it — the resolver must stay a leaf (E4.2).
    explicit_prompt: str | None = None
    #: Optional postcondition, checked after Pi reports success. It must re-read the
    #: external state the stage was supposed to change and return a human-readable
    #: error when that state is wrong (``None`` when the stage's contract holds). A
    #: zero exit from the agent is not evidence that the work happened: an agent can
    #: stop and report a problem in its final message while still exiting 0, so the
    #: stage is marked ``failed`` whenever the check does not pass (design §10).
    verify: Callable[[], str | None] | None = None
    #: The retained §3.5 stage id (``"I1"``, ``"R2"``, ``"A1"``…). ``id`` and ``name`` are
    #: different fields on purpose: run state and the run artifacts key on ``name``, while
    #: the workflow's progress lines print the id (E4.3). :func:`plan_stages` sets it from
    #: the registry's :class:`~aidw.stage_registry.PlannedStage`; it stays empty for a spec
    #: a workflow builds for a stage the registry does not carry.
    id: str = ""


#: Retry a clearly transient Pi invocation error once (design E6, §10). ``aidw
#: --no-retry-transient`` flips this for the whole process.
DEFAULT_RETRY_TRANSIENT = True

#: Show ``.`` progress while Pi works (design §9.3). ``None`` means auto: on only when
#: stderr is an interactive terminal. ``aidw --progress`` / ``--no-progress`` overrides it
#: for the whole process.
DEFAULT_PROGRESS: bool | None = None

#: Serializes run-state mutations so two stages may execute concurrently (design
#: §8 ``--parallel``) without corrupting ``state.json``. Pi itself runs outside the
#: lock; only the short record/save sections are held.
_STATE_LOCK = threading.Lock()


def resolve_prompt(
    toolkit_root: Path,
    target_root: Path,
    name: str,
    explicit_path: str | None = None,
) -> Path:
    """Resolve one stage's prompt file by §3.4's four-level precedence (D14, E4.2).

    In order, highest first:

    1. the stage config's declared ``prompt:`` path (``explicit_path``), resolved against
       the target root when relative (``aidw/prompts/update-traceability.md`` is the
       §3.4 example) and used as-is when absolute;
    2. a same-named file in ``<target>/aidw/prompts/`` — filename shadowing (D14);
    3. the toolkit default ``<toolkit>/prompts/`` (D4);
    4. failure. It never returns ``None`` and never skips a required prompt silently:
       a declared-but-missing path does **not** fall through to levels 2–3.

    ``name`` is normalised the way the old two-argument resolver did: one trailing
    ``.md`` is accepted, so ``code-review`` and ``code-review.md`` name the same file.

    The resolver is deliberately a leaf — it imports no target-config or workflow module
    and performs nothing but ``Path`` existence checks. The caller unpacks the stage
    config and passes the declared ``prompt:`` value as a plain string, which is what
    keeps ``aidw.target_config`` free of a ``target_config -> runner -> workflows`` cycle
    (E4.1's trap).
    """
    filename = name if name.endswith(".md") else f"{name}.md"

    if explicit_path is not None:
        declared = Path(explicit_path)
        candidate = declared if declared.is_absolute() else target_root / declared
        if candidate.is_file():
            return declared if declared.is_absolute() else candidate.resolve()
        raise FileNotFoundError(
            f"prompt not found: the declared prompt path for '{name}' does not exist: "
            f"{candidate} (explicit_path is set, so the declared path is the only "
            "location searched; the target shadow and toolkit default are not "
            "fallbacks for a declared prompt, EXTRACTION.md §3.4)"
        )

    searched = (
        target_root / "aidw" / "prompts" / filename,
        toolkit_root / "prompts" / filename,
    )
    for candidate in searched:
        if candidate.is_file():
            return candidate.resolve()

    locations = "; ".join(str(candidate) for candidate in searched)
    raise FileNotFoundError(
        f"prompt not found: no prompt resolves for '{name}' (explicit_path is None, "
        f"so the target shadow and toolkit default were searched): {locations}"
    )


def _declared_prompt(entry: Mapping[str, Any]) -> str | None:
    """An entry's ``prompt:`` as a plain string, or ``None`` when it declared none."""
    prompt = entry.get("prompt")
    return prompt if isinstance(prompt, str) and prompt else None


def declared_stage_issues(
    workflow: str,
    stages: Sequence[Mapping[str, Any]],
    *,
    toolkit_root: Path,
    target_root: Path,
    agents: Mapping[str, Any],
) -> list[Issue]:
    """Fail-closed preflight checks on a declared stage list's per-entry settings (E4.5b).

    The two things the plan builder would otherwise discover too late, turned into config
    ``ERROR`` issues (the ``workflows.<workflow>.stages`` dotted path, the stage id and the
    rule) so every preflight prints them through ``format_issues`` with exit 2 before any
    run record or worktree:

    * **the prompt resolves** — every declared entry's prompt is resolved exactly as
      :func:`plan_stages` resolves it (a known id by its registry prompt-file name, a
      repo-added id by its declared id) with the entry's ``prompt:`` as D14 level 1. This
      is what keeps :func:`resolve_prompt`'s :class:`FileNotFoundError` out of ``run()``:
      deliberately *not* a ``try``/``except`` at a call site (the roadmap forbids local
      call-site catches), and not a wrapper around ``plan_stages`` either.
    * **a repo-added stage's ``agent`` exists** — the declared ``agent`` is the honoured
      ``StageSpec.agent_id`` (E4.5b req 4), so an id that is missing or absent from the
      loaded agent configs is refused here, never left to ``run_stage``'s
      ``ValueError: unknown agent``. A known stage's ``agent`` is a deferred E4.6 override
      and is deliberately not checked: the plan ignores it.

    Pure apart from the prompt existence checks: no mutation of ``stages`` or ``agents``,
    no run state, no workflow import. The caller passes the resolved list and the agents
    dict it already loaded — which is why this runs **after** ``load_all`` and not at the
    ``validate_stage_list`` site, where the agents dict does not exist yet.
    """
    definition = stage_registry.get_workflow(workflow)
    static = {item.id: item for item in definition.stages}
    source = f"workflows.{workflow}.stages"
    known_agents = ", ".join(sorted(agents)) or "(none configured)"
    issues: list[Issue] = []
    for entry in stages:
        if not isinstance(entry, Mapping):
            # The loader already refused this entry; `validate_stage_list` skips it too.
            continue
        stage_id = entry.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            continue
        declared = _declared_prompt(entry)
        definition_entry = static.get(stage_id)
        prompt_name = definition_entry.prompt_file if definition_entry else stage_id
        try:
            resolve_prompt(
                toolkit_root,
                target_root,
                name=prompt_name,
                explicit_path=declared,
            )
        except FileNotFoundError as exc:
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"stage `{stage_id}`: its prompt does not resolve: {exc}",
                )
            )
        if definition_entry is not None:
            continue
        agent = entry.get("agent")
        if not isinstance(agent, str) or not agent:
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"stage `{stage_id}`: a repo-added stage must declare `agent` "
                    "(EXTRACTION.md §3.5)",
                )
            )
        elif agent not in agents:
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"stage `{stage_id}`: unknown agent `{agent}`; known agents are: "
                    f"{known_agents}",
                )
            )
    return issues


# --------------------------------------------------------------------------- #
# The run-path plan builder (EXTRACTION.md §3.4/§3.5, D2/D14; tasks E4.3/E4.5b)
# --------------------------------------------------------------------------- #

#: Deferred §3.4 stage settings: declared on a stage entry, but ignored by this version's
#: *planning*. Since E4.5b ``enabled: false`` is **honoured** (a repo-optional stage is
#: omitted), and a repo-added stage is **planned** in ``review``/``approve``/``implement``,
#: so neither is a deferred reason any more. E4.6 owns the per-stage agent override, so a
#: known stage's declared ``agent`` still warns. A repo-added stage in ``prompt``/``fix``
#: keeps the E4.3 warning: those two consumers look their stages up by *name* and never run
#: a repo-added stage (E4.5b's non-goal), so it is warned about rather than silently
#: dropped.
_REASON_REPO_ADDED = "no such default stage, so a repo-added stage is deferred (E4.5)"
_REASON_AGENT = "`agent` override (E4.6)"

#: The workflows whose consumers resolve stages by *name* from the registry expansion
#: (``fix._planned_iteration``, ``prompt._prompt_plan``) rather than walking the plan, so a
#: repo-added entry cannot be run there: it is planned (the declaration is honoured on the
#: run path) but draws a warning, because those two consumers look their stages up by name
#: and never run it (E4.5b's non-goal — running it there is a consumer rewrite this task
#: does not own).
_NAME_KEYED_WORKFLOWS = frozenset({"prompt", "fix"})


def plan_stages(
    workflow: str,
    *,
    config: ResolvedConfig,
    toolkit_root: Path,
    target_root: Path,
    **expand_fields: Any,
) -> list[StageSpec]:
    """The stages ``workflow`` runs, as runnable specs, from registry plus config (E4.3).

    This is the **only** run-path plan builder for the five workflows. Every stage on
    every run path derives from the registry here — the dynamic loops included, which
    call it once per round/iteration with the state they have accumulated — so no stage
    list is hand-built anywhere (EXTRACTION.md §3.5, D2).

    ``expand_fields`` is exactly :func:`aidw.stage_registry.expand`'s documented
    per-workflow field set: ``implement`` (``prompt_rel``/``branch``/``task_id``/
    ``base_branch``), ``prompt`` (``phase``/``epic``/``task``/``rel``/``max_revisions``/
    ``rounds``), ``review`` (``pr``/``manifest_rel``/``findings``), ``fix`` (``pr``/
    ``round_index``/``iteration``/``manifest_rel``) and ``approve`` (``pr``). Each expanded
    :class:`~aidw.stage_registry.PlannedStage` becomes one :class:`StageSpec`: its prompt is
    resolved through :func:`resolve_prompt` (D4/D14), ``variables`` is a fresh ``list``
    (the registry's tuples are frozen) and ``extra`` is carried byte for byte.

    ``config`` is the :class:`~aidw.target_config.ResolvedConfig` the caller already
    resolved — the builder never loads it, which keeps this module free of the resolution
    preflight and stops ``aidw.target_config`` importing a workflow module (E4.1's trap).

    A **repo-declared** ``workflows.<workflow>.stages`` list (``source == config``) is a
    whole-list override (§3.4): it replaces the registry's *static* half wholesale, so the
    plan's static stages are the declared entries **in declared order**, each one either

    * a known static id — rendered exactly as :func:`aidw.stage_registry.expand` renders it
      (``name``/``variables``/``extra`` templated from ``expand_fields``, ``agent`` and
      ``prompt_file`` from the registry) with the entry's ``prompt:`` as the D14
      level-1 explicit path; the entry's ``agent`` stays deferred (E4.6);
    * a repo-optional id with ``enabled: false`` — omitted (E4.5a already refused this on a
      core id);
    * a repo-added id — the §3.5 repo-added stage: ``name`` = the declared id,
      ``agent_id`` = the declared ``agent``, its prompt resolved by §3.6 with
      ``name=`` the declared id (so ``<target>/aidw/prompts/<id>.md`` shadows) and the
      declared ``prompt:`` as level 1, ``variables == []``, ``extra == ""``.

    The registry's **loop** portion is appended unchanged. Static and loop stages are split
    **by stage id** — loop ids are ``stages_by_id(workflow)`` minus the static
    ``definition.stages`` ids (E4.5a's formula), never a ``len(definition.stages)`` slice:
    ``review``'s ``R2`` is ``when=findings``, so ``expand``'s static half is one or two
    stages and a count slice would misclassify a loop stage. A declared loop id never
    reaches the plan because :func:`validate_stage_list` refuses it.

    A declared list is validated here too: any ``ERROR`` from
    :func:`aidw.stage_registry.validate_stage_list` raises
    :class:`aidw.stage_registry.StageListError` carrying the validator's own
    ``format_issues`` text. The preflight is expected to have refused first; a direct
    caller (``tests/test_plan_stages.py``, ``aidw exec``) still never gets a silently
    shortened or reordered plan. A declared-but-missing ``prompt:`` raises
    :class:`FileNotFoundError` from :func:`resolve_prompt`; there is no shadow/toolkit
    fallback for a declared prompt. The workflow preflights turn that into a config
    ``ERROR`` through :func:`declared_stage_issues` before ``run()`` reaches this builder.

    Deferred settings are still reported for what this version cannot honour, one
    ``warning:`` line per declared entry naming the workflow, the stage id and every reason
    on that single line: a known stage's ``agent`` (E4.6), and a repo-added stage in a
    name-keyed workflow (:data:`_NAME_KEYED_WORKFLOWS` — it is planned here so the plan
    reflects the declaration, but ``prompt``/``fix`` resolve stages by name and never run
    it; E4.5b's non-goal). ``enabled: false`` and ``prompt:`` are no longer deferred
    reasons, and a repo-added stage in a consumer that walks the plan (review / approve /
    implement) draws no warning at all.

    Performs no I/O beyond the prompt existence checks in :func:`resolve_prompt` and
    mutates neither ``config`` nor the registry defaults.
    """
    planned = stage_registry.expand(workflow, **expand_fields)
    declared = _declared_stage_list(workflow, config)
    if declared is None:
        # No repo-declared list: the registry defaults plan unchanged, byte for byte.
        return [
            _spec_from_planned(stage, workflow, None, toolkit_root, target_root)
            for stage in planned
        ]

    errors = [
        issue
        for issue in stage_registry.validate_stage_list(workflow, declared)
        if issue.level == ERROR
    ]
    if errors:
        raise stage_registry.StageListError(format_issues(errors))

    _warn_deferred_settings(workflow, declared)

    definition = stage_registry.get_workflow(workflow)
    static_ids = [item.id for item in definition.stages]
    # The loop portion is the expansion's id set minus the static definitions (E4.5a's
    # formula), never a slice of the expansion by length.
    loop_ids = set(stage_registry.stages_by_id(workflow)) - set(static_ids)
    rendered_static = {
        stage.id: stage for stage in planned if stage.id in static_ids
    }
    loop_stages = [stage for stage in planned if stage.id in loop_ids]

    specs: list[StageSpec] = []
    for entry in declared:
        if not isinstance(entry, Mapping):
            # The loader already refused this entry; `validate_stage_list` skips it too.
            continue
        stage_id = entry.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            continue
        if stage_id in loop_ids:
            # Refused above: a declared loop id can never be planned.
            continue
        enabled = entry.get("enabled", True)
        rendered = rendered_static.get(stage_id)
        if rendered is not None:
            if enabled is False:
                # Repo-optional `enabled: false` is honoured by omission (a core id would
                # have been refused above).
                continue
            specs.append(
                _spec_from_planned(
                    rendered,
                    workflow,
                    _declared_prompt(entry),
                    toolkit_root,
                    target_root,
                )
            )
        elif stage_id in static_ids:
            # A static stage `expand` withheld for this call (`when=findings` with
            # `findings=False`): the plan stays exactly as short as the expansion is.
            continue
        elif enabled is False:
            # `enabled: false` on a repo-added stage is the same as omitting it.
            continue
        else:
            specs.append(
                _repo_added_spec(
                    workflow, stage_id, entry, toolkit_root, target_root
                )
            )

    specs.extend(
        _spec_from_planned(stage, workflow, None, toolkit_root, target_root)
        for stage in loop_stages
    )
    return specs


def _declared_stage_list(
    workflow: str, config: ResolvedConfig
) -> list[Any] | None:
    """The repo-declared ``workflows.<workflow>.stages`` list, or ``None`` when absent.

    Declared-ness — ``source == config`` — is the test, never truthiness: an explicit
    ``stages: []`` is a declared list (and is refused as "every core stage removed"),
    while an undeclared list is absent from the resolved config. ``ConfigDefaults``
    keeps ``workflows`` empty on purpose (E4.3 req 2), so a ``source == default`` list
    cannot exist today; refusing anything but ``config`` is what makes the plan path the
    single source of truth.
    """
    resolved = config.get(f"workflows.{workflow}.stages")
    if resolved is None or resolved.source != SOURCE_CONFIG:
        return None
    return list(resolved.value or [])


def _spec_from_planned(
    stage: stage_registry.PlannedStage,
    workflow: str,
    declared_prompt: str | None,
    toolkit_root: Path,
    target_root: Path,
) -> StageSpec:
    """One registry stage as a runnable spec (D4/D14), the E4.3 mapping.

    The prompt resolves by the stage's **prompt file name** (filename shadowing, D14 level
    2) unless the entry declared an explicit path (level 1); ``variables`` is a fresh
    ``list`` because the registry's tuples are frozen, and ``extra`` is carried byte for
    byte.
    """
    return StageSpec(
        stage.name,
        stage.agent,
        resolve_prompt(
            toolkit_root,
            target_root,
            name=stage.prompt_file,
            explicit_path=declared_prompt,
        ),
        list(stage.variables),
        workflow=workflow,
        extra=stage.extra,
        explicit_prompt=declared_prompt,
        id=stage.id,
    )


def _repo_added_spec(
    workflow: str,
    stage_id: str,
    entry: Mapping[str, Any],
    toolkit_root: Path,
    target_root: Path,
) -> StageSpec:
    """A §3.5 repo-added stage as a runnable spec (E4.5b req 4).

    ``id`` and ``name`` are both the declared id (a repo-added stage declares no runtime
    name), ``agent_id`` is the declared ``agent`` — the one per-stage setting this version
    *honours*, existence-checked in the preflight — and the prompt resolves with
    ``name=`` the declared id, so §3.6's shadow is ``<target>/aidw/prompts/<id>.md`` and a
    declared relative ``prompt:`` resolves against the **target** root. A repo-added stage
    declares no variables and no ``extra``; those are the registry's to render.
    """
    declared_prompt = _declared_prompt(entry)
    agent = entry.get("agent")
    return StageSpec(
        stage_id,
        agent if isinstance(agent, str) else "",
        resolve_prompt(
            toolkit_root,
            target_root,
            name=stage_id,
            explicit_path=declared_prompt,
        ),
        [],
        workflow=workflow,
        extra="",
        explicit_prompt=declared_prompt,
        id=stage_id,
    )


def _warn_deferred_settings(
    workflow: str, declared: list[Any]
) -> None:
    """One ``warning:`` line per declared entry this version cannot honour (E4.3/E4.5b).

    Counting is by entry, not by field, and only the two surviving deferrals are named:
    a known stage's ``agent`` override (E4.6) and a repo-added stage in a name-keyed
    workflow (:data:`_NAME_KEYED_WORKFLOWS`), which those consumers would otherwise drop
    silently. ``enabled: false`` is honoured by omission and ``prompt:`` is applied, so
    neither is a reason any more.
    """
    static_ids = {item.id for item in stage_registry.get_workflow(workflow).stages}
    for entry in declared:
        if not isinstance(entry, Mapping):
            continue
        stage_id = entry.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            continue
        reasons: list[str] = []
        if stage_id not in static_ids and workflow in _NAME_KEYED_WORKFLOWS:
            reasons.append(_REASON_REPO_ADDED)
        if stage_id in static_ids and entry.get("agent") is not None:
            reasons.append(_REASON_AGENT)
        if reasons:
            print(
                f"warning: workflow `{workflow}` stage `{stage_id}`: ignoring deferred "
                f"settings ({'; '.join(reasons)})",
                file=sys.stderr,
            )


def run_stage(
    spec: StageSpec,
    *,
    repo_root: Path,
    toolkit_root: Path,
    state: RunState,
    logger: RunLogger,
    agents: dict[str, AgentConfig] | None = None,
    dry_run: bool = False,
    retry_transient: bool | None = None,
    show_progress: bool | None = None,
    runs_root: Path,
) -> StageRecord:
    """Execute (or plan) one stage and persist its record in ``state``."""
    if retry_transient is None:
        retry_transient = DEFAULT_RETRY_TRANSIENT
    if show_progress is None:
        show_progress = DEFAULT_PROGRESS
    if agents is None:
        agents, issues = load_all(toolkit_root, repo_root)
        errors = [i for i in issues if i.level == "error"]
        if errors:
            raise ValueError(
                "agent config errors:\n" + "\n".join(str(i) for i in errors)
            )

    agent = agents.get(spec.agent_id)
    if agent is None:
        raise ValueError(f"unknown agent: {spec.agent_id}")

    if not spec.prompt.is_file():
        raise FileNotFoundError(f"prompt not found: {spec.prompt}")

    rendered = render_prompt_file(spec.prompt, spec.variables)
    if spec.extra:
        rendered = f"{rendered}\n\n{spec.extra}"
    directory = run_dir(runs_root, state.run_id)
    prompts_dir = directory / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    rendered_path = prompts_dir / f"{spec.name}.rendered.md"
    rendered_path.write_text(rendered, encoding="utf-8")

    sid = session_id(state.run_id, agent.id, spec.name, shared=agent.session == "shared")
    # ``run_stage`` is the only place the target root is in scope, so it — not
    # ``build_argv`` — composes Pi's complete template-root list (E4.2). The explicit
    # path is the resolver's precedence-1 *return value*, passed only when the stage
    # declared one: a filename-shadowed stage must not be turned into an explicit one.
    argv = build_argv(
        agent,
        session_id=sid,
        prompt_templates=prompt_template_dirs(
            agent,
            repo_root,
            spec.prompt if spec.explicit_prompt is not None else None,
        ),
    )
    env = build_env(agent, dict(os.environ))
    # Prompts invoke the bundled helper scripts with `python3`; the subprocess working
    # directory is the *target* repo, where `aidt/prompts/scripts/...` does not exist
    # once the toolkit lives in its own checkout. Expose the absolute toolkit path
    # instead (EXTRACTION.md §3.6). Set after the agent's `env:` overrides so the
    # toolkit location cannot be shadowed by config.
    env[SCRIPTS_DIR_ENV_VAR] = str((Path(toolkit_root) / "prompts" / "scripts").resolve())
    # Same rule for the run/stage identity a gate needs to record its outcome against
    # (E4.8): the agent runs `aidw gate run` from a subprocess, so the identity travels
    # in the environment it inherits, not in its prompt.
    env[RUN_ID_ENV_VAR] = state.run_id
    env[STAGE_ENV_VAR] = spec.name

    record = StageRecord(
        name=spec.name,
        agent=agent.id,
        model=agent.qualified_model,
        status=PLANNED,
        session_id=sid,
        started_at=utcnow_iso(),
        rendered_prompt=str(rendered_path.relative_to(directory)),
        artifacts={"prompt_source": str(spec.prompt)},
    )
    with _STATE_LOCK:
        state.record_stage(record)
        save(directory, state)

    logger.section(f"stage {spec.name} ({agent.id})")
    logger.info(f"model={agent.qualified_model} session={sid}")
    logger.info(f"prompt={spec.prompt} vars={spec.variables}")

    if dry_run:
        logger.info("dry-run: not invoking Pi")
        logger.info("argv: " + _redact_argv(argv))
        record.status = SUCCEEDED
        record.ended_at = utcnow_iso()
        with _STATE_LOCK:
            state.status = SUCCEEDED
            save(directory, state)
        return record

    with _STATE_LOCK:
        record.status = RUNNING
        save(directory, state)

    stages_dir = directory / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    progress = ProgressIndicator(enabled=resolve_enabled(show_progress))
    progress.start(f"{spec.name} ({agent.id}) model={agent.qualified_model}")
    try:
        result: PiResult = execute(
            argv,
            rendered,
            env=env,
            cwd=agent.cwd,
            timeout=float(agent.timeout_seconds),
            stage_dir=stages_dir,
            stage_name=spec.name,
            logger=logger,
            retry_transient=retry_transient,
            progress=progress,
        )
    finally:
        progress.finish()
    write_meta(
        stages_dir / f"{spec.name}.meta.json",
        result,
        argv,
        model=agent.qualified_model,
        stage=spec.name,
        agent=agent.id,
        prompt_source=str(spec.prompt),
        rendered_prompt=record.rendered_prompt,
    )

    record.ended_at = utcnow_iso()
    record.exit_code = result.exit_code
    record.duration_seconds = result.duration_seconds
    record.cost_usd = result.usage.cost_usd
    record.usage = asdict(result.usage)
    record.generation_seconds = result.generation_seconds
    record.tool_seconds = result.tool_seconds
    record.tool_breakdown = result.tool_breakdown or None
    record.output_tokens_per_second = result.output_tokens_per_second
    record.log = f"stages/{spec.name}.jsonl"
    record.artifacts["out"] = result.out_path
    # A zero cost for real token spend is a pricing gap, not a free run: surface it in
    # run.log so it is caught during the run rather than in a later audit (design §9.2).
    unpriced = cost_note(record.model, record.usage)
    over_budget = (
        agent.max_cost_usd is not None
        and result.usage.cost_usd > agent.max_cost_usd
    )
    # Pi exiting 0 only means the agent finished, not that it did the work: it can
    # report a problem in its final message and still exit 0. When the stage declares a
    # postcondition, re-read the external state and fail the stage if it does not hold
    # (design §10). A check that raises fails the stage rather than crashing the run.
    verification_error: str | None = None
    if not result.failed and not over_budget and spec.verify is not None:
        try:
            verification_error = spec.verify() or None
        except Exception as exc:  # noqa: BLE001 - any check failure fails the stage
            verification_error = f"check raised {type(exc).__name__}: {exc}"
        if verification_error:
            logger.warn(
                f"stage {spec.name}: postcondition not met: {verification_error}"
            )
    with _STATE_LOCK:
        if result.failed:
            record.status = FAILED
            if result.timed_out:
                record.error = "timeout"
            elif result.error_message:
                record.error = f"provider error: {result.error_message[:200]}"
            else:
                record.error = f"exit code {result.exit_code}"
            state.resume = {"next_stage": spec.name}
            state.status = FAILED
        elif over_budget:
            record.status = FAILED
            record.error = (
                f"cost_ceiling: ${result.usage.cost_usd:.4f} > "
                f"${agent.max_cost_usd:.4f}"
            )
            state.resume = {"next_stage": spec.name}
            state.status = FAILED
        elif verification_error:
            record.status = FAILED
            record.error = f"postcondition not met: {verification_error}"
            state.resume = {"next_stage": spec.name}
            state.status = FAILED
        else:
            record.status = SUCCEEDED
        save(directory, state)
    if unpriced:
        logger.warn(f"stage {spec.name}: {unpriced}")
    return record


def _redact_argv(argv: list[str]) -> str:
    """Render argv for logs without dumping inlined system-prompt contents."""
    redacted: list[str] = []
    skip_next = False
    for index, item in enumerate(argv):
        if skip_next:
            redacted.append(f"<{len(item)} chars>")
            skip_next = False
            continue
        redacted.append(item)
        if item in ("--system-prompt", "--append-system-prompt"):
            skip_next = True
    return " ".join(redacted)
