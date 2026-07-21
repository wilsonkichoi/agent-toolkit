#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Deterministic helpers for the dev:shadow historical-replay evaluation workflow.

Every subcommand is a self-contained, dependency-free step the `dev:shadow` skill
orchestrates. Read paths use `gh`/`git` and are safe to run repeatedly; write paths
(`create-shadow-issue`, `create-branches`, `open-shadow-pr`, `cleanup`) re-read GitHub
state and assert the shadow-isolation invariants before reporting success. No subcommand
merges a pull request or mutates the source issue or original PR.

The script never posts raw session logs, prompts, reasoning text, tool arguments,
credentials, or private repository content anywhere. `metrics` reads only numeric usage
metadata from harness logs; `pricing` reads only a static catalog file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, NoReturn, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PRICING_CATALOG = SCRIPT_DIR / "shadow_pricing.json"

REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
GITHUB_ISSUE_URL_RE = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+/issues/\d+$")
GITHUB_PR_URL_RE = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+/pull/\d+$")
STATUS_LABEL_PREFIX = "status:"
SHADOW_LABEL = "experiment:shadow"
DO_NOT_MERGE_LABEL = "do-not-merge"
CLOSING_KEYWORD_RE = re.compile(
    r"\b(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\b\s*#\d+",
    re.IGNORECASE,
)
REFS_RE = re.compile(r"\bRefs\b\s*#\d+")

# The disclosures every dev:shadow report must carry. Reporting always emits these; a
# caller may add more but can never drop one.
REQUIRED_DISCLOSURES = (
    "Same-repository replay is not blind; the original solution may be discoverable in "
    "Git history or through GitHub.",
    "The source issue body is current, not guaranteed to be its exact historical text at "
    "cutoff.",
    "Original token and cost data may be unavailable.",
    "GitHub timestamps are observable workflow timestamps, not continuous agent work.",
    "Estimated API-equivalent cost is not the user's actual subscription charge.",
    "Reviewer and verifier judgments depend on the identified models.",
)

# The comparison table dimensions, in report order. `align` controls rendering only.
COMPARISON_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("Functional tests", "Commands, results, and CI URLs"),
    ("DoD criteria met", "Criterion-level evidence links"),
    ("Review blockers", "SHA-bound review links"),
    ("Fix and review cycles", "Timeline links"),
    ("Files changed", "Git diff statistics"),
    ("Lines added and removed", "Git diff statistics"),
    ("Observable delivery time", "Explicit start and end timestamps"),
    ("Total run time", "Shadow preparation through report"),
    ("CI wait time", "Check or workflow timestamps"),
    ("Input tokens", "Numeric harness usage metadata"),
    ("Cached input tokens", "Numeric harness usage metadata"),
    ("Output tokens", "Numeric harness usage metadata"),
    ("Reasoning tokens", "Numeric metadata when exposed"),
    ("Estimated API-equivalent cost", "Price source and effective date"),
)

UNAVAILABLE = "unavailable"


class ShadowError(RuntimeError):
    """A shadow-replay precondition, reconstruction, mutation, or validation failed."""


def fail(message: str) -> NoReturn:
    raise ShadowError(message)


# --------------------------------------------------------------------------- process


def run_command(argv: Sequence[str], *, context: str) -> str:
    try:
        result = subprocess.run(argv, text=True, capture_output=True, check=False)
    except OSError as error:
        fail(f"cannot execute {argv[0]}: {error}")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        fail(f"{context} failed ({' '.join(argv)}): {detail}")
    return result.stdout


def run_gh(arguments: Sequence[str], *, context: str) -> str:
    return run_command(["gh", *arguments], context=context)


def run_git(arguments: Sequence[str], *, context: str) -> str:
    return run_command(["git", *arguments], context=context)


# --------------------------------------------------------------------------- parsing


def parse_json(raw: str, *, context: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        fail(f"{context} returned invalid JSON: {error.msg}")


def parse_json_object(raw: str, *, context: str) -> dict[str, Any]:
    value = parse_json(raw, context=context)
    if not isinstance(value, dict):
        fail(f"{context} returned {type(value).__name__}, expected an object")
    return value


def parse_jsonl(raw: str, *, context: str) -> list[Any]:
    items: list[Any] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            items.append(json.loads(stripped))
        except json.JSONDecodeError as error:
            fail(f"{context} line {number} is not valid JSON: {error.msg}")
    return items


def read_text_file(path: Path, *, context: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"cannot read {context} {path}: {error}")


def string_field(value: Any, field_name: str, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{context} field {field_name!r} must be a non-empty string")
    return value


def label_names(value: Any, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        fail(f"{context} field 'labels' must be an array")
    names: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
        else:
            fail(f"{context} labels[{index}] must be a string or an object with 'name'")
    return tuple(names)


def status_labels(labels: Iterable[str]) -> tuple[str, ...]:
    return tuple(label for label in labels if label.startswith(STATUS_LABEL_PREFIX))


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# --------------------------------------------------------------------------- run-id


def make_run_id(now: datetime, suffix: str) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{suffix}"


def command_run_id(args: argparse.Namespace) -> None:
    if args.now:
        try:
            now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        except ValueError:
            fail(f"--now must be an ISO 8601 timestamp, got {args.now!r}")
    else:
        now = datetime.now(timezone.utc)
    suffix = args.suffix or secrets.token_hex(4)
    if not re.fullmatch(r"[0-9a-zA-Z]+", suffix):
        fail("--suffix must be alphanumeric")
    emit({"run_id": make_run_id(now, suffix)})


# ----------------------------------------------------------- historical base


@dataclass(frozen=True)
class SourceCommit:
    sha: str
    parents: tuple[str, ...]
    date: str


def read_pr_commits(repo: str, pr: int) -> list[SourceCommit]:
    context = f"pull request #{pr} commit list in {repo}"
    raw = run_gh(
        (
            "api",
            "--paginate",
            f"repos/{repo}/pulls/{pr}/commits",
            "--jq",
            ".[] | {sha: .sha, parents: [.parents[].sha], date: .commit.committer.date}",
        ),
        context=context,
    )
    commits: list[SourceCommit] = []
    for entry in parse_jsonl(raw, context=context):
        if not isinstance(entry, dict):
            fail(f"{context} produced a non-object commit entry")
        parents = entry.get("parents")
        if not isinstance(parents, list):
            fail(f"{context} commit is missing a parents array")
        commits.append(
            SourceCommit(
                sha=string_field(entry.get("sha"), "sha", context=context),
                parents=tuple(str(parent) for parent in parents),
                date=string_field(entry.get("date"), "date", context=context),
            )
        )
    return commits


def reconstruct_historical_base(
    repo: str,
    pr: int,
    *,
    source_head: str | None,
    verify_ancestor: bool,
    repo_path: Path,
) -> dict[str, Any]:
    commits = read_pr_commits(repo, pr)
    if not commits:
        fail(f"pull request #{pr} in {repo} has no commits; nothing to replay")
    first = commits[0]
    if len(first.parents) == 0:
        fail(
            f"first commit {first.sha} of PR #{pr} is a root commit with no parent; "
            "the historical base is ambiguous - stop"
        )
    if len(first.parents) > 1:
        fail(
            f"first commit {first.sha} of PR #{pr} is a merge commit with "
            f"{len(first.parents)} parents; the historical base is ambiguous - stop"
        )
    base = first.parents[0]
    head = source_head or commits[-1].sha
    if verify_ancestor:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "merge-base", "--is-ancestor", base, head],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 1:
            fail(
                f"reconstructed base {base} is not an ancestor of source head {head}; "
                "the historical base cannot be validated - stop"
            )
        if result.returncode != 0:
            detail = result.stderr.strip() or "ancestry check failed"
            fail(f"cannot validate base ancestry for PR #{pr} in {repo}: {detail}")
    return {
        "historical_base": base,
        "first_commit": first.sha,
        "source_head": head,
        "cutoff": first.date,
        "cutoff_rule": "first source-PR commit committed timestamp",
        "commit_count": len(commits),
    }


def command_historical_base(args: argparse.Namespace) -> None:
    result = reconstruct_historical_base(
        args.repo,
        args.source_pr,
        source_head=args.source_head,
        verify_ancestor=not args.no_verify_ancestor,
        repo_path=args.repo_path,
    )
    emit(result)


# ----------------------------------------------------------------- preflight


def normalized_reference_numbers(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return sorted(
        reference["number"]
        for reference in value
        if isinstance(reference, dict) and isinstance(reference.get("number"), int)
    )


def normalized_milestone(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {"number": value.get("number"), "title": value.get("title")}


def normalized_assignees(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        assignee["login"]
        for assignee in value
        if isinstance(assignee, dict) and isinstance(assignee.get("login"), str)
    )


def normalized_comments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for comment in value:
        if not isinstance(comment, dict):
            continue
        author = comment.get("author")
        normalized.append(
            {
                "author": author.get("login") if isinstance(author, dict) else None,
                "body": comment.get("body") or "",
                "createdAt": comment.get("createdAt"),
                "url": comment.get("url"),
            }
        )
    return normalized


def normalized_reviews(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for review in value:
        if not isinstance(review, dict):
            continue
        author = review.get("author")
        commit = review.get("commit")
        normalized.append(
            {
                "author": author.get("login") if isinstance(author, dict) else None,
                "body": review.get("body") or "",
                "state": review.get("state"),
                "submittedAt": review.get("submittedAt"),
                "commit": commit.get("oid") if isinstance(commit, dict) else None,
            }
        )
    return normalized


def source_issue_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    context = "source issue snapshot"
    return {
        "state": value.get("state"),
        "stateReason": value.get("stateReason"),
        "title": value.get("title") or "",
        "body": value.get("body") or "",
        "labels": sorted(label_names(value.get("labels", []), context=context)),
        "milestone": normalized_milestone(value.get("milestone")),
        "assignees": normalized_assignees(value.get("assignees")),
        "closedByPullRequestsReferences": normalized_reference_numbers(
            value.get("closedByPullRequestsReferences")
        ),
        "comments": normalized_comments(value.get("comments")),
    }


def source_pr_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    context = "source PR snapshot"
    merge_commit = value.get("mergeCommit")
    merge_sha = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    return {
        "state": value.get("state"),
        "merged": value.get("merged"),
        "mergedAt": value.get("mergedAt"),
        "mergeCommit": merge_sha,
        "title": value.get("title") or "",
        "body": value.get("body") or "",
        "labels": sorted(label_names(value.get("labels", []), context=context)),
        "baseRefName": value.get("baseRefName"),
        "headRefName": value.get("headRefName"),
        "headRefOid": value.get("headRefOid"),
        "closingIssuesReferences": normalized_reference_numbers(
            value.get("closingIssuesReferences")
        ),
        "comments": normalized_comments(value.get("comments")),
        "reviews": normalized_reviews(value.get("reviews")),
    }


def source_snapshot_sha256(
    issue_snapshot: dict[str, Any], pr_snapshot: dict[str, Any]
) -> str:
    return canonical_sha256({"issue": issue_snapshot, "pr": pr_snapshot})


def read_issue_completion(repo: str, issue: int) -> dict[str, Any]:
    context = f"source issue #{issue} in {repo}"
    raw = run_gh(
        (
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--json",
            "state,stateReason,title,body,labels,milestone,assignees,"
            "closedByPullRequestsReferences,comments",
        ),
        context=context,
    )
    value = parse_json_object(raw, context=context)
    state = string_field(value.get("state"), "state", context=context)
    reason = value.get("stateReason")
    if state.upper() != "CLOSED":
        fail(
            f"source issue #{issue} in {repo} must be completed; GitHub returned "
            f"state {state!r} - dev:shadow replays completed work only"
        )
    if isinstance(reason, str) and reason and reason.upper() != "COMPLETED":
        fail(
            f"source issue #{issue} in {repo} closed as {reason!r}, not completed; "
            "dev:shadow replays completed work only"
        )
    snapshot = source_issue_snapshot(value)
    return {
        "title": snapshot["title"],
        "linked_prs": snapshot["closedByPullRequestsReferences"],
        "snapshot": snapshot,
    }


def read_pr_binding(repo: str, pr: int, issue: int) -> dict[str, Any]:
    context = f"source pull request #{pr} in {repo}"
    raw = run_gh(
        (
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "state,merged,mergedAt,mergeCommit,title,body,labels,baseRefName,"
            "headRefName,closingIssuesReferences,headRefOid,comments,reviews",
        ),
        context=context,
    )
    value = parse_json_object(raw, context=context)
    merged = value.get("merged")
    if merged is not True:
        fail(
            f"source PR #{pr} in {repo} is not merged (merged={merged!r}); "
            "dev:shadow replays merged pull requests only"
        )
    snapshot = source_pr_snapshot(value)
    bound = issue in snapshot["closingIssuesReferences"]
    merge_sha = snapshot["mergeCommit"] or ""
    return {
        "bound": bound,
        "merge_commit": merge_sha,
        "merged_at": value.get("mergedAt") or "",
        "head": value.get("headRefOid") or "",
        "snapshot": snapshot,
    }


def resolve_source_pr(
    repo: str, issue: int, explicit_pr: int | None, linked_prs: list[int]
) -> int:
    if explicit_pr is not None:
        return explicit_pr
    if not linked_prs:
        fail(
            f"source issue #{issue} in {repo} has no linked closing pull request; "
            "pass an explicit 'pr <source-pr>' to identify the merged source PR"
        )
    if len(linked_prs) > 1:
        rendered = ", ".join(f"#{number}" for number in sorted(linked_prs))
        fail(
            f"source issue #{issue} in {repo} maps to multiple linked PRs ({rendered}); "
            "the source PR is ambiguous - pass an explicit 'pr <source-pr>' to select one"
        )
    return linked_prs[0]


def command_preflight(args: argparse.Namespace) -> None:
    completion = read_issue_completion(args.repo, args.source_issue)
    source_pr = resolve_source_pr(
        args.repo, args.source_issue, args.source_pr, completion["linked_prs"]
    )
    binding = read_pr_binding(args.repo, source_pr, args.source_issue)
    if not binding["bound"]:
        fail(
            f"source PR #{source_pr} does not close source issue #{args.source_issue} in "
            f"{args.repo}; closing-reference binding is required even for an explicit PR"
        )
    base = reconstruct_historical_base(
        args.repo,
        source_pr,
        source_head=binding["head"] or None,
        verify_ancestor=not args.no_verify_ancestor,
        repo_path=args.repo_path,
    )
    emit(
        {
            "ok": True,
            "repo": args.repo,
            "source_issue": args.source_issue,
            "source_pr": source_pr,
            "source_title": completion["title"],
            "merge_commit": binding["merge_commit"],
            "merged_at": binding["merged_at"],
            "source_head": base["source_head"],
            "historical_base": base["historical_base"],
            "first_commit": base["first_commit"],
            "cutoff": base["cutoff"],
            "cutoff_rule": base["cutoff_rule"],
            "source_snapshot_sha256": source_snapshot_sha256(
                completion["snapshot"], binding["snapshot"]
            ),
        }
    )


# ---------------------------------------------------------- artifact creation


def ensure_labels(repo: str, labels: Sequence[str]) -> None:
    context = f"label list in {repo}"
    raw = run_gh(
        ("label", "list", "--repo", repo, "--limit", "500", "--json", "name"),
        context=context,
    )
    existing = {
        entry["name"]
        for entry in parse_json(raw, context=context)
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    for label in labels:
        if label not in existing:
            run_gh(
                ("label", "create", label, "--repo", repo, "--force"),
                context=f"create label {label!r} in {repo}",
            )


def read_issue_isolation(repo: str, issue: int) -> dict[str, Any]:
    context = f"shadow issue #{issue} in {repo}"
    raw = run_gh(
        (
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--json",
            "labels,milestone,state,stateReason",
        ),
        context=context,
    )
    value = parse_json_object(raw, context=context)
    labels = label_names(value.get("labels"), context=context)
    milestone = value.get("milestone")
    has_milestone = bool(milestone) if not isinstance(milestone, dict) else bool(
        milestone.get("title") or milestone.get("number")
    )
    return {
        "labels": labels,
        "has_milestone": has_milestone,
        "state": str(value.get("state", "")).upper(),
        "state_reason": value.get("stateReason"),
    }


def assert_issue_isolated(repo: str, issue: int) -> None:
    state = read_issue_isolation(repo, issue)
    labels = state["labels"]
    offending = status_labels(labels)
    if offending:
        fail(
            f"shadow issue #{issue} in {repo} carries lifecycle label(s) "
            f"{', '.join(offending)}; a shadow issue must have no status:* label"
        )
    if SHADOW_LABEL not in labels:
        fail(
            f"shadow issue #{issue} in {repo} is missing required label {SHADOW_LABEL!r}"
        )
    if state["has_milestone"]:
        fail(
            f"shadow issue #{issue} in {repo} has a milestone; a shadow issue must have none"
        )
    if state["state"] != "OPEN":
        fail(
            f"shadow issue #{issue} in {repo} must remain OPEN before cleanup "
            f"(state={state['state']!r})"
        )


def command_create_shadow_issue(args: argparse.Namespace) -> None:
    read_text_file(args.body_file, context="shadow issue body")
    ensure_labels(args.repo, (SHADOW_LABEL, DO_NOT_MERGE_LABEL))
    raw = run_gh(
        (
            "issue",
            "create",
            "--repo",
            args.repo,
            "--title",
            args.title,
            "--body-file",
            str(args.body_file),
            "--label",
            SHADOW_LABEL,
        ),
        context=f"create shadow issue in {args.repo}",
    ).strip()
    issue_number = parse_issue_or_pr_number(raw)
    assert_issue_isolated(args.repo, issue_number)
    emit({"shadow_issue": issue_number, "url": raw, "repo": args.repo})


def parse_issue_or_pr_number(url: str) -> int:
    match = re.search(r"/(\d+)(?:\s*)$", url.strip())
    if not match:
        fail(f"could not parse an issue or PR number from GitHub output {url!r}")
    return int(match.group(1))


def command_create_branches(args: argparse.Namespace) -> None:
    if args.shadow_base == args.candidate:
        fail("--shadow-base and --candidate must differ")
    run_git(
        ("-C", str(args.repo_path), "branch", args.shadow_base, args.base_commit),
        context=f"create shadow-base branch {args.shadow_base}",
    )
    run_git(
        ("-C", str(args.repo_path), "push", args.remote, args.shadow_base),
        context=f"push shadow-base branch {args.shadow_base}",
    )
    run_git(
        ("-C", str(args.repo_path), "branch", args.candidate, args.shadow_base),
        context=f"create candidate branch {args.candidate}",
    )
    run_git(
        ("-C", str(args.repo_path), "push", args.remote, args.candidate),
        context=f"push candidate branch {args.candidate}",
    )
    emit(
        {
            "shadow_base": args.shadow_base,
            "candidate": args.candidate,
            "base_commit": args.base_commit,
            "remote": args.remote,
        }
    )


def command_open_shadow_pr(args: argparse.Namespace) -> None:
    body = read_text_file(args.body_file, context="shadow PR body")
    if CLOSING_KEYWORD_RE.search(body):
        fail(
            "shadow PR body contains a closing keyword (Closes/Fixes/Resolves #N); "
            "a shadow PR must reference its issue with 'Refs #N', never auto-close it"
        )
    if args.shadow_issue is not None:
        if not refs_target_re(args.shadow_issue).search(body):
            fail(
                f"shadow PR body must reference the shadow issue with 'Refs #{args.shadow_issue}'"
            )
    elif not REFS_RE.search(body):
        fail("shadow PR body must reference the shadow issue with 'Refs #<shadow-issue>'")
    base_sha = read_remote_ref_sha(args.remote, args.base, args.repo_path)
    head_sha = read_remote_ref_sha(args.remote, args.head, args.repo_path)
    if base_sha == head_sha:
        fail(
            f"candidate branch {args.head!r} has no commits beyond shadow-base "
            f"{args.base!r}; push the replay implementation before opening the shadow PR"
        )
    head_repository = args.head_repo or args.repo
    head_owner = head_repository.split("/", 1)[0]
    qualified_head = args.head if head_repository == args.repo else f"{head_owner}:{args.head}"
    raw = run_gh(
        (
            "pr",
            "create",
            "--repo",
            args.repo,
            "--draft",
            "--base",
            args.base,
            "--head",
            qualified_head,
            "--title",
            args.title,
            "--body-file",
            str(args.body_file),
        ),
        context=f"create draft shadow PR in {args.repo}",
    ).strip()
    pr_number = parse_issue_or_pr_number(raw)
    run_gh(
        (
            "pr",
            "edit",
            str(pr_number),
            "--repo",
            args.repo,
            "--add-label",
            DO_NOT_MERGE_LABEL,
        ),
        context=f"label shadow PR #{pr_number} do-not-merge",
    )
    violations = check_pr_invariants(
        args.repo,
        pr_number,
        shadow_base=args.base,
        candidate=args.head,
        head_repository=head_repository,
        shadow_issue=args.shadow_issue,
    )
    if violations:
        fail(
            f"shadow PR #{pr_number} failed isolation checks after creation: "
            + "; ".join(violations)
        )
    emit(
        {
            "shadow_pr": pr_number,
            "url": raw,
            "repo": args.repo,
            "head_repository": head_repository,
            "base_sha": base_sha,
            "head_sha": head_sha,
        }
    )


# ------------------------------------------------------- invariant validation


def read_pr_state(repo: str, pr: int) -> dict[str, Any]:
    context = f"shadow pull request #{pr} in {repo}"
    raw = run_gh(
        (
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "isDraft,merged,state,labels,baseRefName,headRefName,headRepository,body",
        ),
        context=context,
    )
    return parse_json_object(raw, context=context)


def refs_target_re(issue: int) -> re.Pattern[str]:
    return re.compile(rf"\bRefs\b\s*#{issue}\b")


def check_pr_invariants(
    repo: str,
    pr: int,
    *,
    shadow_base: str,
    candidate: str,
    head_repository: str,
    shadow_issue: int | None = None,
) -> list[str]:
    value = read_pr_state(repo, pr)
    context = f"shadow pull request #{pr} in {repo}"
    violations: list[str] = []
    if value.get("merged") is True:
        violations.append("PR is merged; a shadow PR must never merge")
    if value.get("isDraft") is not True:
        violations.append("PR is not a draft")
    if str(value.get("state", "")).upper() != "OPEN":
        violations.append(
            f"PR is not OPEN during replay (state={value.get('state')!r})"
        )
    labels = label_names(value.get("labels"), context=context)
    if DO_NOT_MERGE_LABEL not in labels:
        violations.append(f"PR is missing the {DO_NOT_MERGE_LABEL!r} label")
    base_ref = value.get("baseRefName")
    if base_ref != shadow_base:
        violations.append(
            f"PR base is {base_ref!r}, expected the shadow-base branch {shadow_base!r}"
        )
    head_ref = value.get("headRefName")
    if head_ref != candidate:
        violations.append(
            f"PR head is {head_ref!r}, expected the candidate branch {candidate!r}"
        )
    actual_head_repository = value.get("headRepository")
    actual_name = (
        actual_head_repository.get("nameWithOwner")
        if isinstance(actual_head_repository, dict)
        else None
    )
    if actual_name != head_repository:
        violations.append(
            f"PR head repository is {actual_name!r}, expected {head_repository!r}"
        )
    body = value.get("body") or ""
    if CLOSING_KEYWORD_RE.search(body):
        violations.append("PR body contains a closing keyword (Closes/Fixes/Resolves)")
    # Bind the reference to the actual shadow issue, not any incidental "Refs #N".
    if shadow_issue is not None:
        if not refs_target_re(shadow_issue).search(body):
            violations.append(
                f"PR body no longer references the shadow issue with 'Refs #{shadow_issue}'"
            )
    elif not REFS_RE.search(body):
        violations.append("PR body no longer references the shadow issue with 'Refs #N'")
    return violations


def read_remote_ref_sha(remote: str, branch: str, repo_path: Path) -> str:
    context = f"remote ref {branch!r} on {remote!r}"
    raw = run_git(
        ("-C", str(repo_path), "ls-remote", remote, f"refs/heads/{branch}"),
        context=f"read {context}",
    ).strip()
    if not raw:
        fail(f"{context} does not exist; the immutable shadow-base ref is gone")
    return raw.split()[0]


def assert_source_unchanged(
    repo: str,
    source_issue: int,
    source_pr: int,
    merge_sha: str,
    expected_snapshot_sha256: str,
) -> list[str]:
    violations: list[str] = []
    completion_context = f"source issue #{source_issue} in {repo}"
    issue_raw = run_gh(
        (
            "issue",
            "view",
            str(source_issue),
            "--repo",
            repo,
            "--json",
            "state,stateReason,title,body,labels,milestone,assignees,"
            "closedByPullRequestsReferences,comments",
        ),
        context=completion_context,
    )
    issue = parse_json_object(issue_raw, context=completion_context)
    if str(issue.get("state", "")).upper() != "CLOSED":
        violations.append(
            f"source issue #{source_issue} is no longer closed "
            f"(state={issue.get('state')!r})"
        )
    reason = issue.get("stateReason")
    if isinstance(reason, str) and reason and reason.upper() != "COMPLETED":
        violations.append(
            f"source issue #{source_issue} is no longer completed (reason={reason!r})"
        )
    pr_context = f"source pull request #{source_pr} in {repo}"
    pr_raw = run_gh(
        (
            "pr",
            "view",
            str(source_pr),
            "--repo",
            repo,
            "--json",
            "state,merged,mergedAt,mergeCommit,title,body,labels,baseRefName,"
            "headRefName,closingIssuesReferences,headRefOid,comments,reviews",
        ),
        context=pr_context,
    )
    pr = parse_json_object(pr_raw, context=pr_context)
    if pr.get("merged") is not True:
        violations.append(f"source PR #{source_pr} is no longer merged")
    merge_commit = pr.get("mergeCommit")
    current_merge = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    if merge_sha and current_merge != merge_sha:
        violations.append(
            f"source PR #{source_pr} merge commit changed from {merge_sha} to "
            f"{current_merge!r}"
        )
    current_snapshot = source_snapshot_sha256(
        source_issue_snapshot(issue), source_pr_snapshot(pr)
    )
    if current_snapshot != expected_snapshot_sha256:
        violations.append(
            "source issue/PR content changed after preflight "
            f"(snapshot {expected_snapshot_sha256} became {current_snapshot})"
        )
    return violations


def command_validate_invariants(args: argparse.Namespace) -> None:
    source_values = (
        args.source_issue,
        args.source_pr,
        args.source_merge_sha,
        args.source_snapshot_sha256,
    )
    if any(value is not None for value in source_values) and not all(
        value is not None for value in source_values
    ):
        fail(
            "source invariant validation requires --source-issue, --source-pr, "
            "--source-merge-sha, and --source-snapshot-sha256 together"
        )
    violations: list[str] = []
    issue_state = read_issue_isolation(args.repo, args.shadow_issue)
    labels = issue_state["labels"]
    offending = status_labels(labels)
    if offending:
        violations.append(
            f"shadow issue #{args.shadow_issue} carries lifecycle label(s) "
            f"{', '.join(offending)}"
        )
    if SHADOW_LABEL not in labels:
        violations.append(
            f"shadow issue #{args.shadow_issue} is missing required label {SHADOW_LABEL!r}"
        )
    if issue_state["has_milestone"]:
        violations.append(f"shadow issue #{args.shadow_issue} has a milestone")
    if issue_state["state"] != "OPEN":
        violations.append(
            f"shadow issue #{args.shadow_issue} is not OPEN during replay "
            f"(state={issue_state['state']!r})"
        )
    if args.shadow_pr is not None:
        violations.extend(
            check_pr_invariants(
                args.repo,
                args.shadow_pr,
                shadow_base=args.shadow_base,
                candidate=args.candidate,
                head_repository=args.head_repo or args.repo,
                shadow_issue=args.shadow_issue,
            )
        )
    # Bind the shadow-base ref to the immutable historical base (guards a force-push).
    if args.historical_base is not None:
        actual = read_remote_ref_sha(args.remote, args.shadow_base, args.repo_path)
        if actual != args.historical_base:
            violations.append(
                f"remote shadow-base {args.shadow_base!r} points at {actual}, "
                f"expected the immutable historical base {args.historical_base}"
            )
    # Prove the source issue and PR still match their preflight snapshot.
    if args.source_issue is not None and args.source_pr is not None:
        violations.extend(
            assert_source_unchanged(
                args.repo,
                args.source_issue,
                args.source_pr,
                args.source_merge_sha,
                args.source_snapshot_sha256,
            )
        )
    if violations:
        fail(
            f"shadow isolation drift for issue #{args.shadow_issue}"
            + (f" / PR #{args.shadow_pr}" if args.shadow_pr is not None else "")
            + f" in {args.repo}: "
            + "; ".join(violations)
        )
    emit(
        {
            "ok": True,
            "repo": args.repo,
            "shadow_issue": args.shadow_issue,
            "shadow_pr": args.shadow_pr,
        }
    )


# ------------------------------------------------------- review freshness


def command_review_freshness(args: argparse.Namespace) -> None:
    """Guard the verify gate: an approval binds to exactly one candidate head.

    Every fix push advances the candidate head, so an approval whose commit is not the
    current head is stale and its verdict does not carry to the new commits. The skill
    calls this before verification; a stale approval requires a fresh review first.
    """
    if args.review_commit != args.head:
        fail(
            f"stale review: approval targets {args.review_commit} but the current "
            f"candidate head is {args.head}; re-review the new head before verifying"
        )
    emit({"fresh": True, "review_commit": args.review_commit, "head": args.head})


def command_fix_attempt(args: argparse.Namespace) -> None:
    """Reject a fix/review cycle beyond the configured orchestration bound."""
    if args.attempt > args.max_attempts:
        fail(
            f"fix attempt {args.attempt} exceeds max_fix_attempts={args.max_attempts}; "
            "stop with unresolved findings instead of dispatching another fixer"
        )
    emit(
        {
            "allowed": True,
            "attempt": args.attempt,
            "max_attempts": args.max_attempts,
        }
    )


# ------------------------------------------------------------------- cleanup


def command_cleanup(args: argparse.Namespace) -> None:
    state = read_pr_state(args.repo, args.shadow_pr)
    if state.get("merged") is True:
        fail(
            f"refusing cleanup: shadow PR #{args.shadow_pr} in {args.repo} is merged; "
            "a shadow PR must never merge"
        )
    run_gh(
        ("pr", "close", str(args.shadow_pr), "--repo", args.repo),
        context=f"close shadow PR #{args.shadow_pr}",
    )
    reread = read_pr_state(args.repo, args.shadow_pr)
    if reread.get("merged") is True:
        fail(
            f"shadow PR #{args.shadow_pr} in {args.repo} reads as merged after close; "
            "no-merge proof failed"
        )
    if str(reread.get("state", "")).upper() != "CLOSED":
        fail(
            f"shadow PR #{args.shadow_pr} in {args.repo} is not CLOSED after close "
            f"(state={reread.get('state')!r})"
        )
    run_gh(
        (
            "issue",
            "close",
            str(args.shadow_issue),
            "--repo",
            args.repo,
            "--reason",
            "completed",
        ),
        context=f"close shadow issue #{args.shadow_issue}",
    )
    issue_reread = read_issue_isolation(args.repo, args.shadow_issue)
    if issue_reread["state"] != "CLOSED":
        fail(
            f"shadow issue #{args.shadow_issue} in {args.repo} is not CLOSED after close "
            f"(state={issue_reread['state']!r})"
        )
    reason = issue_reread["state_reason"]
    if isinstance(reason, str) and reason and reason.upper() != "COMPLETED":
        fail(
            f"shadow issue #{args.shadow_issue} in {args.repo} closed as {reason!r}, "
            "not completed"
        )
    if args.worktree is not None:
        run_git(
            ("worktree", "remove", str(args.worktree)),
            context=f"remove shadow worktree {args.worktree}",
        )
    emit(
        {
            "ok": True,
            "repo": args.repo,
            "shadow_pr": args.shadow_pr,
            "shadow_issue": args.shadow_issue,
            "merged": False,
            "branches_retained": True,
        }
    )


# ------------------------------------------------------------------- metrics


@dataclass
class ThreadUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_write_tokens: int | None = None
    max_request_input_tokens: int | None = None


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def aggregate_claude_code(records: list[Any]) -> tuple[dict[str, ThreadUsage], ThreadUsage, bool]:
    """Claude Code transcripts emit per-message (incremental) usage; sum within a thread.

    A thread is identified by sessionId plus whether the message is a sidechain
    (subagent) turn. Incremental events are summed - there is no cumulative record to
    pick a single final value from. Claude Code does not expose reasoning tokens.
    """
    threads: dict[str, ThreadUsage] = {}
    unattributed = ThreadUsage(cache_write_tokens=0)
    for record in records:
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        session = record.get("sessionId")
        target = unattributed
        if isinstance(session, str) and session:
            key = f"{session}|{'sidechain' if record.get('isSidechain') else 'main'}"
            target = threads.setdefault(key, ThreadUsage(cache_write_tokens=0))
        target.input_tokens += _int(usage.get("input_tokens"))
        cache_write = _int(usage.get("cache_creation_input_tokens"))
        target.input_tokens += cache_write
        target.cached_input_tokens += _int(usage.get("cache_read_input_tokens"))
        target.output_tokens += _int(usage.get("output_tokens"))
        target.cache_write_tokens = (target.cache_write_tokens or 0) + cache_write
        request_input = (
            _int(usage.get("input_tokens"))
            + cache_write
            + _int(usage.get("cache_read_input_tokens"))
        )
        target.max_request_input_tokens = max(
            target.max_request_input_tokens or 0, request_input
        )
    return threads, unattributed, False


def _codex_token_info(record: Any) -> dict[str, Any] | None:
    """Return a token_count event's `info`, handling both real and direct shapes.

    Real Codex rollouts wrap events: `{"type":"event_msg","payload":{"type":"token_count",
    "info":{...}}}`. A flattened `{"type":"token_count","info":{...}}` shape is also
    accepted so callers can feed already-unwrapped records.
    """
    if not isinstance(record, dict):
        return None
    if record.get("type") == "event_msg":
        payload = record.get("payload")
        if isinstance(payload, dict) and payload.get("type") == "token_count":
            info = payload.get("info")
            return info if isinstance(info, dict) else None
        return None
    if record.get("type") == "token_count":
        info = record.get("info")
        return info if isinstance(info, dict) else None
    return None


def _codex_thread_id(record: Any) -> str | None:
    """Extract a session/thread id from a session-meta record, if present."""
    if not isinstance(record, dict):
        return None
    if record.get("type") in {"session_meta", "SessionMeta"}:
        payload = record.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("id"), str):
            return payload["id"]
        if isinstance(record.get("id"), str):
            return record["id"]
    return None


def aggregate_codex(records: list[Any]) -> tuple[dict[str, ThreadUsage], ThreadUsage, bool]:
    """Codex rollouts emit cumulative token_count events; keep the final one per thread.

    Summing every cumulative event would multiply usage by the number of events, so the
    adapter keeps the LAST cumulative total in the rollout. One rollout file is one thread;
    its session id (from the session-meta record) labels the thread when present, else the
    file is a single unnamed thread. Codex exposes reasoning tokens.
    """
    thread_id: str | None = None
    latest: ThreadUsage | None = None
    max_request_input: int | None = None
    cache_write_total: int | None = None
    reasoning_exposed = False
    for record in records:
        candidate_id = _codex_thread_id(record)
        if candidate_id is not None:
            thread_id = candidate_id
        info = _codex_token_info(record)
        if info is None:
            continue
        totals = info.get("total_token_usage")
        if not isinstance(totals, dict):
            continue
        last = info.get("last_token_usage")
        if isinstance(last, dict):
            request_input = _int(last.get("input_tokens"))
            max_request_input = max(max_request_input or 0, request_input)
        raw_cache_write = totals.get("cache_creation_input_tokens")
        if isinstance(raw_cache_write, (int, float)) and not isinstance(
            raw_cache_write, bool
        ):
            cache_write_total = int(raw_cache_write)
        raw_reasoning = totals.get("reasoning_output_tokens")
        reasoning_exposed = isinstance(raw_reasoning, (int, float)) and not isinstance(
            raw_reasoning, bool
        )
        latest = ThreadUsage(
            input_tokens=_int(totals.get("input_tokens")),
            cached_input_tokens=_int(totals.get("cached_input_tokens")),
            output_tokens=_int(totals.get("output_tokens")),
            reasoning_tokens=_int(raw_reasoning),
            cache_write_tokens=cache_write_total,
            max_request_input_tokens=max_request_input,
        )
    threads: dict[str, ThreadUsage] = {}
    if latest is not None:
        threads[thread_id or "session"] = latest
    return threads, ThreadUsage(cache_write_tokens=0), reasoning_exposed


ADAPTERS = {
    "claude-code": aggregate_claude_code,
    "codex": aggregate_codex,
}


def command_metrics(args: argparse.Namespace) -> None:
    adapter = ADAPTERS[args.harness]
    all_threads: dict[str, ThreadUsage] = {}
    unattributed = ThreadUsage(cache_write_tokens=0)
    reasoning_visibility: list[bool] = []
    for log in args.log:
        raw = read_text_file(log, context=f"{args.harness} session log")
        records = parse_jsonl(raw, context=f"{args.harness} session log {log}")
        threads, log_unattributed, reasoning = adapter(records)
        reasoning_visibility.append(reasoning)
        for key, usage in threads.items():
            all_threads[f"{log}::{key}"] = usage
        unattributed.input_tokens += log_unattributed.input_tokens
        unattributed.cached_input_tokens += log_unattributed.cached_input_tokens
        unattributed.output_tokens += log_unattributed.output_tokens
        unattributed.reasoning_tokens += log_unattributed.reasoning_tokens
        if (
            unattributed.cache_write_tokens is not None
            and log_unattributed.cache_write_tokens is not None
        ):
            unattributed.cache_write_tokens += log_unattributed.cache_write_tokens
        else:
            unattributed.cache_write_tokens = None
        if log_unattributed.max_request_input_tokens is not None:
            unattributed.max_request_input_tokens = max(
                unattributed.max_request_input_tokens or 0,
                log_unattributed.max_request_input_tokens,
            )

    totals = ThreadUsage()
    for usage in all_threads.values():
        totals.input_tokens += usage.input_tokens
        totals.cached_input_tokens += usage.cached_input_tokens
        totals.output_tokens += usage.output_tokens
        totals.reasoning_tokens += usage.reasoning_tokens
    cache_write_values = [
        usage.cache_write_tokens
        for usage in [*all_threads.values(), unattributed]
        if usage.cache_write_tokens is not None
    ]
    cache_write_known = all(
        usage.cache_write_tokens is not None
        for usage in [*all_threads.values(), unattributed]
    )
    max_request_values = [
        usage.max_request_input_tokens
        for usage in [*all_threads.values(), unattributed]
        if usage.max_request_input_tokens is not None
    ]
    unattributed_total = (
        unattributed.input_tokens
        + unattributed.cached_input_tokens
        + unattributed.output_tokens
        + unattributed.reasoning_tokens
    )
    payload: dict[str, Any] = {
        "harness": args.harness,
        "threads": len(all_threads),
        "input_tokens": totals.input_tokens + unattributed.input_tokens,
        "cached_input_tokens": totals.cached_input_tokens + unattributed.cached_input_tokens,
        "output_tokens": totals.output_tokens + unattributed.output_tokens,
        "cache_write_tokens": sum(cache_write_values) if cache_write_known else None,
        "max_request_input_tokens": (
            max(max_request_values) if max_request_values else None
        ),
        "unattributed_tokens": unattributed_total,
    }
    if reasoning_visibility and all(reasoning_visibility):
        payload["reasoning_tokens"] = totals.reasoning_tokens + unattributed.reasoning_tokens
    else:
        payload["reasoning_tokens"] = None
    emit(payload)


# ------------------------------------------------------------------- pricing


def load_pricing_catalog(path: Path) -> dict[str, Any]:
    raw = read_text_file(path, context="pricing catalog")
    catalog = parse_json_object(raw, context=f"pricing catalog {path}")
    prices = catalog.get("prices")
    if not isinstance(prices, list):
        fail(f"pricing catalog {path} field 'prices' must be an array")
    return catalog


def find_price(catalog: dict[str, Any], provider: str, model: str) -> dict[str, Any] | None:
    for entry in catalog["prices"]:
        if (
            isinstance(entry, dict)
            and entry.get("provider") == provider
            and entry.get("model") == model
        ):
            return entry
    return None


def resolve_reasoning_rate(entry: dict[str, Any]) -> float | None:
    treatment = entry.get("reasoning")
    if isinstance(treatment, (int, float)) and not isinstance(treatment, bool):
        return float(treatment)
    if treatment == "output":
        return _rate(entry, "output")
    if treatment == "input":
        return _rate(entry, "input")
    if treatment in {"unpriced", "included_in_output"}:
        return 0.0
    return None


def _rate(entry: dict[str, Any], key: str) -> float | None:
    value = entry.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def command_pricing(args: argparse.Namespace) -> None:
    catalog = load_pricing_catalog(args.catalog)
    entry = find_price(catalog, args.provider, args.model)
    if entry is None:
        emit(
            {
                "cost": UNAVAILABLE,
                "reason": f"no catalog entry for provider {args.provider!r} model {args.model!r}",
                "catalog_version": catalog.get("catalog_version"),
            }
        )
        return
    cache_write_tokens = args.cache_write
    cache_write_rate = _rate(entry, "cache_write")
    if cache_write_rate is not None and cache_write_tokens is None:
        emit(
            {
                "cost": UNAVAILABLE,
                "reason": (
                    f"catalog entry for {args.provider}/{args.model} prices cache writes; "
                    "pass --cache-write with the observed token count (including explicit "
                    "zero when the harness proves no cache writes)"
                ),
                "model": args.model,
                "effective_date": entry.get("effective_date"),
                "source_url": entry.get("source_url"),
            }
        )
        return
    cache_write_tokens = cache_write_tokens or 0

    input_tokens = args.input
    if entry.get("cached_input_is_subset") is True:
        discounted = args.cached_input + cache_write_tokens
        if discounted > input_tokens:
            emit(
                {
                    "cost": UNAVAILABLE,
                    "reason": (
                        "cached-input plus cache-write tokens exceed total input tokens; "
                        "OpenAI usage reports both as subsets of total input"
                    ),
                    "model": args.model,
                    "effective_date": entry.get("effective_date"),
                    "source_url": entry.get("source_url"),
                }
            )
            return
        input_tokens -= discounted

    input_multiplier = 1.0
    output_multiplier = 1.0
    pricing_tier = "base"
    long_context = entry.get("long_context")
    if isinstance(long_context, dict):
        threshold = long_context.get("threshold_input_tokens")
        if not isinstance(threshold, int) or threshold < 0:
            fail(
                "pricing catalog long_context.threshold_input_tokens must be non-negative"
            )
        if args.max_request_input is None:
            emit(
                {
                    "cost": UNAVAILABLE,
                    "reason": (
                        f"catalog entry for {args.provider}/{args.model} changes rates above "
                        f"{threshold} input tokens; pass --max-request-input so the tier is "
                        "explicit"
                    ),
                    "model": args.model,
                    "effective_date": entry.get("effective_date"),
                    "source_url": entry.get("source_url"),
                }
            )
            return
        if args.max_request_input > threshold:
            input_multiplier = float(long_context.get("input_multiplier", 0))
            output_multiplier = float(long_context.get("output_multiplier", 0))
            if input_multiplier <= 0 or output_multiplier <= 0:
                fail("pricing catalog long_context multipliers must be positive")
            pricing_tier = "long_context"

    components = {
        "input": (input_tokens, _rate(entry, "input"), input_multiplier),
        "cached_input": (
            args.cached_input,
            _rate(entry, "cached_input"),
            input_multiplier,
        ),
        "cache_write": (cache_write_tokens, cache_write_rate, input_multiplier),
        "output": (args.output, _rate(entry, "output"), output_multiplier),
        "reasoning": (
            args.reasoning,
            resolve_reasoning_rate(entry),
            output_multiplier,
        ),
    }
    total = 0.0
    for name, (tokens, rate, multiplier) in components.items():
        if tokens <= 0:
            continue
        if rate is None:
            emit(
                {
                    "cost": UNAVAILABLE,
                    "reason": (
                        f"catalog entry for {args.provider}/{args.model} has no {name} "
                        f"rate but {tokens} {name} tokens were reported"
                    ),
                    "model": args.model,
                    "effective_date": entry.get("effective_date"),
                    "source_url": entry.get("source_url"),
                }
            )
            return
        total += tokens * rate * multiplier / 1_000_000
    emit(
        {
            "cost": round(total, 6),
            "currency": entry.get("currency", "USD"),
            "model": args.model,
            "provider": args.provider,
            "effective_date": entry.get("effective_date"),
            "source_url": entry.get("source_url"),
            "catalog_version": catalog.get("catalog_version"),
            "pricing_tier": pricing_tier,
            "max_request_input_tokens": args.max_request_input,
        }
    )


# ------------------------------------------------------------------- compare


def compare_value(bucket: dict[str, Any], key: str) -> str:
    if key not in bucket or bucket[key] is None:
        return UNAVAILABLE
    value = bucket[key]
    if isinstance(value, str):
        return value or UNAVAILABLE
    return str(value)


def compare_measurement(bucket: dict[str, Any], key: str) -> tuple[str, str]:
    raw = bucket.get(key)
    if not isinstance(raw, dict):
        return compare_value(bucket, key), ""
    value = raw.get("value")
    rendered = UNAVAILABLE if value is None or value == "" else str(value)
    evidence = raw.get("evidence")
    return rendered, str(evidence).strip() if evidence is not None else ""


def command_compare(args: argparse.Namespace) -> None:
    original = parse_json_object(
        read_text_file(args.original, context="original evidence"),
        context=f"original evidence {args.original}",
    )
    shadow = parse_json_object(
        read_text_file(args.shadow, context="shadow evidence"),
        context=f"shadow evidence {args.shadow}",
    )
    rows: list[dict[str, str]] = []
    for dimension, _default_evidence in COMPARISON_DIMENSIONS:
        key = dimension.lower().replace(" ", "_").replace("-", "_")
        original_value, original_evidence = compare_measurement(original, key)
        shadow_value, shadow_evidence = compare_measurement(shadow, key)
        evidence_parts = []
        if original_evidence:
            evidence_parts.append(f"Original: {original_evidence}")
        if shadow_evidence:
            evidence_parts.append(f"Shadow: {shadow_evidence}")
        rows.append(
            {
                "dimension": dimension,
                "original": original_value,
                "shadow": shadow_value,
                "evidence": "; ".join(evidence_parts) or UNAVAILABLE,
            }
        )
    emit({"rows": rows})


# -------------------------------------------------------------------- report


# Audit-binding fields a completed report must carry. A report whose final_state names a
# failed stage is exempt (some bindings legitimately never came to exist).
REQUIRED_REPORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("run_id", "run id"),
    ("harness", "harness"),
    ("runtime_version", "runtime version"),
    ("model", "model"),
    ("source_issue_url", "source issue link"),
    ("source_pr_url", "original PR link"),
    ("source_merge_sha", "original PR merge SHA"),
    ("historical_base", "historical base SHA"),
    ("cutoff", "information cutoff"),
    ("shadow_issue_url", "shadow issue link"),
    ("shadow_pr_url", "shadow PR link"),
    ("candidate_head", "reviewed candidate head SHA"),
    ("execution_repository", "execution repository"),
    ("execution_revision", "execution revision"),
    ("rules_loaded", "rules loaded"),
    ("verification", "verification report or evidence link"),
)


def validate_report_schema(data: dict[str, Any]) -> None:
    """A completed report must carry every audit binding; a failure report is exempt."""
    final_state = str(data.get("final_state", ""))
    if final_state.startswith("failed:") and len(final_state) > len("failed:"):
        return
    if final_state != "evaluation-complete":
        fail(
            "completed report final_state must be 'evaluation-complete'; use "
            "'failed:<stage>' for a stopped run"
        )
    missing = [
        label
        for key, label in REQUIRED_REPORT_FIELDS
        if not str(data.get(key) or "").strip()
    ]
    if missing:
        fail(
            "report is missing required audit bindings for a completed evaluation: "
            + ", ".join(missing)
            + " (set final_state to 'failed:<stage>' for an incomplete run)"
        )
    typed_validators = (
        ("source_issue_url", "source issue link", GITHUB_ISSUE_URL_RE),
        ("source_pr_url", "original PR link", GITHUB_PR_URL_RE),
        ("shadow_issue_url", "shadow issue link", GITHUB_ISSUE_URL_RE),
        ("shadow_pr_url", "shadow PR link", GITHUB_PR_URL_RE),
        ("source_merge_sha", "original PR merge SHA", FULL_SHA_RE),
        ("historical_base", "historical base SHA", FULL_SHA_RE),
        ("candidate_head", "reviewed candidate head SHA", FULL_SHA_RE),
        ("execution_revision", "execution revision", FULL_SHA_RE),
    )
    for key, label, pattern in typed_validators:
        value = str(data[key]).strip()
        if not pattern.fullmatch(value):
            fail(f"completed report {label} is malformed: {value!r}")
    rules_loaded = data.get("rules_loaded")
    if isinstance(rules_loaded, list):
        if not rules_loaded or any(not str(item).strip() for item in rules_loaded):
            fail("completed report rules loaded must name paths or use the string 'none'")
    elif not isinstance(rules_loaded, str):
        fail("completed report rules loaded must be a string or an array of paths")
    rows = data.get("comparison")
    if not isinstance(rows, list):
        fail("completed report comparison must be an array with every required row")
    expected = {dimension for dimension, _ in COMPARISON_DIMENSIONS}
    provided: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            fail("completed report comparison rows must be objects")
        dimension = row.get("dimension")
        if not isinstance(dimension, str):
            fail("completed report comparison row dimension must be a string")
        if dimension in provided:
            duplicates.append(dimension)
        provided[dimension] = row
    missing_dimensions = sorted(expected - set(provided))
    unexpected_dimensions = sorted(set(provided) - expected)
    if duplicates or missing_dimensions or unexpected_dimensions:
        problems: list[str] = []
        if missing_dimensions:
            problems.append("missing: " + ", ".join(missing_dimensions))
        if unexpected_dimensions:
            problems.append("unexpected: " + ", ".join(unexpected_dimensions))
        if duplicates:
            problems.append("duplicate: " + ", ".join(sorted(set(duplicates))))
        fail(
            "completed report comparison rows do not match the required schema ("
            + "; ".join(problems)
            + ")"
        )
    for dimension in expected:
        row = provided[dimension]
        for field in ("original", "shadow", "evidence"):
            if not str(row.get(field) or "").strip():
                fail(f"completed report comparison row {dimension!r} has no {field}")
        if str(row["evidence"]).strip().lower() == UNAVAILABLE:
            fail(
                f"completed report comparison row {dimension!r} has no evidence or "
                "missing-data reason"
            )


def render_disclosures(extra: Sequence[str]) -> list[str]:
    disclosures = list(REQUIRED_DISCLOSURES)
    for item in extra:
        if item not in disclosures:
            disclosures.append(item)
    return disclosures


def render_report(data: dict[str, Any]) -> str:
    def value(key: str, default: str = UNAVAILABLE) -> str:
        raw = data.get(key)
        if raw is None or raw == "":
            return default
        return str(raw)

    lines: list[str] = []
    run_id = value("run_id")
    lines.append(f"## dev:shadow evaluation - {run_id}")
    lines.append(f"Run: {run_id}")
    harness = value("harness")
    runtime_version = value("runtime_version")
    lines.append(f"Harness: {harness} {runtime_version}")
    lines.append(f"Model: {value('model')}")
    lines.append(f"Reasoning effort: {value('reasoning_effort')}")
    lines.append(f"Source issue: {value('source_issue_url')}")
    merge_sha = value("source_merge_sha", "")
    source_pr = value("source_pr_url")
    lines.append(
        f"Source PR: {source_pr}" + (f" (merge {merge_sha})" if merge_sha else "")
    )
    lines.append(f"Historical base: {value('historical_base')}")
    lines.append(f"Information cutoff: {value('cutoff')}")
    lines.append(f"Shadow issue: {value('shadow_issue_url')}")
    lines.append(f"Shadow PR: {value('shadow_pr_url')}")
    lines.append(f"Candidate head: {value('candidate_head')}")
    lines.append(f"Execution repository: {value('execution_repository')}")
    lines.append(f"Execution revision: {value('execution_revision')}")
    rules = data.get("rules_loaded")
    rendered_rules = (
        ", ".join(str(item) for item in rules)
        if isinstance(rules, list)
        else value("rules_loaded")
    )
    lines.append(f"Rules loaded: {rendered_rules}")
    lines.append(f"Final state: {value('final_state')}")
    lines.append("")
    lines.append("### Quality and delivery comparison")
    lines.append("")
    lines.append("| Dimension | Original | Shadow | Evidence and limitation |")
    lines.append("|---|---:|---:|---|")
    rows = data.get("comparison")
    if isinstance(rows, list) and rows:
        provided = {
            row.get("dimension"): row for row in rows if isinstance(row, dict)
        }
    else:
        provided = {}
    for dimension, evidence in COMPARISON_DIMENSIONS:
        row = provided.get(dimension, {})
        original = row.get("original", UNAVAILABLE) if isinstance(row, dict) else UNAVAILABLE
        shadow = row.get("shadow", UNAVAILABLE) if isinstance(row, dict) else UNAVAILABLE
        cell_evidence = row.get("evidence", evidence) if isinstance(row, dict) else evidence
        lines.append(f"| {dimension} | {original} | {shadow} | {cell_evidence} |")
    lines.append("")
    lines.append("### Verification evidence")
    lines.append("")
    lines.append(value("verification", "See linked verifier report."))
    lines.append("")
    lines.append("### Limitations")
    lines.append("")
    extra = data.get("disclosures")
    extra_list = [str(item) for item in extra] if isinstance(extra, list) else []
    for disclosure in render_disclosures(extra_list):
        lines.append(f"- {disclosure}")
    return "\n".join(lines) + "\n"


def command_report(args: argparse.Namespace) -> None:
    data = parse_json_object(
        read_text_file(args.data, context="report data"),
        context=f"report data {args.data}",
    )
    validate_report_schema(data)
    report = render_report(data)
    if args.out is None or str(args.out) == "-":
        sys.stdout.write(report)
    else:
        try:
            args.out.write_text(report, encoding="utf-8")
        except OSError as error:
            fail(f"cannot write report to {args.out}: {error}")
        emit({"ok": True, "path": str(args.out)})


# --------------------------------------------------------------------- parser


def repository(value: str) -> str:
    if not REPOSITORY_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("repository must use OWNER/REPO form")
    return value


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic helpers for the dev:shadow historical-replay workflow."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_id = sub.add_parser("run-id", help="Print a collision-resistant run id.")
    run_id.add_argument("--now")
    run_id.add_argument("--suffix")
    run_id.set_defaults(func=command_run_id)

    base = sub.add_parser("historical-base", help="Reconstruct the historical base commit.")
    base.add_argument("--repo", required=True, type=repository)
    base.add_argument("--source-pr", required=True, type=positive_int)
    base.add_argument("--source-head")
    base.add_argument("--repo-path", type=Path, default=Path("."))
    base.add_argument("--no-verify-ancestor", action="store_true")
    base.set_defaults(func=command_historical_base)

    preflight = sub.add_parser("preflight", help="Gate the source issue and PR before replay.")
    preflight.add_argument("--repo", required=True, type=repository)
    preflight.add_argument("--source-issue", required=True, type=positive_int)
    preflight.add_argument("--source-pr", type=positive_int)
    preflight.add_argument("--repo-path", type=Path, default=Path("."))
    preflight.add_argument("--no-verify-ancestor", action="store_true")
    preflight.set_defaults(func=command_preflight)

    create_issue = sub.add_parser(
        "create-shadow-issue", help="Create the isolated [SHADOW] issue."
    )
    create_issue.add_argument("--repo", required=True, type=repository)
    create_issue.add_argument("--title", required=True)
    create_issue.add_argument("--body-file", required=True, type=Path)
    create_issue.set_defaults(func=command_create_shadow_issue)

    branches = sub.add_parser("create-branches", help="Create and push shadow branches.")
    branches.add_argument("--shadow-base", required=True)
    branches.add_argument("--candidate", required=True)
    branches.add_argument("--base-commit", required=True)
    branches.add_argument("--remote", default="origin")
    branches.add_argument("--repo-path", type=Path, default=Path("."))
    branches.set_defaults(func=command_create_branches)

    open_pr = sub.add_parser("open-shadow-pr", help="Open the draft do-not-merge shadow PR.")
    open_pr.add_argument("--repo", required=True, type=repository)
    open_pr.add_argument("--base", required=True)
    open_pr.add_argument("--head", required=True)
    open_pr.add_argument("--head-repo", type=repository)
    open_pr.add_argument("--remote", default="origin")
    open_pr.add_argument("--repo-path", type=Path, default=Path("."))
    open_pr.add_argument("--title", required=True)
    open_pr.add_argument("--body-file", required=True, type=Path)
    open_pr.add_argument("--shadow-issue", type=positive_int)
    open_pr.set_defaults(func=command_open_shadow_pr)

    invariants = sub.add_parser(
        "validate-invariants", help="Re-read and assert shadow isolation."
    )
    invariants.add_argument("--repo", required=True, type=repository)
    invariants.add_argument("--shadow-issue", required=True, type=positive_int)
    invariants.add_argument("--shadow-pr", type=positive_int)
    invariants.add_argument("--shadow-base", required=True)
    invariants.add_argument("--candidate", required=True)
    invariants.add_argument("--head-repo", type=repository)
    invariants.add_argument("--historical-base")
    invariants.add_argument("--remote", default="origin")
    invariants.add_argument("--repo-path", type=Path, default=Path("."))
    invariants.add_argument("--source-issue", type=positive_int)
    invariants.add_argument("--source-pr", type=positive_int)
    invariants.add_argument("--source-merge-sha")
    invariants.add_argument("--source-snapshot-sha256")
    invariants.set_defaults(func=command_validate_invariants)

    freshness = sub.add_parser(
        "review-freshness",
        help="Reject an approval whose commit is not the current candidate head.",
    )
    freshness.add_argument("--review-commit", required=True)
    freshness.add_argument("--head", required=True)
    freshness.set_defaults(func=command_review_freshness)

    attempt = sub.add_parser(
        "fix-attempt",
        help="Reject a fix/review cycle beyond the configured attempt bound.",
    )
    attempt.add_argument("--attempt", required=True, type=positive_int)
    attempt.add_argument("--max-attempts", required=True, type=positive_int)
    attempt.set_defaults(func=command_fix_attempt)

    cleanup = sub.add_parser("cleanup", help="Close the shadow PR unmerged and the issue.")
    cleanup.add_argument("--repo", required=True, type=repository)
    cleanup.add_argument("--shadow-pr", required=True, type=positive_int)
    cleanup.add_argument("--shadow-issue", required=True, type=positive_int)
    cleanup.add_argument("--worktree", type=Path)
    cleanup.set_defaults(func=command_cleanup)

    metrics = sub.add_parser("metrics", help="Aggregate harness token usage.")
    metrics.add_argument("--harness", required=True, choices=sorted(ADAPTERS))
    metrics.add_argument("--log", required=True, action="append", type=Path)
    metrics.set_defaults(func=command_metrics)

    pricing = sub.add_parser("pricing", help="Estimate API-equivalent cost from the catalog.")
    pricing.add_argument("--catalog", type=Path, default=DEFAULT_PRICING_CATALOG)
    pricing.add_argument("--provider", required=True)
    pricing.add_argument("--model", required=True)
    pricing.add_argument("--input", type=non_negative_int, default=0)
    pricing.add_argument("--cached-input", type=non_negative_int, default=0)
    pricing.add_argument("--cache-write", type=non_negative_int)
    pricing.add_argument("--max-request-input", type=non_negative_int)
    pricing.add_argument("--output", type=non_negative_int, default=0)
    pricing.add_argument("--reasoning", type=non_negative_int, default=0)
    pricing.set_defaults(func=command_pricing)

    compare = sub.add_parser("compare", help="Assemble the comparison table rows.")
    compare.add_argument("--original", required=True, type=Path)
    compare.add_argument("--shadow", required=True, type=Path)
    compare.set_defaults(func=command_compare)

    report = sub.add_parser("report", help="Render the Markdown evaluation report.")
    report.add_argument("--data", required=True, type=Path)
    report.add_argument("--out", type=Path)
    report.set_defaults(func=command_report)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except ShadowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
