#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Resolve the project instructions and rules for one dev lifecycle invocation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from functools import cache
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath


CONFIG_PATHS = (
    Path(".agent-toolkit/dev.md"),
    Path(".agent/dev.md"),
    Path(".claude/dev.md"),
)
IMPORT_RE = re.compile(r"^\s*@(?P<path>\S+)\s*$")
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---(?:\n|\Z)", re.DOTALL)
TRIGGER_NAMES = ("paths", "objective", "definition_of_done")
HARNESS_AUTOLOAD_DIRS = (Path(".claude/rules"), Path.home() / ".claude/rules")
UNCLASSIFIED_REMEDY = (
    "Remedy per file: declare `tier: doctrine`, or `tier: gotcha` with at least one "
    "trigger, to load it as a rule; or declare `tier: none` to mark it a non-rule that "
    "stays in place."
)


class ResolutionError(ValueError):
    """The project bootstrap contract is malformed or cannot be resolved."""


@dataclass(frozen=True)
class RuleResult:
    path: str
    tier: str
    matched_by: tuple[str, ...]


@dataclass(frozen=True)
class Resolution:
    tracker_repository: str
    execution_repository: str
    execution_revision: str
    project_instructions: tuple[str, ...]
    rules_loaded: tuple[RuleResult, ...]
    rules_skipped: tuple[RuleResult, ...]
    rules_excluded: tuple[RuleResult, ...]
    warnings: tuple[str, ...]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracker-repo", required=True, type=Path)
    parser.add_argument("--execution-repo", required=True, type=Path)
    parser.add_argument("--execution-revision", required=True)
    parser.add_argument("--objective", default="")
    parser.add_argument("--definition-of-done", default="")
    parser.add_argument("--changed-path", action="append", default=[])
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def read_text(path: Path) -> str:
    try:
        return (
            path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        )
    except FileNotFoundError as error:
        raise ResolutionError(f"required file is missing: {path}") from error
    except UnicodeError as error:
        raise ResolutionError(f"file is not valid UTF-8: {path}: {error}") from error


def frontmatter(text: str) -> str:
    match = FRONTMATTER_RE.match(text)
    return match.group("body") if match else ""


def clean_scalar(value: str) -> str:
    value = value.strip()
    quoted = re.fullmatch(r"(['\"])(.*?)\1(?:\s+#.*)?", value)
    if quoted:
        return quoted.group(2)
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def scalar(metadata: str, name: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.*?)\s*$", metadata)
    if not match:
        return None
    value = clean_scalar(match.group(1))
    return value or None


def find_config(execution_repo: Path) -> Path:
    for relative_path in CONFIG_PATHS:
        candidate = execution_repo / relative_path
        if candidate.is_file():
            return candidate
    choices = ", ".join(path.as_posix() for path in CONFIG_PATHS)
    raise ResolutionError(
        f"execution repository has no dev configuration; checked {choices}"
    )


def git_commit(execution_repo: Path, revision: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(execution_repo),
            "rev-parse",
            "--verify",
            f"{revision}^{{commit}}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ResolutionError(
            f"cannot resolve execution revision {revision!r} in {execution_repo}: {detail}"
        )
    return result.stdout.strip()


def validate_execution_revision(execution_repo: Path, expected_revision: str) -> str:
    expected_commit = git_commit(execution_repo, expected_revision)
    head_commit = git_commit(execution_repo, "HEAD")
    if head_commit != expected_commit:
        raise ResolutionError(
            "execution repository HEAD "
            f"{head_commit} does not match expected execution revision {expected_commit}"
            "; this is a hard stop. Check out the expected revision "
            f"(git worktree add --detach <path> {expected_commit}) and rerun. "
            "Never substitute another revision, including a merge commit whose tree "
            "looks identical."
        )
    return head_commit


def relative_to_repo(path: Path, execution_repo: Path) -> str:
    try:
        return path.relative_to(execution_repo).as_posix()
    except ValueError as error:
        raise ResolutionError(
            f"resolved path escapes execution repository: {path}"
        ) from error


def resolve_project_path(reference: str, source: Path, execution_repo: Path) -> Path:
    reference_path = Path(reference)
    if reference_path.is_absolute():
        raise ResolutionError(f"absolute import is not allowed: @{reference}")
    if reference.startswith(("./", "../")):
        candidate = source.parent / reference_path
    else:
        candidate = execution_repo / reference_path
    resolved = candidate.resolve()
    relative_to_repo(resolved, execution_repo)
    return resolved


def rules_section_imports(config_text: str) -> tuple[str, ...]:
    in_rules = False
    imports: list[str] = []
    for line in config_text.splitlines():
        if line.strip() == "## Rules":
            in_rules = True
            continue
        if in_rules and line.startswith("## "):
            break
        if not in_rules:
            continue
        match = IMPORT_RE.match(line)
        if match:
            imports.append(match.group("path"))
    return tuple(imports)


def all_imports(text: str) -> tuple[str, ...]:
    return tuple(
        match.group("path")
        for line in text.splitlines()
        if (match := IMPORT_RE.match(line))
    )


def trigger_metadata(metadata: str) -> dict[str, tuple[str, ...]]:
    triggers = {name: [] for name in TRIGGER_NAMES}
    lines = metadata.splitlines()
    try:
        trigger_index = next(
            index for index, line in enumerate(lines) if line.rstrip() == "triggers:"
        )
    except StopIteration:
        return {name: () for name in TRIGGER_NAMES}

    current: str | None = None
    for line in lines[trigger_index + 1 :]:
        if line and not line.startswith((" ", "\t")):
            break
        key_match = re.match(r"^\s{2}([a-z_]+):\s*$", line)
        if key_match:
            key = key_match.group(1)
            current = key if key in triggers else None
            continue
        item_match = re.match(r"^\s{4}-\s+(.+?)\s*$", line)
        if item_match and current:
            value = clean_scalar(item_match.group(1))
            if value:
                triggers[current].append(value)
    return {name: tuple(values) for name, values in triggers.items()}


def path_matches(path: str, pattern: str) -> bool:
    normalized_path = path.removeprefix("./")
    normalized_pattern = pattern.removeprefix("./")
    path_parts = PurePosixPath(normalized_path).parts
    pattern_parts = PurePosixPath(normalized_pattern).parts
    if "/" not in normalized_pattern:
        return bool(path_parts) and fnmatchcase(path_parts[-1], normalized_pattern)

    @cache
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        pattern_part = pattern_parts[pattern_index]
        if pattern_part == "**":
            return match(path_index, pattern_index + 1) or (
                path_index < len(path_parts)
                and match(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatchcase(path_parts[path_index], pattern_part)
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def gotcha_matches(
    triggers: dict[str, tuple[str, ...]],
    objective: str,
    definition_of_done: str,
    changed_paths: tuple[str, ...],
) -> tuple[str, ...]:
    matches: list[str] = []
    for pattern in triggers["paths"]:
        for changed_path in changed_paths:
            if path_matches(changed_path, pattern):
                matches.append(f"path:{changed_path} matches {pattern}")
    objective_folded = objective.casefold()
    for term in triggers["objective"]:
        if term.casefold() in objective_folded:
            matches.append(f"objective:{term}")
    dod_folded = definition_of_done.casefold()
    for term in triggers["definition_of_done"]:
        if term.casefold() in dod_folded:
            matches.append(f"definition_of_done:{term}")
    return tuple(dict.fromkeys(matches))


def discover_rule_files(execution_repo: Path, rules_dir: Path) -> tuple[Path, ...]:
    """Enumerate every Markdown file under rules_dir, deepest paths included.

    Discovery, not registration, is what makes a rule file reachable: a file that exists
    on disk can never be silently absent from resolution. A symlink whose target leaves
    the execution repository is a hard stop, which carries forward the path-escape
    guarantee the retired import graph enforced on each edge.
    """
    if not rules_dir.is_dir():
        return ()
    discovered: list[Path] = []
    visited_directories: set[Path] = set()

    def walk(directory: Path) -> None:
        resolved_directory = directory.resolve()
        if resolved_directory in visited_directories:
            return
        visited_directories.add(resolved_directory)
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink():
                relative_to_repo(entry.resolve(), execution_repo)
            if entry.is_dir():
                walk(entry)
            elif entry.is_file() and entry.suffix == ".md":
                discovered.append(entry)

    walk(rules_dir)
    return tuple(
        sorted(discovered, key=lambda path: relative_to_repo(path, execution_repo))
    )


def classify_rule(rule_text: str) -> tuple[str | None, str, str]:
    """Return the declared tier, why an unclassified file failed, and its metadata.

    Anything that is not an explicit `doctrine`, a `gotcha` carrying a trigger, or `none`
    is unclassified; silence is never read as consent.
    """
    metadata_match = FRONTMATTER_RE.match(rule_text)
    if metadata_match is None:
        reason = (
            "malformed frontmatter" if rule_text.startswith("---\n") else "no frontmatter"
        )
        return None, reason, ""
    metadata = metadata_match.group("body")
    declared_tier = scalar(metadata, "tier")
    if declared_tier is None:
        return None, "frontmatter does not declare tier", metadata
    if declared_tier in ("doctrine", "none"):
        return declared_tier, "", metadata
    if declared_tier != "gotcha":
        return None, f"unknown tier {declared_tier!r}", metadata
    if not any(trigger_metadata(metadata).values()):
        return None, "tier: gotcha declares no trigger", metadata
    return declared_tier, "", metadata


def harness_autoload_warning(execution_repo: Path, rules_dir: Path) -> str | None:
    relative_rules_dir = relative_to_repo(rules_dir, execution_repo)
    for autoload_dir in HARNESS_AUTOLOAD_DIRS:
        candidate = (
            execution_repo / autoload_dir if not autoload_dir.is_absolute()
            else autoload_dir
        )
        if rules_dir == candidate or candidate in rules_dir.parents:
            return (
                f"rules_dir {relative_rules_dir} is inside the harness native auto-load "
                f"path {autoload_dir.as_posix()}; a harness loads those files at session "
                "start regardless of tier, so gotcha rules reported under 'Rules skipped:' "
                "and files marked 'tier: none' may still be in context. Over-inclusion is "
                "reported, never a stop; move rules_dir to .agent-toolkit/rules/ to get "
                "parity."
            )
    return None


def resolve(
    tracker_repo: Path,
    execution_repo: Path,
    execution_revision: str,
    objective: str,
    definition_of_done: str,
    changed_paths: tuple[str, ...],
) -> Resolution:
    tracker_repo = tracker_repo.resolve()
    execution_repo = execution_repo.resolve()
    if not tracker_repo.is_dir():
        raise ResolutionError(f"tracker repository is not a directory: {tracker_repo}")
    if not execution_repo.is_dir():
        raise ResolutionError(
            f"execution repository is not a directory: {execution_repo}"
        )
    resolved_execution_revision = validate_execution_revision(
        execution_repo, execution_revision
    )

    config = find_config(execution_repo)
    config_text = read_text(config)
    config_metadata = frontmatter(config_text)
    rules_dir_value = scalar(config_metadata, "rules_dir")
    context_value = scalar(config_metadata, "context_file")
    legacy_unconfigured = (
        config.relative_to(execution_repo) != CONFIG_PATHS[0]
        and rules_dir_value is None
        and context_value is None
    )
    if rules_dir_value is None:
        rules_dir_value = (
            ".claude/rules/" if legacy_unconfigured else ".agent-toolkit/rules/"
        )
    rules_dir = resolve_project_path(rules_dir_value, config, execution_repo)
    if context_value:
        context_file = resolve_project_path(context_value, config, execution_repo)
        read_text(context_file)
    else:
        candidates = (
            (execution_repo / "CLAUDE.md", execution_repo / "AGENTS.md")
            if legacy_unconfigured
            else (execution_repo / "AGENTS.md", execution_repo / "CLAUDE.md")
        )
        context_file = next((path for path in candidates if path.is_file()), None)
        if context_file is None:
            raise ResolutionError(
                "execution repository has no project instructions; checked "
                + ", ".join(relative_to_repo(path, execution_repo) for path in candidates)
            )

    instruction_paths = tuple(
        relative_to_repo(path, execution_repo)
        for path in (context_file, config)
        if path is not None
    )
    discovered_rules = discover_rule_files(execution_repo, rules_dir)
    loaded: list[RuleResult] = []
    skipped: list[RuleResult] = []
    excluded: list[RuleResult] = []
    unclassified: list[str] = []
    with_imports: list[str] = []
    classified: list[tuple[str, str, str]] = []

    for rule_path in discovered_rules:
        relative_rule = relative_to_repo(rule_path, execution_repo)
        rule_text = read_text(rule_path)
        if all_imports(rule_text):
            with_imports.append(relative_rule)
            continue
        tier, reason, metadata = classify_rule(rule_text)
        if tier is None:
            unclassified.append(f"{relative_rule} ({reason})")
        else:
            classified.append((relative_rule, tier, metadata))

    if with_imports:
        raise ResolutionError(
            "rule file contains an `@` import line; rule files are terminal under "
            "discovery, so an import cannot be resolved and its target would load "
            f"unclassified: {', '.join(with_imports)}. Remedy per file: inline the "
            "imported content, or split it into its own tiered file under rules_dir."
        )
    if unclassified:
        raise ResolutionError(
            "rules_dir contains unclassified Markdown; discovery loads every Markdown "
            "file under rules_dir, so an unclassified file is a hard stop rather than a "
            f"silently dropped rule: {', '.join(unclassified)}. {UNCLASSIFIED_REMEDY}"
        )

    for relative_rule, tier, metadata in classified:
        if tier == "none":
            excluded.append(RuleResult(relative_rule, tier, ("tier:none",)))
        elif tier == "doctrine":
            loaded.append(RuleResult(relative_rule, tier, ("tier:doctrine",)))
        else:
            matches = gotcha_matches(
                trigger_metadata(metadata), objective, definition_of_done, changed_paths
            )
            result = RuleResult(relative_rule, tier, matches)
            (loaded if matches else skipped).append(result)

    warnings: list[str] = []
    autoload_warning = harness_autoload_warning(execution_repo, rules_dir)
    if autoload_warning:
        warnings.append(autoload_warning)
    leftover_imports = rules_section_imports(config_text)
    if leftover_imports:
        warnings.append(
            f"{relative_to_repo(config, execution_repo)} still carries "
            f"{len(leftover_imports)} `@` import line(s) under `## Rules`: "
            f"{', '.join(leftover_imports)}. Discovery ignores them, but a harness that "
            "expands imports still loads those files unconditionally, defeating gotcha "
            "triggers. Run dev:setup to remove them."
        )

    return Resolution(
        tracker_repository=str(tracker_repo),
        execution_repository=str(execution_repo),
        execution_revision=resolved_execution_revision,
        project_instructions=instruction_paths,
        rules_loaded=tuple(loaded),
        rules_skipped=tuple(skipped),
        rules_excluded=tuple(excluded),
        warnings=tuple(warnings),
    )


def render_text(result: Resolution) -> str:
    lines = [
        f"Tracker repository: {result.tracker_repository}",
        f"Execution repository: {result.execution_repository}",
        f"Execution revision: {result.execution_revision}",
        "Project instructions:",
    ]
    lines.extend(f"- {path}" for path in result.project_instructions)
    lines.append("Rules loaded:")
    lines.extend(
        f"- {rule.path} [{rule.tier}; {', '.join(rule.matched_by)}]"
        for rule in result.rules_loaded
    )
    if not result.rules_loaded:
        lines.append("- none")
    lines.append("Rules skipped:")
    lines.extend(
        f"- {rule.path} [{rule.tier}; no trigger matched]"
        for rule in result.rules_skipped
    )
    if not result.rules_skipped:
        lines.append("- none")
    lines.append("Rules excluded:")
    lines.extend(f"- {rule.path} [tier:none]" for rule in result.rules_excluded)
    if not result.rules_excluded:
        lines.append("- none")
    lines.append("Warnings:")
    lines.extend(f"- {warning}" for warning in result.warnings)
    if not result.warnings:
        lines.append("- none")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = resolve(
            args.tracker_repo,
            args.execution_repo,
            args.execution_revision,
            args.objective,
            args.definition_of_done,
            tuple(args.changed_path),
        )
    except (OSError, ResolutionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(asdict(result), indent=2))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
