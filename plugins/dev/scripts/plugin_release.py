#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Publish immutable plugin version tags and GitHub Releases for an exact tag.

Two operations share one validation core:

`tag`     compares each plugin's three synchronized version fields between a push
          event's before and head commits and creates one immutable lightweight tag
          per plugin whose version strictly increased.
`release` creates the GitHub Release for one existing tag, using release notes read
          from CHANGELOG.md at the tagged commit.

No code path deletes, moves, force-updates, or recreates a tag or a release.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Sequence


REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
TAG_RE = re.compile(r"^(?P<plugin>[a-z0-9]+(?:-[a-z0-9]+)*)-v(?P<version>\d+\.\d+\.\d+)$")
ZERO_SHA = "0" * 40
CLAUDE_MARKETPLACE = ".claude-plugin/marketplace.json"
CHANGELOG = "CHANGELOG.md"
REACHABLE_STATUSES = {"identical", "ahead"}


class ReleaseError(RuntimeError):
    """A tag or release precondition failed."""


@dataclass(frozen=True)
class PluginVersions:
    """The three lockstep version fields of one plugin at one commit."""

    marketplace: str | None
    claude: str | None
    codex: str | None

    def values(self) -> tuple[str | None, str | None, str | None]:
        return (self.marketplace, self.claude, self.codex)

    def present(self) -> tuple[str, ...]:
        return tuple(value for value in self.values() if value is not None)

    def synchronized(self) -> str | None:
        values = self.values()
        if None in values or len(set(values)) != 1:
            return None
        return values[0]

    def describe(self) -> str:
        return (
            f"marketplace={self.marketplace or 'absent'}, "
            f"Claude={self.claude or 'absent'}, "
            f"Codex={self.codex or 'absent'}"
        )


@dataclass(frozen=True)
class TagPlan:
    """One plugin's decided outcome for a push event."""

    plugin: str
    tag: str | None
    version: str | None
    previous_version: str | None
    action: str


def fail(message: str) -> NoReturn:
    raise ReleaseError(message)


def run(
    command: Sequence[str],
    *,
    accepted_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
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


def run_git(checkout: Path, arguments: Sequence[str]) -> str:
    return run(("git", "-C", str(checkout), *arguments)).stdout


def run_gh(arguments: Sequence[str]) -> str:
    return run(("gh", *arguments)).stdout


def parse_json_object(raw: str, context: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        fail(f"{context} returned invalid JSON: {error.msg}")
    if not isinstance(value, dict):
        fail(f"{context} returned {type(value).__name__}, expected an object")
    return value


def parse_semver(value: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def resolve_commit(checkout: Path, revision: str) -> str:
    result = run(
        ("git", "-C", str(checkout), "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"),
        accepted_returncodes=(0, 1),
    )
    if result.returncode != 0:
        fail(f"commit {revision!r} is not present in {checkout}")
    return result.stdout.strip()


def read_blob(checkout: Path, commit: str, path: str) -> str | None:
    result = run(
        ("git", "-C", str(checkout), "show", f"{commit}:{path}"),
        accepted_returncodes=(0, 128),
    )
    if result.returncode != 0:
        return None
    return result.stdout


def plugin_names_at(checkout: Path, commit: str) -> tuple[str, ...]:
    result = run(
        ("git", "-C", str(checkout), "ls-tree", "--name-only", commit, "plugins/"),
        accepted_returncodes=(0, 128),
    )
    if result.returncode != 0:
        return ()
    names = []
    for line in result.stdout.splitlines():
        entry = line.strip().rstrip("/")
        if entry.startswith("plugins/"):
            names.append(entry.removeprefix("plugins/"))
    return tuple(sorted(names))


def marketplace_version(text: str | None, plugin: str, commit: str) -> str | None:
    if text is None:
        return None
    value = parse_json_object(text, f"{CLAUDE_MARKETPLACE} at {commit}")
    entries = value.get("plugins")
    if not isinstance(entries, list):
        fail(f"{CLAUDE_MARKETPLACE} at {commit}: field 'plugins' must be an array")
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == plugin:
            version = entry.get("version")
            if version is None:
                return None
            if not isinstance(version, str):
                fail(
                    f"{CLAUDE_MARKETPLACE} at {commit}: plugin {plugin!r} "
                    "field 'version' must be a string"
                )
            return version
    return None


def manifest_version(text: str | None, path: str, commit: str) -> str | None:
    if text is None:
        return None
    value = parse_json_object(text, f"{path} at {commit}")
    version = value.get("version")
    if version is None:
        return None
    if not isinstance(version, str):
        fail(f"{path} at {commit}: field 'version' must be a string")
    return version


def plugin_versions(checkout: Path, commit: str, plugin: str) -> PluginVersions:
    claude_path = f"plugins/{plugin}/.claude-plugin/plugin.json"
    codex_path = f"plugins/{plugin}/.codex-plugin/plugin.json"
    return PluginVersions(
        marketplace=marketplace_version(
            read_blob(checkout, commit, CLAUDE_MARKETPLACE), plugin, commit
        ),
        claude=manifest_version(read_blob(checkout, commit, claude_path), claude_path, commit),
        codex=manifest_version(read_blob(checkout, commit, codex_path), codex_path, commit),
    )


def changelog_section(checkout: Path, commit: str, tag: str) -> str | None:
    """Return the body of the exact `## <tag>` release section at `commit`."""
    text = read_blob(checkout, commit, CHANGELOG)
    if text is None:
        return None
    heading = f"## {tag}"
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    try:
        start = lines.index(heading)
    except ValueError:
        return None
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip()


def require_release_heading(checkout: Path, commit: str, tag: str) -> str:
    section = changelog_section(checkout, commit, tag)
    if section is None:
        fail(
            f"{CHANGELOG} at {commit} has no exact release heading '## {tag}'; "
            "add the changelog entry before the tag is created"
        )
    if not section:
        fail(f"{CHANGELOG} at {commit} has an empty '## {tag}' release section")
    return section


def remote_tag_commit(repo: str, tag: str) -> str | None:
    """Return the commit a remote tag points at, or None when the tag does not exist."""
    result = run(
        ("gh", "api", f"repos/{repo}/git/ref/tags/{tag}"),
        accepted_returncodes=(0, 1),
    )
    if result.returncode != 0:
        stderr = result.stderr.lower()
        if "not found" in stderr or "http 404" in stderr:
            return None
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        fail(f"cannot read tag {tag!r} in {repo}: {detail}")
    value = parse_json_object(result.stdout, f"tag {tag!r} in {repo}")
    obj = value.get("object")
    if not isinstance(obj, dict):
        fail(f"tag {tag!r} in {repo}: field 'object' must be an object")
    sha = obj.get("sha")
    if not isinstance(sha, str) or not sha:
        fail(f"tag {tag!r} in {repo}: field 'object.sha' must be a non-empty string")
    return sha


def create_tag(repo: str, tag: str, commit: str) -> None:
    """Create one lightweight tag. GitHub rejects the POST when the ref already exists."""
    run_gh(
        (
            "api",
            "--method",
            "POST",
            f"repos/{repo}/git/refs",
            "-f",
            f"ref=refs/tags/{tag}",
            "-f",
            f"sha={commit}",
        )
    )
    published = remote_tag_commit(repo, tag)
    if published != commit:
        fail(
            f"tag verification failed for {tag!r}: GitHub reports "
            f"{published or 'no tag'}, expected {commit}"
        )


def build_tag_plan(
    checkout: Path,
    before: str,
    head: str,
) -> tuple[TagPlan, ...]:
    plans: list[TagPlan] = []
    for plugin in plugin_names_at(checkout, head):
        head_versions = plugin_versions(checkout, head, plugin)
        if not head_versions.present():
            continue
        before_versions = plugin_versions(checkout, before, plugin)
        if before_versions.values() == head_versions.values():
            plans.append(TagPlan(plugin, None, None, None, "unchanged"))
            continue

        new_version = head_versions.synchronized()
        if new_version is None:
            fail(
                f"plugin {plugin!r} changed version fields that are not in lockstep at "
                f"{head}: {head_versions.describe()}"
            )
        new_parsed = parse_semver(new_version)
        if new_parsed is None:
            fail(f"plugin {plugin!r} version {new_version!r} at {head} is not semver")

        previous_values = before_versions.present()
        previous_version: str | None = None
        if previous_values:
            parsed_previous = []
            for value in previous_values:
                parsed = parse_semver(value)
                if parsed is None:
                    fail(
                        f"plugin {plugin!r} version {value!r} at {before} is not semver; "
                        "cannot decide whether the version increased"
                    )
                parsed_previous.append((parsed, value))
            highest_parsed, previous_version = max(parsed_previous)
            if new_parsed < highest_parsed:
                fail(
                    f"plugin {plugin!r} version regressed from {previous_version} to "
                    f"{new_version}; a release version must never decrease"
                )
            if new_parsed == highest_parsed:
                plans.append(
                    TagPlan(plugin, None, new_version, previous_version, "unchanged")
                )
                continue

        tag = f"{plugin}-v{new_version}"
        require_release_heading(checkout, head, tag)
        plans.append(TagPlan(plugin, tag, new_version, previous_version, "create"))
    return tuple(plans)


def publish_tags(
    repo: str,
    head: str,
    plans: Sequence[TagPlan],
) -> list[dict[str, Any]]:
    pending: list[TagPlan] = []
    results: list[dict[str, Any]] = []
    for plan in plans:
        if plan.action != "create" or plan.tag is None:
            results.append(
                {
                    "plugin": plan.plugin,
                    "tag": None,
                    "version": plan.version,
                    "previous_version": plan.previous_version,
                    "action": "unchanged",
                }
            )
            continue
        existing = remote_tag_commit(repo, plan.tag)
        if existing is None:
            pending.append(plan)
            continue
        if existing != head:
            fail(
                f"tag {plan.tag!r} already exists at {existing}, expected {head}; "
                "a published tag is immutable and is never moved or replaced"
            )
        results.append(
            {
                "plugin": plan.plugin,
                "tag": plan.tag,
                "version": plan.version,
                "previous_version": plan.previous_version,
                "action": "already-tagged",
            }
        )

    for plan in pending:
        assert plan.tag is not None
        create_tag(repo, plan.tag, head)
        results.append(
            {
                "plugin": plan.plugin,
                "tag": plan.tag,
                "version": plan.version,
                "previous_version": plan.previous_version,
                "action": "created",
            }
        )
    results.sort(key=lambda entry: entry["plugin"])
    return results


def execute_tag(arguments: argparse.Namespace) -> dict[str, Any]:
    checkout = arguments.checkout.resolve()
    head = resolve_commit(checkout, arguments.head)
    if arguments.before == ZERO_SHA:
        return {
            "operation": "tag",
            "repository": arguments.repo,
            "head": head,
            "before": None,
            "skipped": "no baseline commit in the push event; no tag was created",
            "tags": [],
        }
    before = resolve_commit(checkout, arguments.before)
    plans = build_tag_plan(checkout, before, head)
    return {
        "operation": "tag",
        "repository": arguments.repo,
        "head": head,
        "before": before,
        "tags": publish_tags(arguments.repo, head, plans),
    }


def known_plugins(checkout: Path) -> tuple[str, ...]:
    directory = checkout / "plugins"
    if not directory.is_dir():
        fail(f"{checkout} has no plugins/ directory")
    return tuple(sorted(entry.name for entry in directory.iterdir() if entry.is_dir()))


def parse_tag(tag: str, checkout: Path) -> tuple[str, str]:
    plugins = known_plugins(checkout)
    match = TAG_RE.fullmatch(tag)
    if match is None or match.group("plugin") not in plugins:
        expected = " or ".join(f"{name}-vX.Y.Z" for name in plugins)
        fail(f"tag {tag!r} must be exactly {expected}")
    version = match.group("version")
    if parse_semver(version) is None:
        fail(f"tag {tag!r} does not carry a semver version")
    return match.group("plugin"), version


def ensure_commit_local(checkout: Path, remote: str, tag: str, commit: str) -> None:
    result = run(
        ("git", "-C", str(checkout), "cat-file", "-e", f"{commit}^{{commit}}"),
        accepted_returncodes=(0, 1, 128),
    )
    if result.returncode == 0:
        return
    run_git(checkout, ("fetch", remote, f"refs/tags/{tag}"))
    resolve_commit(checkout, commit)


def require_reachable_from_main(repo: str, commit: str, tag: str) -> None:
    status = run_gh(("api", f"repos/{repo}/compare/{commit}...main", "--jq", ".status")).strip()
    if status not in REACHABLE_STATUSES:
        fail(
            f"tag {tag!r} commit {commit} is not reachable from {repo} main "
            f"(compare status {status!r}); only merged commits are released"
        )


def read_release(repo: str, tag: str) -> dict[str, Any] | None:
    result = run(
        (
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repo,
            "--json",
            "tagName,name,isDraft,isPrerelease,url,body",
        ),
        accepted_returncodes=(0, 1),
    )
    if result.returncode != 0:
        stderr = result.stderr.lower()
        if "not found" in stderr or "release not found" in stderr:
            return None
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        fail(f"cannot read release {tag!r} in {repo}: {detail}")
    return parse_json_object(result.stdout, f"release {tag!r} in {repo}")


def verify_release(
    release: dict[str, Any],
    tag: str,
    expected_name: str,
    repo: str,
) -> dict[str, Any]:
    context = f"release {tag!r} in {repo}"
    tag_name = release.get("tagName")
    if tag_name != tag:
        fail(f"{context} points at tag {tag_name!r}, expected {tag!r}")
    name = release.get("name")
    if name != expected_name:
        fail(f"{context} is named {name!r}, expected {expected_name!r}")
    if release.get("isDraft") is not False:
        fail(f"{context} is a draft; a published release is never a draft")
    if release.get("isPrerelease") is not False:
        fail(f"{context} is a prerelease; a plugin release is never a prerelease")
    body = release.get("body")
    if not isinstance(body, str) or not body.strip():
        fail(f"{context} has empty release notes")
    url = release.get("url")
    if not isinstance(url, str) or not url:
        fail(f"{context} has no URL")
    return {"name": name, "notes_length": len(body), "tag": tag, "url": url}


def create_release(repo: str, tag: str, title: str, notes: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        notes_path = Path(directory) / "notes.md"
        notes_path.write_text(notes + "\n", encoding="utf-8")
        run_gh(
            (
                "release",
                "create",
                tag,
                "--repo",
                repo,
                "--title",
                title,
                "--notes-file",
                str(notes_path),
                "--verify-tag",
            )
        )


def execute_release(arguments: argparse.Namespace) -> dict[str, Any]:
    checkout = arguments.checkout.resolve()
    plugin, version = parse_tag(arguments.tag, checkout)
    expected_name = f"{plugin} plugin v{version}"

    commit = remote_tag_commit(arguments.repo, arguments.tag)
    if commit is None:
        fail(
            f"tag {arguments.tag!r} does not exist in {arguments.repo}; "
            "the tag is created by the push-to-main workflow before its release"
        )
    require_reachable_from_main(arguments.repo, commit, arguments.tag)
    ensure_commit_local(checkout, arguments.remote, arguments.tag, commit)

    versions = plugin_versions(checkout, commit, plugin)
    synchronized = versions.synchronized()
    if synchronized != version:
        fail(
            f"plugin {plugin!r} version fields at {commit} are {versions.describe()}, "
            f"expected all three to equal {version}"
        )
    notes = require_release_heading(checkout, commit, arguments.tag)

    existing = read_release(arguments.repo, arguments.tag)
    if existing is not None:
        receipt = verify_release(existing, arguments.tag, expected_name, arguments.repo)
        return {
            "operation": "release",
            "repository": arguments.repo,
            "plugin": plugin,
            "version": version,
            "commit": commit,
            "action": "already-published",
            "release": receipt,
        }

    if not arguments.confirm:
        fail(
            f"creating the public release for {arguments.tag} requires explicit human "
            "authorization; rerun with --confirm once the maintainer approves"
        )
    create_release(arguments.repo, arguments.tag, expected_name, notes)
    published = read_release(arguments.repo, arguments.tag)
    if published is None:
        fail(
            f"release verification failed: GitHub reports no release for "
            f"{arguments.tag!r} after creating it"
        )
    receipt = verify_release(published, arguments.tag, expected_name, arguments.repo)
    return {
        "operation": "release",
        "repository": arguments.repo,
        "plugin": plugin,
        "version": version,
        "commit": commit,
        "action": "created",
        "release": receipt,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish immutable plugin version tags and the GitHub Release for an exact tag."
        )
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    tag_parser = subparsers.add_parser(
        "tag", help="create version tags for plugins whose version increased"
    )
    tag_parser.add_argument("--repo", required=True, help="canonical OWNER/REPO")
    tag_parser.add_argument("--before", required=True, help="push event before commit")
    tag_parser.add_argument("--head", required=True, help="push event head commit")
    tag_parser.add_argument(
        "--checkout",
        type=Path,
        default=Path.cwd(),
        help="repository checkout containing both commits (default: current directory)",
    )

    release_parser = subparsers.add_parser(
        "release", help="create the GitHub Release for one existing tag"
    )
    release_parser.add_argument("--repo", required=True, help="canonical OWNER/REPO")
    release_parser.add_argument("--tag", required=True, help="exact existing tag")
    release_parser.add_argument(
        "--checkout",
        type=Path,
        default=Path.cwd(),
        help="repository checkout used to read the tagged commit (default: current directory)",
    )
    release_parser.add_argument(
        "--remote",
        default="origin",
        help="git remote used to fetch the tagged commit when absent (default: origin)",
    )
    release_parser.add_argument(
        "--confirm",
        action="store_true",
        help="authorize creating the public GitHub Release",
    )
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if not REPOSITORY_RE.fullmatch(arguments.repo):
        parser.error("--repo must use OWNER/REPO form")
    if arguments.operation == "tag":
        for field in ("before", "head"):
            value = getattr(arguments, field)
            if not FULL_SHA_RE.fullmatch(value):
                parser.error(f"--{field} must be a full 40-character commit SHA")
    try:
        if arguments.operation == "tag":
            result = execute_tag(arguments)
        elif arguments.operation == "release":
            result = execute_release(arguments)
        else:
            fail(f"unsupported operation: {arguments.operation!r}")
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
