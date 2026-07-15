#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Generate Codex agent TOML files from repository-owned Markdown sources."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_GLOB = "plugins/*/agents/*.md"
OUTPUT_DIRS = (ROOT / ".codex/agents", ROOT / "dist/codex/agents")
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


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _plain_scalar(path: Path, field: str, value: str | None) -> str:
    if value is None or not value:
        raise GenerationError(
            f"{_relative(path)}: field {field!r} must be a non-empty plain scalar"
        )
    if value != value.strip():
        raise GenerationError(
            f"{_relative(path)}: field {field!r} has unsupported surrounding whitespace"
        )
    if value[0] in UNSUPPORTED_SCALAR_PREFIXES:
        raise GenerationError(
            f"{_relative(path)}: field {field!r} uses unsupported YAML syntax; use a plain scalar"
        )
    if "\t" in value or " #" in value or re.search(r":\s", value):
        raise GenerationError(
            f"{_relative(path)}: field {field!r} uses unsupported YAML syntax; use a plain scalar"
        )
    if any(ord(character) < 0x20 for character in value):
        raise GenerationError(
            f"{_relative(path)}: field {field!r} contains a control character"
        )
    return value


def parse_agent_source(path: Path) -> Agent:
    try:
        text = _normalize_newlines(path.read_text(encoding="utf-8"))
    except UnicodeError as error:
        raise GenerationError(
            f"{_relative(path)}: source is not valid UTF-8: {error}"
        ) from error

    lines = text.splitlines(keepends=True)
    if not lines or lines[0] != "---\n":
        raise GenerationError(
            f"{_relative(path)}: frontmatter must start with a line containing only '---'"
        )
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line == "---\n"
        )
    except StopIteration as error:
        raise GenerationError(
            f"{_relative(path)}: frontmatter is missing its closing '---' delimiter"
        ) from error

    values: dict[str, object] = {}
    for line_number, line in enumerate(lines[1:closing_index], start=2):
        content = line.removesuffix("\n")
        match = FIELD_RE.fullmatch(content)
        if not match:
            raise GenerationError(
                f"{_relative(path)}:{line_number}: unsupported frontmatter syntax; expected 'field: value'"
            )
        field, raw_value = match.groups()
        if field not in SUPPORTED_FIELDS:
            raise GenerationError(
                f"{_relative(path)}: unsupported agent frontmatter field {field!r}"
            )
        if field in values:
            raise GenerationError(
                f"{_relative(path)}: duplicate frontmatter field {field!r}"
            )
        if field in PLAIN_SCALAR_FIELDS:
            values[field] = _plain_scalar(path, field, raw_value)
            continue
        if raw_value is None:
            raise GenerationError(
                f"{_relative(path)}: field 'tools' must be an inline JSON-compatible list"
            )
        try:
            parsed_tools = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise GenerationError(
                f"{_relative(path)}: field 'tools' must be an inline JSON-compatible list: {error.msg}"
            ) from error
        if (
            not isinstance(parsed_tools, list)
            or not parsed_tools
            or any(not isinstance(tool, str) or not tool for tool in parsed_tools)
        ):
            raise GenerationError(
                f"{_relative(path)}: field 'tools' must be a non-empty list of strings"
            )
        if len(set(parsed_tools)) != len(parsed_tools):
            raise GenerationError(
                f"{_relative(path)}: field 'tools' contains duplicate entries"
            )
        values[field] = tuple(parsed_tools)

    missing = SUPPORTED_FIELDS - values.keys()
    if missing:
        raise GenerationError(
            f"{_relative(path)}: missing required field(s): {', '.join(sorted(missing))}"
        )

    name = values["name"]
    assert isinstance(name, str)
    if name != path.stem:
        raise GenerationError(
            f"{_relative(path)}: field 'name' is {name!r}, expected filename stem {path.stem!r}"
        )
    model = values["model"]
    assert isinstance(model, str)
    if model != "inherit":
        raise GenerationError(
            f"{_relative(path)}: field 'model' value {model!r} is unsupported; expected 'inherit'"
        )

    body = "".join(lines[closing_index + 1 :])
    if body.startswith("\n"):
        body = body[1:]
    if not body.strip():
        raise GenerationError(
            f"{_relative(path)}: agent instruction body must not be empty"
        )

    description = values["description"]
    color = values["color"]
    tools = values["tools"]
    assert isinstance(description, str)
    assert isinstance(color, str)
    assert isinstance(tools, tuple)
    return Agent(path, name, description, body, model, color, tools)


def discover_agents() -> list[Agent]:
    source_paths = sorted(ROOT.glob(SOURCE_GLOB), key=lambda path: path.as_posix())
    if not source_paths:
        raise GenerationError(f"no authoritative agent sources matched {SOURCE_GLOB!r}")
    agents = [parse_agent_source(path) for path in source_paths]
    output_names = [agent.output_name for agent in agents]
    duplicates = sorted({name for name in output_names if output_names.count(name) > 1})
    if duplicates:
        raise GenerationError(
            f"agent output filename collision(s): {', '.join(duplicates)}"
        )
    return agents


def _toml_basic_string(value: str) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    return encoded.replace("\x7f", "\\u007f")


def _toml_multiline_basic_content(value: str) -> str:
    escaped: list[str] = []
    control_escapes = {"\b": "\\b", "\t": "\\t", "\n": "\n", "\f": "\\f", "\r": "\\r"}
    for character in value:
        if character == "\\":
            escaped.append("\\\\")
        elif character == '"':
            escaped.append('\\"')
        elif character in control_escapes:
            escaped.append(control_escapes[character])
        elif ord(character) < 0x20 or ord(character) == 0x7F:
            escaped.append(f"\\u{ord(character):04x}")
        else:
            escaped.append(character)
    return "".join(escaped)


def render_agent(agent: Agent) -> bytes:
    source = _relative(agent.source)
    document = (
        f"# Generated from {source}; edit the source and regenerate.\n"
        f"name = {_toml_basic_string(agent.name)}\n"
        f"description = {_toml_basic_string(agent.description)}\n"
        'developer_instructions = """\n'
        f"{_toml_multiline_basic_content(agent.instructions)}"
        '"""\n'
    )
    try:
        encoded = document.encode("utf-8")
        parsed = tomllib.loads(document)
    except (UnicodeError, tomllib.TOMLDecodeError) as error:
        raise GenerationError(f"{source}: emitted invalid TOML: {error}") from error
    expected = {
        "name": agent.name,
        "description": agent.description,
        "developer_instructions": agent.instructions,
    }
    if parsed != expected:
        raise GenerationError(
            f"{source}: emitted TOML did not round-trip to the source model"
        )
    if not encoded.endswith(b"\n"):
        raise GenerationError(f"{source}: emitted TOML is missing its final newline")
    return encoded


def run_emitter_self_test() -> None:
    corpus = Agent(
        source=ROOT / "plugins/self-test/agents/emitter-corpus.md",
        name="emitter-corpus",
        description='quotes " and apostrophes; backslash \\; Unicode 台灣; control \x01 and \x7f',
        instructions=(
            'First line with "quotes" and a backslash \\.\n'
            "Second line with Unicode: café, 台灣, 🚀.\n"
            "Controls: \x00 \x01 \b \t \f \r \x7f.\n"
            'Triple-quote-like content: """ and escaped-looking \\"\\"\\".\n'
        ),
        model="inherit",
        color="cyan",
        tools=("Read",),
    )
    render_agent(corpus)


def expected_outputs() -> dict[str, bytes]:
    return {agent.output_name: render_agent(agent) for agent in discover_agents()}


def check_outputs(expected: dict[str, bytes]) -> list[str]:
    failures: list[str] = []
    expected_names = set(expected)
    for output_dir in OUTPUT_DIRS:
        relative_dir = _relative(output_dir)
        if not output_dir.is_dir():
            failures.append(f"{relative_dir}: output directory is missing")
            continue
        actual_names = {path.name for path in output_dir.iterdir() if path.is_file()}
        for missing in sorted(expected_names - actual_names):
            failures.append(f"{relative_dir}/{missing}: generated output is missing")
        for extra in sorted(actual_names - expected_names):
            failures.append(f"{relative_dir}/{extra}: unexpected generated output")
        for name in sorted(expected_names & actual_names):
            if (output_dir / name).read_bytes() != expected[name]:
                failures.append(
                    f"{relative_dir}/{name}: generated output differs from its source"
                )
    return failures


def write_outputs(expected: dict[str, bytes]) -> tuple[int, int]:
    written = 0
    removed = 0
    expected_names = set(expected)
    for output_dir in OUTPUT_DIRS:
        output_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
            if path.is_file() and path.name not in expected_names:
                path.unlink()
                removed += 1
        for name, content in sorted(expected.items()):
            path = output_dir / name
            if not path.exists() or path.read_bytes() != content:
                path.write_bytes(content)
                written += 1
    return written, removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="report drift without writing files"
    )
    arguments = parser.parse_args()
    try:
        run_emitter_self_test()
        print(
            "Emitter self-test: passed (quotes, backslashes, Unicode, control characters, "
            "multiline content, triple-quote-like content)."
        )
        expected = expected_outputs()
        if arguments.check:
            failures = check_outputs(expected)
            if failures:
                for failure in failures:
                    print(f"ERROR: {failure}", file=sys.stderr)
                return 1
            print(
                f"Generated agent check: passed ({len(expected)} files in each output directory)."
            )
            return 0
        written, removed = write_outputs(expected)
        print(
            f"Generated agents: {len(expected)} files in each output directory; "
            f"wrote {written}, removed {removed}."
        )
        return 0
    except (GenerationError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
