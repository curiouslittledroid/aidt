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
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable

from aidw import stage_registry
from aidw.agents import build_argv, build_env, prompt_template_dirs
from aidw.config import ERROR, AgentConfig, Issue, format_issues, load_all
from aidw.log import RunLogger
from aidw.pi import PiResult, execute, write_meta
# ``runner -> github`` adds no cycle: ``aidw.github`` imports stdlib plus ``aidw.paths``
# only, and ``ResolvedConfig`` is already imported below (E6.1).
from aidw.github import serialize_github_config
from aidw.paths import (
    REVIEW_FOLLOWUP_CONFIG_ENV_VAR,
    RUN_ID_ENV_VAR,
    SCRIPTS_DIR_ENV_VAR,
    STAGE_ENV_VAR,
)
from aidw.progress import ProgressIndicator, resolve_enabled
from aidw.prompts import inject_repo_conventions, render_prompt_file
from aidw.report import cost_note
from aidw.target_config import SOURCE_CONFIG, ResolvedConfig
from aidw.state import (
    FAILED,
    PLANNED,
    RUNNING,
    SKIP_REASON_KEY,
    SKIPPED,
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
    #: E4.6's per-stage metadata overrides (D12: "agent/model/timeout/thinking"), all
    #: ``None`` when the stage declared none. :func:`run_stage` applies them to the
    #: resolved :class:`~aidw.config.AgentConfig` **once**, before every consumer (argv,
    #: timeout, run state, cost), so they cannot disagree about the effective model.
    #: ``model`` keeps ``provider/model`` semantics (design §5.1): it replaces only
    #: ``model`` — ``provider`` is not a stage field — so a provider change goes through
    #: ``agent:`` or the global ``paths.agent_configs_dir`` override, never a per-stage
    #: ``model``.
    model: str | None = None
    thinking: str | None = None
    timeout_seconds: int | None = None
    #: The registry's ``if`` condition, carried rather than expanded away (H3.2):
    #: :func:`aidw.stage_registry.expand` plans a conditional stage and puts its
    #: ``when`` here, so a **workflow** can read it and decide at run time
    #: (``spec.when == stage_registry.WHEN_EVIDENCE_GREEN`` — I7's tick, and H3.3's
    #: reuse for ``fix``). Empty for a stage with no condition, which is every stage
    #: today except I7. Additive: the field defaults empty, so a spec a workflow builds
    #: itself (``aidw exec``) keeps today's unconditional behaviour.
    when: str = ""


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
    * **a declared ``agent`` exists** — the declared ``agent`` is the honoured
      ``StageSpec.agent_id``, for a repo-added stage (E4.5b req 4) and since E4.6 for a
      known stage too, so an id that is missing or absent from the loaded agent configs is
      refused here, never left to ``run_stage``'s ``ValueError: unknown agent`` traceback.

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
        agent = entry.get("agent")
        if definition_entry is not None:
            # E4.6 honours a known stage's declared `agent` (it becomes the spec's
            # agent_id), so it has to resolve for the same reason a repo-added one does.
            # A declaration that is absent or non-string is not an override at all; the
            # loader already refused a non-string.
            if isinstance(agent, str) and agent and agent not in agents:
                issues.append(
                    Issue(
                        ERROR,
                        source,
                        f"stage `{stage_id}`: unknown agent `{agent}`; known agents "
                        f"are: {known_agents}",
                    )
                )
            continue
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
#: omitted), a repo-added stage is **planned** in ``review``/``approve``/``implement``, and
#: since E4.6 a known stage's ``agent``/``model``/``thinking``/``timeout_seconds`` are all
#: honoured, so none of those is a deferred reason any more. Only a repo-added stage in
#: ``prompt``/``fix`` keeps the E4.3 warning: those two consumers look their stages up by
#: *name* and never run a repo-added stage (E4.5b's non-goal), so it is warned about rather
#: than silently dropped.
_REASON_REPO_ADDED = "no such default stage, so a repo-added stage is deferred (E4.5)"

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
    ``rounds``), ``review`` (``pr``/``manifest_path``/``findings``), ``fix`` (``pr``/
    ``round_index``/``iteration``/``manifest_path``) and ``approve`` (``pr``). Each expanded
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
      (``name``/``variables``/``extra`` templated from ``expand_fields`` and
      ``prompt_file`` from the registry) with the entry's ``prompt:`` as the D14
      level-1 explicit path; since E4.6 the entry's ``agent`` replaces the registry's
      agent and its ``model``/``thinking``/``timeout_seconds`` ride on the spec. A stage
      the entry does not mention keeps the registry's agent and no overrides.
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
    ``warning:`` line per declared entry naming the workflow and the stage id: a repo-added
    stage in a name-keyed workflow (:data:`_NAME_KEYED_WORKFLOWS` — it is planned here so
    the plan reflects the declaration, but ``prompt``/``fix`` resolve stages by name and
    never run it; E4.5b's non-goal). ``enabled: false``, ``prompt:`` and (E4.6) a known
    stage's ``agent``/``model``/``thinking``/``timeout_seconds`` are no longer deferred, and
    a repo-added stage in a consumer that walks the plan (review / approve / implement)
    draws no warning at all.

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
                    entry,
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


def _stage_metadata_overrides(
    entry: Mapping[str, Any] | None,
) -> tuple[str | None, str | None, int | None]:
    """A declared entry's ``model``/``thinking``/``timeout_seconds`` (E4.6), or ``None``s.

    Type-guarded rather than trusted: the loader validates these on the config path, but
    ``plan_stages`` is also called directly (``aidw exec``, tests) with plain dicts, and a
    wrong-typed value must degrade to "no override" instead of reaching a Pi argv.
    ``bool`` is rejected for the int field for the same reason the loader rejects it.
    """
    if entry is None:
        return None, None, None
    model = entry.get("model")
    thinking = entry.get("thinking")
    timeout_seconds = entry.get("timeout_seconds")
    return (
        model if isinstance(model, str) and model else None,
        thinking if isinstance(thinking, str) and thinking else None,
        timeout_seconds
        if isinstance(timeout_seconds, int) and not isinstance(timeout_seconds, bool)
        else None,
    )


def _spec_from_planned(
    stage: stage_registry.PlannedStage,
    workflow: str,
    entry: Mapping[str, Any] | None,
    toolkit_root: Path,
    target_root: Path,
) -> StageSpec:
    """One registry stage as a runnable spec (D4/D14), the E4.3/E4.6 mapping.

    The prompt resolves by the stage's **prompt file name** (filename shadowing, D14 level
    2) unless the entry declared an explicit path (level 1); ``variables`` is a fresh
    ``list`` because the registry's tuples are frozen, and ``extra`` is carried byte for
    byte.

    ``entry`` is the declared stage entry, or ``None`` for a registry stage no declared
    list mentions. Since E4.6 its ``agent`` is the honoured base agent (an override), and
    its ``model``/``thinking``/``timeout_seconds`` ride on the spec for :func:`run_stage`
    to apply. A stage with no entry keeps the registry's agent and no metadata overrides.
    """
    declared_prompt = _declared_prompt(entry) if entry is not None else None
    agent = entry.get("agent") if entry is not None else None
    model, thinking, timeout_seconds = _stage_metadata_overrides(entry)
    return StageSpec(
        stage.name,
        agent if isinstance(agent, str) and agent else stage.agent,
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
        model=model,
        thinking=thinking,
        timeout_seconds=timeout_seconds,
        when=stage.when,
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
    model, thinking, timeout_seconds = _stage_metadata_overrides(entry)
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
        model=model,
        thinking=thinking,
        timeout_seconds=timeout_seconds,
    )


def _warn_deferred_settings(
    workflow: str, declared: list[Any]
) -> None:
    """One ``warning:`` line per declared entry this version cannot honour (E4.3/E4.5b).

    Counting is by entry, not by field, and only the one surviving deferral is named: a
    repo-added stage in a name-keyed workflow (:data:`_NAME_KEYED_WORKFLOWS`), which those
    consumers would otherwise drop silently. ``enabled: false`` is honoured by omission,
    ``prompt:`` is applied, and since E4.6 a known stage's ``agent``/``model``/
    ``thinking``/``timeout_seconds`` all take effect, so none of those is a reason any
    more.
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
    config: ResolvedConfig | None = None,
) -> StageRecord:
    """Execute (or plan) one stage and persist its record in ``state``.

    E4.6: the spec's ``model``/``thinking``/``timeout_seconds`` are applied to the resolved
    agent config once (:func:`_effective_agent`), so the rendered argv, Pi's timeout, run
    state, stage metadata and the cost note all describe the same invocation. The loaded
    config and every other stage's are left untouched.

    E6.1: ``config`` is the workflow's already-resolved target config. When set, the stage
    environment carries the resolved ``github.markers``/``github.labels`` as
    :data:`aidw.paths.REVIEW_FOLLOWUP_CONFIG_ENV_VAR`, so a script the *agent* invokes (the
    review publisher under R2, or a fix-round ``review_followup.py``) publishes and searches
    for the same markers and labels aidw resolved. ``None`` leaves the variable unset — the
    scripts' frozen fallbacks, byte-identical to the toolkit defaults — which is what keeps
    callers that pass nothing working. The config is never re-loaded or re-resolved here.
    """
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

    # E4.6: the stage's declared metadata applies for this invocation only. Build the
    # effective config **once, here**, before any consumer reads ``agent.model`` —
    # ``build_argv``, ``execute(timeout=…)``, ``StageRecord(model=…)``, ``write_meta``,
    # ``logger.info`` and ``progress.start`` all read it — so argv, run state and the
    # recorded cost (§9) can never disagree about which model ran. ``dataclasses.replace``
    # is what keeps the loaded config (and every other stage's) unchanged.
    # :func:`stage_agent` is the one resolution rule, shared with
    # :func:`record_skipped` so a withheld stage records the agent it would have run.
    agent = stage_agent(spec, agents)

    if not spec.prompt.is_file():
        raise FileNotFoundError(f"prompt not found: {spec.prompt}")

    rendered = render_prompt_file(spec.prompt, spec.variables)
    if spec.extra:
        rendered = f"{rendered}\n\n{spec.extra}"
    # E7.3/D16: the *target* repo's conventions (root ``AGENTS.md`` then optional
    # ``aidw/conventions.md``) reach exactly the four EXTRACTION.md §3.8 prompts, keyed by
    # the resolved prompt basename rather than the stage id (``test.md`` runs as both
    # ``test`` and ``iter{n}-test``). Applied last — after ``spec.extra`` — so the agent
    # reads prompt body → stage extra → repo conventions, and both the written
    # ``.rendered.md`` below and the stdin payload to Pi carry the same text. A repo with
    # no conventions and a prompt outside the four both return the text unchanged, so this
    # never adds noise or fails a stage. ``repo_root`` is the target root: reading
    # ``toolkit_root()`` would pass every self-hosted test and break only after extraction.
    rendered = inject_repo_conventions(rendered, spec.prompt, repo_root)
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
    # directory is the *target* repo, where `prompts/scripts/...` does not exist
    # once the toolkit lives in its own checkout. Expose the absolute toolkit path
    # instead (EXTRACTION.md §3.6). Set after the agent's `env:` overrides so the
    # toolkit location cannot be shadowed by config.
    env[SCRIPTS_DIR_ENV_VAR] = str((Path(toolkit_root) / "prompts" / "scripts").resolve())
    # Same rule for the run/stage identity a gate needs to record its outcome against
    # (E4.8): the agent runs `aidw gate run` from a subprocess, so the identity travels
    # in the environment it inherits, not in its prompt.
    env[RUN_ID_ENV_VAR] = state.run_id
    env[STAGE_ENV_VAR] = spec.name
    # The resolved GitHub contracts travel to the scripts the stage invokes (E6.1). Set
    # after the agent's `env:` overrides for the same reason as `AIDW_SCRIPTS_DIR`: the one
    # resolved value cannot be shadowed per agent. `None` means "not configured" — the
    # variable is then *absent*, never partially populated, so the scripts take their
    # frozen fallback instead of failing closed on an empty handoff.
    if config is None:
        env.pop(REVIEW_FOLLOWUP_CONFIG_ENV_VAR, None)
    else:
        env[REVIEW_FOLLOWUP_CONFIG_ENV_VAR] = serialize_github_config(config)

    # H2.1 req 5: record the rendered prompt's size — ``len(rendered)``, the very string
    # written to ``prompts/<stage>.rendered.md`` above — for the review loop's head stages
    # only, and only on the real-run path. Scoped on purpose: ``run_stage`` renders and
    # records *every* stage and also serves ``--dry-run``, so unscoped recording would put
    # ``rendered_chars`` and its ``run.log`` line on author/fix stages and on the dry-run
    # plan that E4.3's baseline keeps byte-identical. The field stays at its ``None``
    # default everywhere else (an additive record serialises ``rendered_chars: null``).
    rendered_chars = (
        len(rendered)
        if not dry_run and stage_registry.is_review_stage(spec.name)
        else None
    )
    record = StageRecord(
        name=spec.name,
        agent=agent.id,
        model=agent.qualified_model,
        status=PLANNED,
        session_id=sid,
        started_at=utcnow_iso(),
        rendered_prompt=str(rendered_path.relative_to(directory)),
        rendered_chars=rendered_chars,
        artifacts={"prompt_source": str(spec.prompt)},
    )
    with _STATE_LOCK:
        state.record_stage(record)
        save(directory, state)

    logger.section(f"stage {spec.name} ({agent.id})")
    logger.info(f"model={agent.qualified_model} session={sid}")
    logger.info(f"prompt={spec.prompt} vars={spec.variables}")
    if rendered_chars is not None:
        # One line, naming the stage and the size, so the operator can see a review
        # round's prompt grow (or shrink) beside the stage's token usage (H2.1 req 5).
        logger.info(f"stage {spec.name}: rendered prompt {rendered_chars} chars")

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
    # H1.1: the final attempt's reason and the attempt count, so a workflow that fails a
    # stage for an empty final message can name them. The result's ``usage`` and timing
    # are already summed over the attempts that ran (``aidw.pi.execute``), so the cost
    # ceiling check below covers both attempts without a second check.
    record.stop_reason = result.stop_reason
    record.attempts = result.attempts
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


def stage_agent(spec: StageSpec, agents: Mapping[str, AgentConfig]) -> AgentConfig:
    """The agent config one stage runs, or :class:`ValueError` for an unknown id.

    The single resolution rule behind both ``run_stage``'s invocation and
    :func:`record_skipped`'s record (H3.2 req 4): a stage withheld before Pi is invoked
    must still name the agent and ``qualified_model`` it *would* have run, so the skip is
    readable beside the stages that did run and cannot drift from them.
    """
    agent = agents.get(spec.agent_id)
    if agent is None:
        raise ValueError(f"unknown agent: {spec.agent_id}")
    return _effective_agent(agent, spec)


def record_skipped(
    spec: StageSpec,
    *,
    state: RunState,
    directory: Path,
    agents: Mapping[str, AgentConfig],
    reason: str,
) -> StageRecord:
    """Record a stage the workflow withheld before Pi was ever invoked (H3.2 req 4).

    A skip is a *decision with a reason*, not a silent omission, so it gets a full
    :class:`~aidw.state.StageRecord` published exactly the way ``run_stage`` publishes
    its own — under :data:`_STATE_LOCK`, through ``state.record_stage`` and ``save`` — so
    the observable evidence cannot depend on which dispatch path reached it.

    ``status`` is :data:`aidw.state.SKIPPED` and ``error`` stays **unset**: ``error``
    renders as a failure (design §9.3) and a skip is not one. The reason travels in
    ``artifacts[SKIP_REASON_KEY]``, which the stage block prints and ``runs show``/a
    reader of ``state.json`` can cite without a transcript. ``model`` is
    :func:`stage_agent`'s ``qualified_model`` — the same agent resolution
    ``run_stage`` applies — because ``StageRecord.model`` is a required field with no
    default.

    Nothing else is touched: no ``state.status`` stamp and no ``state.resume`` entry,
    since the caller's workflow continues (a skip never fails a run; the red gate that
    caused it already decided the run's outcome).
    """
    agent = stage_agent(spec, agents)
    record = StageRecord(
        name=spec.name,
        agent=agent.id,
        model=agent.qualified_model,
        status=SKIPPED,
        artifacts={SKIP_REASON_KEY: reason},
    )
    with _STATE_LOCK:
        state.record_stage(record)
        save(directory, state)
    return record


def _effective_agent(agent: AgentConfig, spec: StageSpec) -> AgentConfig:
    """The agent config this stage actually runs: ``agent`` with E4.6's overrides applied.

    ``model`` replaces only ``model``, never ``provider``: D12's override surface is
    agent/model/timeout/thinking and the §3.4 stage entry has no ``provider`` key, so a
    per-stage ``model`` is a model-only override riding the base agent's provider. The
    ``provider/model`` split that follows is design §5.1's and already lives in
    :meth:`~aidw.config.AgentConfig.qualified_model` and
    :func:`aidw.agents.model_name`: a value carrying the agent's **own** ``provider/``
    prefix is qualified as-is (and stripped once for ``--model``), while any other
    spelling — a bare slug, or a vendor-namespace slug such as ``meta/muse-spark-1.3``
    under ``openrouter`` — is passed whole to ``--model`` and qualified as
    ``<provider>/<value>``. That is why the override is applied to ``model`` and never
    split here.

    ``thinking`` and ``timeout_seconds`` are design §5.1's fields verbatim. Pure: the
    input config is not mutated (``replace`` copies), and a spec with no overrides returns
    the very same object so nothing downstream changes for an un-overridden stage.
    """
    changes: dict[str, Any] = {}
    if spec.model is not None:
        changes["model"] = spec.model
    if spec.thinking is not None:
        changes["thinking"] = spec.thinking
    if spec.timeout_seconds is not None:
        changes["timeout_seconds"] = spec.timeout_seconds
    return replace(agent, **changes) if changes else agent


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
