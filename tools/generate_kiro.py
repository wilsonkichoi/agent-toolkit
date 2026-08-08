#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Generate deterministic Kiro preview skills and agents from plugin sources."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from agent_sources import Agent, GenerationError, discover_agents

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "dist/kiro"
NAME_MAP_PATH = ROOT / "tools/kiro_names.json"
GENERATOR_VERSION = 1
KIRO_NAME_RE = re.compile(r"[a-z0-9-]{1,64}")
SKILL_SOURCE_GLOB = "plugins/*/skills/*/SKILL.md"
SKILL_FIELDS = {"name", "description", "argument-hint"}
SKILL_OUTPUT_FIELDS = {"name", "description", "compatibility", "metadata"}
AGENT_OUTPUT_FIELDS = {"name", "description", "tools"}
FORBIDDEN_GENERATED_TEXT = (
    "${CLAUDE_PLUGIN_ROOT}",
    "../../runtime_contracts/",
    "../../scripts/",
    "<plugin-root>",
)
AGENT_TOOL_MAP = {
    "Read": "read",
    "Grep": "read",
    "Glob": "read",
    "Write": "write",
    "Edit": "write",
    "Bash": "shell",
}

class KiroGenerationError(ValueError):
    """A Kiro source, mapping, or generated-output invariant failed."""


def fail(message: str) -> NoReturn:
    raise KiroGenerationError(message)


def relative(path: Path, root: Path = ROOT) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def normalized_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeError) as error:
        fail(f"cannot read {path}: {error}")


def split_frontmatter(text: str, path: Path) -> tuple[list[str], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0] != "---\n":
        fail(f"{path}: frontmatter must start with a line containing only '---'")
    try:
        closing = next(
            index for index, line in enumerate(lines[1:], start=1) if line == "---\n"
        )
    except StopIteration:
        fail(f"{path}: frontmatter is missing its closing '---' delimiter")
    return [line.removesuffix("\n") for line in lines[1:closing]], "".join(lines[closing + 1 :])


def scalar_value(raw: str, path: Path, field: str) -> str:
    value = raw.strip()
    if not value:
        fail(f"{path}: field {field!r} must not be empty")
    if value[:1] in {'"', "'"}:
        if value[-1:] != value[:1]:
            fail(f"{path}: field {field!r} has an unterminated quoted scalar")
        if value[0] == '"':
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError as error:
                fail(f"{path}: field {field!r} has invalid JSON quoting: {error.msg}")
            if not isinstance(decoded, str):
                fail(f"{path}: field {field!r} must be a string")
            return decoded
        return value[1:-1]
    return value


@dataclass(frozen=True)
class Skill:
    source_dir: Path
    plugin: str
    source_name: str
    emitted_name: str
    description: str
    argument_hint: str | None
    body: str

def parse_skill(source: Path, emitted_name: str, *, root: Path = ROOT) -> Skill:
    frontmatter, body = split_frontmatter(normalized_text(source), source)
    values: dict[str, str] = {}
    block_field: str | None = None
    block_parts: list[str] = []

    def finish_block() -> None:
        nonlocal block_field, block_parts
        if block_field is None:
            return
        if not block_parts:
            fail(f"{source}: field {block_field!r} has an empty block scalar")
        values[block_field] = " ".join(block_parts)
        block_field = None
        block_parts = []

    for line_number, line in enumerate(frontmatter, start=2):
        if line[:1].isspace():
            if block_field is None:
                fail(f"{source}:{line_number}: unexpected indented frontmatter line")
            stripped = line.strip()
            if stripped:
                block_parts.append(stripped)
            continue
        finish_block()
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):(?: (.*))?", line)
        if not match:
            fail(f"{source}:{line_number}: unsupported frontmatter syntax")
        field, raw = match.groups()
        if field not in SKILL_FIELDS:
            fail(f"{source}: unsupported skill frontmatter field {field!r}")
        if field in values:
            fail(f"{source}: duplicate skill frontmatter field {field!r}")
        if raw in {">", ">-", "|", "|-"}:
            if field != "description":
                fail(f"{source}: block scalars are unsupported for field {field!r}")
            block_field = field
            continue
        if raw is None:
            fail(f"{source}: field {field!r} must have a value")
        values[field] = scalar_value(raw, source, field)
    finish_block()

    missing = {"name", "description"} - values.keys()
    if missing:
        fail(f"{source}: missing required field(s): {', '.join(sorted(missing))}")
    if values["name"] != source.parent.name:
        fail(
            f"{source}: field 'name' is {values['name']!r}, expected directory name "
            f"{source.parent.name!r}"
        )
    if len(values["description"]) > 1024:
        fail(f"{source}: description exceeds Kiro's 1024-character limit")
    plugin = source.relative_to(root / "plugins").parts[0]
    return Skill(
        source.parent,
        plugin,
        values["name"],
        emitted_name,
        values["description"],
        values.get("argument-hint"),
        body,
    )

def discover_skill_paths(root: Path = ROOT) -> list[Path]:
    paths = sorted(root.glob(SKILL_SOURCE_GLOB), key=lambda path: path.as_posix())
    if not paths:
        fail(f"no authoritative skill sources matched {SKILL_SOURCE_GLOB!r}")
    for path in paths:
        if path.is_symlink() or path.parent.is_symlink():
            fail(f"refusing symlinked skill source: {path}")
    return paths


def load_name_map(
    skill_paths: list[Path], agents: list[Agent], *, root: Path = ROOT, path: Path = NAME_MAP_PATH
) -> tuple[dict[str, str], dict[str, str]]:
    try:
        document = json.loads(normalized_text(path))
    except json.JSONDecodeError as error:
        fail(f"{relative(path, root)}: invalid JSON: {error}")
    if not isinstance(document, dict) or set(document) != {"skills", "agents"}:
        fail(f"{relative(path, root)}: top level must contain exactly 'skills' and 'agents'")
    skill_map = document["skills"]
    agent_map = document["agents"]
    if not isinstance(skill_map, dict) or not isinstance(agent_map, dict):
        fail(f"{relative(path, root)}: 'skills' and 'agents' must be objects")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in skill_map.items()):
        fail(f"{relative(path, root)}: skill mappings must be string pairs")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in agent_map.items()):
        fail(f"{relative(path, root)}: agent mappings must be string pairs")

    expected_skills = {relative(source.parent, root) for source in skill_paths}
    expected_agents = {relative(agent.source, root) for agent in agents}
    for label, expected, actual in (
        ("skill", expected_skills, set(skill_map)),
        ("agent", expected_agents, set(agent_map)),
    ):
        if expected != actual:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            fail(
                f"{relative(path, root)}: {label} map coverage mismatch; "
                f"missing={missing}, unexpected={unexpected}"
            )
    names = list(skill_map.values()) + list(agent_map.values())
    invalid = sorted(name for name in names if KIRO_NAME_RE.fullmatch(name) is None)
    if invalid:
        fail(f"{relative(path, root)}: invalid Kiro name(s): {', '.join(invalid)}")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        fail(f"{relative(path, root)}: duplicate emitted name(s): {', '.join(duplicates)}")
    return dict(skill_map), dict(agent_map)

def transform_markdown(
    text: str,
    *,
    plugin: str,
    source_name: str,
    emitted_name: str,
    skill_map: dict[str, str],
    agent_map: dict[str, str],
    rewrite_resources: bool = True,
) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for source_key, target in sorted(skill_map.items(), key=lambda item: (-len(item[0]), item[0])):
        parts = Path(source_key).parts
        source_plugin, name = parts[1], parts[-1]
        text = text.replace(f"/{source_plugin}:{name}", f"/{target}")
    text = re.sub(
        rf"/{re.escape(source_name)}(?![A-Za-z0-9_-])",
        f"/{emitted_name}",
        text,
    )
    for source_key, target in sorted(agent_map.items()):
        name = Path(source_key).stem
        text = text.replace(f"dev:{name}", target)
        text = text.replace(f"`{name}` agent", f"`{target}` agent")
    text = text.replace(
        "(`reviewer`, `verifier`, `test-writer`)",
        "(`dev-reviewer`, `dev-verifier`, `dev-test-writer`)",
    )

    if rewrite_resources:
        for old in ("${CLAUDE_PLUGIN_ROOT}/runtime_contracts/", "../../runtime_contracts/"):
            text = text.replace(old, "references/runtime_contracts/")
        text = re.sub(
            r"(?<!references/)runtime_contracts/",
            "references/runtime_contracts/",
            text,
        )
        for old in (
            "${CLAUDE_PLUGIN_ROOT}/scripts/",
            "../../scripts/",
            "<plugin-root>/scripts/",
        ):
            text = text.replace(old, "scripts/")
        text = text.replace("${CLAUDE_PLUGIN_ROOT}", "the installed Kiro skill directory")
        text = text.replace("<plugin-root>", "the installed Kiro skill directory")
    text = re.sub(
        r"render your harness's invocation for it \(Claude Code: `(/[^`]+)`; Codex: `\$[^`]+`\)",
        r"render the Kiro invocation as `\1`",
        text,
    )
    return text


def skill_note(skill: Skill) -> str:
    invocation = f"`/{skill.emitted_name}`"
    if skill.argument_hint:
        invocation += f" with trailing context matching `{skill.argument_hint}`"
    common = f"""
> **Generated Kiro preview.** Invoke this skill as {invocation}. Resolve bundled
> `references/`, `scripts/`, and `assets/` paths relative to this `SKILL.md` before use. This
> generated path and invocation guidance takes precedence over retained Claude Code or Codex
> examples. The artifact comes from the harness-neutral plugin source; do not edit it directly.
> This preview is supported only in a single-root Kiro IDE workspace. Kiro CLI, multi-root
> active-folder isolation, explicit agent resources, and `dev:shadow` are unsupported; stop if
> inactive-root instructions, steering, or resources appear.

"""
    if skill.plugin != "dev":
        return common
    return common + """> The single-root Kiro IDE lifecycle preview has passed the manual
> `setup → plan → execute → review-pr → verify` lifecycle, safe-stop probes, and bounded
> `dev:auto`. Use Kiro named subagents and the plugin's explicit worktree procedure; do not
> substitute inline review, test authoring, or verification when a required isolated profile is
> unavailable. Dispatch `dev-reviewer`, `dev-test-writer`, and `dev-verifier` by exact name and
> wait for results.

"""

def render_skill(
    skill: Skill, skill_map: dict[str, str], agent_map: dict[str, str]
) -> bytes:
    description = transform_markdown(
        skill.description,
        plugin=skill.plugin,
        source_name=skill.source_name,
        emitted_name=skill.emitted_name,
        skill_map=skill_map,
        agent_map=agent_map,
    )
    body = transform_markdown(
        skill.body,
        plugin=skill.plugin,
        source_name=skill.source_name,
        emitted_name=skill.emitted_name,
        skill_map=skill_map,
        agent_map=agent_map,
    )
    document = (
        "---\n"
        f"name: {skill.emitted_name}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "compatibility: Kiro IDE single-root workspace preview; CLI, multi-root, explicit resources, and dev:shadow unsupported\n"
        "metadata:\n"
        f"  source-plugin: {skill.plugin}\n"
        f"  source-skill: {json.dumps(skill.source_name, ensure_ascii=False)}\n"
        "  generated: \"true\"\n"
        "---\n"
        f"{skill_note(skill)}"
        f"{body.lstrip(chr(10))}"
    )
    return document.encode("utf-8")


def mapped_agent_tools(agent: Agent) -> tuple[str, ...]:
    mapped: list[str] = []
    for source_tool in agent.tools:
        if source_tool not in AGENT_TOOL_MAP:
            fail(f"{agent.source}: unmapped agent tool {source_tool!r}")
        target = AGENT_TOOL_MAP[source_tool]
        if target not in mapped:
            mapped.append(target)
    return tuple(mapped)


def render_agent(
    agent: Agent,
    emitted_name: str,
    skill_map: dict[str, str],
    agent_map: dict[str, str],
) -> bytes:
    if len(agent.description) > 1024:
        fail(f"{agent.source}: description exceeds Kiro's 1024-character limit")
    instructions = transform_markdown(
        agent.instructions,
        plugin="dev",
        source_name=agent.name,
        emitted_name=emitted_name,
        skill_map=skill_map,
        agent_map=agent_map,
        rewrite_resources=False,
    )
    tools = mapped_agent_tools(agent)
    document = (
        "---\n"
        f"name: {emitted_name}\n"
        f"description: {json.dumps(agent.description, ensure_ascii=False)}\n"
        "tools:\n"
        + "".join(f"  - {tool}\n" for tool in tools)
        + "---\n\n"
        + f"> **Generated Kiro preview profile.** Select `{emitted_name}` by name. The source\n"
        + "> `model: inherit` field is omitted so Kiro uses the current/default model. This profile\n"
        + "> requires fresh isolated context in a supported single-root Kiro IDE workspace. Kiro\n"
        + "> CLI, multi-root active-folder isolation, and explicit agent resources are unsupported;\n"
        + "> stop if inactive-root steering appears or isolated context is unavailable.\n\n"
        + instructions.lstrip("\n")
    )
    return document.encode("utf-8")


def render_install_readme(
    skill_records: list[dict[str, object]], agent_records: list[dict[str, str]]
) -> bytes:
    skill_names = [str(record["name"]) for record in skill_records]
    agent_files = [f'{record["name"]}.md' for record in agent_records]
    skill_removals = " \\\n  ".join(f'"$TARGET/skills/{name}"' for name in skill_names)
    agent_removals = " \\\n  ".join(f'"$TARGET/agents/{name}"' for name in agent_files)
    document = f"""# Kiro preview installation

This generated artifact supports **single-root Kiro IDE workspaces only**. Kiro CLI,
multi-root active-folder isolation, explicit agent resources, and `dev:shadow` are not supported.
All utility skills, the named dev agents, the human-gated manual lifecycle, and bounded `dev:auto`
have passed fresh single-root IDE runtime probes. `dev-shadow` remains in the generated set for
source completeness but must not be invoked in Kiro.

Kiro owns permission and trust decisions; this distribution does not install or modify those
settings. Start in a disposable or trusted project and approve only expected operations. Lifecycle
skills can create files, commits, branches, worktrees, tracker updates, and merges after their
documented gates. A denied operation or unavailable required named agent is a safe stop: do not
retry with another tool, substitute inline work, or bypass the denial.

Kiro is not installed through either plugin marketplace. There is no Kiro marketplace manifest,
Power, or installer; the supported distribution is this generated clone/copy artifact.

## Clone and copy

Clone this repository, then set `SOURCE` to this generated directory and `TARGET` to either the
current project's `.kiro` directory or the user-level Kiro directory:

```bash
git clone https://github.com/wilsonkichoi/agent-toolkit.git /tmp/agent-toolkit
SOURCE=/tmp/agent-toolkit/dist/kiro
TARGET="$PWD/.kiro" # workspace install; use "$HOME/.kiro" for a global install
mkdir -p "$TARGET/skills" "$TARGET/agents"
ditto "$SOURCE/skills" "$TARGET/skills"
ditto "$SOURCE/agents" "$TARGET/agents"
```

Open a fresh Kiro window after copying. Workspace skills and agents take precedence over global
artifacts with the same generated name. Kiro's local-folder importer may also import one
`$SOURCE/skills/<name>` directory at a time. Repository-root bulk import and `npx skills add` are
unsupported because they are not proven for this generated layout.

## Update

Pull the clone and repeat the two `ditto` commands. They replace only same-named generated files
and preserve unrelated Kiro artifacts.

## Remove exactly this generated set

Set `TARGET` to the workspace or user-level `.kiro` directory used during installation, then remove
only these manifest-owned paths:

```bash
rm -rf \\
  {skill_removals}
rm -f \\
  {agent_removals}
```

Do not delete the whole `.kiro` directory when it contains unrelated settings, hooks, steering,
skills, or agents. `manifest.json` records every generated source mapping and file hash.
"""
    return document.encode("utf-8")


CODEX_ONLY_SKILL_RESOURCES = {"agents/openai.yaml"}


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def copy_file(
    source: Path,
    destination: Path,
    *,
    transform: bool,
    skill: Skill,
    skill_map: dict[str, str],
    agent_map: dict[str, str],
) -> None:
    if source.is_symlink():
        fail(f"refusing symlinked source resource: {source}")
    if transform:
        content = transform_markdown(
            normalized_text(source),
            plugin=skill.plugin,
            source_name=skill.source_name,
            emitted_name=skill.emitted_name,
            skill_map=skill_map,
            agent_map=agent_map,
        ).encode("utf-8")
    else:
        content = source.read_bytes()
    write_bytes(destination, content)


def copy_tree(
    source: Path,
    destination: Path,
    *,
    transform_markdown_files: bool,
    skill: Skill,
    skill_map: dict[str, str],
    agent_map: dict[str, str],
    excluded: set[str] | None = None,
) -> None:
    excluded = excluded or set()
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            fail(f"refusing symlinked source resource: {path}")
        relative_path = path.relative_to(source)
        if (
            path.is_dir()
            or path.name == ".DS_Store"
            or "__pycache__" in relative_path.parts
            or path.suffix.lower() in {".pyc", ".pyo"}
        ):
            continue
        if relative_path.as_posix() in excluded:
            continue
        copy_file(
            path,
            destination / relative_path,
            transform=transform_markdown_files and path.suffix.lower() == ".md",
            skill=skill,
            skill_map=skill_map,
            agent_map=agent_map,
        )


def plugin_versions(root: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for plugin_dir in sorted((root / "plugins").iterdir(), key=lambda path: path.name):
        manifest = plugin_dir / ".claude-plugin/plugin.json"
        if not manifest.is_file():
            continue
        try:
            version = json.loads(normalized_text(manifest)).get("version")
        except json.JSONDecodeError as error:
            fail(f"{manifest}: invalid JSON: {error}")
        if not isinstance(version, str):
            fail(f"{manifest}: missing string version")
        versions[plugin_dir.name] = version
    return versions

def build_stage(
    stage: Path,
    *,
    root: Path = ROOT,
    name_map_path: Path = NAME_MAP_PATH,
) -> dict[str, object]:
    skill_paths = discover_skill_paths(root)
    agents = discover_agents(root=root)
    skill_map, agent_map = load_name_map(
        skill_paths, agents, root=root, path=name_map_path
    )
    skills = [
        parse_skill(source, skill_map[relative(source.parent, root)], root=root)
        for source in skill_paths
    ]
    skill_records: list[dict[str, object]] = []
    agent_records: list[dict[str, str]] = []

    for skill in skills:
        destination = stage / "skills" / skill.emitted_name
        write_bytes(destination / "SKILL.md", render_skill(skill, skill_map, agent_map))
        if skill.plugin == "dev":
            copy_tree(
                root / "plugins/dev/runtime_contracts",
                destination / "references/runtime_contracts",
                transform_markdown_files=True,
                skill=skill,
                skill_map=skill_map,
                agent_map=agent_map,
            )
            copy_tree(
                root / "plugins/dev/scripts",
                destination / "scripts",
                transform_markdown_files=False,
                skill=skill,
                skill_map=skill_map,
                agent_map=agent_map,
            )
        copy_tree(
            skill.source_dir,
            destination,
            transform_markdown_files=True,
            skill=skill,
            skill_map=skill_map,
            agent_map=agent_map,
            excluded={"SKILL.md", *CODEX_ONLY_SKILL_RESOURCES},
        )
        skill_records.append(
            {
                "source": relative(skill.source_dir, root),
                "name": skill.emitted_name,
                "argument_hint": skill.argument_hint,
            }
        )

    for agent in agents:
        source_key = relative(agent.source, root)
        emitted_name = agent_map[source_key]
        write_bytes(
            stage / "agents" / f"{emitted_name}.md",
            render_agent(agent, emitted_name, skill_map, agent_map),
        )
        agent_records.append({"source": source_key, "name": emitted_name})

    write_bytes(stage / "README.md", render_install_readme(skill_records, agent_records))

    manifest: dict[str, object] = {
        "generator": "tools/generate_kiro.py",
        "generator_version": GENERATOR_VERSION,
        "plugin_versions": plugin_versions(root),
        "skills": skill_records,
        "agents": agent_records,
    }
    validate_stage(stage, manifest)
    manifest["files"] = {
        path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and path.name != "manifest.json"
    }
    write_bytes(
        stage / "manifest.json",
        (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(),
    )
    return manifest

def top_level_fields(path: Path) -> set[str]:
    frontmatter, _ = split_frontmatter(normalized_text(path), path)
    fields: list[str] = []
    for line in frontmatter:
        if line[:1].isspace():
            continue
        match = re.match(r"([A-Za-z][A-Za-z0-9_-]*):", line)
        if not match:
            fail(f"{path}: invalid generated frontmatter line {line!r}")
        fields.append(match.group(1))
    if len(fields) != len(set(fields)):
        fail(f"{path}: duplicate generated frontmatter field")
    return set(fields)


def generated_name(path: Path) -> str:
    frontmatter, _ = split_frontmatter(normalized_text(path), path)
    for line in frontmatter:
        if line.startswith("name: "):
            return line.removeprefix("name: ")
    fail(f"{path}: generated frontmatter has no name")


def validate_stage(stage: Path, manifest: dict[str, object]) -> None:
    skills = manifest.get("skills")
    agents = manifest.get("agents")
    if not isinstance(skills, list) or not isinstance(agents, list):
        fail("generated manifest has invalid skills or agents")
    if not skills or not agents:
        fail("generated output must contain at least one skill and one agent")

    for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            fail(f"generated output unexpectedly contains a symlink: {path}")
        if not path.is_file():
            continue
        if path.suffix == ".py":
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeError) as error:
                fail(f"generated Python is invalid at {path}: {error}")
        if path.suffix.lower() not in {".md", ".yml", ".yaml", ".json", ".py"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for forbidden in FORBIDDEN_GENERATED_TEXT:
            if forbidden in text:
                fail(f"generated file {path} retains forbidden source path {forbidden!r}")

    for record in skills:
        if not isinstance(record, dict) or not isinstance(record.get("name"), str):
            fail("generated manifest contains an invalid skill record")
        name = record["name"]
        skill_file = stage / "skills" / name / "SKILL.md"
        if top_level_fields(skill_file) != SKILL_OUTPUT_FIELDS:
            fail(f"{skill_file}: generated skill frontmatter violates the Kiro allowlist")
        if generated_name(skill_file) != name:
            fail(f"{skill_file}: generated name does not match its directory")
        if str(record.get("source", "")).startswith("plugins/dev/"):
            for required in (
                "references/runtime_contracts/project-bootstrap.md",
                "references/runtime_contracts/shadow.md",
                "references/runtime_contracts/tracker.md",
                "scripts/resolve_project_rules.py",
                "scripts/shadow_pricing.json",
            ):
                if not (skill_file.parent / required).is_file():
                    fail(f"{skill_file}: missing bundled dependency {required}")
        # Every dev skill receives the complete shared contract/helper closure above;
        # local resources are copied recursively, so no source-relative runtime dependency remains.

    for record in agents:
        if not isinstance(record, dict) or not isinstance(record.get("name"), str):
            fail("generated manifest contains an invalid agent record")
        name = record["name"]
        agent_file = stage / "agents" / f"{name}.md"
        if top_level_fields(agent_file) != AGENT_OUTPUT_FIELDS:
            fail(f"{agent_file}: generated agent frontmatter violates the Kiro allowlist")
        if generated_name(agent_file) != name:
            fail(f"{agent_file}: generated name does not match its filename")

def snapshot(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            fail(f"refusing symlinked generated output: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def compare_snapshots(expected: dict[str, bytes], actual: dict[str, bytes]) -> list[str]:
    failures: list[str] = []
    for path in sorted(expected.keys() - actual.keys()):
        failures.append(f"missing: {path}")
    for path in sorted(actual.keys() - expected.keys()):
        failures.append(f"unexpected: {path}")
    for path in sorted(expected.keys() & actual.keys()):
        if expected[path] != actual[path]:
            failures.append(f"changed: {path}")
    return failures


def remove_output(output_root: Path) -> None:
    if output_root.is_symlink():
        fail(f"refusing to remove symlinked output directory: {output_root}")
    if output_root.exists():
        if output_root.resolve().parent != output_root.parent.resolve():
            fail(f"refusing to remove output through an unexpected resolved parent: {output_root}")
        shutil.rmtree(output_root)


def generate(
    *,
    check: bool,
    root: Path = ROOT,
    output_root: Path = OUTPUT_ROOT,
    name_map_path: Path = NAME_MAP_PATH,
) -> int:
    output_root.parent.mkdir(parents=True, exist_ok=True)
    stage: Path | None = Path(
        tempfile.mkdtemp(prefix=".kiro-generation-", dir=output_root.parent)
    )
    try:
        manifest = build_stage(stage, root=root, name_map_path=name_map_path)
        if check:
            failures = compare_snapshots(snapshot(stage), snapshot(output_root))
            if failures:
                for failure in failures:
                    print(f"ERROR: {failure}", file=sys.stderr)
                return 1
            print(
                f"Generated Kiro check: passed ({len(manifest['skills'])} skills, "
                f"{len(manifest['agents'])} agents)."
            )
            return 0
        remove_output(output_root)
        stage.replace(output_root)
        stage = None
        print(
            f"Generated Kiro preview: {len(manifest['skills'])} skills and "
            f"{len(manifest['agents'])} agents under {output_root}."
        )
        return 0
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift without writing files")
    arguments = parser.parse_args()
    try:
        return generate(check=arguments.check)
    except (GenerationError, KiroGenerationError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
