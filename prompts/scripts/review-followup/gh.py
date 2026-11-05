"""All GitHub access, via the ``gh`` CLI.

JSON is parsed in Python rather than with ``gh --jq`` or an external ``jq``
dependency. Note that ``gh api --slurp`` is incompatible with ``--jq``
(gh 2.97), so paginated endpoints are collected with ``--slurp`` and flattened
here.

Every command runs through :mod:`proc`, which uses an argument array and no
shell. Comment bodies are passed on stdin via ``--body-file -``, so markdown,
backticks, apostrophes, and ``$`` are never re-interpreted.

This module also owns the **config handoff** (EXTRACTION.md §3.4/§3.9, D5; task E6.1).
AIDT resolves the target repo's ``github.markers``/``github.labels`` and passes them to
these standalone scripts in one environment variable, :data:`CONFIG_ENV_VAR`, as a JSON
object ``{"markers": {name: template}, "labels": {name: {color, description}}}`` carrying
fully-resolved values (toolkit defaults merged, provenance dropped). The scripts never
read ``aidw/config.yaml`` themselves — they have no YAML dependency and no idea where the
target root is.

The contract is *absent → fallback, present-but-broken → fail closed*:

- unset variable → the frozen :mod:`constants` values, byte-identical to the standalone
  behaviour before E6.1;
- present but unparseable, missing a marker/label field a script needs, or carrying a
  template that cannot render under the keyed ``str.format`` its accessor performs → the
  module refuses at import, with a clear message and exit code 2, **before** anything is
  published. Silently falling back would publish a wrong marker, and a marker rename
  orphans every existing parent/child (D5), so a wrong publish is worse than a stop.

Marker templates are validated at that same resolution step by rendering them with probe
values through the accessors' own keyed argument table (:data:`_MARKER_ARGS`), so a
template can never pass validation and then raise mid-publish: there is no half-published
issue and no mid-run crash.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field

from constants import (
    CHILD_MARKER_TEMPLATE,
    EXIT_ERROR,
    LABEL_DEFINITIONS as FROZEN_LABEL_DEFINITIONS,
    PARENT_MARKER_TEMPLATE,
    SUMMARY_MARKER_TEMPLATE,
)
from logic import ChildIssue
from proc import CommandError, probe, run

GH = "gh"

#: The environment variable aidw sets on every bundled-script invocation that carries the
#: resolved ``github.markers``/``github.labels`` (EXTRACTION.md §3.4/§3.9, D5; E6.1).
#: ``aidw.paths.REVIEW_FOLLOWUP_CONFIG_ENV_VAR`` is the same literal on the toolkit side;
#: the scripts are standalone and deliberately duplicate it rather than import aidw.
CONFIG_ENV_VAR = "AIDW_REVIEW_FOLLOWUP_CONFIG"

#: The keyword arguments each accessor passes to ``str.format`` (E6.1 req 5). One table for
#: both validation and rendering, so the two cannot drift: a template that renders at the
#: resolution step necessarily renders when its accessor is called.
_MARKER_ARGS: dict[str, tuple[str, ...]] = {
    "parent": ("pr_url",),
    "child": ("pr_url", "finding_id"),
    "summary": ("pr_url",),
}

#: Probe values for the resolution-step render check. Concrete (not ``{"pr_url": ""}``) so
#: a template that only fails for a non-empty URL still fails here, not at publish time.
_MARKER_PROBES: dict[str, str] = {
    "pr_url": "https://github.com/o/r/pull/1",
    "finding_id": "F1",
}

#: The label names a script actually reads: the six frozen role labels of
#: :data:`constants.LABEL_DEFINITIONS` (``PUBLISHER_LABELS`` plus ``approve-fix``). Derived
#: from that mapping — never a re-typed list — so a role rename cannot leave this behind.
#: A handoff that omits one is refused rather than silently publishing an undefined label;
#: *extra* labels are allowed, because a repo may add its own (the map is open, D5/§3.9).
_REQUIRED_LABELS: tuple[str, ...] = tuple(FROZEN_LABEL_DEFINITIONS)


def _render_marker(templates: dict[str, str], name: str, **values: str) -> str:
    """Render one marker template with exactly the arguments its accessor passes."""
    return templates[name].format(
        **{arg: values[arg] for arg in _MARKER_ARGS[name]}
    )


def parent_marker(pr_url: str) -> str:
    """Exact parent-issue body marker, from the resolved (or frozen) template."""
    return _render_marker(_MARKER_TEMPLATES, "parent", pr_url=pr_url)


def child_marker(pr_url: str, finding_id: str) -> str:
    """Exact child-issue body marker, one per review finding."""
    return _render_marker(
        _MARKER_TEMPLATES, "child", pr_url=pr_url, finding_id=finding_id
    )


def summary_marker(pr_url: str) -> str:
    """Exact marker on the single PR summary comment."""
    return _render_marker(_MARKER_TEMPLATES, "summary", pr_url=pr_url)


@dataclass
class PrInfo:
    number: int
    title: str
    url: str
    state: str
    headRefName: str  # noqa: N815 - mirrors the ``gh --json`` field names
    baseRefName: str  # noqa: N815


@dataclass
class ParentIssue:
    number: int
    title: str
    url: str
    state: str


@dataclass
class NativeChild:
    number: int
    title: str
    url: str
    state: str


@dataclass
class GhIssue:
    """An issue as read by ``gh issue view``, including the fields reconciliation needs."""

    number: int
    title: str
    url: str
    state: str
    body: str
    labels: list[str] = field(default_factory=list)
    parent: int | None = None
    sub_issue_numbers: list[int] = field(default_factory=list)


def gh_json(args: list[str]) -> object:
    """Parse a ``gh`` command's JSON output, failing loudly on non-JSON."""
    stdout = run(GH, args)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as error:
        raise CommandError(
            f"gh returned output that is not valid JSON for: gh {' '.join(args)}"
        ) from error


def paginate(endpoint: str) -> list:
    """Read a paginated REST endpoint as a single flat array.

    ``gh api --paginate --slurp`` returns one element per page, and each page is
    itself an array, so the result is flattened. A single-page response flattens
    to itself.
    """
    pages = gh_json(["api", "--paginate", "--slurp", endpoint])
    return _flatten(pages)


def _flatten(value: object) -> list:
    if not isinstance(value, list):
        return [value]
    flattened: list = []
    for item in value:
        flattened.extend(_flatten(item))
    return flattened


# ── Context ───────────────────────────────────────────────────────────────


def assert_gh_authenticated() -> None:
    result = probe(GH, ["auth", "status"])
    if not result.ok:
        detail = (result.stderr or result.stdout).strip()
        raise CommandError(
            f"GitHub CLI is not authenticated. Run `gh auth login`.\n{detail}"
        )


def resolve_repo(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    payload = gh_json(["repo", "view", "--json", "nameWithOwner"])
    return str(payload["nameWithOwner"])  # type: ignore[index]


def resolve_pr(ref: str | None = None) -> PrInfo:
    """Resolve a PR number/URL, or the PR for the current branch when omitted."""
    args = ["pr", "view"]
    if ref:
        args.append(ref)
    args += ["--json", "number,title,url,state,headRefName,baseRefName"]
    payload = gh_json(args)
    assert isinstance(payload, dict)
    return PrInfo(
        number=int(payload["number"]),
        title=str(payload["title"]),
        url=str(payload["url"]),
        state=str(payload["state"]),
        headRefName=str(payload["headRefName"]),
        baseRefName=str(payload["baseRefName"]),
    )


def list_issues(repo: str) -> list[dict]:
    return paginate(f"repos/{repo}/issues?state=all&per_page=100")


def list_comments(repo: str, issue_number: int) -> list[dict]:
    return paginate(f"repos/{repo}/issues/{issue_number}/comments?per_page=100")


# ── Parent lookup ─────────────────────────────────────────────────────────


def find_parent_issues(repo: str, pr_url: str) -> list[ParentIssue]:
    """Find parent issues whose body carries the exact ``pr=<canonical PR URL>`` marker.

    The marker is the *effective* one (:func:`parent_marker`), so a configured template and
    the publish path agree. Returns every match; the caller decides whether the ambiguity
    is fatal.
    """
    marker = parent_marker(pr_url)
    parents: list[ParentIssue] = []
    for issue in list_issues(repo):
        if issue.get("pull_request"):
            continue
        if marker not in str(issue.get("body") or ""):
            continue
        parents.append(
            ParentIssue(
                number=int(issue["number"]),
                title=str(issue["title"]),
                # html_url is the browser URL; `url` is the api.github.com URL.
                url=str(issue["html_url"]),
                state=str(issue["state"]).upper(),
            )
        )
    return parents


# ── Children ──────────────────────────────────────────────────────────────


def list_native_children(repo: str, parent_number: int) -> list[NativeChild]:
    """Native sub-issue order. Never inferred from titles, labels, or comments."""
    payload = gh_json(
        ["issue", "view", str(parent_number), "--repo", repo, "--json", "subIssues"]
    )
    assert isinstance(payload, dict)
    sub_issues = payload.get("subIssues") or {}
    nodes = sub_issues.get("nodes") or []
    total_count = sub_issues.get("totalCount", len(nodes))
    if total_count > len(nodes):
        raise CommandError(
            f"Parent #{parent_number} reports {total_count} sub-issues but only "
            f"{len(nodes)} were returned. Refusing to select from a truncated list."
        )
    return [
        NativeChild(
            number=int(node["number"]),
            title=str(node["title"]),
            url=str(node["url"]),
            state=str(node["state"]).upper(),
        )
        for node in nodes
    ]


def get_issue(repo: str, issue_number: int) -> ChildIssue:
    """Read one issue with the labels and comment bodies needed to decide availability.

    This is a single ``gh`` call per child.
    """
    payload = gh_json(
        [
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo,
            "--json",
            "number,title,state,url,labels,comments",
        ]
    )
    assert isinstance(payload, dict)
    return ChildIssue(
        number=int(payload["number"]),
        title=str(payload["title"]),
        url=str(payload["url"]),
        state=str(payload["state"]).upper(),
        labels=[str(label["name"]) for label in (payload.get("labels") or [])],
        comment_bodies=[
            str(comment.get("body") or "") for comment in (payload.get("comments") or [])
        ],
    )


def issue_view(repo: str, number: int) -> GhIssue:
    """Read a full issue, including body and parent/sub-issue relationships."""
    payload = gh_json(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,title,url,state,body,labels,parent,subIssues",
        ]
    )
    assert isinstance(payload, dict)
    parent = payload.get("parent")
    sub_issues = payload.get("subIssues") or {}
    return GhIssue(
        number=int(payload["number"]),
        title=str(payload["title"]),
        url=str(payload["url"]),
        state=str(payload["state"]).upper(),
        body=str(payload.get("body") or ""),
        labels=[str(label["name"]) for label in (payload.get("labels") or [])],
        parent=int(parent["number"]) if parent else None,
        sub_issue_numbers=[int(node["number"]) for node in (sub_issues.get("nodes") or [])],
    )


# ── Writes ────────────────────────────────────────────────────────────────


def add_comment(repo: str, issue_number: int, body: str) -> None:
    """Post a comment.

    The body is passed on stdin via ``--body-file -``, so no shell quoting
    applies to markdown, backticks, or apostrophes.
    """
    run(GH, ["issue", "comment", str(issue_number), "--repo", repo, "--body-file", "-"], body)


def close_issue(repo: str, issue_number: int, body: str) -> None:
    """Close an issue with a closing comment.

    ``gh issue close`` supports only ``--comment`` (there is no ``--body-file``),
    so the body is passed as a single argv element — still shell-free, because
    this module never goes through a shell.
    """
    run(GH, ["issue", "close", str(issue_number), "--repo", repo, "--comment", body])


def create_issue(
    repo: str,
    *,
    title: str,
    body: str,
    labels: list[str],
    parent_number: int | None = None,
) -> GhIssue:
    """Create an issue and return it.

    The body is passed on stdin. The browser issue URL printed by ``gh`` is
    parsed to discover the new number, and the issue is re-read so the caller
    validates GitHub's actual state.
    """
    args = ["issue", "create", "--repo", repo, "--title", title, "--body-file", "-"]
    if parent_number is not None:
        args += ["--parent", str(parent_number)]
    for label in labels:
        args += ["--label", label]

    output = run(GH, args, body)
    number = issue_number_from_browser_url(output, repo)
    return issue_view(repo, number)


def edit_issue(
    repo: str,
    number: int,
    *,
    title: str | None = None,
    body: str | None = None,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> None:
    """Edit an issue's title, body, and labels. The body is passed on stdin."""
    args = ["issue", "edit", str(number), "--repo", repo]
    if title is not None:
        args += ["--title", title]
    for label in add_labels or []:
        args += ["--add-label", label]
    for label in remove_labels or []:
        args += ["--remove-label", label]

    if body is not None:
        args += ["--body-file", "-"]
        run(GH, args, body)
        return
    run(GH, args)


def label_list(repo: str) -> list[dict]:
    payload = gh_json(
        [
            "label",
            "list",
            "--repo",
            repo,
            "--limit",
            "1000",
            "--json",
            "name,color,description",
        ]
    )
    return payload if isinstance(payload, list) else []


def create_label(repo: str, name: str, color: str, description: str) -> None:
    run(GH, ["label", "create", name, "--repo", repo, "--color", color, "--description", description])


def create_pr_comment(repo: str, pr_number: int, body: str) -> None:
    """Create a comment on a pull request."""
    run(GH, ["pr", "comment", str(pr_number), "--repo", repo, "--body-file", "-"], body)


def update_issue_comment(repo: str, comment_id: int, body: str) -> None:
    """Replace the body of an existing issue/PR comment."""
    run(
        GH,
        [
            "api",
            f"repos/{repo}/issues/comments/{comment_id}",
            "--method",
            "PATCH",
            "-f",
            f"body={body}",
        ],
    )


def issue_number_from_browser_url(output: str, repo: str) -> int:
    """Parse the browser issue URL printed by ``gh issue create`` into a number."""
    escaped_repo = re.escape(repo)
    match = re.search(rf"https://github\.com/{escaped_repo}/issues/(\d+)", output)
    if not match:
        raise CommandError(
            f"Could not parse a browser issue URL from gh output: {output.strip()}"
        )
    return int(match.group(1))


def issue_url(repo: str, number: int) -> str:
    return f"https://github.com/{repo}/issues/{number}"


def labels_of(issue: GhIssue) -> set[str]:
    return set(issue.labels)


# ── Config handoff (E6.1) ─────────────────────────────────────────────────


class ConfigError(Exception):
    """A malformed ``AIDW_REVIEW_FOLLOWUP_CONFIG`` handoff.

    Never swallowed: :func:`_load_config` turns it into a clear message and exit code 2 at
    import time, because silently falling back to the frozen literals would publish a
    different marker than the one aidw resolved (D5).
    """


def _config_error(detail: str) -> ConfigError:
    return ConfigError(
        f"{CONFIG_ENV_VAR} is set but unusable: {detail}. Unset it to use the bundled "
        f"frozen markers/labels, or pass a JSON object "
        f'{{"markers": {{parent, child, summary}}, "labels": {{name: '
        f'{{color, description}}}}}}.'
    )


def _marker_templates(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise _config_error("`markers` must be a JSON object")
    templates: dict[str, str] = {}
    for name in _MARKER_ARGS:
        if name not in raw:
            raise _config_error(f"`markers.{name}` is missing")
        value = raw[name]
        if not isinstance(value, str):
            raise _config_error(f"`markers.{name}` must be a string")
        templates[name] = value
    return templates


def _label_definitions(raw: object) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        raise _config_error("`labels` must be a JSON object")
    labels: dict[str, dict[str, str]] = {}
    for name, entry in raw.items():
        if not isinstance(name, str) or not name:
            raise _config_error("`labels` keys must be non-empty strings")
        if not isinstance(entry, dict):
            raise _config_error(f"`labels.{name}` must be a JSON object")
        values: dict[str, str] = {}
        for key in ("color", "description"):
            value = entry.get(key)
            if not isinstance(value, str):
                raise _config_error(f"`labels.{name}.{key}` must be a string")
            values[key] = value
        labels[name] = values
    missing = [name for name in _REQUIRED_LABELS if name not in labels]
    if missing:
        raise _config_error(f"`labels` is missing {', '.join(missing)}")
    return labels


def _validate_templates(templates: dict[str, str]) -> None:
    """Prove every template renders under the keyed ``.format`` its accessor performs.

    A stray ``{`` raises ``ValueError``, an unknown placeholder ``KeyError``, and a
    positional placeholder ``IndexError``. All three are caught here, at the one
    resolution step, so the failure is a clear stop **before** any marker renders rather
    than a traceback after some issues have already been written (E6.1 req 3/req 5).
    """
    for name, args in _MARKER_ARGS.items():
        try:
            templates[name].format(**{arg: _MARKER_PROBES[arg] for arg in args})
        except (AttributeError, KeyError, ValueError, IndexError) as error:
            raise _config_error(
                f"`markers.{name}` template {templates[name]!r} does not render with "
                f"{', '.join('{' + arg + '}' for arg in args)} ({error})"
            ) from error


def parse_config_json(text: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Parse one handoff payload into the effective marker templates and label definitions.

    Pure (no environment, no I/O) so the contract is unit-testable. Raises
    :class:`ConfigError` for anything malformed — including a syntactically valid payload
    whose marker template cannot render. Both returned containers are fresh, so a caller
    can keep them for the process lifetime without aliasing the frozen ``constants``.
    """
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as error:
        raise _config_error(f"not valid JSON ({error})") from error
    if not isinstance(payload, dict):
        raise _config_error("the payload must be a JSON object")
    # Unknown top-level keys are *tolerated*, not refused: only ``markers`` and ``labels``
    # are read, the fields the scripts need are validated below, and a copied copy of these
    # standalone scripts outliving one aidw release must not refuse a newer payload over a
    # key it does not use. A typo'd key still fails closed — as a *missing* required field.
    # Markers first, then their render check, then labels: the first defect reported is the
    # one that would otherwise break a publish (a template that cannot render), and a
    # template problem is never masked by a label problem in the same payload.
    templates = _marker_templates(payload.get("markers"))
    _validate_templates(templates)
    labels = _label_definitions(payload.get("labels"))
    return templates, labels


def _frozen_config() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """The standalone defaults: the frozen ``constants`` literals, freshly copied."""
    return (
        {
            "parent": PARENT_MARKER_TEMPLATE,
            "child": CHILD_MARKER_TEMPLATE,
            "summary": SUMMARY_MARKER_TEMPLATE,
        },
        {
            name: dict(definition)
            for name, definition in FROZEN_LABEL_DEFINITIONS.items()
        },
    )


def _load_config() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Resolve the effective markers/labels once, at import.

    Absent variable → the frozen fallback (the standalone case). Present → the handoff,
    validated; anything wrong exits 2 with one ``error:`` line and writes nothing.

    An *empty* value counts as present-but-broken rather than absent: aidw's serializer
    never emits one, so an empty value means a shell or wrapper mangled the handoff, and a
    silent fallback there is exactly the wrong-marker publish D5 forbids.
    """
    raw = os.environ.get(CONFIG_ENV_VAR)
    if raw is None:
        return _frozen_config()
    try:
        return parse_config_json(raw)
    except ConfigError as error:
        sys.stderr.write(f"error: {error}\n")
        raise SystemExit(EXIT_ERROR) from error


#: The three marker templates in force for this process, keyed ``parent``/``child``/
#: ``summary``; :func:`parent_marker` and friends render these.
_MARKER_TEMPLATES, LABEL_DEFINITIONS = _load_config()
