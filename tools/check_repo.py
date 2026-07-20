#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Validate the repository's deterministic authoring invariants."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import generate_codex_agents as generator


ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MARKETPLACE = ROOT / ".claude-plugin/marketplace.json"
CODEX_MARKETPLACE = ROOT / ".agents/plugins/marketplace.json"
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class CheckFailure(ValueError):
    """A named repository check failed."""


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def fail(path: Path, message: str) -> CheckFailure:
    return CheckFailure(f"{relative(path)}: {message}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise fail(path, "required JSON manifest is missing") from error
    except UnicodeError as error:
        raise fail(path, f"JSON manifest is not valid UTF-8: {error}") from error
    except json.JSONDecodeError as error:
        raise fail(
            path,
            f"invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}",
        ) from error
    if not isinstance(value, dict):
        raise fail(path, "JSON manifest root must be an object")
    return value


def require_object(container: dict[str, Any], field: str, path: Path) -> dict[str, Any]:
    value = container.get(field)
    if not isinstance(value, dict):
        raise fail(path, f"field {field!r} must be an object")
    return value


def require_list(container: dict[str, Any], field: str, path: Path) -> list[Any]:
    value = container.get(field)
    if not isinstance(value, list):
        raise fail(path, f"field {field!r} must be an array")
    return value


def require_string(container: dict[str, Any], field: str, path: Path) -> str:
    value = container.get(field)
    if not isinstance(value, str) or not value:
        raise fail(path, f"field {field!r} must be a non-empty string")
    return value


def require_semver(value: str, path: Path, field: str) -> None:
    if not SEMVER_RE.fullmatch(value):
        raise fail(
            path, f"field {field!r} must be semver major.minor.patch, got {value!r}"
        )


def unique_plugin_entries(entries: list[Any], path: Path) -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise fail(path, f"plugins[{index}] must be an object")
        name = require_string(entry, "name", path)
        if name in by_name:
            raise fail(path, f"duplicate plugin name {name!r}")
        by_name[name] = entry
    return by_name


def validate_claude_marketplace() -> dict[str, dict[str, Any]]:
    path = CLAUDE_MARKETPLACE
    manifest = load_json(path)
    require_string(manifest, "name", path)
    metadata = require_object(manifest, "metadata", path)
    require_string(metadata, "description", path)
    catalog_version = require_string(metadata, "version", path)
    require_semver(catalog_version, path, "metadata.version")
    require_string(require_object(manifest, "owner", path), "name", path)
    entries = unique_plugin_entries(require_list(manifest, "plugins", path), path)
    for name, entry in entries.items():
        expected_source = f"./plugins/{name}"
        source = require_string(entry, "source", path)
        if source != expected_source or not (ROOT / source).is_dir():
            raise fail(
                path,
                f"plugin {name!r} source must be existing path {expected_source!r}, got {source!r}",
            )
        require_string(entry, "category", path)
        require_string(entry, "description", path)
        version = require_string(entry, "version", path)
        require_semver(version, path, f"plugins[{name}].version")
        keywords = require_list(entry, "keywords", path)
        if not keywords or any(
            not isinstance(keyword, str) or not keyword for keyword in keywords
        ):
            raise fail(
                path,
                f"plugin {name!r} field 'keywords' must be a non-empty array of strings",
            )
    return entries


def validate_codex_marketplace() -> dict[str, dict[str, Any]]:
    path = CODEX_MARKETPLACE
    manifest = load_json(path)
    require_string(manifest, "name", path)
    require_string(require_object(manifest, "interface", path), "displayName", path)
    entries = unique_plugin_entries(require_list(manifest, "plugins", path), path)
    for name, entry in entries.items():
        source = require_object(entry, "source", path)
        if require_string(source, "source", path) != "local":
            raise fail(path, f"plugin {name!r} source.source must equal 'local'")
        expected_path = f"./plugins/{name}"
        source_path = require_string(source, "path", path)
        if source_path != expected_path or not (ROOT / source_path).is_dir():
            raise fail(
                path,
                f"plugin {name!r} source.path must be existing path {expected_path!r}, got {source_path!r}",
            )
        installation = require_string(
            require_object(entry, "policy", path), "installation", path
        )
        if installation != "AVAILABLE":
            raise fail(
                path, f"plugin {name!r} policy.installation must equal 'AVAILABLE'"
            )
        require_string(entry, "category", path)
    return entries


def check_claude_import() -> None:
    path = ROOT / "CLAUDE.md"
    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        raise fail(path, "required Claude import file is missing") from error
    if content != b"@AGENTS.md\n":
        raise fail(path, "must contain exactly '@AGENTS.md' plus one final newline")


def check_json_manifests() -> None:
    validate_claude_marketplace()
    validate_codex_marketplace()
    for plugin_dir in sorted((ROOT / "plugins").iterdir(), key=lambda path: path.name):
        if not plugin_dir.is_dir():
            continue
        load_json(plugin_dir / ".claude-plugin/plugin.json")
        load_json(plugin_dir / ".codex-plugin/plugin.json")


def check_plugin_set_and_versions() -> None:
    claude_entries = validate_claude_marketplace()
    codex_entries = validate_codex_marketplace()
    plugin_dirs = {
        path.name: path for path in (ROOT / "plugins").iterdir() if path.is_dir()
    }
    disk_names = set(plugin_dirs)
    if set(claude_entries) != disk_names:
        raise fail(
            CLAUDE_MARKETPLACE,
            f"plugin names {sorted(claude_entries)} do not equal plugin directories {sorted(disk_names)}",
        )
    if set(codex_entries) != disk_names:
        raise fail(
            CODEX_MARKETPLACE,
            f"plugin names {sorted(codex_entries)} do not equal plugin directories {sorted(disk_names)}",
        )

    for name, plugin_dir in sorted(plugin_dirs.items()):
        claude_path = plugin_dir / ".claude-plugin/plugin.json"
        codex_path = plugin_dir / ".codex-plugin/plugin.json"
        claude = load_json(claude_path)
        codex = load_json(codex_path)
        if require_string(claude, "name", claude_path) != name:
            raise fail(
                claude_path, f"field 'name' must equal plugin directory {name!r}"
            )
        if require_string(codex, "name", codex_path) != name:
            raise fail(codex_path, f"field 'name' must equal plugin directory {name!r}")
        require_string(claude, "description", claude_path)
        require_string(codex, "description", codex_path)
        require_string(
            require_object(claude, "author", claude_path), "name", claude_path
        )
        require_string(claude, "repository", claude_path)

        skills_value = require_string(codex, "skills", codex_path)
        expected_skills = (plugin_dir / "skills").resolve()
        actual_skills = (plugin_dir / skills_value).resolve()
        if (
            skills_value != "./skills/"
            or actual_skills != expected_skills
            or not actual_skills.is_dir()
        ):
            raise fail(
                codex_path,
                "field 'skills' must equal './skills/' and resolve to the plugin skills directory",
            )

        marketplace_version = require_string(
            claude_entries[name], "version", CLAUDE_MARKETPLACE
        )
        claude_version = require_string(claude, "version", claude_path)
        codex_version = require_string(codex, "version", codex_path)
        require_semver(
            marketplace_version, CLAUDE_MARKETPLACE, f"plugins[{name}].version"
        )
        require_semver(claude_version, claude_path, "version")
        require_semver(codex_version, codex_path, "version")
        if len({marketplace_version, claude_version, codex_version}) != 1:
            raise CheckFailure(
                f"plugin {name!r}: release versions are not in lockstep: marketplace={marketplace_version}, "
                f"Claude={claude_version}, Codex={codex_version}"
            )


def parse_skill_frontmatter(path: Path) -> tuple[str, str]:
    try:
        text = (
            path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        )
    except FileNotFoundError as error:
        raise fail(
            path, "every immediate skill directory must contain SKILL.md"
        ) from error
    except UnicodeError as error:
        raise fail(path, f"SKILL.md is not valid UTF-8: {error}") from error
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise fail(path, "frontmatter must start with a line containing only '---'")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as error:
        raise fail(
            path, "frontmatter is missing its closing '---' delimiter"
        ) from error
    frontmatter = lines[1:closing_index]

    name_values = [
        line.removeprefix("name: ") for line in frontmatter if line.startswith("name: ")
    ]
    if len(name_values) != 1 or not name_values[0].strip():
        raise fail(
            path, "frontmatter must contain exactly one non-empty 'name' plain scalar"
        )
    name = name_values[0].strip()

    description_indices = [
        index
        for index, line in enumerate(frontmatter)
        if line.startswith("description:")
    ]
    if len(description_indices) != 1:
        raise fail(path, "frontmatter must contain exactly one 'description' field")
    description_index = description_indices[0]
    description_value = (
        frontmatter[description_index].removeprefix("description:").strip()
    )
    if description_value in {">", ">-", ">+"}:
        folded_lines: list[str] = []
        for line in frontmatter[description_index + 1 :]:
            if line.startswith((" ", "\t")):
                folded_lines.append(line.strip())
            else:
                break
        description = " ".join(line for line in folded_lines if line)
    elif description_value.startswith(("|", "[", "{", "&", "*", "!", "'", '"')):
        raise fail(
            path, "field 'description' must use a plain scalar or folded '>' form"
        )
    else:
        description = description_value
    if not description:
        raise fail(path, "frontmatter field 'description' must not be empty")
    return name, description


def check_skill_frontmatter() -> None:
    for plugin_dir in sorted((ROOT / "plugins").iterdir(), key=lambda path: path.name):
        skills_dir = plugin_dir / "skills"
        if not skills_dir.is_dir():
            raise fail(skills_dir, "plugin skills directory is missing")
        for skill_dir in sorted(skills_dir.iterdir(), key=lambda path: path.name):
            if not skill_dir.is_dir():
                continue
            skill_path = skill_dir / "SKILL.md"
            name, _description = parse_skill_frontmatter(skill_path)
            if name != skill_dir.name:
                raise fail(
                    skill_path,
                    f"frontmatter name {name!r} must equal skill directory {skill_dir.name!r}",
                )


def check_agent_sources_and_outputs() -> None:
    try:
        agents = generator.discover_agents()
        expected = {
            agent.output_name: generator.render_agent(agent) for agent in agents
        }
    except generator.GenerationError as error:
        raise CheckFailure(str(error)) from error
    expected_names = set(expected)
    for output_dir in generator.OUTPUT_DIRS:
        if not output_dir.is_dir():
            raise fail(output_dir, "generated agent output directory is missing")
        actual_paths = {
            path.name: path for path in output_dir.iterdir() if path.is_file()
        }
        if set(actual_paths) != expected_names:
            raise fail(
                output_dir,
                f"generated file set {sorted(actual_paths)} does not equal expected set {sorted(expected_names)}",
            )
        for agent in agents:
            path = actual_paths[agent.output_name]
            data = path.read_bytes()
            expected_source_line = f"# Generated from {relative(agent.source)}; edit the source and regenerate.\n".encode()
            if not data.startswith(expected_source_line):
                raise fail(
                    path,
                    f"must name authoritative source {relative(agent.source)!r} on its first line",
                )
            try:
                parsed = tomllib.loads(data.decode("utf-8"))
            except (UnicodeError, tomllib.TOMLDecodeError) as error:
                raise fail(path, f"invalid generated TOML: {error}") from error
            expected_values = {
                "name": agent.name,
                "description": agent.description,
                "developer_instructions": agent.instructions,
            }
            if parsed != expected_values:
                raise fail(
                    path,
                    "parsed TOML values do not match the authoritative agent source",
                )
            if data != expected[agent.output_name]:
                raise fail(path, "bytes differ from deterministic generator output")

    first_dir, second_dir = generator.OUTPUT_DIRS
    for name in sorted(expected_names):
        if (first_dir / name).read_bytes() != (second_dir / name).read_bytes():
            raise CheckFailure(
                f"generated agent {name!r}: project-scoped and distributable bytes differ"
            )


def check_generator_drift() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/generate_codex_agents.py"), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        details = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        raise CheckFailure(f"generator --check failed:\n{details}")


def check_project_rule_resolver() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/test_resolve_project_rules.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        details = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        raise CheckFailure(f"project rule resolver tests failed:\n{details}")


def check_project_bootstrap_adoption() -> None:
    task_scoped_skills = (
        "auto",
        "backlog",
        "execute",
        "retro",
        "review-pr",
        "verify",
    )
    for name in task_scoped_skills:
        path = ROOT / "plugins/dev/skills" / name / "SKILL.md"
        content = path.read_text(encoding="utf-8")
        for required in (
            "docs/project-bootstrap.md",
            "Execution revision:",
            "Rules loaded:",
        ):
            if required not in content:
                raise fail(path, f"task-scoped skill must contain {required!r}")

    for name in ("reviewer", "test-writer", "verifier"):
        path = ROOT / "plugins/dev/agents" / f"{name}.md"
        content = path.read_text(encoding="utf-8")
        if "docs/project-bootstrap.md" not in content:
            raise fail(
                path, "delegated agent must require resolved project bootstrap context"
            )


CHECKS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("claude-import", check_claude_import),
    ("json-manifests", check_json_manifests),
    ("plugin-set-and-versions", check_plugin_set_and_versions),
    ("skill-frontmatter", check_skill_frontmatter),
    ("agent-sources-and-outputs", check_agent_sources_and_outputs),
    ("generator-drift", check_generator_drift),
    ("project-rule-resolver", check_project_rule_resolver),
    ("project-bootstrap-adoption", check_project_bootstrap_adoption),
)


def main() -> int:
    failures: list[tuple[str, str]] = []
    for name, check in CHECKS:
        try:
            check()
        except (CheckFailure, OSError) as error:
            failures.append((name, str(error)))
            print(f"FAIL {name}: {error}", file=sys.stderr)
        else:
            print(f"PASS {name}")
    if failures:
        print(
            f"Repository validation failed: {len(failures)} check(s) failed.",
            file=sys.stderr,
        )
        return 1
    print(f"Repository validation passed: {len(CHECKS)} checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
