#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Merge a GitHub PR, clean up its exact branch, or perform both operations."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Sequence


REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
ACCEPTED_CHECK_CONCLUSIONS = {"NEUTRAL", "SKIPPED", "SUCCESS"}


class MergeError(RuntimeError):
    """A merge or cleanup precondition failed."""


@dataclass(frozen=True)
class PullRequest:
    state: str
    is_draft: bool
    mergeable: str
    merge_state_status: str
    head_branch: str
    head_oid: str
    head_repository: str
    base_branch: str
    checks: tuple[dict[str, Any], ...]
    merge_commit: str | None
    url: str


def fail(message: str) -> NoReturn:
    raise MergeError(message)


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    accepted_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        fail(f"cannot execute {command[0]}: {error}")
    if result.returncode not in accepted_returncodes:
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        fail(f"command failed ({shlex.join(command)}): {detail}")
    return result


def run_gh(arguments: Sequence[str]) -> str:
    return run(("gh", *arguments)).stdout


def run_git(checkout: Path, arguments: Sequence[str]) -> str:
    return run(("git", "-C", str(checkout), *arguments)).stdout


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


def optional_oid(value: Any, field: str, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        fail(f"{context} field {field!r} must be an object or null")
    oid = value.get("oid")
    if oid is None:
        return None
    return string_field(oid, "oid", f"{context} {field}")


def read_pull_request(repo: str, pr_number: int) -> PullRequest:
    context = f"PR #{pr_number} in {repo}"
    raw = run_gh(
        (
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            (
                "state,isDraft,mergeable,mergeStateStatus,headRefName,headRefOid,"
                "headRepository,baseRefName,statusCheckRollup,mergeCommit,url"
            ),
        )
    )
    value = parse_json_object(raw, context)
    head_repository = value.get("headRepository")
    if not isinstance(head_repository, dict):
        fail(f"{context} field 'headRepository' must be an object")
    checks = value.get("statusCheckRollup")
    if not isinstance(checks, list) or not all(
        isinstance(check, dict) for check in checks
    ):
        fail(f"{context} field 'statusCheckRollup' must be an array of objects")
    is_draft = value.get("isDraft")
    if not isinstance(is_draft, bool):
        fail(f"{context} field 'isDraft' must be a boolean")
    return PullRequest(
        state=string_field(value.get("state"), "state", context),
        is_draft=is_draft,
        mergeable=string_field(value.get("mergeable"), "mergeable", context),
        merge_state_status=string_field(
            value.get("mergeStateStatus"), "mergeStateStatus", context
        ),
        head_branch=string_field(value.get("headRefName"), "headRefName", context),
        head_oid=string_field(value.get("headRefOid"), "headRefOid", context),
        head_repository=string_field(
            head_repository.get("nameWithOwner"),
            "nameWithOwner",
            f"{context} headRepository",
        ),
        base_branch=string_field(value.get("baseRefName"), "baseRefName", context),
        checks=tuple(checks),
        merge_commit=optional_oid(value.get("mergeCommit"), "mergeCommit", context),
        url=string_field(value.get("url"), "url", context),
    )


def require_settled_checks(pr: PullRequest) -> None:
    pending: list[str] = []
    failed: list[str] = []
    for check in pr.checks:
        check_type = check.get("__typename")
        if check_type == "CheckRun":
            name = str(check.get("name") or "unnamed check")
            status = check.get("status")
            conclusion = check.get("conclusion")
            if status != "COMPLETED":
                pending.append(name)
            elif conclusion not in ACCEPTED_CHECK_CONCLUSIONS:
                failed.append(f"{name} ({conclusion or 'no conclusion'})")
        elif check_type == "StatusContext":
            name = str(check.get("context") or "unnamed status")
            state = check.get("state")
            if state == "PENDING":
                pending.append(name)
            elif state != "SUCCESS":
                failed.append(f"{name} ({state or 'no state'})")
        else:
            fail(f"unsupported statusCheckRollup entry type: {check_type!r}")
    if pending:
        fail(f"PR checks are still pending: {', '.join(pending)}")
    if failed:
        fail(f"PR checks are not green: {', '.join(failed)}")


def require_open_mergeable(pr: PullRequest) -> None:
    if pr.state != "OPEN":
        fail(f"PR must be OPEN before merge; found {pr.state!r}")
    if pr.is_draft:
        fail("PR is still a draft")
    if pr.mergeable != "MERGEABLE":
        fail(f"PR is not mergeable; GitHub returned {pr.mergeable!r}")
    if pr.merge_state_status != "CLEAN":
        fail(f"PR merge state must be CLEAN; GitHub returned {pr.merge_state_status!r}")
    require_settled_checks(pr)


def normalize_github_repository(url: str) -> str:
    patterns = (
        r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$",
        r"^(?:ssh://git@|https?://)github\.com/([^/]+/[^/]+?)(?:\.git)?/?$",
    )
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            return match.group(1)
    fail(f"remote URL is not a supported GitHub repository URL: {url!r}")


def require_remote_repository(checkout: Path, remote: str, expected_repo: str) -> None:
    url = run_git(checkout, ("remote", "get-url", remote)).strip()
    actual_repo = normalize_github_repository(url)
    if actual_repo.lower() != expected_repo.lower():
        fail(
            f"git remote {remote!r} resolves to {actual_repo!r}, "
            f"expected {expected_repo!r}"
        )


def local_ref_oid(checkout: Path, ref: str) -> str | None:
    result = run(
        (
            "git",
            "-C",
            str(checkout),
            "rev-parse",
            "--verify",
            "--quiet",
            f"{ref}^{{commit}}",
        ),
        accepted_returncodes=(0, 1),
    )
    if result.returncode == 1:
        return None
    return result.stdout.strip()


def remote_branch_oid(checkout: Path, remote: str, branch: str) -> str | None:
    output = run_git(
        checkout,
        ("ls-remote", "--heads", remote, f"refs/heads/{branch}"),
    ).strip()
    if not output:
        return None
    lines = output.splitlines()
    if len(lines) != 1:
        fail(
            f"remote branch lookup returned {len(lines)} entries for {remote}/{branch}"
        )
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != f"refs/heads/{branch}":
        fail(f"remote branch lookup returned malformed output: {lines[0]!r}")
    return fields[0]


def require_clean_checkout(path: Path, label: str) -> None:
    dirty = run_git(path, ("status", "--porcelain")).strip()
    if dirty:
        fail(f"{label} has uncommitted changes; cleanup would be unsafe:\n{dirty}")


def worktree_records(checkout: Path) -> tuple[dict[str, str], ...]:
    output = run_git(checkout, ("worktree", "list", "--porcelain"))
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in (*output.splitlines(), ""):
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return tuple(records)


def worktree_record(checkout: Path, target: Path) -> dict[str, str] | None:
    resolved_target = target.resolve()
    for record in worktree_records(checkout):
        path = record.get("worktree")
        if path and Path(path).resolve() == resolved_target:
            return record
    return None


def validate_cleanup_inputs(
    checkout: Path,
    pr: PullRequest,
    *,
    base_remote: str,
    push_remote: str,
    delete_remote_branch: bool,
    worktree: Path | None,
    allow_missing_worktree: bool,
    canonical_repo: str,
) -> None:
    top_level = Path(run_git(checkout, ("rev-parse", "--show-toplevel")).strip())
    if top_level.resolve() != checkout.resolve():
        fail(f"--checkout must be the repository root: {top_level}")
    require_clean_checkout(checkout, "base checkout")
    require_remote_repository(checkout, base_remote, canonical_repo)
    if remote_branch_oid(checkout, base_remote, pr.base_branch) is None:
        fail(f"base branch {base_remote}/{pr.base_branch} does not exist")
    if pr.head_branch == pr.base_branch:
        fail(
            "PR head and base branch names are identical; automatic cleanup is ambiguous"
        )

    current = run(
        (
            "git",
            "-C",
            str(checkout),
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
        ),
        accepted_returncodes=(0, 1),
    )
    if current.returncode != 0:
        fail("base checkout is detached; cleanup would be unsafe")

    resolved_checkout = checkout.resolve()
    expected_worktree = worktree.resolve() if worktree else None
    if expected_worktree == resolved_checkout:
        fail(
            "--worktree must not name the base checkout; omit it for an in-place branch"
        )
    for record in worktree_records(checkout):
        record_path_value = record.get("worktree")
        if not record_path_value:
            continue
        record_path = Path(record_path_value).resolve()
        record_branch = record.get("branch")
        if (
            record_branch == f"refs/heads/{pr.base_branch}"
            and record_path != resolved_checkout
        ):
            fail(
                f"base branch {pr.base_branch!r} is checked out in another worktree: "
                f"{record_path}"
            )
        if (
            record_branch == f"refs/heads/{pr.head_branch}"
            and record_path != resolved_checkout
            and record_path != expected_worktree
        ):
            fail(
                f"PR branch {pr.head_branch!r} is checked out at {record_path}; "
                "pass that path with --worktree"
            )

    local_oid = local_ref_oid(checkout, f"refs/heads/{pr.head_branch}")
    if local_oid is not None and local_oid != pr.head_oid:
        fail(
            f"local branch {pr.head_branch!r} is at {local_oid}, "
            f"expected verified PR head {pr.head_oid}"
        )

    if worktree is not None:
        record = worktree_record(checkout, worktree)
        if record is None:
            if not allow_missing_worktree:
                fail(f"task worktree is not registered: {worktree}")
        else:
            if record.get("HEAD") != pr.head_oid:
                fail(
                    f"task worktree HEAD is {record.get('HEAD')!r}, "
                    f"expected {pr.head_oid}"
                )
            if record.get("branch") != f"refs/heads/{pr.head_branch}":
                fail(
                    f"task worktree branch is {record.get('branch')!r}, "
                    f"expected refs/heads/{pr.head_branch}"
                )
            require_clean_checkout(worktree, "task worktree")

    if delete_remote_branch:
        require_remote_repository(checkout, push_remote, pr.head_repository)
        remote_oid = remote_branch_oid(checkout, push_remote, pr.head_branch)
        if remote_oid is not None and remote_oid != pr.head_oid:
            fail(
                f"remote branch {push_remote}/{pr.head_branch} is at {remote_oid}, "
                f"expected verified PR head {pr.head_oid}"
            )


def remove_worktree(checkout: Path, worktree: Path | None) -> bool:
    if worktree is None or worktree_record(checkout, worktree) is None:
        return False
    parent = worktree.resolve().parent
    run_git(checkout, ("worktree", "remove", str(worktree.resolve())))
    try:
        parent.rmdir()
    except OSError:
        pass
    return True


def update_base(checkout: Path, remote: str, branch: str) -> None:
    run_git(checkout, ("fetch", remote, branch))
    remote_ref = f"refs/remotes/{remote}/{branch}"
    if local_ref_oid(checkout, f"refs/heads/{branch}") is None:
        run_git(
            checkout, ("switch", "--create", branch, "--track", f"{remote}/{branch}")
        )
    else:
        current = run(
            ("git", "-C", str(checkout), "symbolic-ref", "--quiet", "--short", "HEAD"),
            accepted_returncodes=(0, 1),
        )
        if current.returncode != 0:
            fail("base checkout is detached; cannot update the base branch safely")
        if current.stdout.strip() != branch:
            run_git(checkout, ("switch", branch))
    run_git(checkout, ("merge", "--ff-only", remote_ref))
    local_oid = run_git(checkout, ("rev-parse", "HEAD")).strip()
    remote_oid = run_git(checkout, ("rev-parse", remote_ref)).strip()
    if local_oid != remote_oid:
        fail(
            f"base update verification failed: local {branch} is {local_oid}, "
            f"{remote}/{branch} is {remote_oid}"
        )


def delete_local_branch(checkout: Path, branch: str, expected_oid: str) -> bool:
    ref = f"refs/heads/{branch}"
    local_oid = local_ref_oid(checkout, ref)
    if local_oid is None:
        return False
    if local_oid != expected_oid:
        fail(
            f"refusing to delete local branch {branch!r}: found {local_oid}, "
            f"expected {expected_oid}"
        )
    run_git(checkout, ("branch", "-D", branch))
    if local_ref_oid(checkout, ref) is not None:
        fail(f"local branch deletion did not remove {branch!r}")
    return True


def delete_remote_branch(
    checkout: Path,
    remote: str,
    branch: str,
    expected_oid: str,
) -> bool:
    remote_oid = remote_branch_oid(checkout, remote, branch)
    if remote_oid is None:
        return False
    if remote_oid != expected_oid:
        fail(
            f"refusing to delete remote branch {remote}/{branch}: found {remote_oid}, "
            f"expected {expected_oid}"
        )
    run_git(checkout, ("push", remote, "--delete", branch))
    if remote_branch_oid(checkout, remote, branch) is not None:
        fail(f"remote branch deletion did not remove {remote}/{branch}")
    return True


def require_expected_head(pr: PullRequest, expected_head: str | None) -> None:
    if expected_head and pr.head_oid != expected_head:
        fail(f"PR head changed: expected {expected_head}, found {pr.head_oid}")


def merge_pull_request(
    repo: str,
    pr_number: int,
    merge_policy: str,
    pr: PullRequest,
) -> tuple[PullRequest, bool]:
    if pr.state == "MERGED":
        if not pr.merge_commit:
            fail("PR is MERGED but GitHub returned no merge commit")
        return pr, False
    require_open_mergeable(pr)
    merge_flag = {"merge": "--merge", "squash": "--squash"}[merge_policy]
    run_gh(
        (
            "pr",
            "merge",
            str(pr_number),
            "--repo",
            repo,
            merge_flag,
            "--match-head-commit",
            pr.head_oid,
        )
    )
    merged_pr = read_pull_request(repo, pr_number)
    if merged_pr.head_oid != pr.head_oid:
        fail(
            "PR head changed while merging: "
            f"expected {pr.head_oid}, found {merged_pr.head_oid}"
        )
    if merged_pr.state != "MERGED" or not merged_pr.merge_commit:
        fail("GitHub accepted the merge command but the PR is not MERGED")
    return merged_pr, True


def cleanup_pull_request(
    arguments: argparse.Namespace,
    pr: PullRequest,
    *,
    allow_missing_worktree: bool,
) -> dict[str, bool]:
    cleanup_pull_request_preflight(arguments, pr, allow_missing_worktree)
    return perform_cleanup(arguments, pr)


def execute(arguments: argparse.Namespace) -> dict[str, Any]:
    pr = read_pull_request(arguments.repo, arguments.pr)
    require_expected_head(pr, arguments.expected_head)
    merged_now = False
    cleanup_result = {
        "base_updated": False,
        "local_branch_deleted": False,
        "remote_branch_deleted": False,
        "worktree_removed": False,
    }

    if arguments.operation == "merge":
        pr, merged_now = merge_pull_request(
            arguments.repo,
            arguments.pr,
            arguments.merge_policy,
            pr,
        )
    elif arguments.operation == "cleanup":
        if pr.state != "MERGED" or not pr.merge_commit:
            fail(f"cleanup requires a MERGED PR; found {pr.state!r}")
        cleanup_result = cleanup_pull_request(
            arguments,
            pr,
            allow_missing_worktree=True,
        )
    elif arguments.operation == "merge-cleanup":
        already_merged = pr.state == "MERGED"
        if not already_merged:
            require_open_mergeable(pr)
        cleanup_pull_request_preflight(arguments, pr, already_merged)
        pr, merged_now = merge_pull_request(
            arguments.repo,
            arguments.pr,
            arguments.merge_policy,
            pr,
        )
        cleanup_result = perform_cleanup(arguments, pr)
    else:
        fail(f"unsupported operation: {arguments.operation!r}")

    return {
        "base_branch": pr.base_branch,
        "head_branch": pr.head_branch,
        "head_oid": pr.head_oid,
        "merge_commit": pr.merge_commit,
        "merged_now": merged_now,
        "operation": arguments.operation,
        "pr": arguments.pr,
        "pr_url": pr.url,
        "repository": arguments.repo,
        **cleanup_result,
    }


def cleanup_pull_request_preflight(
    arguments: argparse.Namespace,
    pr: PullRequest,
    allow_missing_worktree: bool,
) -> None:
    checkout = arguments.checkout.resolve()
    worktree = arguments.worktree.resolve() if arguments.worktree else None
    validate_cleanup_inputs(
        checkout,
        pr,
        base_remote=arguments.base_remote,
        push_remote=arguments.push_remote,
        delete_remote_branch=arguments.delete_remote_branch,
        worktree=worktree,
        allow_missing_worktree=allow_missing_worktree,
        canonical_repo=arguments.repo,
    )


def perform_cleanup(
    arguments: argparse.Namespace,
    pr: PullRequest,
) -> dict[str, bool]:
    checkout = arguments.checkout.resolve()
    worktree = arguments.worktree.resolve() if arguments.worktree else None
    worktree_removed = remove_worktree(checkout, worktree)
    update_base(checkout, arguments.base_remote, pr.base_branch)
    local_branch_deleted = delete_local_branch(checkout, pr.head_branch, pr.head_oid)
    remote_branch_deleted = False
    if arguments.delete_remote_branch:
        remote_branch_deleted = delete_remote_branch(
            checkout,
            arguments.push_remote,
            pr.head_branch,
            pr.head_oid,
        )
    return {
        "base_updated": True,
        "local_branch_deleted": local_branch_deleted,
        "remote_branch_deleted": remote_branch_deleted,
        "worktree_removed": worktree_removed,
    }


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, help="canonical OWNER/REPO")
    parser.add_argument("--pr", required=True, type=int, help="pull request number")
    parser.add_argument(
        "--expected-head",
        help="optional full PR HEAD SHA to require",
    )


def add_merge_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--merge-policy",
        choices=("merge", "squash"),
        default="squash",
    )


def add_cleanup_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--checkout",
        type=Path,
        default=Path.cwd(),
        help="clean repository root to update (default: current directory)",
    )
    parser.add_argument(
        "--base-remote",
        default="origin",
        help="remote carrying the canonical base branch (default: origin)",
    )
    parser.add_argument(
        "--worktree",
        type=Path,
        help="separate PR worktree to validate and remove",
    )
    parser.add_argument(
        "--delete-remote-branch",
        action="store_true",
        help="delete the exact PR branch from --push-remote",
    )
    parser.add_argument(
        "--push-remote",
        default="origin",
        help="remote whose exact PR branch may be deleted (default: origin)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Merge a GitHub PR, clean up its exact branch, or perform both operations."
        )
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    merge_parser = subparsers.add_parser("merge", help="merge the PR only")
    add_common_arguments(merge_parser)
    add_merge_arguments(merge_parser)
    cleanup_parser = subparsers.add_parser(
        "cleanup", help="clean up a merged PR branch only"
    )
    add_common_arguments(cleanup_parser)
    add_cleanup_arguments(cleanup_parser)
    combined_parser = subparsers.add_parser(
        "merge-cleanup", help="merge the PR and clean up its branch"
    )
    add_common_arguments(combined_parser)
    add_merge_arguments(combined_parser)
    add_cleanup_arguments(combined_parser)
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if not REPOSITORY_RE.fullmatch(arguments.repo):
        parser.error("--repo must use OWNER/REPO form")
    if arguments.pr <= 0:
        parser.error("--pr must be positive")
    if arguments.expected_head and not FULL_SHA_RE.fullmatch(arguments.expected_head):
        parser.error("--expected-head must be a full 40-character commit SHA")
    try:
        result = execute(arguments)
    except MergeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
