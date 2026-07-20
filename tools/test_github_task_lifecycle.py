#!/usr/bin/env -S uv run
"""Black-box contract tests for the GitHub task-lifecycle CLI."""

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
LIFECYCLE_CLI = (
    REPOSITORY_ROOT / "plugins/dev/scripts/github_task_lifecycle.py"
)
TEST_REPOSITORY = "example/project"


FAKE_GH = r'''#!/usr/bin/env -S uv run --script
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


scenario_path = Path(os.environ["GITHUB_LIFECYCLE_TEST_SCENARIO"])
calls_path = Path(os.environ["GITHUB_LIFECYCLE_TEST_CALLS"])
arguments = sys.argv[1:]

with calls_path.open("a", encoding="utf-8") as calls_file:
    calls_file.write(json.dumps(arguments) + "\n")

if len(arguments) < 2 or arguments[0] != "issue":
    print(f"unexpected gh invocation: {arguments!r}", file=sys.stderr)
    raise SystemExit(97)

operation = arguments[1]
scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
responses = scenario.get("responses", {}).get(operation, [])
indexes = scenario.setdefault("indexes", {})
index = indexes.get(operation, 0)
if index >= len(responses):
    print(
        f"unexpected gh issue {operation} invocation #{index + 1}: {arguments!r}",
        file=sys.stderr,
    )
    raise SystemExit(98)

response = responses[index]
indexes[operation] = index + 1
scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

stdout = response.get("stdout", "")
if not isinstance(stdout, str):
    stdout = json.dumps(stdout)
if stdout:
    sys.stdout.write(stdout)
    if not stdout.endswith("\n"):
        sys.stdout.write("\n")

stderr = response.get("stderr", "")
if stderr:
    sys.stderr.write(stderr)
    if not stderr.endswith("\n"):
        sys.stderr.write("\n")

raise SystemExit(response.get("returncode", 0))
'''


class GitHubTaskLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.fake_bin = root / "bin"
        self.fake_bin.mkdir()
        self.scenario_path = root / "scenario.json"
        self.calls_path = root / "calls.jsonl"
        self.calls_path.write_text("", encoding="utf-8")
        fake_gh = self.fake_bin / "gh"
        fake_gh.write_text(textwrap.dedent(FAKE_GH), encoding="utf-8")
        fake_gh.chmod(0o755)

    def response(
        self,
        stdout: dict[str, Any] | None = None,
        *,
        returncode: int = 0,
        stderr: str = "",
    ) -> dict[str, Any]:
        return {
            "stdout": stdout or "",
            "returncode": returncode,
            "stderr": stderr,
        }

    def issue(
        self,
        *labels: str,
        state: str = "OPEN",
        assignees: tuple[str, ...] = (),
        comments: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return {
            "state": state,
            "labels": [{"name": label} for label in labels],
            "assignees": [{"login": login} for login in assignees],
            "comments": [{"body": body} for body in comments],
        }

    def lifecycle_process(
        self,
        command: str,
        *arguments: str,
        views: tuple[dict[str, Any], ...] = (),
        edits: tuple[dict[str, Any], ...] = (),
        comments: tuple[dict[str, Any], ...] = (),
        issue_number: int = 10,
    ) -> subprocess.CompletedProcess[str]:
        scenario = {
            "responses": {
                "view": list(views),
                "edit": list(edits),
                "comment": list(comments),
            },
            "indexes": {},
        }
        self.scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        self.calls_path.write_text("", encoding="utf-8")
        environment = os.environ.copy()
        environment["PATH"] = f"{self.fake_bin}{os.pathsep}{environment['PATH']}"
        environment["GITHUB_LIFECYCLE_TEST_SCENARIO"] = str(self.scenario_path)
        environment["GITHUB_LIFECYCLE_TEST_CALLS"] = str(self.calls_path)
        environment["GH_REPO"] = "wrong/inferred-repository"
        return subprocess.run(
            [
                "uv",
                "run",
                str(LIFECYCLE_CLI),
                command,
                "--repo",
                TEST_REPOSITORY,
                "--issue",
                str(issue_number),
                *arguments,
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def gh_calls(self) -> list[list[str]]:
        return [
            json.loads(line)
            for line in self.calls_path.read_text(encoding="utf-8").splitlines()
        ]

    def option_values(self, arguments: list[str], option: str) -> list[str]:
        values: list[str] = []
        for index, argument in enumerate(arguments):
            if argument == option and index + 1 < len(arguments):
                values.append(arguments[index + 1])
            elif argument.startswith(f"{option}="):
                values.append(argument.split("=", 1)[1])
        return values

    def json_fields(self, arguments: list[str]) -> set[str]:
        fields: set[str] = set()
        for value in self.option_values(arguments, "--json"):
            fields.update(field.strip() for field in value.split(","))
        return fields

    def assert_explicit_repository(self, calls: list[list[str]]) -> None:
        self.assertTrue(calls, "expected at least one gh call")
        for call in calls:
            self.assertEqual(call[:1], ["issue"])
            self.assertEqual(
                self.option_values(call, "--repo"),
                [TEST_REPOSITORY],
                f"gh call did not explicitly target the configured repository: {call}",
            )

    def assert_issue_operation(
        self,
        call: list[str],
        operation: str,
        issue_number: int = 10,
    ) -> None:
        self.assertEqual(call[:2], ["issue", operation])
        self.assertIn(str(issue_number), call)

    def assert_failure_contains(
        self,
        result: subprocess.CompletedProcess[str],
        expected: str,
    ) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected.lower(), result.stderr.lower())

    def test_issue_10_without_labels_fails_before_any_mutation(self) -> None:
        result = self.lifecycle_process(
            "validate-todo",
            views=(self.response(self.issue()),),
        )

        self.assert_failure_contains(result, "status:todo")
        calls = self.gh_calls()
        self.assertEqual(len(calls), 1)
        self.assert_issue_operation(calls[0], "view")
        self.assert_explicit_repository(calls)
        self.assertEqual({"state", "labels"} - self.json_fields(calls[0]), set())

    def test_validate_todo_accepts_one_todo_label_on_an_open_issue(self) -> None:
        result = self.lifecycle_process(
            "validate-todo",
            views=(self.response(self.issue("status:todo")),),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls], ["view"])
        self.assert_explicit_repository(calls)

    def test_validate_todo_rejects_multiple_and_wrong_lifecycle_labels(self) -> None:
        invalid_labels = (
            ("status:todo", "status:backlog"),
            ("status:in-progress",),
        )
        for labels in invalid_labels:
            with self.subTest(labels=labels):
                result = self.lifecycle_process(
                    "validate-todo",
                    views=(self.response(self.issue(*labels)),),
                )

                self.assert_failure_contains(result, "status:todo")
                calls = self.gh_calls()
                self.assertEqual([call[1] for call in calls], ["view"])
                self.assert_explicit_repository(calls)

    def test_validate_todo_rejects_closed_issue(self) -> None:
        result = self.lifecycle_process(
            "validate-todo",
            views=(self.response(self.issue("status:todo", state="CLOSED")),),
        )

        self.assert_failure_contains(result, "open")
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls], ["view"])
        self.assert_explicit_repository(calls)

    def test_validate_todo_surfaces_failed_github_read(self) -> None:
        result = self.lifecycle_process(
            "validate-todo",
            views=(
                self.response(returncode=42, stderr="canonical issue read denied"),
            ),
        )

        self.assert_failure_contains(result, "canonical issue read denied")
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls], ["view"])
        self.assert_explicit_repository(calls)

    def test_claim_writes_once_and_verifies_status_and_assignment(self) -> None:
        result = self.lifecycle_process(
            "claim",
            views=(
                self.response(self.issue("status:todo")),
                self.response(
                    self.issue("status:in-progress", assignees=("test-user",))
                ),
            ),
            edits=(self.response(),),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls], ["view", "edit", "view"])
        self.assert_explicit_repository(calls)
        edit = calls[1]
        self.assert_issue_operation(edit, "edit")
        self.assertEqual(self.option_values(edit, "--remove-label"), ["status:todo"])
        self.assertEqual(
            self.option_values(edit, "--add-label"), ["status:in-progress"]
        )
        self.assertEqual(self.option_values(edit, "--add-assignee"), ["@me"])
        self.assertEqual(
            {"state", "labels", "assignees"} - self.json_fields(calls[2]), set()
        )

    def test_claim_stops_when_edit_fails(self) -> None:
        result = self.lifecycle_process(
            "claim",
            views=(self.response(self.issue("status:todo")),),
            edits=(self.response(returncode=43, stderr="claim edit denied"),),
        )

        self.assert_failure_contains(result, "claim edit denied")
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls], ["view", "edit"])
        self.assert_explicit_repository(calls)

    def test_claim_rejects_incorrect_post_write_state(self) -> None:
        invalid_post_writes = (
            self.issue("status:in-progress"),
            self.issue("status:todo", assignees=("test-user",)),
        )
        for post_write in invalid_post_writes:
            with self.subTest(post_write=post_write):
                result = self.lifecycle_process(
                    "claim",
                    views=(
                        self.response(self.issue("status:todo")),
                        self.response(post_write),
                    ),
                    edits=(self.response(),),
                )

                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertTrue(result.stderr.strip(), "failure must be actionable")
                calls = self.gh_calls()
                self.assertEqual(
                    [call[1] for call in calls], ["view", "edit", "view"]
                )
                self.assert_explicit_repository(calls)

    def test_transition_writes_once_and_verifies_handoff(self) -> None:
        result = self.lifecycle_process(
            "transition",
            "--from-status",
            "status:in-progress",
            "--to-status",
            "status:in-review",
            views=(
                self.response(self.issue("status:in-progress")),
                self.response(self.issue("status:in-review")),
            ),
            edits=(self.response(),),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls], ["view", "edit", "view"])
        self.assert_explicit_repository(calls)
        edit = calls[1]
        self.assertEqual(
            self.option_values(edit, "--remove-label"), ["status:in-progress"]
        )
        self.assertEqual(
            self.option_values(edit, "--add-label"), ["status:in-review"]
        )
        for view in (calls[0], calls[2]):
            self.assertEqual({"state", "labels"} - self.json_fields(view), set())

    def test_transition_rejects_incorrect_post_write_state(self) -> None:
        result = self.lifecycle_process(
            "transition",
            "--from-status",
            "status:in-progress",
            "--to-status",
            "status:in-review",
            views=(
                self.response(self.issue("status:in-progress")),
                self.response(self.issue("status:in-progress")),
            ),
            edits=(self.response(),),
        )

        self.assert_failure_contains(result, "status:in-review")
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls], ["view", "edit", "view"])
        self.assert_explicit_repository(calls)

    def test_transition_rejects_wrong_pre_read_without_mutation(self) -> None:
        result = self.lifecycle_process(
            "transition",
            "--from-status",
            "status:in-progress",
            "--to-status",
            "status:in-review",
            views=(self.response(self.issue("status:todo")),),
        )

        self.assert_failure_contains(result, "status:in-progress")
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls], ["view"])
        self.assert_explicit_repository(calls)

    def test_transition_accepts_only_non_terminal_lifecycle_labels(self) -> None:
        invalid_arguments = (
            (
                "--from-status",
                "status:done",
                "--to-status",
                "status:in-review",
            ),
            (
                "--from-status",
                "status:in-progress",
                "--to-status",
                "status:done",
            ),
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                result = self.lifecycle_process("transition", *arguments)

                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertTrue(result.stderr.strip(), "failure must be actionable")
                self.assertEqual(self.gh_calls(), [])

    def test_block_transitions_comments_and_verifies_both_records(self) -> None:
        diagnostic = "Implementation failed after three attempts.\nLast error: CI failed.\n"
        diagnostic_path = Path(self.temporary_directory.name) / "diagnostic.md"
        diagnostic_path.write_text(diagnostic, encoding="utf-8")
        post_write = self.issue(
            "status:blocked",
            comments=(diagnostic,),
        )
        result = self.lifecycle_process(
            "block",
            "--from-status",
            "status:in-progress",
            "--comment-file",
            str(diagnostic_path),
            views=(
                self.response(self.issue("status:in-progress")),
                self.response(post_write),
                self.response(post_write),
            ),
            edits=(self.response(),),
            comments=(self.response(),),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.gh_calls()
        operations = [call[1] for call in calls]
        self.assertEqual(operations[:3], ["view", "edit", "comment"])
        self.assertIn(len(operations), (4, 5))
        self.assertTrue(all(operation == "view" for operation in operations[3:]))
        self.assert_explicit_repository(calls)

        edit = calls[1]
        self.assertEqual(
            self.option_values(edit, "--remove-label"), ["status:in-progress"]
        )
        self.assertEqual(
            self.option_values(edit, "--add-label"), ["status:blocked"]
        )

        comment = calls[2]
        body_files = self.option_values(comment, "--body-file")
        bodies = self.option_values(comment, "--body")
        self.assertTrue(body_files or bodies, "comment must contain the diagnostic")
        if body_files:
            self.assertEqual(Path(body_files[0]).read_text(encoding="utf-8"), diagnostic)
        else:
            self.assertEqual(bodies, [diagnostic])

        reread_fields = set().union(
            *(self.json_fields(call) for call in calls[3:])
        )
        self.assertEqual(
            {"state", "labels", "comments"} - reread_fields,
            set(),
            "block must re-read both issue lifecycle state and comments",
        )

    def test_block_fails_when_exact_comment_is_missing_after_write(self) -> None:
        diagnostic = "Blocked diagnostic\n"
        diagnostic_path = Path(self.temporary_directory.name) / "diagnostic.md"
        diagnostic_path.write_text(diagnostic, encoding="utf-8")
        incorrect_post_write = self.issue(
            "status:blocked",
            comments=("Different comment\n",),
        )
        result = self.lifecycle_process(
            "block",
            "--from-status",
            "status:in-progress",
            "--comment-file",
            str(diagnostic_path),
            views=(
                self.response(self.issue("status:in-progress")),
                self.response(incorrect_post_write),
                self.response(incorrect_post_write),
            ),
            edits=(self.response(),),
            comments=(self.response(),),
        )

        self.assert_failure_contains(result, "comment")
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls[:3]], ["view", "edit", "comment"])
        self.assertTrue(any(call[1] == "view" for call in calls[3:]))
        self.assert_explicit_repository(calls)

    def test_block_stops_when_comment_mutation_fails(self) -> None:
        diagnostic_path = Path(self.temporary_directory.name) / "diagnostic.md"
        diagnostic_path.write_text("Blocked diagnostic\n", encoding="utf-8")
        result = self.lifecycle_process(
            "block",
            "--from-status",
            "status:in-progress",
            "--comment-file",
            str(diagnostic_path),
            views=(self.response(self.issue("status:in-progress")),),
            edits=(self.response(),),
            comments=(
                self.response(returncode=44, stderr="diagnostic comment denied"),
            ),
        )

        self.assert_failure_contains(result, "diagnostic comment denied")
        calls = self.gh_calls()
        self.assertEqual([call[1] for call in calls], ["view", "edit", "comment"])
        self.assert_explicit_repository(calls)


if __name__ == "__main__":
    unittest.main()
