#!/usr/bin/env -S uv run
"""Contract tests for the shared dev:execute work-summary validator."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPOSITORY_ROOT / "plugins/dev/scripts/work_summary.py"
FULL_SHA = "a" * 40


def summary(
    *,
    classification: str = "planned",
    revision: str = FULL_SHA,
) -> str:
    return (
        "## Work summary (dev:execute - 2026-08-03)\n"
        "- PR: https://github.com/example/project/pull/11\n"
        "- Branch: task/10-example\n"
        f"- Queue classification: {classification}\n"
        "- Execution repository: /workspace/example-project\n"
        f"- Execution revision: {revision}\n"
        "- Implemented: shared work-summary validation.\n"
        "- Key decisions: none\n"
        "- Obstacles: none\n"
        "- Spec gaps found: none\n"
    )


class WorkSummaryTests(unittest.TestCase):
    def run_validator(self, text: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "work-summary.md"
            path.write_text(text, encoding="utf-8")
            return subprocess.run(
                [
                    "uv",
                    "run",
                    str(VALIDATOR),
                    "validate",
                    "--file",
                    str(path),
                ],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def assert_invalid(self, text: str, *messages: str) -> None:
        result = self.run_validator(text)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        for message in messages:
            self.assertIn(message.lower(), result.stderr.lower())

    def test_valid_classifications_and_full_sha_are_accepted(self) -> None:
        for classification in ("planned", "external", "secondary"):
            with self.subTest(classification=classification):
                result = self.run_validator(summary(classification=classification))

                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output["queue_classification"], classification)
                self.assertEqual(output["execution_revision"], FULL_SHA)

    def test_same_validator_accepts_github_and_non_github_fixtures(self) -> None:
        fixtures = {
            "github": summary(classification="planned"),
            "linear": summary(classification="external", revision="B" * 40),
        }
        for backend, fixture in fixtures.items():
            with self.subTest(backend=backend):
                result = self.run_validator(fixture)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_heading_must_match_exact_work_summary_heading(self) -> None:
        self.assert_invalid(
            summary().replace(
                "## Work summary (dev:execute - 2026-08-03)",
                "## Work summary (dev:execute - 2026-08-03) extra",
            ),
            "heading",
        )

    def test_each_required_field_is_required(self) -> None:
        fields = {
            "PR": "- PR: https://github.com/example/project/pull/11\n",
            "Branch": "- Branch: task/10-example\n",
            "Queue classification": "- Queue classification: planned\n",
            "Execution repository": "- Execution repository: /workspace/example-project\n",
            "Execution revision": f"- Execution revision: {FULL_SHA}\n",
        }
        for field, line in fields.items():
            with self.subTest(field=field):
                self.assert_invalid(summary().replace(line, ""), field)

    def test_classification_must_be_supported(self) -> None:
        self.assert_invalid(
            summary(classification="todo"),
            "Queue classification",
            "planned, external, secondary",
        )

    def test_revision_must_be_exactly_40_hexadecimal_characters(self) -> None:
        self.assert_invalid(
            summary(revision="a" * 7),
            "Execution revision",
            "40 hexadecimal characters",
        )
        self.assert_invalid(
            summary(revision=FULL_SHA + " trailing text"),
            "Execution revision",
            "40 hexadecimal characters",
        )

    def test_duplicate_fields_and_malformed_lines_are_rejected(self) -> None:
        self.assert_invalid(
            summary() + "- Branch: another-branch\n",
            "Branch",
            "exactly once",
        )
        self.assert_invalid(summary() + "not a field", "line", "exact")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
