#!/usr/bin/env -S uv run
"""Network-free contract tests for the GitHub PR merge-and-cleanup CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MERGE_CLI = REPOSITORY_ROOT / "plugins/dev/scripts/github_pr.py"
TEST_REPOSITORY = "example/project"
TEST_PR = 12


FAKE_GH = r"""#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


scenario_path = Path(os.environ["GITHUB_PR_MERGE_TEST_SCENARIO"])
calls_path = Path(os.environ["GITHUB_PR_MERGE_TEST_GH_CALLS"])
arguments = sys.argv[1:]

with calls_path.open("a", encoding="utf-8") as calls_file:
    calls_file.write(json.dumps(arguments) + "\n")

if arguments[:2] == ["pr", "view"]:
    operation = "view"
elif arguments[:2] == ["pr", "merge"]:
    operation = "merge"
else:
    print(f"unexpected gh invocation: {arguments!r}", file=sys.stderr)
    raise SystemExit(97)

scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
responses = scenario.get("responses", {}).get(operation, [])
indexes = scenario.setdefault("indexes", {})
index = indexes.get(operation, 0)
if index >= len(responses):
    print(
        f"unexpected gh {operation} invocation #{index + 1}: {arguments!r}",
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
    print(stdout)
stderr = response.get("stderr", "")
if stderr:
    print(stderr, file=sys.stderr)
raise SystemExit(response.get("returncode", 0))
"""


FAKE_GIT = r"""#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations

import os
import sys


arguments = sys.argv[1:]
if (
    len(arguments) == 5
    and arguments[0] == "-C"
    and arguments[2:4] == ["remote", "get-url"]
):
    remote = arguments[4]
    print(f"https://github.com/example/project.git" if remote == "origin" else remote)
    raise SystemExit(0)

real_git = os.environ["GITHUB_PR_MERGE_TEST_REAL_GIT"]
os.execv(real_git, [real_git, *arguments])
"""


class GitHubPrMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.remote = self.root / "remote.git"
        self.checkout = self.root / "checkout"
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.scenario_path = self.root / "scenario.json"
        self.calls_path = self.root / "gh-calls.jsonl"
        self.calls_path.write_text("", encoding="utf-8")
        self.real_git = shutil.which("git")
        if not self.real_git:
            self.fail("git is required")

        fake_gh = self.fake_bin / "gh"
        fake_gh.write_text(textwrap.dedent(FAKE_GH), encoding="utf-8")
        fake_gh.chmod(0o755)
        fake_git = self.fake_bin / "git"
        fake_git.write_text(textwrap.dedent(FAKE_GIT), encoding="utf-8")
        fake_git.chmod(0o755)

        self.git(None, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(None, "clone", str(self.remote), str(self.checkout))
        self.git(self.checkout, "config", "user.name", "Merge Test")
        self.git(self.checkout, "config", "user.email", "merge-test@example.com")
        (self.checkout / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(self.checkout, "add", "base.txt")
        self.git(self.checkout, "commit", "-m", "base")
        self.git(self.checkout, "push", "-u", "origin", "main")
        self.base_oid = self.git(self.checkout, "rev-parse", "HEAD").stdout.strip()

        self.git(self.checkout, "switch", "-c", "feature/merge-helper")
        (self.checkout / "feature.txt").write_text("feature\n", encoding="utf-8")
        self.git(self.checkout, "add", "feature.txt")
        self.git(self.checkout, "commit", "-m", "feature")
        self.head_oid = self.git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        self.git(self.checkout, "push", "-u", "origin", "feature/merge-helper")

        self.git(self.checkout, "switch", "main")
        self.git(self.checkout, "merge", "--squash", "feature/merge-helper")
        self.git(self.checkout, "commit", "-m", "merged feature")
        self.merge_oid = self.git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        self.git(self.checkout, "push", "origin", "main")

    def git(
        self,
        cwd: Path | None,
        *arguments: str,
        accepted_returncodes: Sequence[int] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [self.real_git or "git", *arguments],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode not in accepted_returncodes:
            self.fail(
                f"git {' '.join(arguments)} failed: {result.stderr or result.stdout}"
            )
        return result

    def response(
        self,
        stdout: Any = None,
        *,
        returncode: int = 0,
        stderr: str = "",
    ) -> dict[str, Any]:
        return {
            "stdout": stdout or "",
            "returncode": returncode,
            "stderr": stderr,
        }

    def pull_request(
        self,
        *,
        state: str = "OPEN",
        head_oid: str | None = None,
        mergeable: str = "MERGEABLE",
        merge_state_status: str = "CLEAN",
        checks: list[dict[str, Any]] | None = None,
        merge_commit: str | None = None,
    ) -> dict[str, Any]:
        return {
            "state": state,
            "isDraft": False,
            "mergeable": mergeable,
            "mergeStateStatus": merge_state_status,
            "headRefName": "feature/merge-helper",
            "headRefOid": head_oid or self.head_oid,
            "headRepository": {"nameWithOwner": TEST_REPOSITORY},
            "baseRefName": "main",
            "statusCheckRollup": checks or [],
            "mergeCommit": {"oid": merge_commit} if merge_commit else None,
            "url": f"https://github.com/{TEST_REPOSITORY}/pull/{TEST_PR}",
        }

    def merge_process(
        self,
        *,
        views: tuple[dict[str, Any], ...],
        merges: tuple[dict[str, Any], ...] = (),
        extra_arguments: tuple[str, ...] = (),
        operation: str = "merge-cleanup",
    ) -> subprocess.CompletedProcess[str]:
        scenario = {
            "responses": {"view": list(views), "merge": list(merges)},
            "indexes": {},
        }
        self.scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        self.calls_path.write_text("", encoding="utf-8")
        environment = os.environ.copy()
        environment["PATH"] = f"{self.fake_bin}{os.pathsep}{environment['PATH']}"
        environment["GITHUB_PR_MERGE_TEST_SCENARIO"] = str(self.scenario_path)
        environment["GITHUB_PR_MERGE_TEST_GH_CALLS"] = str(self.calls_path)
        environment["GITHUB_PR_MERGE_TEST_REAL_GIT"] = self.real_git or "git"
        command = [
            "uv",
            "run",
            str(MERGE_CLI),
            operation,
            "--repo",
            TEST_REPOSITORY,
            "--pr",
            str(TEST_PR),
            "--expected-head",
            self.head_oid,
        ]
        if operation != "merge":
            command.extend(("--checkout", str(self.checkout)))
        command.extend(extra_arguments)
        return subprocess.run(
            command,
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

    def assert_failed(
        self, result: subprocess.CompletedProcess[str], text: str
    ) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(text.lower(), result.stderr.lower())

    def test_merge_removes_clean_worktree_and_exact_local_and_remote_branch(
        self,
    ) -> None:
        worktree = self.root / "worktrees" / "task"
        worktree.parent.mkdir()
        self.git(
            self.checkout,
            "worktree",
            "add",
            str(worktree),
            "feature/merge-helper",
        )
        result = self.merge_process(
            views=(
                self.response(
                    self.pull_request(
                        checks=[
                            {
                                "__typename": "CheckRun",
                                "name": "tests",
                                "status": "COMPLETED",
                                "conclusion": "SUCCESS",
                            }
                        ]
                    )
                ),
                self.response(
                    self.pull_request(state="MERGED", merge_commit=self.merge_oid)
                ),
            ),
            merges=(self.response(),),
            extra_arguments=(
                "--worktree",
                str(worktree),
                "--delete-remote-branch",
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["merged_now"])
        self.assertTrue(payload["worktree_removed"])
        self.assertTrue(payload["local_branch_deleted"])
        self.assertTrue(payload["remote_branch_deleted"])
        self.assertFalse(worktree.exists())
        self.assertIsNone(
            self.git(
                self.checkout,
                "rev-parse",
                "--verify",
                "--quiet",
                "refs/heads/feature/merge-helper^{commit}",
                accepted_returncodes=(0, 1),
            ).stdout.strip()
            or None
        )
        self.assertEqual(
            self.git(
                self.checkout,
                "ls-remote",
                "--heads",
                "origin",
                "refs/heads/feature/merge-helper",
            ).stdout,
            "",
        )
        calls = self.gh_calls()
        self.assertEqual(
            [call[:2] for call in calls],
            [["pr", "view"], ["pr", "merge"], ["pr", "view"]],
        )
        merge_call = calls[1]
        self.assertIn("--match-head-commit", merge_call)
        self.assertIn(self.head_oid, merge_call)
        self.assertIn("--repo", merge_call)
        self.assertIn(TEST_REPOSITORY, merge_call)
        self.assertNotIn("--delete-branch", merge_call)

    def test_empty_check_set_is_allowed(self) -> None:
        worktree = self.root / "worktrees" / "task"
        worktree.parent.mkdir()
        self.git(
            self.checkout,
            "worktree",
            "add",
            str(worktree),
            "feature/merge-helper",
        )
        result = self.merge_process(
            views=(
                self.response(self.pull_request(checks=[])),
                self.response(
                    self.pull_request(state="MERGED", merge_commit=self.merge_oid)
                ),
            ),
            merges=(self.response(),),
            operation="merge",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["merge_commit"], self.merge_oid)
        self.assertEqual(payload["operation"], "merge")
        self.assertFalse(payload["base_updated"])
        self.assertTrue(worktree.exists())
        self.assertEqual(
            self.git(
                self.checkout,
                "rev-parse",
                "refs/heads/feature/merge-helper",
            ).stdout.strip(),
            self.head_oid,
        )

    def test_pending_check_stops_before_merge(self) -> None:
        result = self.merge_process(
            views=(
                self.response(
                    self.pull_request(
                        checks=[
                            {
                                "__typename": "CheckRun",
                                "name": "tests",
                                "status": "IN_PROGRESS",
                                "conclusion": "",
                            }
                        ]
                    )
                ),
            ),
            operation="merge",
        )

        self.assert_failed(result, "still pending")
        self.assertEqual([call[:2] for call in self.gh_calls()], [["pr", "view"]])

    def test_failed_check_stops_before_merge(self) -> None:
        result = self.merge_process(
            views=(
                self.response(
                    self.pull_request(
                        checks=[
                            {
                                "__typename": "StatusContext",
                                "context": "lint",
                                "state": "FAILURE",
                            }
                        ]
                    )
                ),
            ),
            operation="merge",
        )

        self.assert_failed(result, "not green")
        self.assertEqual([call[:2] for call in self.gh_calls()], [["pr", "view"]])

    def test_registered_task_worktree_must_be_named_for_cleanup(self) -> None:
        worktree = self.root / "worktrees" / "task"
        worktree.parent.mkdir()
        self.git(
            self.checkout,
            "worktree",
            "add",
            str(worktree),
            "feature/merge-helper",
        )
        result = self.merge_process(
            views=(self.response(self.pull_request()),),
        )

        self.assert_failed(result, "pass that path with --worktree")
        self.assertEqual([call[:2] for call in self.gh_calls()], [["pr", "view"]])
        self.assertTrue(worktree.exists())

    def test_expected_head_mismatch_stops_before_merge(self) -> None:
        other_oid = "f" * 40
        result = self.merge_process(
            views=(self.response(self.pull_request(head_oid=other_oid)),),
            operation="merge",
        )

        self.assert_failed(result, "PR head changed")
        self.assertEqual([call[:2] for call in self.gh_calls()], [["pr", "view"]])

    def test_remote_branch_mismatch_stops_before_merge_or_deletion(self) -> None:
        self.git(
            self.checkout,
            "push",
            "--force",
            "origin",
            "main:refs/heads/feature/merge-helper",
        )
        result = self.merge_process(
            views=(self.response(self.pull_request()),),
            extra_arguments=("--delete-remote-branch",),
        )

        self.assert_failed(result, "expected verified PR head")
        self.assertEqual([call[:2] for call in self.gh_calls()], [["pr", "view"]])
        remote_oid = self.git(
            self.checkout,
            "ls-remote",
            "--heads",
            "origin",
            "refs/heads/feature/merge-helper",
        ).stdout.split()[0]
        self.assertEqual(remote_oid, self.merge_oid)

    def test_rerun_after_merge_finishes_cleanup_without_second_merge(self) -> None:
        result = self.merge_process(
            views=(
                self.response(
                    self.pull_request(state="MERGED", merge_commit=self.merge_oid)
                ),
            ),
            extra_arguments=("--delete-remote-branch",),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["merged_now"])
        self.assertTrue(payload["local_branch_deleted"])
        self.assertTrue(payload["remote_branch_deleted"])
        self.assertEqual([call[:2] for call in self.gh_calls()], [["pr", "view"]])

    def test_cleanup_only_removes_merged_pr_branch_without_merge_call(self) -> None:
        result = self.merge_process(
            views=(
                self.response(
                    self.pull_request(state="MERGED", merge_commit=self.merge_oid)
                ),
            ),
            extra_arguments=("--delete-remote-branch",),
            operation="cleanup",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["operation"], "cleanup")
        self.assertFalse(payload["merged_now"])
        self.assertTrue(payload["local_branch_deleted"])
        self.assertTrue(payload["remote_branch_deleted"])
        self.assertEqual([call[:2] for call in self.gh_calls()], [["pr", "view"]])

    def test_cleanup_only_rejects_open_pr_before_git_mutation(self) -> None:
        result = self.merge_process(
            views=(self.response(self.pull_request()),),
            operation="cleanup",
        )

        self.assert_failed(result, "requires a MERGED PR")
        self.assertEqual([call[:2] for call in self.gh_calls()], [["pr", "view"]])
        self.assertEqual(
            self.git(
                self.checkout,
                "rev-parse",
                "refs/heads/feature/merge-helper",
            ).stdout.strip(),
            self.head_oid,
        )


if __name__ == "__main__":
    unittest.main()
