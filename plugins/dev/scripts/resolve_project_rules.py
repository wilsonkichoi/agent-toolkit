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


def resolve_rule_files(
    config: Path,
    config_text: str,
    execution_repo: Path,
    rules_dir: Path,
) -> tuple[Path, ...]:
    roots = rules_section_imports(config_text)
    resolved: list[Path] = []
    visited: set[Path] = set()
    active: list[Path] = []

    def visit(path: Path) -> None:
        if path in active:
            cycle = " -> ".join(
                relative_to_repo(item, execution_repo) for item in (*active, path)
            )
            raise ResolutionError(f"rule import cycle: {cycle}")
        if path in visited:
            return
        try:
            path.relative_to(rules_dir)
        except ValueError as error:
            raise ResolutionError(
                f"rule import is outside configured rules_dir: {relative_to_repo(path, execution_repo)}"
            ) from error
        text = read_text(path)
        imports = all_imports(text)
        active.append(path)
        if imports:
            if scalar(frontmatter(text), "tier"):
                raise ResolutionError(
                    f"rule index cannot also declare tier: {relative_to_repo(path, execution_repo)}"
                )
            for reference in imports:
                visit(resolve_project_path(reference, path, execution_repo))
        else:
            resolved.append(path)
        active.pop()
        visited.add(path)

    for reference in roots:
        visit(resolve_project_path(reference, config, execution_repo))
    return tuple(resolved)


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
    terminal_rules = resolve_rule_files(config, config_text, execution_repo, rules_dir)
    loaded: list[RuleResult] = []
    skipped: list[RuleResult] = []
    for rule_path in terminal_rules:
        rule_text = read_text(rule_path)
        metadata_match = FRONTMATTER_RE.match(rule_text)
        relative_rule = relative_to_repo(rule_path, execution_repo)
        if metadata_match is None and rule_text.startswith("---\n"):
            raise ResolutionError(f"invalid rule frontmatter: {relative_rule}")
        metadata = metadata_match.group("body") if metadata_match else ""
        declared_tier = scalar(metadata, "tier")
        if metadata_match is not None and declared_tier is None:
            raise ResolutionError(
                f"terminal rule frontmatter must declare tier: {relative_rule}"
            )
        tier = declared_tier or "doctrine"
        if tier == "doctrine":
            reason = "tier:doctrine" if declared_tier else "legacy-default:doctrine"
            loaded.append(RuleResult(relative_rule, tier, (reason,)))
            continue
        if tier != "gotcha":
            raise ResolutionError(f"invalid rule tier {tier!r}: {relative_rule}")
        triggers = trigger_metadata(metadata)
        if not any(triggers.values()):
            raise ResolutionError(f"gotcha rule has no triggers: {relative_rule}")
        matches = gotcha_matches(triggers, objective, definition_of_done, changed_paths)
        result = RuleResult(relative_rule, tier, matches)
        (loaded if matches else skipped).append(result)

    return Resolution(
        tracker_repository=str(tracker_repo),
        execution_repository=str(execution_repo),
        execution_revision=resolved_execution_revision,
        project_instructions=instruction_paths,
        rules_loaded=tuple(loaded),
        rules_skipped=tuple(skipped),
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
