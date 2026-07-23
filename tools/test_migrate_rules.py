#!/usr/bin/env -S uv run
"""Fixture tests for the rule-discovery migration, one per ADR 0001 migration case."""

from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MIGRATOR = REPOSITORY_ROOT / "plugins/dev/scripts/migrate_rules.py"
RESOLVER = REPOSITORY_ROOT / "plugins/dev/scripts/resolve_project_rules.py"


class MigrateRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repository = Path(self.temporary_directory.name) / "project"
        self.repository.mkdir()
        subprocess.run(
            ["git", "-C", str(self.repository), "init", "-b", "main"],
            check=True,
            capture_output=True,
        )
        self.write("AGENTS.md", "Project instructions.\n")

    def write(self, relative_path: str, content: str) -> Path:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def write_config(self, rules_section: str) -> Path:
        return self.write(
            ".agent-toolkit/dev.md",
            "---\n"
            "tracker: local\n"
            "context_file: AGENTS.md\n"
            "rules_dir: .agent-toolkit/rules/\n"
            "---\n\n"
            "# Development configuration\n\n"
            "## Rules\n\n"
            f"{rules_section}",
        )

    def migrate(self, *arguments: str) -> dict[str, Any]:
        result = subprocess.run(
            [
                "uv",
                "run",
                str(MIGRATOR),
                "--repo",
                str(self.repository),
                *arguments,
                "--format",
                "json",
            ],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"migration failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return json.loads(result.stdout)

    def resolve(self) -> subprocess.CompletedProcess[str]:
        subprocess.run(
            ["git", "-C", str(self.repository), "add", "."],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repository),
                "-c",
                "user.name=Migration Tests",
                "-c",
                "user.email=migration-tests@example.invalid",
                "commit",
                "-m",
                "fixture",
                "--allow-empty",
            ],
            check=True,
            capture_output=True,
        )
        return subprocess.run(
            [
                "uv",
                "run",
                str(RESOLVER),
                "--tracker-repo",
                str(self.repository),
                "--execution-repo",
                str(self.repository),
                "--execution-revision",
                "HEAD",
                "--format",
                "json",
            ],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def config_text(self) -> str:
        return (self.repository / ".agent-toolkit/dev.md").read_text(encoding="utf-8")

    def stamped_paths(self, plan: dict[str, Any]) -> set[str]:
        return {item["path"] for item in plan["files_stamped"]}

    def decision_paths(self, plan: dict[str, Any]) -> set[str]:
        return {item["path"] for item in plan["decisions_required"]}

    def test_case_one_pre_0056_descriptive_registry_stamps_and_clears(self) -> None:
        self.write_config(
            "- `@.agent-toolkit/rules/guard-suite.md` - always run the guard suite\n"
            "- `@.agent-toolkit/rules/naming.md` - naming conventions\n"
        )
        self.write(
            ".agent-toolkit/rules/guard-suite.md", "Run the guard suite.\n"
        )
        self.write(
            ".agent-toolkit/rules/naming.md",
            "---\nsummary: naming\n---\n\nUse kebab-case slugs.\n",
        )

        # These rules are invisible to both the resolver and the harness before migration.
        self.assertNotEqual(self.resolve().returncode, 0)

        plan = self.migrate("--apply")

        self.assertEqual(
            set(plan["registry_entries_removed"]),
            {".agent-toolkit/rules/guard-suite.md", ".agent-toolkit/rules/naming.md"},
        )
        self.assertEqual(
            self.stamped_paths(plan),
            {".agent-toolkit/rules/guard-suite.md", ".agent-toolkit/rules/naming.md"},
        )
        self.assertEqual(self.decision_paths(plan), set())
        self.assertNotIn("@.agent-toolkit/rules/guard-suite.md", self.config_text())

        # The pre-existing frontmatter key survives alongside the stamped tier.
        naming = (self.repository / ".agent-toolkit/rules/naming.md").read_text(
            encoding="utf-8"
        )
        self.assertTrue(naming.startswith("---\ntier: doctrine\nsummary: naming\n---\n"))
        self.assertIn("Use kebab-case slugs.", naming)

        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr)
        resolution = json.loads(result.stdout)
        self.assertEqual(
            {rule["path"] for rule in resolution["rules_loaded"]},
            {".agent-toolkit/rules/guard-suite.md", ".agent-toolkit/rules/naming.md"},
        )
        self.assertEqual(resolution["warnings"], [])

    def test_case_two_bare_registry_clears_without_touching_tiered_files(self) -> None:
        self.write_config(
            "@.agent-toolkit/rules/guard-suite.md\n@.agent-toolkit/rules/shell.md\n"
        )
        self.write(
            ".agent-toolkit/rules/guard-suite.md",
            "---\ntier: doctrine\n---\n\nRun the guard suite.\n",
        )
        self.write(
            ".agent-toolkit/rules/shell.md",
            """
            ---
            tier: gotcha
            triggers:
              paths:
                - "scripts/**/*.sh"
            ---
            Shell safety rule.
            """,
        )
        before = {
            path: (self.repository / path).read_text(encoding="utf-8")
            for path in (
                ".agent-toolkit/rules/guard-suite.md",
                ".agent-toolkit/rules/shell.md",
            )
        }

        plan = self.migrate("--apply")

        self.assertEqual(len(plan["registry_entries_removed"]), 2)
        self.assertEqual(self.stamped_paths(plan), set())
        self.assertEqual(self.decision_paths(plan), set())
        self.assertTrue(plan["config_section_rewritten"])
        for path, content in before.items():
            self.assertEqual(
                (self.repository / path).read_text(encoding="utf-8"),
                content,
                f"{path} must not be rewritten",
            )
        self.assertNotIn("@.agent-toolkit/rules/", self.config_text())

        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr)
        resolution = json.loads(result.stdout)
        self.assertEqual(
            {rule["path"] for rule in resolution["rules_loaded"]},
            {".agent-toolkit/rules/guard-suite.md"},
        )
        self.assertEqual(
            {rule["path"] for rule in resolution["rules_skipped"]},
            {".agent-toolkit/rules/shell.md"},
        )
        self.assertEqual(resolution["warnings"], [])

    def test_case_three_repository_with_no_rules_is_untouched(self) -> None:
        self.write_config("")
        config_before = self.config_text()

        plan = self.migrate("--apply")

        self.assertEqual(plan["registry_entries_removed"], [])
        self.assertEqual(plan["files_stamped"], [])
        self.assertEqual(plan["decisions_required"], [])
        self.assertEqual(plan["files_unchanged"], [])
        self.assertFalse(plan["changed"])
        self.assertEqual(self.config_text(), config_before)
        self.assertEqual(self.resolve().returncode, 0)

    def test_case_four_unregistered_files_are_decisions_never_guesses(self) -> None:
        self.write_config("@.agent-toolkit/rules/guard-suite.md\n")
        self.write(".agent-toolkit/rules/guard-suite.md", "Run the guard suite.\n")
        self.write(".agent-toolkit/rules/README.md", "How this directory works.\n")
        self.write(
            ".agent-toolkit/rules/notes/scratch.md", "Half-written thought.\n"
        )

        plan = self.migrate("--apply")

        self.assertEqual(
            self.stamped_paths(plan), {".agent-toolkit/rules/guard-suite.md"}
        )
        self.assertEqual(
            self.decision_paths(plan),
            {".agent-toolkit/rules/README.md", ".agent-toolkit/rules/notes/scratch.md"},
        )
        for relative_path, original in (
            (".agent-toolkit/rules/README.md", "How this directory works.\n"),
            (".agent-toolkit/rules/notes/scratch.md", "Half-written thought.\n"),
        ):
            self.assertEqual(
                (self.repository / relative_path).read_text(encoding="utf-8"),
                original,
                "an undecided file must never be rewritten",
            )

        # The decision is the human's; resolution stays stopped until they make it.
        result = self.resolve()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unclassified Markdown", result.stderr)

    def test_unfixable_classification_errors_are_decisions_even_when_registered(
        self,
    ) -> None:
        self.write_config(
            "@.agent-toolkit/rules/bad-tier.md\n"
            "@.agent-toolkit/rules/trigger-free.md\n"
            "@.agent-toolkit/rules/malformed.md\n"
        )
        self.write(
            ".agent-toolkit/rules/bad-tier.md", "---\ntier: advisory\n---\n\nBody.\n"
        )
        self.write(
            ".agent-toolkit/rules/trigger-free.md", "---\ntier: gotcha\n---\n\nBody.\n"
        )
        self.write(
            ".agent-toolkit/rules/malformed.md", "---\ntier: doctrine\n\nUnterminated.\n"
        )

        plan = self.migrate("--apply")

        self.assertEqual(self.stamped_paths(plan), set())
        self.assertEqual(
            self.decision_paths(plan),
            {
                ".agent-toolkit/rules/bad-tier.md",
                ".agent-toolkit/rules/trigger-free.md",
                ".agent-toolkit/rules/malformed.md",
            },
        )

    def test_migration_is_idempotent(self) -> None:
        self.write_config(
            "- `@.agent-toolkit/rules/guard-suite.md` - always run the guard suite\n"
        )
        self.write(".agent-toolkit/rules/guard-suite.md", "Run the guard suite.\n")

        self.migrate("--apply")
        config_after_first = self.config_text()
        rule_after_first = (
            self.repository / ".agent-toolkit/rules/guard-suite.md"
        ).read_text(encoding="utf-8")

        second = self.migrate("--apply")

        self.assertFalse(second["changed"])
        self.assertEqual(second["registry_entries_removed"], [])
        self.assertEqual(second["files_stamped"], [])
        self.assertEqual(second["decisions_required"], [])
        self.assertEqual(
            second["files_unchanged"], [".agent-toolkit/rules/guard-suite.md"]
        )
        self.assertEqual(self.config_text(), config_after_first)
        self.assertEqual(
            (self.repository / ".agent-toolkit/rules/guard-suite.md").read_text(
                encoding="utf-8"
            ),
            rule_after_first,
        )

    def test_dry_run_is_the_default_and_writes_nothing(self) -> None:
        self.write_config("@.agent-toolkit/rules/guard-suite.md\n")
        self.write(".agent-toolkit/rules/guard-suite.md", "Run the guard suite.\n")
        config_before = self.config_text()
        rule_before = (
            self.repository / ".agent-toolkit/rules/guard-suite.md"
        ).read_text(encoding="utf-8")

        plan = self.migrate()

        self.assertFalse(plan["applied"])
        self.assertTrue(plan["changed"])
        self.assertEqual(
            self.stamped_paths(plan), {".agent-toolkit/rules/guard-suite.md"}
        )
        self.assertEqual(self.config_text(), config_before)
        self.assertEqual(
            (self.repository / ".agent-toolkit/rules/guard-suite.md").read_text(
                encoding="utf-8"
            ),
            rule_before,
        )


if __name__ == "__main__":
    unittest.main()
