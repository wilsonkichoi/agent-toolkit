#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Deterministic redaction and draft helpers for the dev:feedback skill.

Subcommands:
  redact    Strip secrets, private paths, and private repo references from text.
  draft     Render a complete issue body from structured JSON input.
  search    Search for duplicate issues in the target repository.

The redact pass is conservative: it removes anything that looks like a secret or private
path rather than risk leaking sensitive data. False positives are acceptable; false
negatives are not.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, Sequence


TARGET_REPO = "wilsonkichoi/agent-toolkit"

CATEGORY_LABELS = {
    "bug": "bug",
    "enhancement": "enhancement",
    "docs": "documentation",
    "workflow": "enhancement",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password|credential|auth)[=:]\s*\S+"),
    re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-proj-[A-Za-z0-9\-_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"xoxb-[A-Za-z0-9\-]+"),
    re.compile(r"xoxp-[A-Za-z0-9\-]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"[a-z+]+://[^\s:]+:[^\s@]+@[^\s]+"),
]

HOME_PATH_RE = re.compile(r"/(?:Users|home)/[A-Za-z0-9_.\-]+/")


def redact_secrets(text: str) -> str:
    """Replace secret-like patterns with <REDACTED>."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("<REDACTED>", text)
    return text


def redact_home_paths(text: str) -> str:
    """Replace /Users/<name>/ or /home/<name>/ with ~/."""
    return HOME_PATH_RE.sub("~/", text)


def redact_private_repos(text: str, public_repos: set[str] | None = None) -> str:
    """Replace repository references that are not in the public set.

    A 'repository reference' here is owner/repo appearing in a GitHub URL or as a
    standalone owner/repo token. The target repo is always considered public.
    """
    if public_repos is None:
        public_repos = set()
    public_repos = public_repos | {TARGET_REPO}

    def _replace_url(match: re.Match[str]) -> str:
        repo = match.group(1)
        if repo in public_repos:
            return match.group(0)
        return match.group(0).replace(repo, "<private-repo>")

    github_url_re = re.compile(
        r"https://github\.com/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)"
    )
    text = github_url_re.sub(_replace_url, text)
    return text


def redact_text(
    text: str, public_repos: set[str] | None = None
) -> str:
    """Apply all redaction passes in order."""
    text = redact_secrets(text)
    text = redact_home_paths(text)
    text = redact_private_repos(text, public_repos)
    return text


def render_draft(
    title: str,
    category: str,
    objective: str,
    why: str,
    definition_of_done: str,
    references: str = "",
    implementation: str = "",
) -> dict[str, str]:
    """Render a complete issue draft from structured fields.

    Returns a dict with 'title', 'label', 'body', and 'command' keys.
    """
    label = CATEGORY_LABELS.get(category, "enhancement")
    sections = [
        f"## Objective\n\n{objective}",
        f"## Why\n\n{why}",
        f"## Definition of Done\n\n{definition_of_done}",
    ]
    if references:
        sections.append(f"## Relevant references\n\n{references}")
    else:
        sections.append("## Relevant references\n\nNone")
    if implementation:
        sections.append(f"## Suggested implementation\n\n{implementation}")

    body = "\n\n".join(sections)

    command = (
        f"gh issue create --repo {TARGET_REPO}"
        f" --title '{_shell_escape(title)}'"
        f" --label '{label}'"
        f" --body-file <draft-file>"
    )

    return {
        "title": title,
        "label": label,
        "body": body,
        "command": command,
    }


class SearchError(RuntimeError):
    """Raised when duplicate search cannot complete reliably."""


def search_duplicates(keywords: list[str]) -> list[dict[str, Any]]:
    """Search for duplicate issues in the target repository.

    Returns a list of candidate matches with number, title, state, and url.
    Requires `gh` CLI to be authenticated.

    Raises SearchError if gh is unavailable or every query fails (rate limit,
    auth error, timeout), so callers cannot mistake a failed search for
    "no duplicates found".
    """
    results: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    errors: list[str] = []
    successes = 0

    for state in ("open", "closed"):
        for query in keywords:
            try:
                proc = subprocess.run(
                    [
                        "gh", "search", "issues",
                        "--repo", TARGET_REPO,
                        "--state", state,
                        "--limit", "5",
                        "--json", "number,title,state,url",
                        query,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                errors.append(f"timeout: state={state} query={query!r}")
                continue
            except FileNotFoundError:
                raise SearchError("gh binary not found")

            if proc.returncode != 0:
                errors.append(
                    f"gh exit {proc.returncode}: state={state} query={query!r}: "
                    f"{proc.stderr.strip()}"
                )
                continue

            output = proc.stdout.strip()
            if not output:
                successes += 1
                continue

            try:
                items = json.loads(output)
            except json.JSONDecodeError as exc:
                errors.append(
                    f"JSON parse error: state={state} query={query!r}: {exc}"
                )
                continue

            successes += 1
            for item in items:
                num = item.get("number")
                if num and num not in seen_numbers:
                    seen_numbers.add(num)
                    results.append(item)

    if successes == 0:
        raise SearchError(
            f"All duplicate searches failed ({len(errors)} errors): "
            + "; ".join(errors[:5])
        )

    return results


def check_gh_access() -> dict[str, Any]:
    """Check whether gh is authenticated and has write access to the target repo.

    Returns a dict with 'authenticated' (bool), 'has_write' (bool), and
    'permission' (str or None).
    """
    try:
        auth_result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        authenticated = auth_result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"authenticated": False, "has_write": False, "permission": None}

    if not authenticated:
        return {"authenticated": False, "has_write": False, "permission": None}

    try:
        perm_output = subprocess.run(
            [
                "gh", "repo", "view", TARGET_REPO,
                "--json", "viewerPermission",
                "--jq", ".viewerPermission",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"authenticated": True, "has_write": False, "permission": None}

    write_permissions = {"ADMIN", "MAINTAIN", "WRITE"}
    has_write = perm_output in write_permissions

    return {
        "authenticated": authenticated,
        "has_write": has_write,
        "permission": perm_output or None,
    }


def _shell_escape(text: str) -> str:
    """Escape text for safe embedding in single-quoted shell strings."""
    return text.replace("'", "'\\''")



def die(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def cmd_redact(args: argparse.Namespace) -> None:
    """Subcommand: redact text from stdin or --text."""
    if args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    public = set(args.public_repo) if args.public_repo else None
    result = redact_text(text, public)
    print(result, end="")


def cmd_draft(args: argparse.Namespace) -> None:
    """Subcommand: render a draft from JSON input."""
    if args.input:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        data = json.loads(sys.stdin.read())

    required = ("title", "category", "objective", "why", "definition_of_done")
    for field in required:
        if field not in data:
            die(f"missing required field: {field}")

    draft = render_draft(
        title=data["title"],
        category=data["category"],
        objective=data["objective"],
        why=data["why"],
        definition_of_done=data["definition_of_done"],
        references=data.get("references", ""),
        implementation=data.get("implementation", ""),
    )
    print(json.dumps(draft, indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    """Subcommand: search for duplicates."""
    try:
        results = search_duplicates(args.keywords)
    except SearchError as exc:
        die(str(exc))
    print(json.dumps(results, indent=2))


def cmd_access(args: argparse.Namespace) -> None:
    """Subcommand: check GitHub access."""
    result = check_gh_access()
    print(json.dumps(result, indent=2))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Feedback redaction and drafting helpers."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    redact_parser = subparsers.add_parser("redact", help="Redact sensitive content.")
    redact_parser.add_argument("--text", help="Text to redact (default: stdin).")
    redact_parser.add_argument(
        "--public-repo",
        action="append",
        default=[],
        help="Repository known to be public (repeatable).",
    )

    draft_parser = subparsers.add_parser("draft", help="Render issue draft from JSON.")
    draft_parser.add_argument(
        "--input", help="JSON file path (default: stdin)."
    )

    search_parser = subparsers.add_parser("search", help="Search for duplicates.")
    search_parser.add_argument("keywords", nargs="+", help="Search keywords.")

    subparsers.add_parser("access", help="Check GitHub write access.")

    parsed = parser.parse_args(argv)
    if parsed.command == "redact":
        cmd_redact(parsed)
    elif parsed.command == "draft":
        cmd_draft(parsed)
    elif parsed.command == "search":
        cmd_search(parsed)
    elif parsed.command == "access":
        cmd_access(parsed)


if __name__ == "__main__":
    main()
