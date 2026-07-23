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
        self.run_git("init", "-b", "main")

    def run_git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.execution_repository), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            "git command failed\n"
            f"command: git -C {self.execution_repository} {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        return result.stdout.strip()

    def commit_execution_repository(self, message: str = "test fixture") -> str:
        self.run_git("add", ".")
        staged = subprocess.run(
            [
                "git",
                "-C",
                str(self.execution_repository),
                "diff",
                "--cached",
                "--quiet",
            ],
            check=False,
        )
        if staged.returncode == 1:
            self.run_git(
                "-c",
                "user.name=Resolver Tests",
                "-c",
                "user.email=resolver-tests@example.invalid",
                "commit",
                "-m",
                message,
            )
        elif staged.returncode != 0:
            self.fail(f"git diff --cached --quiet failed with {staged.returncode}")
        return self.run_git("rev-parse", "HEAD")

    def write(self, repository: Path, relative_path: str, content: str) -> Path:
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def write_config(
        self,
        repository: Path,
        *,
        config_path: str = ".agent-toolkit/dev.md",
        context_file: str = "AGENTS.md",
        rules_dir: str = ".agent-toolkit/rules/",
        rules_section: str = "",
    ) -> Path:
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
            f"{rules_section}\n",
        )

    def resolver_process(
        self,
        *arguments: str,
        execution_revision: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        revision = execution_revision or self.commit_execution_repository()
        command = [
            "uv",
            "run",
            str(RESOLVER),
            "--tracker-repo",
            str(self.tracker_repository),
            "--execution-repo",
            str(self.execution_repository),
            "--execution-revision",
            revision,
            *arguments,
            "--format",
            "json",
        ]
        return subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_resolver(self, *arguments: str) -> dict[str, Any]:
        result = self.resolver_process(*arguments)
        self.assertEqual(
            result.returncode,
            0,
            "resolver command failed\n"
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

    def assert_resolver_fails(
        self,
        expected_error: str,
        *arguments: str,
        execution_revision: str | None = None,
    ) -> str:
        result = self.resolver_process(
            *arguments,
            execution_revision=execution_revision,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected_error, result.stderr)
        return result.stderr

    def loaded_rules_by_name(self, result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {Path(rule["path"]).name: rule for rule in result["rules_loaded"]}

    def skipped_rules_by_name(
        self, result: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        return {Path(rule["path"]).name: rule for rule in result["rules_skipped"]}

    def excluded_rules_by_name(
        self, result: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        return {Path(rule["path"]).name: rule for rule in result["rules_excluded"]}

    def execution_path(self, reported_path: str) -> Path:
        path = Path(reported_path)
        if not path.is_absolute():
            path = self.execution_repository / path
        return path.resolve()

    def write_doctrine(self, relative_path: str, body: str = "Doctrine body.") -> Path:
        return self.write(
            self.execution_repository,
            relative_path,
            f"---\ntier: doctrine\n---\n\n{body}\n",
        )

    def test_cross_repository_uses_execution_instructions_and_path_gotcha(self) -> None:
        tracker_agents = self.write(
            self.tracker_repository,
            "AGENTS.md",
            "Tracker instructions must not be selected.\n",
        )
        self.write_config(self.tracker_repository)
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
        self.assertEqual(result["execution_revision"], self.run_git("rev-parse", "HEAD"))
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

    def test_execution_checkout_must_match_expected_task_revision(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Main instructions.\n")
        self.write_config(self.execution_repository)
        self.commit_execution_repository("main revision")
        self.run_git("checkout", "-b", "task/test-revision")
        self.write(self.execution_repository, "AGENTS.md", "Task instructions.\n")
        task_revision = self.commit_execution_repository("task revision")
        self.run_git("checkout", "main")

        self.assert_resolver_fails(
            "does not match expected execution revision",
            execution_revision=task_revision,
        )

    def test_revision_mismatch_error_states_the_stop_and_the_remedy(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Main instructions.\n")
        self.write_config(self.execution_repository)
        self.commit_execution_repository("main revision")
        self.run_git("checkout", "-b", "task/test-remedy")
        self.write(self.execution_repository, "AGENTS.md", "Task instructions.\n")
        task_revision = self.commit_execution_repository("task revision")
        self.run_git("checkout", "main")

        result = self.resolver_process(execution_revision=task_revision)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        for expected in (
            "this is a hard stop",
            "git worktree add --detach",
            task_revision,
            "Never substitute another revision",
        ):
            self.assertIn(expected, result.stderr)

    def test_discovery_loads_every_classified_file_without_registration(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
        doctrine_rule = self.write_doctrine(".agent-toolkit/rules/guard-suite.md")
        nested_doctrine = self.write_doctrine(
            ".agent-toolkit/rules/backend/deep/migrations.md"
        )
        matching_gotcha = self.write(
            self.execution_repository,
            ".agent-toolkit/rules/nested/shell.md",
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
        unmatched_gotcha = self.write(
            self.execution_repository,
            ".agent-toolkit/rules/nested/docs.md",
            """
            ---
            tier: gotcha
            triggers:
              paths:
                - docs/README.md
            ---
            Documentation rule.
            """,
        )

        result = self.run_resolver(
            "--objective",
            "Harden the release script",
            "--definition-of-done",
            "The release script is covered",
            "--changed-path",
            "scripts/release.sh",
        )

        loaded = self.loaded_rules_by_name(result)
        self.assertEqual(
            set(loaded),
            {doctrine_rule.name, nested_doctrine.name, matching_gotcha.name},
        )
        self.assertEqual(loaded[nested_doctrine.name]["tier"], "doctrine")
        self.assertEqual(
            loaded[nested_doctrine.name]["path"],
            ".agent-toolkit/rules/backend/deep/migrations.md",
        )
        self.assertEqual(set(self.skipped_rules_by_name(result)), {unmatched_gotcha.name})
        self.assertEqual(result["rules_excluded"], [])
        self.assertEqual(result["warnings"], [])

    def test_each_unclassified_class_is_a_hard_stop(self) -> None:
        unclassified_classes = {
            "no frontmatter": "Rule body with no frontmatter at all.\n",
            "malformed frontmatter": "---\ntier: doctrine\n\nUnterminated frontmatter.\n",
            "frontmatter does not declare tier": (
                "---\nteir: gotcha\n---\n\nMisspelled tier key.\n"
            ),
            "unknown tier 'advisory'": "---\ntier: advisory\n---\n\nUnknown tier.\n",
            "tier: gotcha declares no trigger": (
                "---\ntier: gotcha\n---\n\nTrigger-free gotcha.\n"
            ),
        }
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
        self.write_doctrine(".agent-toolkit/rules/valid-doctrine.md")
        offender = self.execution_repository / ".agent-toolkit/rules/offender.md"
        for reason, content in unclassified_classes.items():
            with self.subTest(reason=reason):
                offender.write_text(content, encoding="utf-8")
                try:
                    stderr = self.assert_resolver_fails("unclassified Markdown")
                    self.assertIn(f".agent-toolkit/rules/offender.md ({reason})", stderr)
                    self.assertNotIn("valid-doctrine.md", stderr)
                finally:
                    offender.unlink()
        self.assertEqual(
            set(self.loaded_rules_by_name(self.run_resolver())), {"valid-doctrine.md"}
        )

    def test_unclassified_diagnostic_is_ordered_and_states_both_remedies(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
        offenders = (
            ".agent-toolkit/rules/a-no-frontmatter.md",
            ".agent-toolkit/rules/b-no-tier.md",
            ".agent-toolkit/rules/nested/c-unknown-tier.md",
        )
        self.write(
            self.execution_repository, offenders[0], "No frontmatter here.\n"
        )
        self.write(
            self.execution_repository, offenders[1], "---\nname: b\n---\n\nNo tier.\n"
        )
        self.write(
            self.execution_repository, offenders[2], "---\ntier: maybe\n---\n\nBad.\n"
        )

        stderr = self.assert_resolver_fails("unclassified Markdown")

        positions = [stderr.index(path) for path in offenders]
        self.assertEqual(positions, sorted(positions), stderr)
        self.assertIn("`tier: doctrine`", stderr)
        self.assertIn("`tier: gotcha` with at least one trigger", stderr)
        self.assertIn("`tier: none`", stderr)

    def test_tier_none_excludes_non_rule_markdown(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
        doctrine_rule = self.write_doctrine(".agent-toolkit/rules/guard-suite.md")
        readme = self.write(
            self.execution_repository,
            ".agent-toolkit/rules/README.md",
            """
            ---
            tier: none
            ---
            Notes for human maintainers; not an agent instruction.
            """,
        )

        result = self.run_resolver()

        self.assertEqual(set(self.loaded_rules_by_name(result)), {doctrine_rule.name})
        excluded = self.excluded_rules_by_name(result)
        self.assertEqual(set(excluded), {readme.name})
        self.assertEqual(excluded[readme.name]["tier"], "none")
        self.assertEqual(excluded[readme.name]["path"], ".agent-toolkit/rules/README.md")

    def test_unmarked_rule_file_still_fails_beside_an_excluded_readme(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
        self.write(
            self.execution_repository,
            ".agent-toolkit/rules/README.md",
            "---\ntier: none\n---\n\nDirectory notes.\n",
        )
        self.write(
            self.execution_repository,
            ".agent-toolkit/rules/unmarked.md",
            "An unmarked rule file must never be treated as excluded.\n",
        )

        stderr = self.assert_resolver_fails("unclassified Markdown")

        self.assertIn(".agent-toolkit/rules/unmarked.md (no frontmatter)", stderr)
        self.assertNotIn("README.md", stderr)

    def test_directory_of_only_excluded_markdown_resolves_to_zero_rules(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
        for relative_path in (
            ".agent-toolkit/rules/README.md",
            ".agent-toolkit/rules/notes/decisions.md",
        ):
            self.write(
                self.execution_repository,
                relative_path,
                "---\ntier: none\n---\n\nHuman notes.\n",
            )

        result = self.run_resolver()

        self.assertEqual(result["rules_loaded"], [])
        self.assertEqual(result["rules_skipped"], [])
        self.assertEqual(len(result["rules_excluded"]), 2)

    def test_import_line_inside_a_rule_file_is_a_hard_stop(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
        self.write(
            self.execution_repository,
            ".agent-toolkit/rules/chain/one.md",
            "@.agent-toolkit/rules/chain/two.md\n",
        )
        self.write_doctrine(".agent-toolkit/rules/chain/two.md")

        stderr = self.assert_resolver_fails("`@` import line")

        self.assertIn(".agent-toolkit/rules/chain/one.md", stderr)

    def test_rule_symlink_escaping_the_repository_is_a_hard_stop(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
        self.write_doctrine(".agent-toolkit/rules/guard-suite.md")
        outside_rule = self.write(
            Path(self.temporary_directory.name),
            "outside/leaked.md",
            "---\ntier: doctrine\n---\n\nOutside the execution repository.\n",
        )
        link = self.execution_repository / ".agent-toolkit/rules/leaked.md"
        link.symlink_to(outside_rule)

        self.assert_resolver_fails("escapes execution repository")

    def test_missing_configured_context_file_is_a_hard_stop(self) -> None:
        self.write_config(self.execution_repository, context_file="AGENTS.md")
        self.write_doctrine(".agent-toolkit/rules/guard-suite.md")

        self.assert_resolver_fails("required file is missing")

    def test_rules_dir_on_a_harness_autoload_path_warns_without_stopping(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository, rules_dir=".claude/rules/")
        doctrine_rule = self.write_doctrine(".claude/rules/guard-suite.md")

        result = self.run_resolver()

        self.assertEqual(set(self.loaded_rules_by_name(result)), {doctrine_rule.name})
        self.assertEqual(len(result["warnings"]), 1)
        warning = result["warnings"][0]
        self.assertIn(".claude/rules", warning)
        self.assertIn("gotcha", warning)
        self.assertIn("never a stop", warning)

    def test_leftover_registry_imports_warn_without_stopping(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(
            self.execution_repository,
            rules_section="@.agent-toolkit/rules/guard-suite.md\n",
        )
        doctrine_rule = self.write_doctrine(".agent-toolkit/rules/guard-suite.md")

        result = self.run_resolver()

        self.assertEqual(set(self.loaded_rules_by_name(result)), {doctrine_rule.name})
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn(
            ".agent-toolkit/rules/guard-suite.md", result["warnings"][0]
        )
        self.assertIn("dev:setup", result["warnings"][0])

    def test_objective_and_definition_of_done_triggers_load_gotchas(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
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

    def test_unmatched_gotcha_is_reported_as_skipped(self) -> None:
        self.write(self.execution_repository, "AGENTS.md", "Project instructions.\n")
        self.write_config(self.execution_repository)
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
        legacy_rule = self.write_doctrine(".claude/rules/legacy.md")
        self.write(
            self.execution_repository,
            ".claude/dev.md",
            "---\ntracker: linear\n---\n\n## Rules\n",
        )

        result = self.run_resolver()

        instruction_paths = {
            self.execution_path(path) for path in result["project_instructions"]
        }
        self.assertIn(claude_context.resolve(), instruction_paths)
        loaded = self.loaded_rules_by_name(result)
        self.assertEqual(set(loaded), {legacy_rule.name})
        self.assertEqual(loaded[legacy_rule.name]["tier"], "doctrine")

    def test_missing_project_instructions_is_an_error(self) -> None:
        self.write(
            self.execution_repository,
            ".agent-toolkit/dev.md",
            "---\n"
            "tracker: linear\n"
            "rules_dir: .agent-toolkit/rules/\n"
            "---\n\n"
            "## Rules\n",
        )

        self.assert_resolver_fails("execution repository has no project instructions")

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
            "## Rules\n",
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

        for changed_path in (
            "scripts/release.sh",
            "scripts/init/check-init.sh",
            "scripts/init/deep/check-init.sh",
        ):
            with self.subTest(changed_path=changed_path):
                result = self.run_resolver("--changed-path", changed_path)
                loaded = self.loaded_rules_by_name(result)
                self.assertEqual(set(loaded), {shell_rule.name})
                self.assertEqual(loaded[shell_rule.name]["tier"], "gotcha")


if __name__ == "__main__":
    unittest.main()
