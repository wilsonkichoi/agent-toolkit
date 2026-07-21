#!/usr/bin/env -S uv run
"""Contract tests for the feedback redaction and drafting CLI."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_CLI = REPOSITORY_ROOT / "plugins/dev/scripts/feedback_redact.py"


def run_cli(
    *args: str,
    stdin: str = "",
    env_override: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    return subprocess.run(
        ["uv", "run", str(FEEDBACK_CLI), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


class TestRedaction(unittest.TestCase):
    """Tests for the redact subcommand covering secret stripping and path sanitization."""

    def test_redacts_api_key(self) -> None:
        text = "config: api_key=sk-abc123def456ghi789jkl012mno"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("sk-abc123def456ghi789jkl012mno", result.stdout)
        self.assertIn("<REDACTED>", result.stdout)

    def test_redacts_github_token(self) -> None:
        text = "token: ghp_1234567890abcdefghijklmnopqrstuvwxyz1234"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("ghp_", result.stdout)
        self.assertIn("<REDACTED>", result.stdout)

    def test_redacts_bearer_token(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("eyJhbGci", result.stdout)
        self.assertIn("<REDACTED>", result.stdout)

    def test_redacts_aws_key(self) -> None:
        text = "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", result.stdout)
        self.assertIn("<REDACTED>", result.stdout)

    def test_redacts_home_path(self) -> None:
        text = "file at /Users/wilson/src/my-project/config.yaml"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertIn("~/", result.stdout)
        self.assertNotIn("/Users/wilson/", result.stdout)

    def test_redacts_linux_home_path(self) -> None:
        text = "path: /home/developer/workspace/secret.env"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertIn("~/", result.stdout)
        self.assertNotIn("/home/developer/", result.stdout)

    def test_redacts_private_repo_url(self) -> None:
        text = "see https://github.com/myorg/private-project/issues/42"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertIn("<private-repo>", result.stdout)
        self.assertNotIn("myorg/private-project", result.stdout)

    def test_preserves_target_repo_url(self) -> None:
        text = "related: https://github.com/wilsonkichoi/agent-toolkit/issues/10"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertIn("wilsonkichoi/agent-toolkit", result.stdout)
        self.assertNotIn("<private-repo>", result.stdout)

    def test_preserves_public_repo_when_declared(self) -> None:
        text = "see https://github.com/public-org/open-lib/pull/5"
        result = run_cli(
            "redact", "--text", text, "--public-repo", "public-org/open-lib"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("public-org/open-lib", result.stdout)
        self.assertNotIn("<private-repo>", result.stdout)

    def test_redacts_multiple_secrets_in_one_pass(self) -> None:
        text = (
            "token=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
            "and password: secret=hunter2 "
            "at /Users/admin/code/thing.py"
        )
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("ghp_", result.stdout)
        self.assertNotIn("/Users/admin/", result.stdout)
        self.assertIn("~/", result.stdout)

    def test_stdin_input(self) -> None:
        text = "key: api_key=mysecretvalue123"
        result = run_cli("redact", stdin=text)
        self.assertEqual(result.returncode, 0)
        self.assertIn("<REDACTED>", result.stdout)

    def test_redacts_github_pat(self) -> None:
        text = "github=github_pat_abcdefghijklmnopqrstuv123456"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("github_pat_", result.stdout)
        self.assertIn("<REDACTED>", result.stdout)

    def test_redacts_sk_proj_token(self) -> None:
        text = "openai=sk-proj-abcdefghijklmnopqrstuv"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("sk-proj-", result.stdout)
        self.assertIn("<REDACTED>", result.stdout)

    def test_redacts_connection_string(self) -> None:
        text = "db: postgresql://dbuser:dbpass@db.internal/app"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("dbuser:dbpass", result.stdout)
        self.assertIn("<REDACTED>", result.stdout)

    def test_redacts_standalone_private_repo(self) -> None:
        text = "tracker repository: acme/private-platform"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("acme/private-platform", result.stdout)
        self.assertIn("<private-repo>", result.stdout)

    def test_preserves_standalone_target_repo(self) -> None:
        text = "filed in wilsonkichoi/agent-toolkit"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertIn("wilsonkichoi/agent-toolkit", result.stdout)
        self.assertNotIn("<private-repo>", result.stdout)

    def test_redacts_non_home_absolute_path(self) -> None:
        text = "config at /opt/customer-alpha/config.yaml"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("/opt/customer-alpha", result.stdout)
        self.assertIn("<redacted-path>", result.stdout)


class TestDraft(unittest.TestCase):
    """Tests for the draft subcommand covering template rendering."""

    def _draft_input(self, **overrides: str) -> dict[str, str]:
        base = {
            "title": "Rule resolver fails on symlinked rules_dir",
            "category": "bug",
            "objective": "Fix rule resolution when rules_dir is a symlink.",
            "why": "Symlinked rules directories cause resolve_project_rules.py to reject valid paths.",
            "definition_of_done": "- [ ] Symlinked rules_dir resolves correctly\n- [ ] Test added",
        }
        base.update(overrides)
        return base

    def test_renders_bug_draft(self) -> None:
        data = self._draft_input()
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertEqual(draft["title"], data["title"])
        self.assertEqual(draft["label"], "bug")
        self.assertIn("## Objective", draft["body"])
        self.assertIn("## Why", draft["body"])
        self.assertIn("## Definition of Done", draft["body"])
        self.assertIn("## Relevant references\n\nNone", draft["body"])
        self.assertIn("gh issue create", draft["command"])

    def test_renders_enhancement_draft(self) -> None:
        data = self._draft_input(category="enhancement")
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertEqual(draft["label"], "enhancement")

    def test_renders_docs_draft(self) -> None:
        data = self._draft_input(category="docs")
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertEqual(draft["label"], "documentation")

    def test_renders_workflow_draft(self) -> None:
        data = self._draft_input(category="workflow")
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertEqual(draft["label"], "enhancement")

    def test_includes_references_when_provided(self) -> None:
        data = self._draft_input(references="See #10 and DESIGN.md section 4.")
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertIn("See #10", draft["body"])
        self.assertNotIn("None", draft["body"].split("## Relevant references")[1].split("##")[0])

    def test_includes_implementation_when_provided(self) -> None:
        data = self._draft_input(implementation="Add a symlink-aware resolve step.")
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertIn("## Suggested implementation", draft["body"])
        self.assertIn("symlink-aware", draft["body"])

    def test_omits_implementation_section_when_empty(self) -> None:
        data = self._draft_input()
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertNotIn("## Suggested implementation", draft["body"])

    def test_missing_required_field_fails(self) -> None:
        data = {"title": "Incomplete", "category": "bug"}
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required field", result.stderr)

    def test_draft_from_file(self) -> None:
        data = self._draft_input()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(data, tmp)
            tmp_path = tmp.name
        try:
            result = run_cli("draft", "--input", tmp_path)
            self.assertEqual(result.returncode, 0)
            draft = json.loads(result.stdout)
            self.assertEqual(draft["title"], data["title"])
        finally:
            os.unlink(tmp_path)

    def test_command_includes_target_repo(self) -> None:
        data = self._draft_input()
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertIn("wilsonkichoi/agent-toolkit", draft["command"])

    def test_command_uses_single_quotes_for_title(self) -> None:
        data = self._draft_input(title="Bug with $HOME and $(whoami)")
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertIn("--title '", draft["command"])

    def test_draft_redacts_title(self) -> None:
        data = self._draft_input(
            title="Token sk-proj-abcdefghijklmnopqrstuv in acme/private-platform"
        )
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertNotIn("sk-proj-", draft["title"])
        self.assertNotIn("acme/private-platform", draft["title"])
        self.assertIn("<REDACTED>", draft["title"])
        self.assertIn("<private-repo>", draft["title"])

    def test_draft_redacts_body_fields(self) -> None:
        data = self._draft_input(
            objective="Fix /Users/dev/secret path and postgresql://u:p@host/db"
        )
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertNotIn("/Users/dev/", draft["body"])
        self.assertNotIn("u:p@host", draft["body"])


class TestDuplicateSearch(unittest.TestCase):
    """Tests for the search subcommand covering duplicate detection.

    These tests use a fake gh to avoid network calls.
    """

    def setUp(self) -> None:
        self._tmp_dir = tempfile.mkdtemp()
        self._fake_gh_path = os.path.join(self._tmp_dir, "gh")
        self._calls_path = os.path.join(self._tmp_dir, "calls.log")
        self._scenario_path = os.path.join(self._tmp_dir, "scenario.json")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _write_fake_gh(self, responses: list[str]) -> None:
        """Write a fake gh that returns canned JSON responses in sequence."""
        script = textwrap.dedent(f"""\
            #!/bin/bash
            echo "$@" >> "{self._calls_path}"
            COUNTER_FILE="{self._tmp_dir}/counter"
            if [ ! -f "$COUNTER_FILE" ]; then
                echo "0" > "$COUNTER_FILE"
            fi
            INDEX=$(cat "$COUNTER_FILE")
            NEXT=$((INDEX + 1))
            echo "$NEXT" > "$COUNTER_FILE"
        """)
        for i, response in enumerate(responses):
            resp_file = os.path.join(self._tmp_dir, f"resp_{i}.json")
            with open(resp_file, "w") as f:
                f.write(response)
            script += f'    if [ "$INDEX" = "{i}" ]; then cat "{resp_file}"; exit 0; fi\n'
        script += "    echo '[]'; exit 0\n"

        with open(self._fake_gh_path, "w") as f:
            f.write(script)
        os.chmod(self._fake_gh_path, 0o755)

    def test_search_returns_results(self) -> None:
        results_json = json.dumps([
            {"number": 10, "title": "Rule resolver fails on cross-repo", "state": "OPEN", "url": "https://github.com/wilsonkichoi/agent-toolkit/issues/10"},
        ])
        self._write_fake_gh([results_json] * 4)

        env = {"PATH": f"{self._tmp_dir}:{os.environ.get('PATH', '')}"}
        result = run_cli("search", "rule resolver", "cross-repo", env_override=env)
        self.assertEqual(result.returncode, 0)
        items = json.loads(result.stdout)
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0]["number"], 10)

    def test_search_deduplicates(self) -> None:
        same_issue = json.dumps([
            {"number": 10, "title": "Same issue", "state": "OPEN", "url": "https://github.com/wilsonkichoi/agent-toolkit/issues/10"},
        ])
        self._write_fake_gh([same_issue] * 4)

        env = {"PATH": f"{self._tmp_dir}:{os.environ.get('PATH', '')}"}
        result = run_cli("search", "same issue", "same issue again", env_override=env)
        self.assertEqual(result.returncode, 0)
        items = json.loads(result.stdout)
        numbers = [item["number"] for item in items]
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_search_handles_no_results(self) -> None:
        self._write_fake_gh(["[]"] * 4)
        env = {"PATH": f"{self._tmp_dir}:{os.environ.get('PATH', '')}"}
        result = run_cli("search", "nonexistent topic xyz", env_override=env)
        self.assertEqual(result.returncode, 0)
        items = json.loads(result.stdout)
        self.assertEqual(items, [])

    def test_search_fails_when_all_queries_error(self) -> None:
        """When every gh call fails (rate limit, auth), search exits nonzero."""
        script = textwrap.dedent(f"""\
            #!/bin/bash
            echo "rate limit exceeded" >&2
            exit 1
        """)
        with open(self._fake_gh_path, "w") as f:
            f.write(script)
        os.chmod(self._fake_gh_path, 0o755)
        env = {"PATH": f"{self._tmp_dir}:{os.environ.get('PATH', '')}"}
        result = run_cli("search", "some query", env_override=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error:", result.stderr)

    def test_search_fails_when_one_state_entirely_fails(self) -> None:
        """Open queries succeed but all closed queries fail: partial-state failure."""
        call_count_file = os.path.join(self._tmp_dir, "counter")
        script = textwrap.dedent(f"""\
            #!/bin/bash
            COUNTER_FILE="{call_count_file}"
            if [ ! -f "$COUNTER_FILE" ]; then
                echo "0" > "$COUNTER_FILE"
            fi
            INDEX=$(cat "$COUNTER_FILE")
            NEXT=$((INDEX + 1))
            echo "$NEXT" > "$COUNTER_FILE"
            # First call is open state (succeeds), second is closed state (fails)
            if echo "$@" | grep -q "\\-\\-state closed"; then
                echo "rate limit" >&2
                exit 1
            fi
            echo '[]'
            exit 0
        """)
        with open(self._fake_gh_path, "w") as f:
            f.write(script)
        os.chmod(self._fake_gh_path, 0o755)
        env = {"PATH": f"{self._tmp_dir}:{os.environ.get('PATH', '')}"}
        result = run_cli("search", "some query", env_override=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("closed", result.stderr)


class TestGitHubAccess(unittest.TestCase):
    """Tests for the access subcommand covering unavailable GitHub scenarios.

    Uses a fake gh to simulate auth failures.
    """

    def setUp(self) -> None:
        self._tmp_dir = tempfile.mkdtemp()
        self._fake_gh_path = os.path.join(self._tmp_dir, "gh")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _write_fake_gh(self, auth_exit: int, perm_output: str = "") -> None:
        script = textwrap.dedent(f"""\
            #!/bin/bash
            if echo "$@" | grep -q "auth status"; then
                exit {auth_exit}
            fi
            if echo "$@" | grep -q "viewerPermission"; then
                echo "{perm_output}"
                exit 0
            fi
            exit 1
        """)
        with open(self._fake_gh_path, "w") as f:
            f.write(script)
        os.chmod(self._fake_gh_path, 0o755)

    def test_unauthenticated(self) -> None:
        self._write_fake_gh(auth_exit=1)
        env = {"PATH": f"{self._tmp_dir}:{os.environ.get('PATH', '')}"}
        result = run_cli("access", env_override=env)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertFalse(data["authenticated"])
        self.assertFalse(data["has_write"])

    def test_authenticated_with_write(self) -> None:
        self._write_fake_gh(auth_exit=0, perm_output="ADMIN")
        env = {"PATH": f"{self._tmp_dir}:{os.environ.get('PATH', '')}"}
        result = run_cli("access", env_override=env)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertTrue(data["authenticated"])
        self.assertTrue(data["has_write"])
        self.assertEqual(data["permission"], "ADMIN")

    def test_authenticated_without_write(self) -> None:
        self._write_fake_gh(auth_exit=0, perm_output="READ")
        env = {"PATH": f"{self._tmp_dir}:{os.environ.get('PATH', '')}"}
        result = run_cli("access", env_override=env)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertTrue(data["authenticated"])
        self.assertFalse(data["has_write"])
        self.assertEqual(data["permission"], "READ")

    def test_gh_binary_not_functional(self) -> None:
        # Simulate gh being entirely non-functional (exits 127).
        script = "#!/bin/bash\nexit 127\n"
        with open(self._fake_gh_path, "w") as f:
            f.write(script)
        os.chmod(self._fake_gh_path, 0o755)
        env = {"PATH": f"{self._tmp_dir}:{os.environ.get('PATH', '')}"}
        result = run_cli("access", env_override=env)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertFalse(data["authenticated"])
        self.assertFalse(data["has_write"])


class TestCrossRepoContext(unittest.TestCase):
    """Tests verifying that redaction handles cross-repository lifecycle context correctly."""

    def test_preserves_agent_toolkit_issue_references(self) -> None:
        text = (
            "Found during dev:verify of wilsonkichoi/agent-toolkit#10. "
            "The rule resolver at https://github.com/wilsonkichoi/agent-toolkit/blob/main/scripts/resolve.py "
            "failed when invoked from https://github.com/myorg/private-project/pull/42."
        )
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertIn("wilsonkichoi/agent-toolkit", result.stdout)
        self.assertNotIn("myorg/private-project", result.stdout)
        self.assertIn("<private-repo>", result.stdout)

    def test_redacts_private_task_identifiers_in_paths(self) -> None:
        text = "task LB-46 at /Users/dev/src/lagunabeach-md/docs/SPEC.md"
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("/Users/dev/", result.stdout)
        self.assertIn("~/", result.stdout)

    def test_preserves_skill_names_and_config_fields(self) -> None:
        text = (
            "Invoked dev:verify with tracker: github, "
            "github_primary_repo: wilsonkichoi/agent-toolkit, "
            "fork_contributions: true"
        )
        result = run_cli("redact", "--text", text)
        self.assertEqual(result.returncode, 0)
        self.assertIn("dev:verify", result.stdout)
        self.assertIn("tracker: github", result.stdout)
        self.assertIn("fork_contributions: true", result.stdout)


class TestWorkflowContract(unittest.TestCase):
    """Tests verifying the skill workflow contract.

    The workflow is: access check -> (if authenticated) search -> draft -> submit.
    The CLI never submits; it renders a command the LLM executes after human approval.
    When access is unavailable, search is skipped and the draft is the final output.
    """

    def test_draft_produces_command_but_does_not_execute(self) -> None:
        data = {
            "title": "Test issue",
            "category": "bug",
            "objective": "Fix the thing.",
            "why": "It is broken.",
            "definition_of_done": "- [ ] Thing works",
        }
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertIn("gh issue create", draft["command"])
        self.assertIn("--body-file", draft["command"])

    def test_offline_draft_path_produces_complete_output(self) -> None:
        """When access check shows no auth, draft still renders a complete issue."""
        tmp_dir = tempfile.mkdtemp()
        try:
            fake_gh = os.path.join(tmp_dir, "gh")
            with open(fake_gh, "w") as f:
                f.write("#!/bin/bash\nexit 1\n")
            os.chmod(fake_gh, 0o755)
            env = {"PATH": f"{tmp_dir}:{os.environ.get('PATH', '')}"}
            access = run_cli("access", env_override=env)
            self.assertEqual(access.returncode, 0)
            access_data = json.loads(access.stdout)
            self.assertFalse(access_data["authenticated"])

            data = {
                "title": "Offline test issue",
                "category": "enhancement",
                "objective": "Something useful.",
                "why": "Needed.",
                "definition_of_done": "- [ ] Done",
            }
            draft = run_cli("draft", stdin=json.dumps(data))
            self.assertEqual(draft.returncode, 0)
            draft_data = json.loads(draft.stdout)
            self.assertIn("gh issue create", draft_data["command"])
            self.assertIn("## Objective", draft_data["body"])
            self.assertEqual(draft_data["title"], "Offline test issue")
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_draft_with_redaction_prevents_secret_in_command(self) -> None:
        """A title with secrets gets redacted in both title and command output."""
        data = {
            "title": "Token sk-proj-abcdefghijklmnopqrstuv leaks",
            "category": "bug",
            "objective": "Stop the leak.",
            "why": "Security.",
            "definition_of_done": "- [ ] No leak",
        }
        result = run_cli("draft", stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0)
        draft = json.loads(result.stdout)
        self.assertNotIn("sk-proj-", draft["title"])
        self.assertNotIn("sk-proj-", draft["command"])


if __name__ == "__main__":
    unittest.main()
