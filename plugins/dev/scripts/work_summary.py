#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Parse and validate the shared dev:execute work-summary contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Sequence


REQUIRED_FIELDS = (
    "PR",
    "Branch",
    "Queue classification",
    "Execution repository",
    "Execution revision",
)
ALLOWED_CLASSIFICATIONS = ("planned", "external", "secondary")
HEADING_RE = re.compile(r"^## Work summary \(dev:execute - [^)\r\n]+\)$")
FIELD_RE = re.compile(r"^- (?P<name>[^:\r\n]+): (?P<value>[^\r\n]*)$")
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class WorkSummaryError(ValueError):
    """A work-summary contract violation."""


@dataclass(frozen=True)
class WorkSummary:
    """The required routing fields from one validated work summary."""

    heading: str
    pr: str
    branch: str
    queue_classification: str
    execution_repository: str
    execution_revision: str

    def as_dict(self) -> dict[str, str]:
        return {
            "branch": self.branch,
            "execution_repository": self.execution_repository,
            "execution_revision": self.execution_revision,
            "pr": self.pr,
            "queue_classification": self.queue_classification,
        }


def fail(message: str) -> NoReturn:
    raise WorkSummaryError(message)


def parse_work_summary(text: str) -> WorkSummary:
    """Validate and return the routing fields from an exact work-summary body."""

    if not isinstance(text, str):
        fail("work summary must be text")

    lines = text.splitlines()
    if not lines or not HEADING_RE.fullmatch(lines[0]):
        fail(
            "work summary heading must exactly match "
            "'## Work summary (dev:execute - <date>)'"
        )

    fields: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:], start=2):
        if not line:
            continue
        match = FIELD_RE.fullmatch(line)
        if match is None:
            fail(
                f"work summary line {line_number} must use the exact "
                "'- Field: value' format"
            )
        name = match.group("name")
        value = match.group("value")
        if name in fields:
            fail(f"work summary field {name!r} must appear exactly once")
        fields[name] = value

    for field in REQUIRED_FIELDS:
        if field not in fields:
            fail(f"work summary is missing required field {field!r}")
        if not fields[field]:
            fail(f"work summary field {field!r} must have a non-empty value")

    classification = fields["Queue classification"]
    if classification not in ALLOWED_CLASSIFICATIONS:
        allowed = ", ".join(ALLOWED_CLASSIFICATIONS)
        fail(
            f"work summary field 'Queue classification' must be one of: {allowed}"
        )

    revision = fields["Execution revision"]
    if not FULL_SHA_RE.fullmatch(revision):
        fail(
            "work summary field 'Execution revision' must be exactly "
            "40 hexadecimal characters"
        )

    return WorkSummary(
        heading=lines[0],
        pr=fields["PR"],
        branch=fields["Branch"],
        queue_classification=classification,
        execution_repository=fields["Execution repository"],
        execution_revision=revision,
    )


def read_summary(path: Path | None) -> str:
    if path is None:
        return sys.stdin.read()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"cannot read work summary {path}: {error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the shared dev:execute work-summary contract."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument(
        "--file",
        type=Path,
        help="read the exact work-summary body from this file; otherwise read stdin",
    )
    validate_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        summary = parse_work_summary(read_summary(arguments.file))
    except (OSError, WorkSummaryError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if arguments.format == "json":
        print(json.dumps(summary.as_dict(), sort_keys=True))
    else:
        print("valid work summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
