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
            "state,stateReason,title,closedByPullRequestsReferences",
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
    references = value.get("closedByPullRequestsReferences")
    linked: list[int] = []
    if isinstance(references, list):
        for reference in references:
            if isinstance(reference, dict) and isinstance(reference.get("number"), int):
                linked.append(reference["number"])
    return {"title": value.get("title") or "", "linked_prs": linked}


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
            "state,merged,mergedAt,mergeCommit,closingIssuesReferences,headRefOid",
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
    closing = value.get("closingIssuesReferences")
    bound = False
    if isinstance(closing, list):
        for reference in closing:
            if isinstance(reference, dict) and reference.get("number") == issue:
                bound = True
    merge_commit = value.get("mergeCommit")
    merge_sha = ""
    if isinstance(merge_commit, dict) and isinstance(merge_commit.get("oid"), str):
        merge_sha = merge_commit["oid"]
    return {
        "bound": bound,
        "merge_commit": merge_sha,
        "merged_at": value.get("mergedAt") or "",
        "head": value.get("headRefOid") or "",
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


def read_issue_isolation(repo: str, issue: int) -> tuple[tuple[str, ...], bool]:
    context = f"shadow issue #{issue} in {repo}"
    raw = run_gh(
        (
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--json",
            "labels,milestone,state",
        ),
        context=context,
    )
    value = parse_json_object(raw, context=context)
    labels = label_names(value.get("labels"), context=context)
    milestone = value.get("milestone")
    has_milestone = bool(milestone) if not isinstance(milestone, dict) else bool(
        milestone.get("title") or milestone.get("number")
    )
    return labels, has_milestone


def assert_issue_isolated(repo: str, issue: int) -> None:
    labels, has_milestone = read_issue_isolation(repo, issue)
    offending = status_labels(labels)
    if offending:
        fail(
            f"shadow issue #{issue} in {repo} carries lifecycle label(s) "
            f"{', '.join(offending)}; a shadow issue must have no status:* label"
        )
    if has_milestone:
        fail(
            f"shadow issue #{issue} in {repo} has a milestone; a shadow issue must have none"
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
            args.head,
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
        shadow_issue=args.shadow_issue,
    )
    if violations:
        fail(
            f"shadow PR #{pr_number} failed isolation checks after creation: "
            + "; ".join(violations)
        )
    emit({"shadow_pr": pr_number, "url": raw, "repo": args.repo})


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
            "isDraft,merged,state,labels,baseRefName,headRefName,body",
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
    shadow_issue: int | None = None,
) -> list[str]:
    value = read_pr_state(repo, pr)
    context = f"shadow pull request #{pr} in {repo}"
    violations: list[str] = []
    if value.get("merged") is True:
        violations.append("PR is merged; a shadow PR must never merge")
    if value.get("isDraft") is not True:
        violations.append("PR is not a draft")
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
    repo: str, source_issue: int, source_pr: int, merge_sha: str
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
            "state,stateReason",
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
            "merged,mergeCommit",
        ),
        context=pr_context,
    )
    pr = parse_json_object(pr_raw, context=pr_context)
    if pr.get("merged") is not True:
        violations.append(f"source PR #{source_pr} is no longer merged")
    merge_commit = pr.get("mergeCommit")
    current_merge = (
        merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    )
    if merge_sha and current_merge != merge_sha:
        violations.append(
            f"source PR #{source_pr} merge commit changed from {merge_sha} to "
            f"{current_merge!r}"
        )
    return violations


def command_validate_invariants(args: argparse.Namespace) -> None:
    violations: list[str] = []
    labels, has_milestone = read_issue_isolation(args.repo, args.shadow_issue)
    offending = status_labels(labels)
    if offending:
        violations.append(
            f"shadow issue #{args.shadow_issue} carries lifecycle label(s) "
            f"{', '.join(offending)}"
        )
    if has_milestone:
        violations.append(f"shadow issue #{args.shadow_issue} has a milestone")
    violations.extend(
        check_pr_invariants(
            args.repo,
            args.shadow_pr,
            shadow_base=args.shadow_base,
            candidate=args.candidate,
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
                args.source_merge_sha or "",
            )
        )
    if violations:
        fail(
            f"shadow isolation drift for issue #{args.shadow_issue} / PR "
            f"#{args.shadow_pr} in {args.repo}: " + "; ".join(violations)
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


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def aggregate_claude_code(records: list[Any]) -> tuple[dict[str, ThreadUsage], ThreadUsage, bool]:
    """Claude Code transcripts emit per-message (incremental) usage; sum within a thread.

    A thread is identified by sessionId plus whether the message is a sidechain
    (subagent) turn. Incremental events are summed - there is no cumulative record to
    pick a single final value from. Claude Code does not expose reasoning tokens.
    """
    threads: dict[str, ThreadUsage] = {}
    unattributed = ThreadUsage()
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
            target = threads.setdefault(key, ThreadUsage())
        target.input_tokens += _int(usage.get("input_tokens"))
        target.input_tokens += _int(usage.get("cache_creation_input_tokens"))
        target.cached_input_tokens += _int(usage.get("cache_read_input_tokens"))
        target.output_tokens += _int(usage.get("output_tokens"))
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
        latest = ThreadUsage(
            input_tokens=_int(totals.get("input_tokens")),
            cached_input_tokens=_int(totals.get("cached_input_tokens")),
            output_tokens=_int(totals.get("output_tokens")),
            reasoning_tokens=_int(totals.get("reasoning_output_tokens")),
        )
    threads: dict[str, ThreadUsage] = {}
    if latest is not None:
        threads[thread_id or "session"] = latest
    return threads, ThreadUsage(), True


ADAPTERS = {
    "claude-code": aggregate_claude_code,
    "codex": aggregate_codex,
}


def command_metrics(args: argparse.Namespace) -> None:
    adapter = ADAPTERS[args.harness]
    all_threads: dict[str, ThreadUsage] = {}
    unattributed = ThreadUsage()
    exposes_reasoning = False
    for log in args.log:
        raw = read_text_file(log, context=f"{args.harness} session log")
        records = parse_jsonl(raw, context=f"{args.harness} session log {log}")
        threads, log_unattributed, reasoning = adapter(records)
        exposes_reasoning = exposes_reasoning or reasoning
        for key, usage in threads.items():
            all_threads[f"{log}::{key}"] = usage
        unattributed.input_tokens += log_unattributed.input_tokens
        unattributed.cached_input_tokens += log_unattributed.cached_input_tokens
        unattributed.output_tokens += log_unattributed.output_tokens
        unattributed.reasoning_tokens += log_unattributed.reasoning_tokens

    totals = ThreadUsage()
    for usage in all_threads.values():
        totals.input_tokens += usage.input_tokens
        totals.cached_input_tokens += usage.cached_input_tokens
        totals.output_tokens += usage.output_tokens
        totals.reasoning_tokens += usage.reasoning_tokens
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
        "unattributed_tokens": unattributed_total,
    }
    if exposes_reasoning:
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
    if treatment == "unpriced":
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
    components = {
        "input": (args.input, _rate(entry, "input")),
        "cached_input": (args.cached_input, _rate(entry, "cached_input")),
        "output": (args.output, _rate(entry, "output")),
        "reasoning": (args.reasoning, resolve_reasoning_rate(entry)),
    }
    total = 0.0
    for name, (tokens, rate) in components.items():
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
        total += tokens * rate / 1_000_000
    emit(
        {
            "cost": round(total, 6),
            "currency": entry.get("currency", "USD"),
            "model": args.model,
            "provider": args.provider,
            "effective_date": entry.get("effective_date"),
            "source_url": entry.get("source_url"),
            "catalog_version": catalog.get("catalog_version"),
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
    for dimension, evidence in COMPARISON_DIMENSIONS:
        key = dimension.lower().replace(" ", "_").replace("-", "_")
        rows.append(
            {
                "dimension": dimension,
                "original": compare_value(original, key),
                "shadow": compare_value(shadow, key),
                "evidence": evidence,
            }
        )
    emit({"rows": rows})


# -------------------------------------------------------------------- report


# Audit-binding fields a completed report must carry. A report whose final_state names a
# failed stage is exempt (some bindings legitimately never came to exist).
REQUIRED_REPORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("run_id", "run id"),
    ("harness", "harness and version"),
    ("model", "model"),
    ("source_issue_url", "source issue link"),
    ("source_pr_url", "original PR link"),
    ("source_merge_sha", "original PR merge SHA"),
    ("historical_base", "historical base SHA"),
    ("cutoff", "information cutoff"),
    ("shadow_issue_url", "shadow issue link"),
    ("shadow_pr_url", "shadow PR link"),
    ("candidate_head", "reviewed candidate head SHA"),
    ("verification", "verification report or evidence link"),
)


def validate_report_schema(data: dict[str, Any]) -> None:
    """A completed report must carry every audit binding; a failure report is exempt."""
    final_state = str(data.get("final_state", ""))
    if final_state.startswith("failed"):
        return
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
    lines.append(f"Harness: {value('harness')}")
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
    open_pr.add_argument("--title", required=True)
    open_pr.add_argument("--body-file", required=True, type=Path)
    open_pr.add_argument("--shadow-issue", type=positive_int)
    open_pr.set_defaults(func=command_open_shadow_pr)

    invariants = sub.add_parser(
        "validate-invariants", help="Re-read and assert shadow isolation."
    )
    invariants.add_argument("--repo", required=True, type=repository)
    invariants.add_argument("--shadow-issue", required=True, type=positive_int)
    invariants.add_argument("--shadow-pr", required=True, type=positive_int)
    invariants.add_argument("--shadow-base", required=True)
    invariants.add_argument("--candidate", required=True)
    invariants.add_argument("--historical-base")
    invariants.add_argument("--remote", default="origin")
    invariants.add_argument("--repo-path", type=Path, default=Path("."))
    invariants.add_argument("--source-issue", type=positive_int)
    invariants.add_argument("--source-pr", type=positive_int)
    invariants.add_argument("--source-merge-sha")
    invariants.set_defaults(func=command_validate_invariants)

    freshness = sub.add_parser(
        "review-freshness",
        help="Reject an approval whose commit is not the current candidate head.",
    )
    freshness.add_argument("--review-commit", required=True)
    freshness.add_argument("--head", required=True)
    freshness.set_defaults(func=command_review_freshness)

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
