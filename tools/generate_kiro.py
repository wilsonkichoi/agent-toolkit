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

from agent_sources import Agent, GenerationError, discover_agents, validate_source_path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "dist/kiro"
NAME_MAP_PATH = ROOT / "tools/kiro_names.json"
GENERATOR_VERSION = 1
KIRO_NAME_RE = re.compile(r"[a-z0-9-]{1,64}")
SKILL_SOURCE_GLOB = "plugins/*/skills/*/SKILL.md"
# Skill sources deliberately kept out of the Kiro preview. `feedback` and `release` act on the
# agent-toolkit repository itself rather than an adopter's project, and `shadow` is unsupported in
# Kiro. No shipped skill hands off to any of them, so excluding them leaves no dead pointer; the
# tests assert that property rather than trusting this comment.
EXCLUDED_SKILL_SOURCES = frozenset(
    {
        "plugins/dev/skills/feedback",
        "plugins/dev/skills/release",
        "plugins/dev/skills/shadow",
    }
)
SKILL_FIELDS = {"name", "description", "argument-hint"}
SKILL_OUTPUT_FIELDS = {"name", "description", "compatibility", "metadata"}
AGENT_OUTPUT_FIELDS = {"name", "description", "tools"}
KIRO_SKILL_DIRECTORY = "the installed Kiro skill directory"
# A harness-mapping sentence whose two sides both resolve to the Kiro directory renders as
# "`X` is `X`". Guard the result rather than trusting the rewrite that avoids it.
PLUGIN_ROOT_TAUTOLOGY = f"`{KIRO_SKILL_DIRECTORY}` is `{KIRO_SKILL_DIRECTORY}`"
FORBIDDEN_GENERATED_TEXT = (
    "${CLAUDE_PLUGIN_ROOT}",
    "../../runtime_contracts/",
    "../../scripts/",
    "<plugin-root>",
    "The Claude Code validator",
    "Codex-relative form",
    PLUGIN_ROOT_TAUTOLOGY,
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
    discovered = sorted(root.glob(SKILL_SOURCE_GLOB), key=lambda path: path.as_posix())
    if not discovered:
        fail(f"no authoritative skill sources matched {SKILL_SOURCE_GLOB!r}")
    unknown = EXCLUDED_SKILL_SOURCES - {relative(path.parent, root) for path in discovered}
    if unknown:
        fail(f"EXCLUDED_SKILL_SOURCES names missing skill source(s): {', '.join(sorted(unknown))}")
    paths = [
        path for path in discovered if relative(path.parent, root) not in EXCLUDED_SKILL_SOURCES
    ]
    if not paths:
        fail("every discovered skill source is excluded from the Kiro preview")
    for path in paths:
        validate_source_path(path, root=root)
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
    # Rewrite a bare `/<source-name>` only in a genuine invocation position: the start of the
    # text, or immediately after whitespace, a backtick, or an opening parenthesis. The lead is
    # a positive constraint rather than a blocklist so path segments and prose keep their source
    # spelling - `plugins/dev/skills/feedback/SKILL.md`, `runtime_contracts/shadow.md`,
    # `id/title/status`, and `review/verify` are all left alone.
    text = re.sub(
        rf"(?P<lead>\A|[\s`(])/{re.escape(source_name)}(?![A-Za-z0-9_-])",
        lambda match: f"{match.group('lead')}/{emitted_name}",
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
        # Collapse the Claude-Code/Codex plugin-root mapping sentence before the substitutions
        # below reach it. Rewriting both of its sides to the Kiro directory would emit the
        # tautology "`the installed Kiro skill directory` is `the installed Kiro skill
        # directory`", which PLUGIN_ROOT_TAUTOLOGY guards against if this stops matching.
        text = re.sub(
            r"On Claude Code `<plugin-root>` is `\$\{CLAUDE_PLUGIN_ROOT\}`; "
            r"on Codex the script is",
            "In Kiro the script is",
            text,
        )
        text = re.sub(
            r"The Claude Code\s+validator is\s+"
            r"`\$\{CLAUDE_PLUGIN_ROOT\}/scripts/work_summary\.py`\. "
            r"Resolve the\s+Codex-relative form",
            "Resolve that skill-relative form",
            text,
        )
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
        text = text.replace("${CLAUDE_PLUGIN_ROOT}", KIRO_SKILL_DIRECTORY)
        text = text.replace("<plugin-root>", KIRO_SKILL_DIRECTORY)
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
> active-folder isolation, and explicit agent resources are unsupported; stop if inactive-root
> instructions, steering, or resources appear.

"""
    if skill.plugin != "dev":
        return common
    return common + """> Every bare `dev:<name>` reference below names a source skill whose Kiro
> invocation is `/dev-<name>`; `dev:execute` is `/dev-execute`, `dev:verify` is `/dev-verify`.
> The single-root Kiro IDE lifecycle preview has passed the manual
> `setup → plan → execute → review-pr → verify` lifecycle, safe-stop probes, and bounded
> `dev:auto`; the recorded scope, Kiro version, and outcomes are in this repository's
> `docs/kiro-preview-validation.md`. Use Kiro named subagents and the plugin's explicit worktree
> procedure; do not substitute inline review, test authoring, or verification when a required
> isolated profile is unavailable. Dispatch `dev-reviewer`, `dev-test-writer`, and
> `dev-verifier` by exact name and wait for results.

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
        "compatibility: Kiro IDE single-root workspace preview; CLI, multi-root, and explicit agent resources unsupported\n"
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

This generated artifact supports **single-root Kiro IDE workspaces only**. Kiro CLI, multi-root
active-folder isolation, and explicit agent resources are not supported. All utility skills, the
named dev agents, the human-gated manual lifecycle, and bounded `dev:auto` have passed fresh
single-root IDE runtime probes; what was run, on which Kiro build, and with what outcome is
recorded in this repository's `docs/kiro-preview-validation.md`.

This is a subset of the dev plugin, not a mirror of it. `dev:feedback` and `dev:release` act on the
agent-toolkit repository itself rather than your project, and `dev:shadow` is unsupported in Kiro,
so none of the three is generated here. Use Claude Code or Codex for those. Each generated skill
bundles only the shared contracts and helpers it actually needs; `manifest.json` records that set
per skill.

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

CONTRACTS_SOURCE = "plugins/dev/runtime_contracts"
SCRIPTS_SOURCE = "plugins/dev/scripts"


def shared_sources(root: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    contracts = {
        path.name: path
        for path in sorted((root / CONTRACTS_SOURCE).iterdir())
        if path.is_file() and path.suffix == ".md"
    }
    helpers = {
        path.name: path
        for path in sorted((root / SCRIPTS_SOURCE).iterdir())
        if path.is_file() and path.suffix in {".py", ".json"}
    }
    if not contracts or not helpers:
        fail("no shared dev contracts or helpers were discovered")
    return contracts, helpers


def shared_closure(
    text: str, contracts: dict[str, Path], helpers: dict[str, Path]
) -> tuple[list[str], list[str]]:
    """The shared contracts and helpers one dev skill needs, from its source SKILL.md.

    Kiro follows the Agent Skills standard, where a skill directory is the unit of distribution
    and file references resolve relative to `SKILL.md`. There is no plugin root, so anything a
    skill shares has to be copied inside it. This computes the smallest correct copy set:

    1. Seed from the shared file names the skill's own text mentions, in any form - a full
       `runtime_contracts/tracker.md` path, a bare `tracker.md`, or a `scripts/work_summary.py`
       command. Substring matching over the known shared file names deliberately over-includes
       rather than parse every citation shape.
    2. Close it in both directions to a fixpoint: a contract brings every shared helper it names,
       a helper brings the contract that governs it, and a contract brings any contract it names.
       The reverse direction is what keeps a helper from shipping without the contract that
       explains how to run it - `dev:status` names `resolve_project_rules.py` directly but never
       names `project-bootstrap.md`, and would otherwise ship the resolver with no contract.

    A dependency that appears only as untraceable prose ("run the shared validator", with no file
    name anywhere) is outside what this can see. The bidirectional step covers the realistic
    cases, because such prose refers to helpers the governing contract already pulls in.
    """
    contract_helpers: dict[str, set[str]] = {}
    contract_contracts: dict[str, set[str]] = {}
    for name, path in contracts.items():
        contract_text = normalized_text(path)
        contract_helpers[name] = {
            helper for helper in helpers if helper in contract_text
        }
        contract_contracts[name] = {
            other for other in contracts if other != name and other in contract_text
        }
    governing = {
        helper: name
        for name, owned in contract_helpers.items()
        for helper in owned
    }

    needed_contracts = {name for name in contracts if name in text}
    needed_helpers = {helper for helper in helpers if helper in text}
    while True:
        grown_contracts = set(needed_contracts)
        grown_contracts |= {
            governing[helper] for helper in needed_helpers if helper in governing
        }
        for name in list(grown_contracts):
            grown_contracts |= contract_contracts[name]
        grown_helpers = set(needed_helpers)
        for name in grown_contracts:
            grown_helpers |= contract_helpers[name]
        if grown_contracts == needed_contracts and grown_helpers == needed_helpers:
            break
        needed_contracts, needed_helpers = grown_contracts, grown_helpers
    return sorted(needed_contracts), sorted(needed_helpers)


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

    contracts, helpers = shared_sources(root)
    closures: dict[str, tuple[list[str], list[str]]] = {}

    for skill in skills:
        destination = stage / "skills" / skill.emitted_name
        write_bytes(destination / "SKILL.md", render_skill(skill, skill_map, agent_map))
        if skill.plugin == "dev":
            needed_contracts, needed_helpers = shared_closure(
                normalized_text(skill.source_dir / "SKILL.md"), contracts, helpers
            )
            closures[skill.emitted_name] = (needed_contracts, needed_helpers)
            for name in needed_contracts:
                copy_file(
                    contracts[name],
                    destination / "references/runtime_contracts" / name,
                    transform=True,
                    skill=skill,
                    skill_map=skill_map,
                    agent_map=agent_map,
                )
            for name in needed_helpers:
                copy_file(
                    helpers[name],
                    destination / "scripts" / name,
                    transform=False,
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
        record: dict[str, object] = {
            "source": relative(skill.source_dir, root),
            "name": skill.emitted_name,
            "argument_hint": skill.argument_hint,
        }
        if skill.emitted_name in closures:
            needed_contracts, needed_helpers = closures[skill.emitted_name]
            record["bundled_contracts"] = needed_contracts
            record["bundled_helpers"] = needed_helpers
        skill_records.append(record)

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


BUNDLED_RESOURCE_ROOTS = ("references/", "scripts/", "assets/")
SHARED_CLOSURE_ROOTS = ("references/runtime_contracts/", "scripts/")
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
PARENTHETICAL_RE = re.compile(r"\([^()]*\)", re.DOTALL)
PATH_SHAPED_RE = re.compile(r"[^\s`]+/[^\s`]*\.[A-Za-z0-9]+")


def leading_token(span: str) -> str:
    parts = span.split()
    return parts[0] if parts else ""


def path_shaped(token: str) -> bool:
    if "<" in token or ">" in token or "*" in token:
        return False
    return PATH_SHAPED_RE.fullmatch(token) is not None


def cited_bundled_paths(text: str) -> list[str]:
    """Bundled-resource paths a generated SKILL.md cites in backticks.

    Discrimination rule: a backticked path under `references/`, `scripts/`, or `assets/` is a
    citation of a file the skill must ship, unless it sits inside a parenthesized enumeration
    that also lists a path-shaped span outside those roots. Source prose uses exactly that mixed
    shape to illustrate path *forms* - `scripts/tool.py` next to `config/settings.yml` and
    `src/module.mjs` in the feedback redaction rules - and never cites a bundled file beside a
    path the skill cannot own. Bare directory mentions (`scripts/`) carry no extension and
    command spans (`scripts/work_summary.py validate --file <path>`) reduce to their leading
    token, so neither is treated as a distinct citation. The rule can under-include (a real
    citation listed beside a foreign path is skipped); it must not over-include, because a false
    positive here would be unfixable without editing harness-neutral source prose.
    """
    illustrative: set[int] = set()
    for group in PARENTHETICAL_RE.finditer(text):
        spans = list(CODE_SPAN_RE.finditer(group.group(0)))
        paths = [
            token
            for token in (leading_token(span.group(1)) for span in spans)
            if path_shaped(token)
        ]
        if len(paths) >= 2 and any(
            not token.startswith(BUNDLED_RESOURCE_ROOTS) for token in paths
        ):
            illustrative.update(group.start() + span.start() for span in spans)

    cited: list[str] = []
    for match in CODE_SPAN_RE.finditer(text):
        token = leading_token(match.group(1))
        if not token.startswith(BUNDLED_RESOURCE_ROOTS) or not path_shaped(token):
            continue
        if match.start() in illustrative or token in cited:
            continue
        cited.append(token)
    return cited


HELPER_GOVERNING_CONTRACT = {
    "resolve_project_rules.py": "project-bootstrap.md",
    "github_task_lifecycle.py": "tracker.md",
    "work_summary.py": "tracker.md",
    "shadow_replay.py": "shadow.md",
    "shadow_pricing.json": "shadow.md",
}


def validate_skill_closure(skill_file: Path, record: dict[str, object]) -> None:
    """A dev skill ships exactly its recorded closure, and no helper without its contract.

    The manifest records what `shared_closure` computed; this asserts the emitted tree matches it
    and that the bidirectional rule actually held. A helper shipped without the contract that
    governs it is the failure mode that a purely forward closure produces, so it is checked
    independently of the code that computes the closure.
    """
    skill_dir = skill_file.parent
    for field, subdirectory in (
        ("bundled_contracts", "references/runtime_contracts"),
        ("bundled_helpers", "scripts"),
    ):
        recorded = record.get(field)
        if not isinstance(recorded, list):
            fail(f"{skill_file}: manifest is missing a {field} list")
        expected = sorted(str(name) for name in recorded)
        directory = skill_dir / subdirectory
        emitted = sorted(path.name for path in directory.iterdir()) if directory.is_dir() else []
        if emitted != expected:
            fail(
                f"{skill_file}: emitted {subdirectory} contents {emitted} do not match the "
                f"recorded closure {expected}"
            )

    shipped_contracts = set(str(name) for name in record["bundled_contracts"])  # type: ignore[union-attr]
    for helper in record["bundled_helpers"]:  # type: ignore[union-attr]
        governing = HELPER_GOVERNING_CONTRACT.get(str(helper))
        if governing is not None and governing not in shipped_contracts:
            fail(
                f"{skill_file}: bundles {helper} without its governing contract {governing}; "
                "a helper must never ship without the contract that documents its use"
            )


def validate_bundled_references(stage: Path, skill_names: list[str]) -> None:
    escaped: list[str] = []
    unresolved: list[str] = []
    for name in skill_names:
        skill_file = stage / "skills" / name / "SKILL.md"
        skill_root = skill_file.parent.resolve()
        for cited in cited_bundled_paths(normalized_text(skill_file)):
            candidate = skill_file.parent / cited
            try:
                candidate.resolve().relative_to(skill_root)
            except ValueError:
                escaped.append(f"{name} -> {cited}")
                continue
            if not candidate.is_file():
                unresolved.append(f"{name} -> {cited}")
    if escaped:
        fail(
            "generated skills cite bundled resources that escape their skill directory: "
            + "; ".join(sorted(escaped))
        )
    if unresolved:
        fail(
            "generated skills cite bundled resources that do not resolve: "
            + "; ".join(sorted(unresolved))
        )


def validate_shared_copies(stage: Path, skill_names: list[str]) -> None:
    """Require every copy of a shared closure file to be byte-identical across skills.

    Scoped to the generated shared closure roots, which are copied into each dev skill from one
    source tree. Per-skill content legitimately differs at the same relative path - `SKILL.md`
    above all - so a whole-tree comparison would be wrong.
    """
    digests: dict[str, dict[str, list[str]]] = {}
    for name in skill_names:
        skill_dir = stage / "skills" / name
        for path in sorted(skill_dir.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            relative_path = path.relative_to(skill_dir).as_posix()
            if not relative_path.startswith(SHARED_CLOSURE_ROOTS):
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            digests.setdefault(relative_path, {}).setdefault(digest, []).append(name)

    divergent = sorted(
        relative_path for relative_path, groups in digests.items() if len(groups) > 1
    )
    if divergent:
        details = "; ".join(
            f"{relative_path}: "
            + " vs ".join(
                "[" + ", ".join(sorted(names)) + "]"
                for _, names in sorted(digests[relative_path].items())
            )
            for relative_path in divergent
        )
        fail(f"shared bundled copies are not byte-identical across skills: {details}")


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
            validate_skill_closure(skill_file, record)

    skill_names = [str(record["name"]) for record in skills]
    validate_bundled_references(stage, skill_names)
    validate_shared_copies(stage, skill_names)

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
