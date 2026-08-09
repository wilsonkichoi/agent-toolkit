#!/usr/bin/env -S uv run
"""Contract tests for the shared dev:execute work-summary validator."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import check_repo


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = (REPOSITORY_ROOT / "plugins/dev/scripts/work_summary.py").resolve()
FULL_SHA = "a" * 40


def summary(
    *,
    classification: str = "planned",
    revision: str = FULL_SHA,
    pr_url: str = "https://github.com/example/project/pull/11",
) -> str:
    return (
        "## Work summary (dev:execute - 2026-08-03)\n"
        f"- PR: {pr_url}\n"
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
            adopter_root = Path(temporary_directory)
            path = adopter_root / "work-summary.md"
            path.write_text(text, encoding="utf-8")
            self.assertFalse((adopter_root / "scripts/work_summary.py").exists())
            return subprocess.run(
                [
                    "uv",
                    "run",
                    str(VALIDATOR),
                    "validate",
                    "--file",
                    str(path),
                ],
                cwd=adopter_root,
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

    def test_installed_validator_accepts_github_and_non_github_fixtures_from_adopter_cwd(self) -> None:
        fixtures = {
            "github-planned": summary(classification="planned"),
            "non-github-external": summary(
                classification="external",
                revision="B" * 40,
                pr_url="https://gitlab.example.com/group/project/-/merge_requests/11",
            ),
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


class BundledHelperLocationGuardTests(unittest.TestCase):
    def guard(self, surfaces: dict[str, str]) -> list[str]:
        return check_repo.bundled_helper_location_violations(surfaces)

    def test_executable_bare_helper_references_are_reported_deterministically(self) -> None:
        surfaces = {
            "plugins/dev/skills/execute/SKILL.md": (
                "Run `uv run scripts/work_summary.py validate --file summary.md`."
            ),
            ".codex/agents/verifier.toml": (
                'developer_instructions = "Execute `python scripts/work_summary.py validate`."'
            ),
        }

        violations = self.guard(surfaces)

        self.assertEqual(
            violations,
            self.guard(dict(reversed(tuple(surfaces.items())))),
        )
        self.assertEqual(len(violations), 2)
        for surface in surfaces:
            self.assertTrue(
                any(surface in violation for violation in violations),
                f"missing diagnostic for {surface}: {violations}",
            )

    def test_resolvable_and_descriptive_helper_references_are_accepted(self) -> None:
        surfaces = {
            "plugins/dev/skills/execute/SKILL.md": "\n".join(
                (
                    "Run `${CLAUDE_PLUGIN_ROOT}/scripts/work_summary.py validate`.",
                    "Run `../../scripts/work_summary.py validate`.",
                    "Run `<plugin-root>/scripts/work_summary.py validate`.",
                    "Run `/opt/installed/dev/scripts/work_summary.py validate`.",
                    "Run `$WORK_SUMMARY_HELPER validate` after resolving the supplied path.",
                    "Validator source: plugins/dev/scripts/work_summary.py.",
                    "The repository may contain scripts/work_summary.py.",
                )
            ),
            ".codex/agents/verifier.toml": "\n".join(
                (
                    'developer_instructions = "Run `${CLAUDE_PLUGIN_ROOT}/scripts/work_summary.py validate`."',
                    'source_note = "plugins/dev/scripts/work_summary.py"',
                    'prose = "A checkout can contain scripts/work_summary.py."',
                )
            ),
        }

        self.assertEqual(self.guard(surfaces), [])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
