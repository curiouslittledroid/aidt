"""All GitHub access, via the ``gh`` CLI.

JSON is parsed in Python rather than with ``gh --jq`` or an external ``jq``
dependency. Note that ``gh api --slurp`` is incompatible with ``--jq``
(gh 2.97), so paginated endpoints are collected with ``--slurp`` and flattened
here.

Every command runs through :mod:`proc`, which uses an argument array and no
shell. Comment bodies are passed on stdin via ``--body-file -``, so markdown,
backticks, apostrophes, and ``$`` are never re-interpreted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from constants import parent_marker
from logic import ChildIssue
from proc import CommandError, probe, run

GH = "gh"


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

    Returns every match; the caller decides whether the ambiguity is fatal.
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
