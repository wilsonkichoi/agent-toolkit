#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Migrate a project from the retired `## Rules` registry to rule discovery.

Reports by default; `--apply` writes. Idempotent: a migrated project reports no changes.
The migration never guesses whether an unregistered file is a rule - it hands those back
as decisions for a human.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Classification, discovery, and config resolution live in the resolver. Import them rather
# than restating them here: two copies of the rule-classification logic drifting apart is
# the exact failure mode discovery was adopted to remove.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from resolve_project_rules import (  # noqa: E402
    CONFIG_PATHS,
    FRONTMATTER_RE,
    ResolutionError,
    classify_rule,
    discover_rule_files,
    find_config,
    frontmatter,
    read_text,
    relative_to_repo,
    resolve_project_path,
    scalar,
)

# `<` and `>` are excluded so a placeholder like `@<rules_dir>/<slug>.md` in the section's
# maintainer comment is never reported as a real registry entry.
REGISTRY_ENTRY_RE = re.compile(r"@(?P<path>[^\s`'\"()\[\]<>]+\.md)")
RULES_HEADING = "## Rules"
RULES_SECTION_BODY = (
    "<!-- Rule files are discovered under `rules_dir`; this section is not a registry.\n"
    "     Add a rule by writing `<rules_dir>/<slug>.md` with `tier` frontmatter -\n"
    "     see runtime_contracts/project-bootstrap.md. -->"
)
STAMPED_REASON = "registered in the retired `## Rules` section"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the migration; omit to report the plan without touching files",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def split_rules_section(config_text: str) -> tuple[str, str, str] | None:
    """Return the text before `## Rules`, the section body, and the text after it."""
    lines = config_text.splitlines(keepends=True)
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() == RULES_HEADING
        ),
        None,
    )
    if start is None:
        return None
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    return "".join(lines[: start + 1]), "".join(lines[start + 1 : end]), "".join(
        lines[end:]
    )


def registry_entries(section_body: str) -> tuple[str, ...]:
    """Every `@<path>.md` reference in the section, bare or wrapped in prose.

    Pre-0.0.56 registries used backticked, descriptive list items that the resolver's
    whole-line import pattern never matched, so those rules were invisible to both the
    resolver and the harness. They are still registry entries and still migrate.
    """
    return tuple(
        dict.fromkeys(match.group("path") for match in REGISTRY_ENTRY_RE.finditer(section_body))
    )


def stamped_text(rule_text: str, reason: str) -> str | None:
    """Add `tier: doctrine` to a file the registry already declared a rule.

    Returns None when the file cannot be stamped without interpreting its content -
    malformed frontmatter, a tier the resolver does not know, a trigger-free gotcha, or an
    `@` import line. Those go back to the human.
    """
    if reason == "no frontmatter":
        return f"---\ntier: doctrine\n---\n\n{rule_text.lstrip()}"
    if reason == "frontmatter does not declare tier":
        match = FRONTMATTER_RE.match(rule_text)
        if match is None:
            return None
        block = f"---\ntier: doctrine\n{match.group('body')}\n---"
        if rule_text[: match.end()].endswith("\n"):
            block += "\n"
        return block + rule_text[match.end() :]
    return None


def resolve_rules_dir(repo: Path, config: Path, config_text: str) -> Path:
    metadata = frontmatter(config_text)
    rules_dir_value = scalar(metadata, "rules_dir")
    if rules_dir_value is None:
        legacy_unconfigured = (
            config.relative_to(repo) != CONFIG_PATHS[0]
            and scalar(metadata, "context_file") is None
        )
        rules_dir_value = (
            ".claude/rules/" if legacy_unconfigured else ".agent-toolkit/rules/"
        )
    return resolve_project_path(rules_dir_value, config, repo)


def plan_migration(repo: Path, apply: bool) -> dict[str, object]:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ResolutionError(f"repository is not a directory: {repo}")
    config = find_config(repo)
    config_text = read_text(config)
    rules_dir = resolve_rules_dir(repo, config, config_text)

    sections = split_rules_section(config_text)
    entries: tuple[str, ...] = ()
    new_config_text = config_text
    if sections is not None:
        before, body, after = sections
        entries = registry_entries(body)
        # ADR 0001 migration case 3: a project with no registry entries gets no action,
        # so a config that never registered anything is never rewritten.
        if entries:
            new_config_text = f"{before}\n{RULES_SECTION_BODY}\n"
            if after:
                new_config_text += "\n" + after

    registered: set[Path] = set()
    for entry in entries:
        try:
            registered.add(resolve_project_path(entry, config, repo))
        except ResolutionError:
            # A registry entry pointing outside the repository is stale text, not a rule
            # file to migrate. Removing the section drops it either way.
            continue

    stamped: list[dict[str, str]] = []
    decisions: list[dict[str, str]] = []
    unchanged: list[str] = []
    writes: list[tuple[Path, str]] = []

    for rule_path in discover_rule_files(repo, rules_dir):
        relative_rule = relative_to_repo(rule_path, repo)
        rule_text = read_text(rule_path)
        tier, reason, _ = classify_rule(rule_text)
        if tier is not None:
            unchanged.append(relative_rule)
            continue
        replacement = (
            stamped_text(rule_text, reason) if rule_path in registered else None
        )
        if replacement is None:
            decisions.append({"path": relative_rule, "reason": reason})
            continue
        stamped.append(
            {"path": relative_rule, "tier": "doctrine", "reason": STAMPED_REASON}
        )
        writes.append((rule_path, replacement))

    config_changed = new_config_text != config_text
    if apply:
        for path, text in writes:
            path.write_text(text, encoding="utf-8")
        if config_changed:
            config.write_text(new_config_text, encoding="utf-8")

    return {
        "repository": str(repo),
        "config": relative_to_repo(config, repo),
        "rules_dir": relative_to_repo(rules_dir, repo),
        "applied": apply,
        "registry_entries_removed": list(entries),
        "config_section_rewritten": config_changed,
        "files_stamped": stamped,
        "decisions_required": decisions,
        "files_unchanged": unchanged,
        "changed": bool(config_changed or stamped),
    }


def render_text(plan: dict[str, object]) -> str:
    verb = "Applied" if plan["applied"] else "Planned (dry run; pass --apply to write)"
    lines = [
        f"{verb} rule-discovery migration",
        f"Repository: {plan['repository']}",
        f"Configuration: {plan['config']}",
        f"rules_dir: {plan['rules_dir']}",
        "Registry entries removed:",
    ]
    entries = plan["registry_entries_removed"]
    lines.extend(f"- @{entry}" for entry in entries)
    if not entries:
        lines.append("- none")
    lines.append(
        "Configuration `## Rules` section rewritten: "
        f"{'yes' if plan['config_section_rewritten'] else 'no'}"
    )
    lines.append("Files stamped `tier: doctrine`:")
    stamped = plan["files_stamped"]
    lines.extend(f"- {item['path']} ({item['reason']})" for item in stamped)
    if not stamped:
        lines.append("- none")
    lines.append("Decisions required (never guessed):")
    decisions = plan["decisions_required"]
    lines.extend(
        f"- {item['path']} ({item['reason']}) - declare a tier to keep it as a rule, "
        "`tier: none` to keep it in place as a non-rule, or move it out of rules_dir"
        for item in decisions
    )
    if not decisions:
        lines.append("- none")
    lines.append("Files already classified (untouched):")
    lines.extend(f"- {path}" for path in plan["files_unchanged"])
    if not plan["files_unchanged"]:
        lines.append("- none")
    if not plan["changed"] and not decisions:
        lines.append("Nothing to migrate; this project already uses rule discovery.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        plan = plan_migration(args.repo, args.apply)
    except (OSError, ResolutionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(plan, indent=2))
    else:
        print(render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
