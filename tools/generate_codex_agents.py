#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Generate Codex agent TOML files from repository-owned Markdown sources."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from agent_sources import (
    Agent,
    GenerationError,
    SOURCE_GLOB,
    discover_agents,
    parse_agent_source,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRS = (ROOT / ".codex/agents", ROOT / "dist/codex/agents")


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


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
