#!/usr/bin/env -S uv run
"""Black-box contract tests for the project-rule resolver CLI."""

from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESOLVER = REPOSITORY_ROOT / "plugins/dev/scripts/resolve_project_rules.py"


class ResolveProjectRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.tracker_repository = root / "tracker-repository"
        self.execution_repository = root / "execution-repository"
        self.tracker_repository.mkdir()
        self.execution_repository.mkdir()

    def write(self, repository: Path, relative_path: str, content: str) -> Path:
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def write_config(
        self,
        repository: Path,
        imports: list[str],
        *,
        config_path: str = ".agent-toolkit/dev.md",
        context_file: str = "AGENTS.md",
        rules_dir: str = ".agent-toolkit/rules/",
    ) -> Path:
        import_lines = "\n".join(f"@{path}" for path in imports)
        return self.write(
            repository,
            config_path,
            "---\n"
            "tracker: linear\n"
            f"context_file: {context_file}\n"
            f"rules_dir: {rules_dir}\n"
            "---\n\n"
            "# Development configuration\n\n"
            "## Rules\n\n"
            f"{import_lines}\n",
        )

    def run_resolver(self, *arguments: str) -> dict[str, Any]:
        command = [
            "uv",
            "run",
            str(RESOLVER),
            "--tracker-repo",
            str(self.tracker_repository),
            "--execution-repo",
            str(self.execution_repository),
            *arguments,
            "--format",
            "json",
        ]
        result = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            "resolver command failed\n"
            f"command: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            self.fail(
                f"resolver did not emit valid JSON: {error}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

    def loaded_rules_by_name(self, result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {Path(rule["path"]).name: rule for rule in result["rules_loaded"]}

    def skipped_rules_by_name(
        self, result: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        return {Path(rule["path"]).name: rule for rule in result["rules_skipped"]}

    def execution_path(self, reported_path: str) -> Path:
        path = Path(reported_path)
        if not path.is_absolute():
            path = self.execution_repository / path
        return path.resolve()

    def test_cross_repository_uses_execution_instructions_and_path_gotcha(self) -> None:
        tracker_agents = self.write(
            self.tracker_repository,
            "AGENTS.md",
            "Tracker instructions must not be selected.\n",
        )
        self.write_config(
            self.tracker_repository,
            [".agent-toolkit/rules/tracker-shell.md"],
        )
        tracker_rule = self.write(
            self.tracker_repository,
            ".agent-toolkit/rules/tracker-shell.md",
            """
            ---
            tier: gotcha
            triggers:
              paths:
                - scripts/release.sh
            ---
            This tracker-side decoy must not load.
            """,
        )

        execution_agents = self.write(
            self.execution_repository,
            "AGENTS.md",
            "Execution repository instructions.\n",
        )
        execution_config = self.write_config(
            self.execution_repository,
            [
                ".project-rules/baseline.md",
                ".project-rules/shell-safety.md",
                ".project-rules/docs-only.md",
            ],
            config_path=".agent/dev.md",
            rules_dir=".project-rules/",
        )
        baseline_rule = self.write(
            self.execution_repository,
            ".project-rules/baseline.md",
            """
            ---
            tier: doctrine
            ---
            Always load this execution doctrine.
            """,
        )
        shell_rule = self.write(
            self.execution_repository,
            ".project-rules/shell-safety.md",
            """
            ---
            tier: gotcha
            triggers:
              paths:
                - scripts/release.sh
            ---
            Apply shell release safety checks.
            """,
        )
        docs_rule = self.write(
            self.execution_repository,
            ".project-rules/docs-only.md",
            """
            ---
            tier: gotcha
            triggers:
              paths:
                - docs/README.md
            ---
            Apply documentation checks.
            """,
        )

        result = self.run_resolver(
            "--objective",
            "Update the release helper",
            "--definition-of-done",
            "The shell script is tested",
            "--changed-path",
            "scripts/release.sh",
        )

        self.assertEqual(
            Path(result["tracker_repository"]), self.tracker_repository.resolve()
        )
        self.assertEqual(
            Path(result["execution_repository"]), self.execution_repository.resolve()
        )
        instruction_paths = {
            self.execution_path(path) for path in result["project_instructions"]
        }
        self.assertIn(execution_agents.resolve(), instruction_paths)
        self.assertIn(execution_config.resolve(), instruction_paths)
        self.assertNotIn(tracker_agents.resolve(), instruction_paths)

        loaded = self.loaded_rules_by_name(result)
        self.assertEqual(set(loaded), {baseline_rule.name, shell_rule.name})
        self.assertEqual(loaded[baseline_rule.name]["tier"], "doctrine")
        self.assertEqual(loaded[shell_rule.name]["tier"], "gotcha")
        self.assertTrue(loaded[baseline_rule.name]["matched_by"])
        self.assertTrue(loaded[shell_rule.name]["matched_by"])

        skipped = self.skipped_rules_by_name(result)
        self.assertIn(docs_rule.name, skipped)
        all_reported_paths = {
            self.execution_path(rule["path"])
            for rule in result["rules_loaded"] + result["rules_skipped"]
        }
        self.assertNotIn(tracker_rule.resolve(), all_reported_paths)

    def test_codex_resolves_three_import_indirections_to_terminal_rule(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Codex instructions.\n")
        self.write_config(
            self.execution_repository,
            [".agent-toolkit/rules/chain/one.md"],
        )
        self.write(
            self.execution_repository,
            ".agent-toolkit/rules/chain/one.md",
            "@.agent-toolkit/rules/chain/two.md\n",
        )
        self.write(
            self.execution_repository,
            ".agent-toolkit/rules/chain/two.md",
            "@.agent-toolkit/rules/chain/three.md\n",
        )
        terminal_rule = self.write(
            self.execution_repository,
            ".agent-toolkit/rules/chain/three.md",
            """
            ---
            tier: doctrine
            ---
            Terminal Codex rule reached without harness import expansion.
            """,
        )

        result = self.run_resolver()

        loaded_paths = {
            self.execution_path(rule["path"]) for rule in result["rules_loaded"]
        }
        self.assertIn(terminal_rule.resolve(), loaded_paths)
        terminal = self.loaded_rules_by_name(result)[terminal_rule.name]
        self.assertEqual(terminal["tier"], "doctrine")
        self.assertTrue(terminal["matched_by"])

    def test_objective_and_definition_of_done_triggers_load_gotchas(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(
            self.execution_repository,
            [
                ".agent-toolkit/rules/key-rotation.md",
                ".agent-toolkit/rules/audit-proof.md",
            ],
        )
        objective_rule = self.write(
            self.execution_repository,
            ".agent-toolkit/rules/key-rotation.md",
            """
            ---
            tier: gotcha
            triggers:
              objective:
                - rotate encryption keys
            ---
            Key rotation procedure.
            """,
        )
        dod_rule = self.write(
            self.execution_repository,
            ".agent-toolkit/rules/audit-proof.md",
            """
            ---
            tier: gotcha
            triggers:
              definition_of_done:
                - attach audit evidence
            ---
            Audit evidence procedure.
            """,
        )

        result = self.run_resolver(
            "--objective",
            "Rotate encryption keys for the payments service",
            "--definition-of-done",
            "Attach audit evidence to the completed task",
        )

        loaded = self.loaded_rules_by_name(result)
        self.assertEqual(set(loaded), {objective_rule.name, dod_rule.name})
        self.assertEqual(loaded[objective_rule.name]["tier"], "gotcha")
        self.assertEqual(loaded[dod_rule.name]["tier"], "gotcha")
        self.assertTrue(loaded[objective_rule.name]["matched_by"])
        self.assertTrue(loaded[dod_rule.name]["matched_by"])

    def test_legacy_terminal_rule_without_metadata_defaults_to_doctrine(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(
            self.execution_repository,
            [".agent-toolkit/rules/legacy.md"],
        )
        legacy_rule = self.write(
            self.execution_repository,
            ".agent-toolkit/rules/legacy.md",
            "Legacy rule content with no frontmatter.\n",
        )

        result = self.run_resolver()

        loaded = self.loaded_rules_by_name(result)
        self.assertEqual(set(loaded), {legacy_rule.name})
        self.assertEqual(loaded[legacy_rule.name]["tier"], "doctrine")
        self.assertTrue(loaded[legacy_rule.name]["matched_by"])

    def test_unmatched_gotcha_is_reported_as_skipped(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(
            self.execution_repository,
            [".agent-toolkit/rules/database-migration.md"],
        )
        gotcha_rule = self.write(
            self.execution_repository,
            ".agent-toolkit/rules/database-migration.md",
            """
            ---
            tier: gotcha
            triggers:
              paths:
                - migrations/001.sql
              objective:
                - migrate the database
              definition_of_done:
                - rollback tested
            ---
            Database migration safety procedure.
            """,
        )

        result = self.run_resolver(
            "--objective",
            "Update the user guide",
            "--definition-of-done",
            "Documentation renders successfully",
            "--changed-path",
            "docs/user-guide.md",
        )

        self.assertEqual(result["rules_loaded"], [])
        skipped = self.skipped_rules_by_name(result)
        self.assertIn(gotcha_rule.name, skipped)
        self.assertEqual(skipped[gotcha_rule.name]["tier"], "gotcha")

    def test_unconfigured_legacy_config_preserves_claude_rule_fallback(self) -> None:
        claude_context = self.write(
            self.execution_repository,
            "CLAUDE.md",
            "Legacy Claude project instructions.\n",
        )
        self.write(
            self.execution_repository,
            "AGENTS.md",
            "Newer context file must not replace the legacy fallback.\n",
        )
        legacy_rule = self.write(
            self.execution_repository,
            ".claude/rules/legacy.md",
            "Legacy correctness rule.\n",
        )
        self.write(
            self.execution_repository,
            ".claude/dev.md",
            "---\ntracker: linear\n---\n\n## Rules\n\n@.claude/rules/legacy.md\n",
        )

        result = self.run_resolver()

        instruction_paths = {
            self.execution_path(path) for path in result["project_instructions"]
        }
        self.assertIn(claude_context.resolve(), instruction_paths)
        loaded = self.loaded_rules_by_name(result)
        self.assertEqual(set(loaded), {legacy_rule.name})
        self.assertEqual(loaded[legacy_rule.name]["tier"], "doctrine")

    def test_config_and_trigger_metadata_accept_inline_comments(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write(
            self.execution_repository,
            ".agent-toolkit/dev.md",
            "---\n"
            "tracker: linear\n"
            "context_file: AGENTS.md  # project context\n"
            "rules_dir: .agent-toolkit/rules/  # promoted rules\n"
            "---\n\n"
            "## Rules\n\n"
            "@.agent-toolkit/rules/shell.md\n",
        )
        shell_rule = self.write(
            self.execution_repository,
            ".agent-toolkit/rules/shell.md",
            """
            ---
            tier: gotcha  # conditional rule
            triggers:
              paths:
                - "scripts/**/*.sh"  # shell files
            ---
            Shell safety rule.
            """,
        )

        result = self.run_resolver("--changed-path", "scripts/init/check-init.sh")

        loaded = self.loaded_rules_by_name(result)
        self.assertEqual(set(loaded), {shell_rule.name})
        self.assertEqual(loaded[shell_rule.name]["tier"], "gotcha")


if __name__ == "__main__":
    unittest.main()
