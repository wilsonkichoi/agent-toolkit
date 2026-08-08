#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Validate and mutate planned GitHub task lifecycle labels."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Sequence
from urllib.parse import urlsplit

from work_summary import WorkSummaryError, parse_work_summary


LIFECYCLE_STATUSES = (
    "status:backlog",
    "status:todo",
    "status:in-progress",
    "status:in-review",
    "status:blocked",
)
REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


class LifecycleError(RuntimeError):
    """A lifecycle precondition, mutation, or verification failed."""


@dataclass(frozen=True)
class IssueSnapshot:
    state: str
    labels: tuple[str, ...]
    assignees: tuple[str, ...]

    @property
    def lifecycle_labels(self) -> tuple[str, ...]:
        return tuple(label for label in self.labels if label.startswith("status:"))


@dataclass(frozen=True)
class IssueComment:
    body: str
    author: str


@dataclass(frozen=True)
class PullRequestSnapshot:
    url: str
    author: str
    branch: str
    head_oid: str


def fail(message: str) -> NoReturn:
    raise LifecycleError(message)


def run_gh(arguments: Sequence[str]) -> str:
    command = ["gh", *arguments]
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        fail(f"cannot execute gh: {error}")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        fail(f"GitHub command failed ({' '.join(command)}): {detail}")
    return result.stdout


def parse_json_object(raw: str, context: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        fail(f"{context} returned invalid JSON: {error.msg}")
    if not isinstance(value, dict):
        fail(f"{context} returned {type(value).__name__}, expected an object")
    return value


def string_field(value: Any, field: str, context: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{context} field {field!r} must be a non-empty string")
    return value


def object_field(value: Any, field: str, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{context} field {field!r} must be an object")
    return value


def named_items(value: Any, field: str, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        fail(f"{context} field {field!r} must be an array")
    names: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            fail(f"{context} field {field}[{index}] must be an object")
        names.append(
            string_field(item.get("name"), "name", f"{context} {field}[{index}]")
        )
    return tuple(names)


def assignee_items(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        fail(f"{context} field 'assignees' must be an array")
    logins: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            fail(f"{context} field assignees[{index}] must be an object")
        logins.append(
            string_field(
                item.get("login"),
                "login",
                f"{context} assignees[{index}]",
            )
        )
    return tuple(logins)


def read_issue(repo: str, issue: int) -> IssueSnapshot:
    context = f"issue #{issue} in {repo}"
    raw = run_gh(
        (
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--json",
            "state,labels,assignees",
        )
    )
    value = parse_json_object(raw, context)
    return IssueSnapshot(
        state=string_field(value.get("state"), "state", context),
        labels=named_items(value.get("labels"), "labels", context),
        assignees=assignee_items(value.get("assignees"), context),
    )


def authenticated_login() -> str:
    login = run_gh(
        (
            "auth",
            "status",
            "--active",
            "--hostname",
            "github.com",
            "--json",
            "hosts",
            "--jq",
            '.hosts["github.com"][] | select(.active) | .login',
        )
    ).strip()
    if not login:
        fail("GitHub authenticated-user lookup returned an empty login")
    return login


def require_status(
    snapshot: IssueSnapshot,
    expected: str,
    repo: str,
    issue: int,
) -> None:
    if snapshot.state != "OPEN":
        fail(
            f"planned task #{issue} in {repo} must be open; "
            f"GitHub returned state {snapshot.state!r}"
        )
    actual = snapshot.lifecycle_labels
    if actual != (expected,):
        rendered = ", ".join(actual) if actual else "none"
        fail(
            f"planned task #{issue} in {repo} requires exactly {expected!r}; "
            f"found lifecycle labels: {rendered}. Repair the planned queue state or "
            "explicitly select the external-contribution path before retrying"
        )


def edit_status(
    repo: str,
    issue: int,
    from_status: str,
    to_status: str,
    *,
    assign: bool = False,
) -> None:
    arguments = [
        "issue",
        "edit",
        str(issue),
        "--repo",
        repo,
        "--remove-label",
        from_status,
        "--add-label",
        to_status,
    ]
    if assign:
        arguments.extend(("--add-assignee", "@me"))
    run_gh(arguments)


def verify_transition(repo: str, issue: int, expected: str) -> IssueSnapshot:
    snapshot = read_issue(repo, issue)
    require_status(snapshot, expected, repo, issue)
    return snapshot


def validate_todo(repo: str, issue: int) -> None:
    require_status(read_issue(repo, issue), "status:todo", repo, issue)
    print_result(repo, issue, "status:todo")


def claim(repo: str, issue: int) -> None:
    require_status(read_issue(repo, issue), "status:todo", repo, issue)
    claimant = authenticated_login()
    edit_status(
        repo,
        issue,
        "status:todo",
        "status:in-progress",
        assign=True,
    )
    snapshot = verify_transition(repo, issue, "status:in-progress")
    if claimant not in snapshot.assignees:
        fail(
            f"claim verification failed for planned task #{issue} in {repo}: "
            f"status:in-progress is present but authenticated user {claimant!r} "
            f"is not assigned; found assignees: {', '.join(snapshot.assignees) or 'none'}"
        )
    print_result(repo, issue, "status:in-progress", assignees=snapshot.assignees)


def transition(
    repo: str,
    issue: int,
    from_status: str,
    to_status: str,
    work_summary_file: Path | None = None,
    pr_url: str | None = None,
) -> None:
    if from_status == to_status:
        fail("--from-status and --to-status must differ")
    if to_status == "status:in-review":
        if work_summary_file is None:
            fail(
                "transition to status:in-review requires --work-summary-file so "
                "the posted work summary can be validated before the handoff"
            )
        if pr_url is None:
            fail(
                "transition to status:in-review requires --pr-url so the "
                "work summary can be bound to the current pull request"
            )
    elif work_summary_file is not None or pr_url is not None:
        fail(
            "--work-summary-file and --pr-url are only valid for "
            "status:in-review transitions"
        )
    require_status(read_issue(repo, issue), from_status, repo, issue)
    if to_status == "status:in-review":
        validate_posted_work_summary(repo, issue, work_summary_file, pr_url)
    edit_status(repo, issue, from_status, to_status)
    verify_transition(repo, issue, to_status)
    print_result(repo, issue, to_status)


def read_comment_bodies(repo: str, issue: int) -> tuple[str, ...]:
    context = f"comments for issue #{issue} in {repo}"
    raw = run_gh(
        (
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--json",
            "comments",
        )
    )
    value = parse_json_object(raw, context)
    comments = value.get("comments")
    if not isinstance(comments, list):
        fail(f"{context} field 'comments' must be an array")
    bodies: list[str] = []
    for index, comment in enumerate(comments):
        if not isinstance(comment, dict):
            fail(f"{context} comments[{index}] must be an object")
        bodies.append(
            string_field(comment.get("body"), "body", f"{context} comments[{index}]")
        )
    return tuple(bodies)


def parse_pull_request_number(repo: str, pr_url: str) -> int:
    parsed = urlsplit(pr_url)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or len(parts) != 4
        or parts[2] != "pull"
        or not parts[3].isdigit()
    ):
        fail(
            "work summary field 'PR' must be an exact GitHub pull-request URL "
            "in https://github.com/OWNER/REPO/pull/NUMBER form"
        )
    target_repo = "/".join(parts[:2])
    if target_repo != repo:
        fail(
            f"work summary field 'PR' must target the configured repository "
            f"{repo!r}; found {target_repo!r}"
        )
    return int(parts[3])


def read_pull_request(repo: str, pr_url: str) -> PullRequestSnapshot:
    pr_number = parse_pull_request_number(repo, pr_url)
    context = f"pull request {pr_url} in {repo}"
    raw = run_gh(
        (
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "url,author,headRefName,headRefOid",
        )
    )
    value = parse_json_object(raw, context)
    author = object_field(value.get("author"), "author", context)
    current_url = string_field(value.get("url"), "url", context)
    if current_url != pr_url:
        fail(
            f"current pull request URL {current_url!r} does not match the "
            f"requested URL {pr_url!r}"
        )
    return PullRequestSnapshot(
        url=current_url,
        author=string_field(author.get("login"), "login", f"{context} author"),
        branch=string_field(value.get("headRefName"), "headRefName", context),
        head_oid=string_field(value.get("headRefOid"), "headRefOid", context),
    )


def read_issue_comments(repo: str, issue: int) -> tuple[IssueComment, ...]:
    context = f"comments for issue #{issue} in {repo}"
    raw = run_gh(
        (
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--json",
            "comments",
        )
    )
    value = parse_json_object(raw, context)
    comments = value.get("comments")
    if not isinstance(comments, list):
        fail(f"{context} field 'comments' must be an array")
    parsed_comments: list[IssueComment] = []
    for index, comment in enumerate(comments):
        if not isinstance(comment, dict):
            fail(f"{context} comments[{index}] must be an object")
        author = object_field(
            comment.get("author"),
            "author",
            f"{context} comments[{index}]",
        )
        parsed_comments.append(
            IssueComment(
                body=string_field(
                    comment.get("body"),
                    "body",
                    f"{context} comments[{index}]",
                ),
                author=string_field(
                    author.get("login"),
                    "login",
                    f"{context} comments[{index}] author",
                ),
            )
        )
    return tuple(parsed_comments)


def validate_revision_ancestry(
    repo: str,
    execution_revision: str,
    current_head: str,
) -> None:
    comparison = run_gh(
        (
            "api",
            f"repos/{repo}/compare/{execution_revision}...{current_head}",
            "--jq",
            ".status",
        )
    ).strip()
    if comparison not in ("identical", "ahead"):
        fail(
            "work summary field 'Execution revision' must be the current pull "
            "request head or its ancestor; "
            f"GitHub compare returned status {comparison!r}"
        )


def validate_posted_work_summary(
    repo: str,
    issue: int,
    summary_file: Path,
    pr_url: str,
) -> None:
    try:
        summary = summary_file.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"cannot read work summary {summary_file}: {error}")

    try:
        parsed_summary = parse_work_summary(summary)
    except WorkSummaryError as error:
        fail(str(error))

    if parsed_summary.queue_classification != "planned":
        fail(
            "planned GitHub transition requires work summary field "
            "'Queue classification' to be 'planned'"
        )

    pull_request = read_pull_request(repo, pr_url)
    if parsed_summary.pr != pull_request.url:
        fail(
            f"work summary field 'PR' must match the current pull request URL "
            f"{pull_request.url!r}; found {parsed_summary.pr!r}"
        )
    if parsed_summary.branch != pull_request.branch:
        fail(
            f"work summary field 'Branch' must match the current pull request "
            f"head branch {pull_request.branch!r}; found {parsed_summary.branch!r}"
        )

    matching_comments = [
        comment
        for comment in read_issue_comments(repo, issue)
        if comment.body == summary
    ]
    if not matching_comments:
        fail(
            f"work summary {summary_file} was not found as an exact posted comment "
            f"on planned task #{issue} in {repo}"
        )
    if not any(comment.author == pull_request.author for comment in matching_comments):
        authors = ", ".join(sorted({comment.author for comment in matching_comments}))
        fail(
            "work summary comment author must equal the pull request author "
            f"{pull_request.author!r}; found: {authors}"
        )
    validate_revision_ancestry(
        repo,
        parsed_summary.execution_revision,
        pull_request.head_oid,
    )


def block(repo: str, issue: int, from_status: str, comment_file: Path) -> None:
    if from_status == "status:blocked":
        fail("--from-status must name the current non-blocked lifecycle status")
    try:
        diagnostic = comment_file.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"cannot read diagnostic comment file {comment_file}: {error}")
    if not diagnostic.strip():
        fail(f"diagnostic comment file {comment_file} is empty")

    snapshot = read_issue(repo, issue)
    if snapshot.state != "OPEN":
        fail(
            f"planned task #{issue} in {repo} must be open; "
            f"GitHub returned state {snapshot.state!r}"
        )
    actual = snapshot.lifecycle_labels
    if actual not in ((from_status,), ("status:blocked",)):
        rendered = ", ".join(actual) if actual else "none"
        fail(
            f"planned task #{issue} in {repo} requires exactly {from_status!r} "
            f"or a partially completed 'status:blocked' retry; "
            f"found lifecycle labels: {rendered}"
        )

    if diagnostic not in read_comment_bodies(repo, issue):
        run_gh(
            (
                "issue",
                "comment",
                str(issue),
                "--repo",
                repo,
                "--body-file",
                str(comment_file),
            )
        )
        if diagnostic not in read_comment_bodies(repo, issue):
            fail(
                f"blocked verification failed for planned task #{issue} in {repo}: "
                "the exact diagnostic comment was not found after posting"
            )

    if actual == (from_status,):
        edit_status(repo, issue, from_status, "status:blocked")
    verify_transition(repo, issue, "status:blocked")
    print_result(repo, issue, "status:blocked", diagnostic_comment=True)


def print_result(
    repo: str,
    issue: int,
    status: str,
    *,
    assignees: tuple[str, ...] = (),
    diagnostic_comment: bool = False,
) -> None:
    print(
        json.dumps(
            {
                "assignees": list(assignees),
                "diagnostic_comment": diagnostic_comment,
                "issue": issue,
                "repo": repo,
                "status": status,
                "verified": True,
            },
            sort_keys=True,
        )
    )


def repository(value: str) -> str:
    if not REPOSITORY_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("repository must use OWNER/REPO form")
    return value


def issue_number(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("issue must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("issue must be a positive integer")
    return parsed


def add_target_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, type=repository)
    parser.add_argument("--issue", required=True, type=issue_number)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enforce verified lifecycle transitions for planned GitHub tasks."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-todo")
    add_target_arguments(validate_parser)

    claim_parser = subparsers.add_parser("claim")
    add_target_arguments(claim_parser)

    transition_parser = subparsers.add_parser("transition")
    add_target_arguments(transition_parser)
    transition_parser.add_argument(
        "--from-status", required=True, choices=LIFECYCLE_STATUSES
    )
    transition_parser.add_argument(
        "--to-status", required=True, choices=LIFECYCLE_STATUSES
    )
    transition_parser.add_argument("--work-summary-file", type=Path)
    transition_parser.add_argument(
        "--pr-url",
        help="canonical current pull-request URL for a status:in-review handoff",
    )

    block_parser = subparsers.add_parser("block")
    add_target_arguments(block_parser)
    block_parser.add_argument(
        "--from-status", required=True, choices=LIFECYCLE_STATUSES
    )
    block_parser.add_argument("--comment-file", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "validate-todo":
            validate_todo(arguments.repo, arguments.issue)
        elif arguments.command == "claim":
            claim(arguments.repo, arguments.issue)
        elif arguments.command == "transition":
            transition(
                arguments.repo,
                arguments.issue,
                arguments.from_status,
                arguments.to_status,
                arguments.work_summary_file,
                arguments.pr_url,
            )
        elif arguments.command == "block":
            block(
                arguments.repo,
                arguments.issue,
                arguments.from_status,
                arguments.comment_file,
            )
        else:  # pragma: no cover - argparse enforces the subcommand choices.
            raise AssertionError(f"unknown command: {arguments.command}")
    except LifecycleError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
