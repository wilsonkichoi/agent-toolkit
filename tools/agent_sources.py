"""Strict shared parser for repository-owned Markdown agent sources."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_GLOB = "plugins/*/agents/*.md"
PLAIN_SCALAR_FIELDS = {"name", "description", "model", "color"}
SUPPORTED_FIELDS = PLAIN_SCALAR_FIELDS | {"tools"}
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?: (.*))?$")
UNSUPPORTED_SCALAR_PREFIXES = set("'\"[{&*!|>@`%")


class GenerationError(ValueError):
    """A source or generated-output invariant failed."""


@dataclass(frozen=True)
class Agent:
    source: Path
    name: str
    description: str
    instructions: str
    model: str
    color: str
    tools: tuple[str, ...]

    @property
    def output_name(self) -> str:
        return f"{self.name}.toml"


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")
def _plain_scalar(path: Path, field: str, value: str | None, root: Path) -> str:
    if value is None or not value:
        raise GenerationError(
            f"{_relative(path, root)}: field {field!r} must be a non-empty plain scalar"
        )
    if value != value.strip():
        raise GenerationError(
            f"{_relative(path, root)}: field {field!r} has unsupported surrounding whitespace"
        )
    if value[0] in UNSUPPORTED_SCALAR_PREFIXES:
        raise GenerationError(
            f"{_relative(path, root)}: field {field!r} uses unsupported YAML syntax; use a plain scalar"
        )
    if "\t" in value or " #" in value or re.search(r":\s", value):
        raise GenerationError(
            f"{_relative(path, root)}: field {field!r} uses unsupported YAML syntax; use a plain scalar"
        )
    if any(ord(character) < 0x20 for character in value):
        raise GenerationError(
            f"{_relative(path, root)}: field {field!r} contains a control character"
        )
    return value


def parse_agent_source(path: Path, *, root: Path = ROOT) -> Agent:
    try:
        text = _normalize_newlines(path.read_text(encoding="utf-8"))
    except UnicodeError as error:
        raise GenerationError(
            f"{_relative(path, root)}: source is not valid UTF-8: {error}"
        ) from error

    lines = text.splitlines(keepends=True)
    if not lines or lines[0] != "---\n":
        raise GenerationError(
            f"{_relative(path, root)}: frontmatter must start with a line containing only '---'"
        )
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line == "---\n"
        )
    except StopIteration as error:
        raise GenerationError(
            f"{_relative(path, root)}: frontmatter is missing its closing '---' delimiter"
        ) from error
    values: dict[str, object] = {}
    for line_number, line in enumerate(lines[1:closing_index], start=2):
        content = line.removesuffix("\n")
        match = FIELD_RE.fullmatch(content)
        if not match:
            raise GenerationError(
                f"{_relative(path, root)}:{line_number}: unsupported frontmatter syntax; "
                "expected 'field: value'"
            )
        field, raw_value = match.groups()
        if field not in SUPPORTED_FIELDS:
            raise GenerationError(
                f"{_relative(path, root)}: unsupported agent frontmatter field {field!r}"
            )
        if field in values:
            raise GenerationError(
                f"{_relative(path, root)}: duplicate frontmatter field {field!r}"
            )
        if field in PLAIN_SCALAR_FIELDS:
            values[field] = _plain_scalar(path, field, raw_value, root)
            continue
        if raw_value is None:
            raise GenerationError(
                f"{_relative(path, root)}: field 'tools' must be an inline JSON-compatible list"
            )
        try:
            parsed_tools = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise GenerationError(
                f"{_relative(path, root)}: field 'tools' must be an inline "
                f"JSON-compatible list: {error.msg}"
            ) from error
        if (
            not isinstance(parsed_tools, list)
            or not parsed_tools
            or any(not isinstance(tool, str) or not tool for tool in parsed_tools)
        ):
            raise GenerationError(
                f"{_relative(path, root)}: field 'tools' must be a non-empty list of strings"
            )
        if len(set(parsed_tools)) != len(parsed_tools):
            raise GenerationError(
                f"{_relative(path, root)}: field 'tools' contains duplicate entries"
            )
        values[field] = tuple(parsed_tools)

    missing = SUPPORTED_FIELDS - values.keys()
    if missing:
        raise GenerationError(
            f"{_relative(path, root)}: missing required field(s): "
            f"{', '.join(sorted(missing))}"
        )
    name = values["name"]
    assert isinstance(name, str)
    if name != path.stem:
        raise GenerationError(
            f"{_relative(path, root)}: field 'name' is {name!r}, "
            f"expected filename stem {path.stem!r}"
        )
    model = values["model"]
    assert isinstance(model, str)
    if model != "inherit":
        raise GenerationError(
            f"{_relative(path, root)}: field 'model' value {model!r} is unsupported; "
            "expected 'inherit'"
        )

    body = "".join(lines[closing_index + 1 :])
    if body.startswith("\n"):
        body = body[1:]
    if not body.strip():
        raise GenerationError(
            f"{_relative(path, root)}: agent instruction body must not be empty"
        )

    description = values["description"]
    color = values["color"]
    tools = values["tools"]
    assert isinstance(description, str)
    assert isinstance(color, str)
    assert isinstance(tools, tuple)
    return Agent(path, name, description, body, model, color, tools)


def validate_source_path(path: Path, *, root: Path = ROOT) -> None:
    """Reject a discovered source reached through a symlink or outside its repository."""
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError as error:
        raise GenerationError(f"source path is outside the repository: {path}") from error

    candidate = root
    for part in relative_parts:
        candidate /= part
        if candidate.is_symlink():
            raise GenerationError(f"refusing symlinked source: {path}")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise GenerationError(f"source path escapes the repository: {path}") from error


def discover_agents(
    *, root: Path = ROOT, source_glob: str = SOURCE_GLOB
) -> list[Agent]:
    source_paths = sorted(root.glob(source_glob), key=lambda path: path.as_posix())
    if not source_paths:
        raise GenerationError(
            f"no authoritative agent sources matched {source_glob!r}"
        )
    for path in source_paths:
        validate_source_path(path, root=root)
    agents = [parse_agent_source(path, root=root) for path in source_paths]
    output_names = [agent.output_name for agent in agents]
    duplicates = sorted({name for name in output_names if output_names.count(name) > 1})
    if duplicates:
        raise GenerationError(
            f"agent output filename collision(s): {', '.join(duplicates)}"
        )
    return agents
