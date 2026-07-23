#!/usr/bin/env -S uv run
"""Black-box contract tests for the shadow-replay CLI.

Tests exercise only the public interface described in ``plugins/dev/runtime_contracts/shadow.md``
and the task packet. ``gh`` and ``git`` are driven exclusively through fake
executables placed first on ``PATH``; no test hits real GitHub or mutates a real
repository.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CLI = REPOSITORY_ROOT / "plugins/dev/scripts/shadow_replay.py"
REPO = "octo/demo"


# Fake ``gh``: records every invocation and replays scripted responses keyed by a
# coarse operation name. An unscripted operation exits 98 so missing scripting is a
# loud failure rather than a silent success.
FAKE_GH = r'''#!/usr/bin/env -S uv run --script
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
calls_path = Path(os.environ["SHADOW_TEST_GH_CALLS"])
with calls_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\n")

if args and args[0] == "api":
    operation = "api"
elif len(args) >= 2:
    operation = args[0] + " " + args[1]
elif args:
    operation = args[0]
else:
    operation = ""

scenario_path = Path(os.environ["SHADOW_TEST_GH_SCENARIO"])
scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
responses = scenario.get("responses", {}).get(operation, [])
indexes = scenario.setdefault("indexes", {})
index = indexes.get(operation, 0)
if index >= len(responses):
    print(
        f"unexpected gh {operation!r} invocation #{index + 1}: {args!r}",
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


# Fake ``git``: records every invocation. Unscripted operations succeed (exit 0)
# because most git mutations here produce no stdout the script parses; the
# exit-code-sensitive cases (``merge-base --is-ancestor``) are scripted explicitly.
FAKE_GIT = r'''#!/usr/bin/env -S uv run --script
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
calls_path = Path(os.environ["SHADOW_TEST_GIT_CALLS"])
with calls_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\n")

if args and args[0] == "-C":
    operation = args[2] if len(args) > 2 else ""
elif args:
    operation = args[0]
else:
    operation = ""

scenario_path = Path(os.environ["SHADOW_TEST_GIT_SCENARIO"])
scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
responses = scenario.get("responses", {}).get(operation, [])
indexes = scenario.setdefault("indexes", {})
index = indexes.get(operation, 0)
if index < len(responses):
    response = responses[index]
    indexes[operation] = index + 1
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
else:
    response = {"returncode": 0, "stdout": "", "stderr": ""}

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


REQUIRED_DISCLOSURES = (
    "Same-repository replay is not blind; the original solution may be discoverable "
    "in Git history or through GitHub.",
    "The source issue body is current, not guaranteed to be its exact historical text "
    "at cutoff.",
    "Original token and cost data may be unavailable.",
    "GitHub timestamps are observable workflow timestamps, not continuous agent work.",
    "Estimated API-equivalent cost is not the user's actual subscription charge.",
    "Reviewer and verifier judgments depend on the identified models.",
)

COMPARISON_DIMENSIONS = (
    "Functional tests",
    "DoD criteria met",
    "Review blockers",
    "Fix and review cycles",
    "Files changed",
    "Lines added and removed",
    "Observable delivery time",
    "Total run time",
    "CI wait time",
    "Input tokens",
    "Cached input tokens",
    "Output tokens",
    "Reasoning tokens",
    "Estimated API-equivalent cost",
)


class ShadowReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        (self.fake_bin / "gh").write_text(FAKE_GH, encoding="utf-8")
        (self.fake_bin / "gh").chmod(0o755)
        (self.fake_bin / "git").write_text(FAKE_GIT, encoding="utf-8")
        (self.fake_bin / "git").chmod(0o755)
        self.gh_scenario = self.root / "gh_scenario.json"
        self.git_scenario = self.root / "git_scenario.json"
        self.gh_calls_path = self.root / "gh_calls.jsonl"
        self.git_calls_path = self.root / "git_calls.jsonl"

    # ------------------------------------------------------------------ helpers
    def resp(
        self,
        stdout: Any = "",
        *,
        returncode: int = 0,
        stderr: str = "",
    ) -> dict[str, Any]:
        return {"stdout": stdout, "returncode": returncode, "stderr": stderr}

    def run_cli(
        self,
        *args: str,
        gh: dict[str, list[dict[str, Any]]] | None = None,
        git: dict[str, list[dict[str, Any]]] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.gh_scenario.write_text(
            json.dumps({"responses": gh or {}, "indexes": {}}), encoding="utf-8"
        )
        self.git_scenario.write_text(
            json.dumps({"responses": git or {}, "indexes": {}}), encoding="utf-8"
        )
        self.gh_calls_path.write_text("", encoding="utf-8")
        self.git_calls_path.write_text("", encoding="utf-8")
        environment = os.environ.copy()
        environment["PATH"] = f"{self.fake_bin}{os.pathsep}{environment['PATH']}"
        environment["SHADOW_TEST_GH_SCENARIO"] = str(self.gh_scenario)
        environment["SHADOW_TEST_GH_CALLS"] = str(self.gh_calls_path)
        environment["SHADOW_TEST_GIT_SCENARIO"] = str(self.git_scenario)
        environment["SHADOW_TEST_GIT_CALLS"] = str(self.git_calls_path)
        environment["GH_REPO"] = "wrong/inferred-repository"
        return subprocess.run(
            ["uv", "run", str(CLI), *args],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def gh_calls(self) -> list[list[str]]:
        return [
            json.loads(line)
            for line in self.gh_calls_path.read_text(encoding="utf-8").splitlines()
        ]

    def git_calls(self) -> list[list[str]]:
        return [
            json.loads(line)
            for line in self.git_calls_path.read_text(encoding="utf-8").splitlines()
        ]

    def opt(self, call: list[str], option: str) -> str | None:
        for index, token in enumerate(call):
            if token == option and index + 1 < len(call):
                return call[index + 1]
            if token.startswith(f"{option}="):
                return token.split("=", 1)[1]
        return None

    def payload(self, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_failure(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue(result.stderr.strip(), "failure must be actionable on stderr")

    def assert_gh_repo_targeting(self, calls: list[list[str]]) -> None:
        self.assertTrue(calls, "expected at least one gh call")
        for call in calls:
            if call and call[0] == "api":
                self.assertTrue(
                    any(token.startswith(f"repos/{REPO}/") for token in call),
                    f"gh api call did not target the repository path: {call}",
                )
            else:
                self.assertEqual(
                    self.opt(call, "--repo"),
                    REPO,
                    f"gh call did not explicitly target --repo {REPO}: {call}",
                )

    def commits_jsonl(self, *commits: dict[str, Any]) -> str:
        return "\n".join(json.dumps(commit) for commit in commits)

    def clean_issue(
        self,
        *,
        labels: tuple[str, ...] = ("experiment:shadow",),
        milestone: Any = None,
        state: str = "OPEN",
        body: str = "Shadow replay.\n",
        assignees: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return {
            "labels": [{"name": name} for name in labels],
            "milestone": milestone,
            "state": state,
            "body": body,
            "assignees": [{"login": login} for login in assignees],
        }

    def clean_pr(
        self,
        *,
        base: str = "B",
        head: str = "C",
        head_repo: str = REPO,
        is_draft: bool = True,
        merged: bool = False,
        state: str = "OPEN",
        labels: tuple[str, ...] = ("do-not-merge",),
        body: str = "Refs #99\n",
        head_oid: str = "head1",
    ) -> dict[str, Any]:
        return {
            "isDraft": is_draft,
            "merged": merged,
            "state": state,
            "labels": [{"name": name} for name in labels],
            "baseRefName": base,
            "headRefName": head,
            "headRefOid": head_oid,
            "headRepository": {"nameWithOwner": head_repo},
            "body": body,
        }

    # ---------------------------------------------------------------- run-id
    def test_run_id_is_deterministic_with_now_and_suffix(self) -> None:
        result = self.run_cli(
            "run-id", "--now", "2026-07-21T14:30:00Z", "--suffix", "a1b2c3d4"
        )
        payload = self.payload(result)
        self.assertEqual(payload["run_id"], "20260721T143000Z-a1b2c3d4")
        self.assertEqual(self.gh_calls(), [])
        self.assertEqual(self.git_calls(), [])

    def test_run_id_rejects_non_alphanumeric_suffix(self) -> None:
        self.assert_failure(
            self.run_cli("run-id", "--now", "2026-07-21T14:30:00Z", "--suffix", "bad-!")
        )

    def test_run_id_rejects_non_iso_now(self) -> None:
        self.assert_failure(
            self.run_cli("run-id", "--now", "not-a-timestamp", "--suffix", "abcd1234")
        )

    # -------------------------------------------------------- historical-base
    def test_historical_base_happy_path(self) -> None:
        commits = self.commits_jsonl(
            {"sha": "c1", "parents": ["base0"], "date": "2026-01-01T00:00:00Z"},
            {"sha": "c2", "parents": ["c1"], "date": "2026-01-02T00:00:00Z"},
        )
        result = self.run_cli(
            "historical-base",
            "--repo",
            REPO,
            "--source-pr",
            "5",
            gh={"api": [self.resp(commits)]},
            git={"merge-base": [self.resp(returncode=0)]},
        )
        payload = self.payload(result)
        self.assertEqual(payload["historical_base"], "base0")
        self.assertEqual(payload["first_commit"], "c1")
        self.assertEqual(payload["source_head"], "c2")
        self.assertEqual(payload["cutoff"], "2026-01-01T00:00:00Z")
        self.assertEqual(payload["commit_count"], 2)
        self.assertIn("cutoff_rule", payload)
        self.assert_gh_repo_targeting(self.gh_calls())
        ancestor_call = self.git_calls()[0]
        self.assertIn("merge-base", ancestor_call)
        self.assertIn("--is-ancestor", ancestor_call)
        self.assertIn("base0", ancestor_call)
        self.assertIn("c2", ancestor_call)

    def test_historical_base_honors_explicit_source_head(self) -> None:
        commits = self.commits_jsonl(
            {"sha": "c1", "parents": ["base0"], "date": "2026-01-01T00:00:00Z"},
        )
        result = self.run_cli(
            "historical-base",
            "--repo",
            REPO,
            "--source-pr",
            "5",
            "--source-head",
            "explicit-head",
            gh={"api": [self.resp(commits)]},
            git={"merge-base": [self.resp(returncode=0)]},
        )
        payload = self.payload(result)
        self.assertEqual(payload["source_head"], "explicit-head")
        self.assertIn("explicit-head", self.git_calls()[0])

    def test_historical_base_no_verify_ancestor_skips_git(self) -> None:
        commits = self.commits_jsonl(
            {"sha": "c1", "parents": ["base0"], "date": "2026-01-01T00:00:00Z"},
        )
        result = self.run_cli(
            "historical-base",
            "--repo",
            REPO,
            "--source-pr",
            "5",
            "--no-verify-ancestor",
            gh={"api": [self.resp(commits)]},
        )
        self.payload(result)
        self.assertEqual(self.git_calls(), [])

    def test_historical_base_rejects_root_commit(self) -> None:
        commits = self.commits_jsonl(
            {"sha": "c1", "parents": [], "date": "2026-01-01T00:00:00Z"},
        )
        result = self.run_cli(
            "historical-base",
            "--repo",
            REPO,
            "--source-pr",
            "5",
            gh={"api": [self.resp(commits)]},
        )
        self.assert_failure(result)
        self.assertEqual(self.git_calls(), [])

    def test_historical_base_rejects_merge_commit(self) -> None:
        commits = self.commits_jsonl(
            {"sha": "c1", "parents": ["a", "b"], "date": "2026-01-01T00:00:00Z"},
        )
        result = self.run_cli(
            "historical-base",
            "--repo",
            REPO,
            "--source-pr",
            "5",
            gh={"api": [self.resp(commits)]},
        )
        self.assert_failure(result)
        self.assertEqual(self.git_calls(), [])

    def test_historical_base_rejects_non_ancestor(self) -> None:
        commits = self.commits_jsonl(
            {"sha": "c1", "parents": ["base0"], "date": "2026-01-01T00:00:00Z"},
            {"sha": "c2", "parents": ["c1"], "date": "2026-01-02T00:00:00Z"},
        )
        result = self.run_cli(
            "historical-base",
            "--repo",
            REPO,
            "--source-pr",
            "5",
            gh={"api": [self.resp(commits)]},
            git={"merge-base": [self.resp(returncode=1)]},
        )
        self.assert_failure(result)

    # ------------------------------------------------------------- preflight
    def test_preflight_happy_path_uses_pr_head_as_source_head(self) -> None:
        issue = {
            "state": "CLOSED",
            "stateReason": "COMPLETED",
            "title": "Fix the widget",
            "closedByPullRequestsReferences": [{"number": 7}],
        }
        pr = {
            "state": "MERGED",
            "merged": True,
            "mergedAt": "2026-01-05T00:00:00Z",
            "mergeCommit": {"oid": "mergecommit1"},
            "closingIssuesReferences": [{"number": 3}],
            "headRefOid": "prhead1",
        }
        commits = self.commits_jsonl(
            {"sha": "c1", "parents": ["base0"], "date": "2026-01-01T00:00:00Z"},
        )
        result = self.run_cli(
            "preflight",
            "--repo",
            REPO,
            "--source-issue",
            "3",
            gh={
                "issue view": [self.resp(issue)],
                "pr view": [self.resp(pr)],
                "api": [self.resp(commits)],
            },
            git={"merge-base": [self.resp(returncode=0)]},
        )
        payload = self.payload(result)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source_pr"], 7)
        self.assertEqual(payload["source_title"], "Fix the widget")
        self.assertEqual(payload["merge_commit"], "mergecommit1")
        self.assertEqual(payload["merged_at"], "2026-01-05T00:00:00Z")
        self.assertEqual(payload["source_head"], "prhead1")
        self.assertEqual(payload["historical_base"], "base0")
        self.assertEqual(payload["first_commit"], "c1")
        self.assertRegex(payload["source_snapshot_sha256"], r"^[0-9a-f]{64}$")
        self.assert_gh_repo_targeting(self.gh_calls())
        self.assertIn("prhead1", self.git_calls()[0])

    def test_preflight_snapshot_binds_issue_comments_and_pr_reviews(self) -> None:
        issue = {
            "state": "CLOSED",
            "stateReason": "COMPLETED",
            "title": "Fix the widget",
            "closedByPullRequestsReferences": [{"number": 7}],
            "comments": [
                {
                    "author": {"login": "octocat"},
                    "body": "issue comment",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "url": "https://github.com/octo/demo/issues/3#issuecomment-1",
                }
            ],
        }
        pr = {
            "state": "MERGED",
            "merged": True,
            "mergedAt": "2026-01-05T00:00:00Z",
            "mergeCommit": {"oid": "mergecommit1"},
            "closingIssuesReferences": [{"number": 3}],
            "headRefOid": "prhead1",
            "comments": [],
            "reviews": [
                {
                    "author": {"login": "reviewer"},
                    "body": "approved",
                    "state": "APPROVED",
                    "submittedAt": "2026-01-04T00:00:00Z",
                    "commit": {"oid": "prhead1"},
                }
            ],
        }
        commits = self.commits_jsonl(
            {"sha": "c1", "parents": ["base0"], "date": "2026-01-01T00:00:00Z"},
        )
        first = self.payload(
            self.run_cli(
                "preflight",
                "--repo",
                REPO,
                "--source-issue",
                "3",
                gh={
                    "issue view": [self.resp(issue)],
                    "pr view": [self.resp(pr)],
                    "api": [self.resp(commits)],
                },
                git={"merge-base": [self.resp(returncode=0)]},
            )
        )
        changed_issue = {**issue, "comments": [*issue["comments"], {"body": "new"}]}
        changed_pr = {**pr, "reviews": [{**pr["reviews"][0], "body": "edited"}]}
        second = self.payload(
            self.run_cli(
                "preflight",
                "--repo",
                REPO,
                "--source-issue",
                "3",
                gh={
                    "issue view": [self.resp(changed_issue)],
                    "pr view": [self.resp(changed_pr)],
                    "api": [self.resp(commits)],
                },
                git={"merge-base": [self.resp(returncode=0)]},
            )
        )
        self.assertNotEqual(
            first["source_snapshot_sha256"], second["source_snapshot_sha256"]
        )

    def test_preflight_rejects_ambiguous_source_pr_selection(self) -> None:
        issue = {
            "state": "CLOSED",
            "stateReason": "COMPLETED",
            "title": "Ambiguous",
            "closedByPullRequestsReferences": [{"number": 7}, {"number": 8}],
        }
        result = self.run_cli(
            "preflight",
            "--repo",
            REPO,
            "--source-issue",
            "3",
            gh={"issue view": [self.resp(issue)]},
        )
        self.assert_failure(result)
        operations = [call[:2] for call in self.gh_calls()]
        self.assertEqual(operations, [["issue", "view"]])
        self.assertNotIn(["pr", "view"], operations)

    def test_preflight_rejects_uncompleted_issue(self) -> None:
        issue = {
            "state": "OPEN",
            "stateReason": None,
            "title": "Still open",
            "closedByPullRequestsReferences": [{"number": 7}],
        }
        result = self.run_cli(
            "preflight",
            "--repo",
            REPO,
            "--source-issue",
            "3",
            gh={"issue view": [self.resp(issue)]},
        )
        self.assert_failure(result)
        self.assertIn("completed", result.stderr.lower())

    def test_preflight_rejects_non_completed_state_reason(self) -> None:
        issue = {
            "state": "CLOSED",
            "stateReason": "NOT_PLANNED",
            "title": "Closed not planned",
            "closedByPullRequestsReferences": [{"number": 7}],
        }
        result = self.run_cli(
            "preflight",
            "--repo",
            REPO,
            "--source-issue",
            "3",
            gh={"issue view": [self.resp(issue)]},
        )
        self.assert_failure(result)

    def test_preflight_rejects_unmerged_source_pr(self) -> None:
        issue = {
            "state": "CLOSED",
            "stateReason": "COMPLETED",
            "title": "Fix",
            "closedByPullRequestsReferences": [{"number": 7}],
        }
        pr = {
            "state": "OPEN",
            "merged": False,
            "mergedAt": None,
            "mergeCommit": None,
            "closingIssuesReferences": [{"number": 3}],
            "headRefOid": "prhead1",
        }
        result = self.run_cli(
            "preflight",
            "--repo",
            REPO,
            "--source-issue",
            "3",
            gh={"issue view": [self.resp(issue)], "pr view": [self.resp(pr)]},
        )
        self.assert_failure(result)
        self.assertIn("merged", result.stderr.lower())

    def test_preflight_rejects_unbound_explicit_source_pr(self) -> None:
        issue = {
            "state": "CLOSED",
            "stateReason": "COMPLETED",
            "title": "Fix",
            "closedByPullRequestsReferences": [{"number": 7}],
        }
        pr = {
            "state": "MERGED",
            "merged": True,
            "mergedAt": "2026-01-05T00:00:00Z",
            "mergeCommit": {"oid": "mc1"},
            "closingIssuesReferences": [{"number": 999}],
            "headRefOid": "prhead1",
        }
        result = self.run_cli(
            "preflight",
            "--repo",
            REPO,
            "--source-issue",
            "3",
            "--source-pr",
            "7",
            gh={"issue view": [self.resp(issue)], "pr view": [self.resp(pr)]},
        )
        self.assert_failure(result)
        operations = [call[:2] for call in self.gh_calls()]
        self.assertNotIn(["api"], [[call[0]] for call in self.gh_calls()])
        self.assertIn(["pr", "view"], operations)

    # --------------------------------------------------- create-shadow-issue
    def _body_file(self, text: str = "shadow body\n") -> str:
        path = self.root / "body.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_create_shadow_issue_happy_path(self) -> None:
        result = self.run_cli(
            "create-shadow-issue",
            "--repo",
            REPO,
            "--title",
            "[SHADOW] Replay",
            "--body-file",
            self._body_file(),
            gh={
                "label list": [self.resp([{"name": "experiment:shadow"}])],
                "label create": [self.resp("")],
                "issue create": [
                    self.resp("https://github.com/octo/demo/issues/99")
                ],
                "issue view": [
                    self.resp(
                        {
                            "labels": [{"name": "experiment:shadow"}],
                            "milestone": None,
                            "state": "OPEN",
                        }
                    )
                ],
            },
        )
        payload = self.payload(result)
        self.assertEqual(payload["shadow_issue"], 99)
        self.assertEqual(payload["url"], "https://github.com/octo/demo/issues/99")
        self.assertEqual(payload["repo"], REPO)
        calls = self.gh_calls()
        self.assert_gh_repo_targeting(calls)
        # Only the missing label (do-not-merge) is created.
        created = [call for call in calls if call[:2] == ["label", "create"]]
        self.assertEqual(len(created), 1)
        self.assertIn("do-not-merge", created[0])
        self.assertIn("--force", created[0])
        issue_create = next(call for call in calls if call[:2] == ["issue", "create"])
        self.assertEqual(self.opt(issue_create, "--label"), "experiment:shadow")

    def test_create_shadow_issue_skips_existing_labels(self) -> None:
        result = self.run_cli(
            "create-shadow-issue",
            "--repo",
            REPO,
            "--title",
            "[SHADOW] Replay",
            "--body-file",
            self._body_file(),
            gh={
                "label list": [
                    self.resp(
                        [{"name": "experiment:shadow"}, {"name": "do-not-merge"}]
                    )
                ],
                "issue create": [
                    self.resp("https://github.com/octo/demo/issues/99")
                ],
                "issue view": [
                    self.resp(
                        {
                            "labels": [{"name": "experiment:shadow"}],
                            "milestone": None,
                            "state": "OPEN",
                        }
                    )
                ],
            },
        )
        self.payload(result)
        self.assertNotIn(
            ["label", "create"], [call[:2] for call in self.gh_calls()]
        )

    def test_create_shadow_issue_rejects_status_label_on_reread(self) -> None:
        result = self.run_cli(
            "create-shadow-issue",
            "--repo",
            REPO,
            "--title",
            "[SHADOW] Replay",
            "--body-file",
            self._body_file(),
            gh={
                "label list": [
                    self.resp(
                        [{"name": "experiment:shadow"}, {"name": "do-not-merge"}]
                    )
                ],
                "issue create": [
                    self.resp("https://github.com/octo/demo/issues/99")
                ],
                "issue view": [
                    self.resp(
                        {
                            "labels": [
                                {"name": "experiment:shadow"},
                                {"name": "status:todo"},
                            ],
                            "milestone": None,
                            "state": "OPEN",
                        }
                    )
                ],
            },
        )
        self.assert_failure(result)

    def test_create_shadow_issue_rejects_milestone_on_reread(self) -> None:
        result = self.run_cli(
            "create-shadow-issue",
            "--repo",
            REPO,
            "--title",
            "[SHADOW] Replay",
            "--body-file",
            self._body_file(),
            gh={
                "label list": [
                    self.resp(
                        [{"name": "experiment:shadow"}, {"name": "do-not-merge"}]
                    )
                ],
                "issue create": [
                    self.resp("https://github.com/octo/demo/issues/99")
                ],
                "issue view": [
                    self.resp(
                        {
                            "labels": [{"name": "experiment:shadow"}],
                            "milestone": {"title": "M1"},
                            "state": "OPEN",
                        }
                    )
                ],
            },
        )
        self.assert_failure(result)

    def test_create_shadow_issue_rejects_missing_body_file(self) -> None:
        result = self.run_cli(
            "create-shadow-issue",
            "--repo",
            REPO,
            "--title",
            "[SHADOW] Replay",
            "--body-file",
            str(self.root / "does-not-exist.md"),
        )
        self.assert_failure(result)

    def test_create_shadow_issue_rejects_blocked_by_dependency_before_mutation(self) -> None:
        result = self.run_cli(
            "create-shadow-issue",
            "--repo",
            REPO,
            "--title",
            "[SHADOW] Replay",
            "--body-file",
            self._body_file("Replay packet.\n\nBlocked by #11\n"),
        )
        self.assert_failure(result)
        self.assertEqual(self.gh_calls(), [])

    # ------------------------------------------------------- create-branches
    def test_create_branches_happy_path(self) -> None:
        result = self.run_cli(
            "create-branches",
            "--shadow-base",
            "shadow-base/x/run",
            "--candidate",
            "shadow/x/run",
            "--base-commit",
            "base0",
        )
        payload = self.payload(result)
        self.assertEqual(payload["shadow_base"], "shadow-base/x/run")
        self.assertEqual(payload["candidate"], "shadow/x/run")
        self.assertEqual(payload["base_commit"], "base0")
        self.assertEqual(payload["remote"], "origin")
        self.assertEqual(self.gh_calls(), [])
        operations = [
            call[2] if call[0] == "-C" else call[0] for call in self.git_calls()
        ]
        self.assertEqual(operations, ["branch", "push", "branch", "push"])

    def test_create_branches_rejects_identical_base_and_candidate(self) -> None:
        result = self.run_cli(
            "create-branches",
            "--shadow-base",
            "same",
            "--candidate",
            "same",
            "--base-commit",
            "base0",
        )
        self.assert_failure(result)
        self.assertEqual(self.git_calls(), [])

    # --------------------------------------------------------- open-shadow-pr
    def test_open_shadow_pr_happy_path(self) -> None:
        body = self._body_file("Replay work.\n\nRefs #99\n")
        result = self.run_cli(
            "open-shadow-pr",
            "--repo",
            REPO,
            "--base",
            "B",
            "--head",
            "C",
            "--head-repo",
            REPO,
            "--title",
            "[SHADOW] PR",
            "--body-file",
            body,
            gh={
                "pr create": [self.resp("https://github.com/octo/demo/pull/100")],
                "pr edit": [self.resp("")],
                "pr view": [self.resp(self.clean_pr())],
            },
            git={
                "ls-remote": [
                    self.resp("base0\trefs/heads/B"),
                    self.resp("head1\trefs/heads/C"),
                ]
            },
        )
        payload = self.payload(result)
        self.assertEqual(payload["shadow_pr"], 100)
        self.assertEqual(payload["url"], "https://github.com/octo/demo/pull/100")
        self.assertEqual(payload["repo"], REPO)
        calls = self.gh_calls()
        self.assert_gh_repo_targeting(calls)
        create = next(call for call in calls if call[:2] == ["pr", "create"])
        self.assertIn("--draft", create)
        self.assertEqual(self.opt(create, "--base"), "B")
        self.assertEqual(self.opt(create, "--head"), "C")
        edit = next(call for call in calls if call[:2] == ["pr", "edit"])
        self.assertEqual(self.opt(edit, "--add-label"), "do-not-merge")

    def test_open_shadow_pr_qualifies_cross_repository_head(self) -> None:
        body = self._body_file("Replay work.\n\nRefs #99\n")
        result = self.run_cli(
            "open-shadow-pr",
            "--repo",
            REPO,
            "--base",
            "B",
            "--head",
            "C",
            "--head-repo",
            "contributor/demo",
            "--title",
            "[SHADOW] PR",
            "--body-file",
            body,
            "--shadow-issue",
            "99",
            gh={
                "pr create": [self.resp("https://github.com/octo/demo/pull/100")],
                "pr edit": [self.resp("")],
                "pr view": [
                    self.resp(self.clean_pr(head_repo="contributor/demo"))
                ],
            },
            git={
                "ls-remote": [
                    self.resp("base0\trefs/heads/B"),
                    self.resp("head1\trefs/heads/C"),
                ]
            },
        )
        self.payload(result)
        create = next(call for call in self.gh_calls() if call[:2] == ["pr", "create"])
        self.assertEqual(self.opt(create, "--head"), "contributor:C")

    def test_open_shadow_pr_rejects_wrong_head_repository_after_create(self) -> None:
        body = self._body_file("Replay work.\n\nRefs #99\n")
        result = self.run_cli(
            "open-shadow-pr",
            "--repo",
            REPO,
            "--base",
            "B",
            "--head",
            "C",
            "--head-repo",
            "contributor/demo",
            "--title",
            "[SHADOW] PR",
            "--body-file",
            body,
            "--shadow-issue",
            "99",
            gh={
                "pr create": [self.resp("https://github.com/octo/demo/pull/100")],
                "pr edit": [self.resp("")],
                "pr view": [self.resp(self.clean_pr(head_repo="attacker/demo"))],
            },
            git={
                "ls-remote": [
                    self.resp("base0\trefs/heads/B"),
                    self.resp("head1\trefs/heads/C"),
                ]
            },
        )
        self.assert_failure(result)
        self.assertIn("head repository", result.stderr)

    def test_open_shadow_pr_rejects_candidate_without_a_commit(self) -> None:
        body = self._body_file("Replay work.\n\nRefs #99\n")
        result = self.run_cli(
            "open-shadow-pr",
            "--repo",
            REPO,
            "--base",
            "B",
            "--head",
            "C",
            "--head-repo",
            REPO,
            "--title",
            "[SHADOW] PR",
            "--body-file",
            body,
            "--shadow-issue",
            "99",
            git={
                "ls-remote": [
                    self.resp("base0\trefs/heads/B"),
                    self.resp("base0\trefs/heads/C"),
                ]
            },
        )
        self.assert_failure(result)
        self.assertIn("no commits", result.stderr)
        self.assertEqual(self.gh_calls(), [])

    def test_open_shadow_pr_rejects_closing_keyword_before_create(self) -> None:
        bodies = (
            "Refs #99\nCloses #99\n",
            "Refs #99\nCloses: #99\n",
            "Refs #99\nFixes octo/demo#99\n",
        )
        for body_text in bodies:
            with self.subTest(body=body_text):
                result = self.run_cli(
                    "open-shadow-pr",
                    "--repo",
                    REPO,
                    "--base",
                    "B",
                    "--head",
                    "C",
                    "--title",
                    "[SHADOW] PR",
                    "--body-file",
                    self._body_file(body_text),
                )
                self.assert_failure(result)
                self.assertEqual(self.gh_calls(), [])

    def test_open_shadow_pr_rejects_missing_refs(self) -> None:
        body = self._body_file("Replay work with no reference.\n")
        result = self.run_cli(
            "open-shadow-pr",
            "--repo",
            REPO,
            "--base",
            "B",
            "--head",
            "C",
            "--title",
            "[SHADOW] PR",
            "--body-file",
            body,
        )
        self.assert_failure(result)
        self.assertEqual(self.gh_calls(), [])

    # --------------------------------------------------- validate-invariants
    def _validate(
        self,
        issue: dict[str, Any],
        pr: dict[str, Any],
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "validate-invariants",
            "--repo",
            REPO,
            "--shadow-issue",
            "99",
            "--shadow-pr",
            "100",
            "--shadow-base",
            "B",
            "--candidate",
            "C",
            "--head-repo",
            REPO,
            gh={
                "issue view": [self.resp(issue)],
                "pr view": [self.resp(pr)],
            },
        )

    def test_validate_invariants_clean_pass(self) -> None:
        result = self._validate(self.clean_issue(), self.clean_pr())
        payload = self.payload(result)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["repo"], REPO)
        self.assertEqual(payload["shadow_issue"], 99)
        self.assertEqual(payload["shadow_pr"], 100)
        self.assert_gh_repo_targeting(self.gh_calls())

    def test_validate_invariants_before_pr_checks_pre_pr_state(self) -> None:
        result = self.run_cli(
            "validate-invariants",
            "--repo",
            REPO,
            "--shadow-issue",
            "99",
            "--shadow-base",
            "B",
            "--candidate",
            "C",
            "--historical-base",
            "base0",
            "--remote",
            "origin",
            "--repo-path",
            str(self.root),
            gh={"issue view": [self.resp(self.clean_issue())]},
            git={"ls-remote": [self.resp("base0\trefs/heads/B")]},
        )
        payload = self.payload(result)
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["shadow_pr"])
        self.assertNotIn(["pr", "view"], [call[:2] for call in self.gh_calls()])

    def test_validate_invariants_detects_each_drift(self) -> None:
        drifts = {
            "status_label": (
                self.clean_issue(labels=("experiment:shadow", "status:todo")),
                self.clean_pr(),
            ),
            "milestone": (
                self.clean_issue(milestone={"title": "M1"}),
                self.clean_pr(),
            ),
            "assigned_issue": (
                self.clean_issue(assignees=("octocat",)),
                self.clean_pr(),
            ),
            "blocked_by_dependency": (
                self.clean_issue(body="Replay packet.\n\nBlocked by #11\n"),
                self.clean_pr(),
            ),
            "wrong_base": (self.clean_issue(), self.clean_pr(base="WRONG")),
            "wrong_head": (self.clean_issue(), self.clean_pr(head="WRONG")),
            "missing_do_not_merge": (
                self.clean_issue(),
                self.clean_pr(labels=()),
            ),
            "not_draft": (self.clean_issue(), self.clean_pr(is_draft=False)),
            "merged": (self.clean_issue(), self.clean_pr(merged=True)),
            "closing_keyword": (
                self.clean_issue(),
                self.clean_pr(body="Refs #99\nCloses #99\n"),
            ),
            "missing_shadow_label": (self.clean_issue(labels=()), self.clean_pr()),
            "closed_issue": (self.clean_issue(state="CLOSED"), self.clean_pr()),
            "closed_pr": (self.clean_issue(), self.clean_pr(state="CLOSED")),
            "wrong_head_repository": (
                self.clean_issue(),
                self.clean_pr(head_repo="attacker/demo"),
            ),
        }
        for name, (issue, pr) in drifts.items():
            with self.subTest(drift=name):
                result = self._validate(issue, pr)
                self.assert_failure(result)

    # ---------------------------------------------------------------- cleanup
    def test_cleanup_closes_draft_without_merge(self) -> None:
        worktree = self.root / "wt"
        worktree.mkdir()
        result = self.run_cli(
            "cleanup",
            "--repo",
            REPO,
            "--shadow-pr",
            "100",
            "--shadow-issue",
            "99",
            "--worktree",
            str(worktree),
            gh={
                "pr view": [
                    self.resp(self.clean_pr()),
                    self.resp(self.clean_pr(state="CLOSED")),
                ],
                "pr close": [self.resp("")],
                "issue close": [self.resp("")],
                "issue view": [
                    self.resp(self.clean_issue(state="CLOSED")),
                ],
            },
        )
        payload = self.payload(result)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["merged"])
        self.assertTrue(payload["branches_retained"])
        self.assertEqual(payload["repo"], REPO)
        calls = self.gh_calls()
        self.assert_gh_repo_targeting(calls)
        operations = [call[:2] for call in calls]
        self.assertNotIn(["pr", "merge"], operations)
        self.assertIn(["pr", "close"], operations)
        issue_close = next(call for call in calls if call[:2] == ["issue", "close"])
        self.assertEqual(self.opt(issue_close, "--reason"), "completed")
        git_operations = [
            call[2] if call and call[0] == "-C" else (call[0] if call else "")
            for call in self.git_calls()
        ]
        self.assertNotIn("merge", git_operations)
        self.assertIn("worktree", git_operations)

    def test_cleanup_rejects_ineffective_issue_close_before_worktree_removal(self) -> None:
        worktree = self.root / "wt"
        worktree.mkdir()
        result = self.run_cli(
            "cleanup",
            "--repo",
            REPO,
            "--shadow-pr",
            "100",
            "--shadow-issue",
            "99",
            "--worktree",
            str(worktree),
            gh={
                "pr view": [
                    self.resp(self.clean_pr()),
                    self.resp(self.clean_pr(state="CLOSED")),
                ],
                "pr close": [self.resp("")],
                "issue close": [self.resp("")],
                "issue view": [self.resp(self.clean_issue(state="OPEN"))],
            },
        )
        self.assert_failure(result)
        self.assertIn("not CLOSED", result.stderr)
        self.assertNotIn("worktree", [call[0] for call in self.git_calls() if call])

    def test_cleanup_refuses_merged_pr(self) -> None:
        result = self.run_cli(
            "cleanup",
            "--repo",
            REPO,
            "--shadow-pr",
            "100",
            "--shadow-issue",
            "99",
            gh={"pr view": [self.resp(self.clean_pr(merged=True, state="MERGED"))]},
        )
        self.assert_failure(result)
        operations = [call[:2] for call in self.gh_calls()]
        self.assertNotIn(["pr", "close"], operations)
        self.assertNotIn(["pr", "merge"], operations)
        self.assertNotIn(["issue", "close"], operations)
        git_operations = [
            call[2] if call and call[0] == "-C" else (call[0] if call else "")
            for call in self.git_calls()
        ]
        self.assertNotIn("merge", git_operations)

    # ---------------------------------------------------------------- metrics
    def _log_file(self, name: str, records: list[dict[str, Any]]) -> str:
        path = self.root / name
        path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )
        return str(path)

    def test_metrics_claude_code_sums_incremental_and_counts_threads(self) -> None:
        log = self._log_file(
            "claude.jsonl",
            [
                {
                    "type": "assistant",
                    "sessionId": "s1",
                    "message": {
                        "usage": {
                            "input_tokens": 100,
                            "cache_read_input_tokens": 10,
                            "cache_creation_input_tokens": 5,
                            "output_tokens": 20,
                        }
                    },
                },
                {
                    "type": "assistant",
                    "sessionId": "s1",
                    "message": {
                        "usage": {
                            "input_tokens": 200,
                            "cache_read_input_tokens": 30,
                            "cache_creation_input_tokens": 15,
                            "output_tokens": 40,
                        }
                    },
                },
                {
                    "type": "assistant",
                    "sessionId": "s1",
                    "isSidechain": True,
                    "message": {
                        "usage": {
                            "input_tokens": 50,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                            "output_tokens": 5,
                        }
                    },
                },
            ],
        )
        result = self.run_cli("metrics", "--harness", "claude-code", "--log", log)
        payload = self.payload(result)
        self.assertEqual(payload["harness"], "claude-code")
        self.assertEqual(payload["threads"], 2)
        # input = (100+5)+(200+15)+(50+0)
        self.assertEqual(payload["input_tokens"], 370)
        self.assertEqual(payload["cached_input_tokens"], 40)
        self.assertEqual(payload["output_tokens"], 65)
        self.assertIsNone(payload["reasoning_tokens"])
        self.assertEqual(payload["unattributed_tokens"], 0)
        self.assertEqual(payload["cache_write_tokens"], 20)
        self.assertEqual(payload["max_request_input_tokens"], 245)
        self.assertEqual(self.gh_calls(), [])
        self.assertEqual(self.git_calls(), [])

    def _codex_token_event(
        self, *, last_input: int | None = None, **totals: int
    ) -> dict[str, Any]:
        # Real Codex rollout envelope: type=event_msg, payload.type=token_count.
        info: dict[str, Any] = {"total_token_usage": totals}
        if last_input is not None:
            info["last_token_usage"] = {"input_tokens": last_input}
        return {
            "type": "event_msg",
            "payload": {"type": "token_count", "info": info},
        }

    def test_metrics_codex_keeps_last_cumulative_event(self) -> None:
        log = self._log_file(
            "codex.jsonl",
            [
                {"type": "session_meta", "payload": {"id": "sess-1"}},
                self._codex_token_event(
                    last_input=100,
                    input_tokens=100,
                    cached_input_tokens=10,
                    output_tokens=20,
                    reasoning_output_tokens=5,
                ),
                self._codex_token_event(
                    last_input=250,
                    input_tokens=300,
                    cached_input_tokens=30,
                    output_tokens=60,
                    reasoning_output_tokens=15,
                ),
            ],
        )
        result = self.run_cli("metrics", "--harness", "codex", "--log", log)
        payload = self.payload(result)
        self.assertEqual(payload["harness"], "codex")
        self.assertEqual(payload["threads"], 1)
        # Last cumulative event wins; NOT summed (400/40/80/20).
        self.assertEqual(payload["input_tokens"], 300)
        self.assertEqual(payload["cached_input_tokens"], 30)
        self.assertEqual(payload["output_tokens"], 60)
        self.assertEqual(payload["reasoning_tokens"], 15)
        self.assertEqual(payload["max_request_input_tokens"], 250)
        self.assertIsNone(payload["cache_write_tokens"])

    def test_metrics_codex_sums_across_logs(self) -> None:
        # One rollout file is one thread; parent + child sessions are separate logs, summed.
        log_a = self._log_file(
            "codex_a.jsonl",
            [
                self._codex_token_event(
                    input_tokens=300,
                    cached_input_tokens=30,
                    output_tokens=60,
                    reasoning_output_tokens=15,
                )
            ],
        )
        log_b = self._log_file(
            "codex_b.jsonl",
            [
                self._codex_token_event(
                    input_tokens=100,
                    cached_input_tokens=5,
                    output_tokens=10,
                    reasoning_output_tokens=5,
                )
            ],
        )
        result = self.run_cli(
            "metrics", "--harness", "codex", "--log", log_a, "--log", log_b
        )
        payload = self.payload(result)
        self.assertEqual(payload["threads"], 2)
        self.assertEqual(payload["input_tokens"], 400)
        self.assertEqual(payload["cached_input_tokens"], 35)
        self.assertEqual(payload["output_tokens"], 70)
        self.assertEqual(payload["reasoning_tokens"], 20)

    def test_metrics_codex_missing_reasoning_is_unavailable(self) -> None:
        log = self._log_file(
            "codex_no_reasoning.jsonl",
            [
                self._codex_token_event(
                    input_tokens=300,
                    cached_input_tokens=30,
                    output_tokens=60,
                )
            ],
        )
        payload = self.payload(
            self.run_cli("metrics", "--harness", "codex", "--log", log)
        )
        self.assertIsNone(payload["reasoning_tokens"])

    def test_metrics_claude_code_unattributed_records_bucketed_and_totaled(self) -> None:
        # A claude-code assistant record with no sessionId is unattributable; its tokens
        # go to the unattributed bucket but are still included in the grand totals.
        log = self._log_file(
            "cc_unattr.jsonl",
            [
                {
                    "type": "assistant",
                    "sessionId": "s1",
                    "message": {"usage": {"input_tokens": 100, "output_tokens": 10}},
                },
                {
                    "type": "assistant",
                    "message": {"usage": {"input_tokens": 40, "output_tokens": 4}},
                },
            ],
        )
        result = self.run_cli("metrics", "--harness", "claude-code", "--log", log)
        payload = self.payload(result)
        self.assertGreater(payload["unattributed_tokens"], 0)
        self.assertEqual(payload["input_tokens"], 140)
        self.assertEqual(payload["output_tokens"], 14)

    # ---------------------------------------------------------------- pricing
    def test_pricing_known_model_exact_cost(self) -> None:
        result = self.run_cli(
            "pricing",
            "--provider",
            "anthropic",
            "--model",
            "claude-opus-4-8",
            "--input",
            "1000000",
            "--cached-input",
            "1000000",
            "--cache-write",
            "1000000",
            "--output",
            "1000000",
            "--reasoning",
            "1000000",
        )
        payload = self.payload(result)
        # 5.0 + 0.5 + 6.25 + 25.0 + reasoning-at-output 25.0
        self.assertAlmostEqual(payload["cost"], 61.75)
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(payload["model"], "claude-opus-4-8")
        self.assertEqual(payload["provider"], "anthropic")
        self.assertEqual(payload["catalog_version"], "5")

    def test_pricing_gpt_5_6_base_rates_handle_subsets_and_cache_writes(self) -> None:
        result = self.run_cli(
            "pricing",
            "--provider",
            "openai",
            "--model",
            "openai/gpt-5.6",
            "--input",
            "1000000",
            "--cached-input",
            "100000",
            "--cache-write",
            "50000",
            "--output",
            "100000",
            "--reasoning",
            "10000",
            "--max-request-input",
            "200000",
        )
        payload = self.payload(result)
        # OpenAI input includes cached reads and cache writes as subsets, and Codex
        # reasoning_output_tokens is already included in output_tokens:
        # 850k*5 + 100k*0.5 + 50k*6.25 + 100k*30.
        self.assertAlmostEqual(payload["cost"], 7.6125)
        self.assertEqual(payload["pricing_tier"], "base")
        self.assertEqual(payload["catalog_version"], "5")

    def test_pricing_gpt_5_6_applies_long_context_multipliers(self) -> None:
        result = self.run_cli(
            "pricing",
            "--provider",
            "openai",
            "--model",
            "openai/gpt-5.6",
            "--input",
            "1000000",
            "--cached-input",
            "100000",
            "--cache-write",
            "50000",
            "--output",
            "100000",
            "--reasoning",
            "10000",
            "--max-request-input",
            "272001",
        )
        payload = self.payload(result)
        self.assertAlmostEqual(payload["cost"], 13.725)
        self.assertEqual(payload["pricing_tier"], "long_context")

    def test_pricing_gpt_5_6_requires_explicit_context_tier(self) -> None:
        result = self.run_cli(
            "pricing",
            "--provider",
            "openai",
            "--model",
            "openai/gpt-5.6",
            "--input",
            "1000",
            "--cache-write",
            "0",
        )
        payload = self.payload(result)
        self.assertEqual(payload["cost"], "unavailable")
        self.assertIn("--max-request-input", payload["reason"])

    def test_pricing_gpt_5_6_requires_explicit_cache_writes(self) -> None:
        result = self.run_cli(
            "pricing",
            "--provider",
            "openai",
            "--model",
            "openai/gpt-5.6",
            "--input",
            "1000",
            "--max-request-input",
            "1000",
        )
        payload = self.payload(result)
        self.assertEqual(payload["cost"], "unavailable")
        self.assertIn("cache writes", payload["reason"])

    def test_pricing_unknown_model_is_unavailable(self) -> None:
        result = self.run_cli(
            "pricing",
            "--provider",
            "anthropic",
            "--model",
            "no-such-model",
            "--input",
            "1000",
        )
        payload = self.payload(result)
        self.assertEqual(payload["cost"], "unavailable")
        self.assertIn("reason", payload)

    def test_pricing_missing_rate_is_unavailable(self) -> None:
        catalog = self.root / "catalog.json"
        catalog.write_text(
            json.dumps(
                {
                    "catalog_version": "9",
                    "generated": "2026-01-01",
                    "prices": [
                        {
                            "provider": "test",
                            "model": "norate",
                            "effective_date": "2026-01-01",
                            "source_url": "https://example.test",
                            "currency": "USD",
                            "unit": "per_mtok",
                            "input": 10.0,
                            "cached_input": 1.0,
                            "reasoning": "output",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = self.run_cli(
            "pricing",
            "--catalog",
            str(catalog),
            "--provider",
            "test",
            "--model",
            "norate",
            "--output",
            "1000000",
        )
        payload = self.payload(result)
        self.assertEqual(payload["cost"], "unavailable")
        self.assertIn("reason", payload)

    # ---------------------------------------------------------------- compare
    def _compare_file(self, name: str, blob: dict[str, Any]) -> str:
        path = self.root / name
        path.write_text(json.dumps(blob), encoding="utf-8")
        return str(path)

    @staticmethod
    def _norm(text: str) -> str:
        return text.strip().lower().replace(" ", "_").replace("-", "_")

    def test_compare_renders_missing_values_as_unavailable(self) -> None:
        original = self._compare_file(
            "original.json",
            {
                "dod_criteria_met": {
                    "value": "5/5",
                    "evidence": "https://example.test/original-dod",
                },
                "input_tokens": 1000,
                "files_changed": None,
            },
        )
        shadow = self._compare_file(
            "shadow.json",
            {
                "dod_criteria_met": {
                    "value": "5/5",
                    "evidence": "https://example.test/shadow-dod",
                },
                "output_tokens": 2000,
            },
        )
        result = self.run_cli("compare", "--original", original, "--shadow", shadow)
        payload = self.payload(result)
        rows = payload["rows"]
        self.assertEqual(len(rows), 14)
        for row in rows:
            self.assertEqual(
                {"dimension", "original", "shadow", "evidence"} - set(row), set()
            )
        by_dimension = {self._norm(row["dimension"]): row for row in rows}

        input_row = by_dimension["input_tokens"]
        self.assertNotEqual(input_row["original"], "unavailable")
        self.assertEqual(input_row["shadow"], "unavailable")

        output_row = by_dimension["output_tokens"]
        self.assertEqual(output_row["original"], "unavailable")
        self.assertNotEqual(output_row["shadow"], "unavailable")

        # A null value renders as unavailable, same as a missing key.
        self.assertEqual(by_dimension["files_changed"]["original"], "unavailable")
        self.assertIn("original-dod", by_dimension["dod_criteria_met"]["evidence"])
        self.assertIn("shadow-dod", by_dimension["dod_criteria_met"]["evidence"])

    # ----------------------------------------------------------------- report
    def _report_data(self, **overrides: Any) -> dict[str, Any]:
        data = {
            "run_id": "20260721T143000Z-abcd1234",
            "harness": "claude-code",
            "runtime_version": "2.1.0",
            "model": "claude-opus-4-8",
            "reasoning_effort": "high",
            "source_issue_url": "https://github.com/octo/demo/issues/3",
            "source_pr_url": "https://github.com/octo/demo/pull/7",
            "source_merge_sha": "a" * 40,
            "historical_base": "b" * 40,
            "cutoff": "2026-01-01T00:00:00Z",
            "shadow_issue_url": "https://github.com/octo/demo/issues/99",
            "shadow_pr_url": "https://github.com/octo/demo/pull/100",
            "candidate_head": "c" * 40,
            "execution_repository": "/workspace/replay",
            "execution_revision": "b" * 40,
            "rules_loaded": "none",
            "final_state": "evaluation-complete",
            "comparison": [
                {
                    "dimension": dimension,
                    "original": "5/5",
                    "shadow": "5/5",
                    "evidence": f"https://example.test/evidence#{index}",
                }
                for index, dimension in enumerate(COMPARISON_DIMENSIONS, start=1)
            ],
            "verification": "All DoD criteria satisfied.",
            "disclosures": ["Custom extra disclosure sentence for this run."],
        }
        data.update(overrides)
        return data

    def _write_report_data(self, data: dict[str, Any]) -> str:
        path = self.root / "report_data.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_report_renders_all_sections_and_disclosures(self) -> None:
        data_file = self._write_report_data(self._report_data())
        result = self.run_cli("report", "--data", data_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        markdown = result.stdout
        self.assertIn(
            "## dev:shadow evaluation - 20260721T143000Z-abcd1234", markdown
        )
        self.assertIn("### Quality and delivery comparison", markdown)
        self.assertIn("Harness: claude-code 2.1.0", markdown)
        self.assertIn("Execution repository: /workspace/replay", markdown)
        self.assertIn(f"Execution revision: {'b' * 40}", markdown)
        self.assertIn("Rules loaded: none", markdown)
        self.assertIn("|", markdown)
        self.assertIn("### Limitations", markdown)
        for disclosure in REQUIRED_DISCLOSURES:
            self.assertIn(disclosure, markdown)
        self.assertIn("Custom extra disclosure sentence for this run.", markdown)

    def test_report_renders_missing_optional_value_as_unavailable(self) -> None:
        # reasoning_effort is not an audit binding, so its absence renders "unavailable"
        # rather than failing schema validation.
        data = self._report_data()
        del data["reasoning_effort"]
        data_file = self._write_report_data(data)
        result = self.run_cli("report", "--data", data_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Reasoning effort: unavailable", result.stdout)

    def test_report_rejects_missing_required_binding(self) -> None:
        # A completed report missing an audit binding (reviewed candidate head) must fail,
        # not silently render "unavailable" and let cleanup close the artifacts.
        data = self._report_data()
        del data["candidate_head"]
        data_file = self._write_report_data(data)
        result = self.run_cli("report", "--data", data_file)
        self.assert_failure(result)
        self.assertIn("candidate head", result.stderr.lower())

    def test_report_rejects_missing_source_merge_sha(self) -> None:
        data = self._report_data()
        del data["source_merge_sha"]
        data_file = self._write_report_data(data)
        result = self.run_cli("report", "--data", data_file)
        self.assert_failure(result)

    def test_report_rejects_malformed_urls_and_shas(self) -> None:
        for field, value in (
            ("source_issue_url", "x"),
            ("source_pr_url", "x"),
            ("shadow_issue_url", "x"),
            ("shadow_pr_url", "x"),
            ("source_merge_sha", "merge9"),
            ("historical_base", "base0"),
            ("candidate_head", "head1"),
            ("execution_revision", "base0"),
        ):
            with self.subTest(field=field):
                data = self._report_data(**{field: value})
                result = self.run_cli("report", "--data", self._write_report_data(data))
                self.assert_failure(result)

    def test_report_rejects_missing_runtime_and_project_provenance(self) -> None:
        for field in (
            "runtime_version",
            "execution_repository",
            "execution_revision",
            "rules_loaded",
        ):
            with self.subTest(field=field):
                data = self._report_data()
                del data[field]
                result = self.run_cli("report", "--data", self._write_report_data(data))
                self.assert_failure(result)

    def test_report_rejects_missing_final_state(self) -> None:
        data = self._report_data()
        del data["final_state"]
        result = self.run_cli("report", "--data", self._write_report_data(data))
        self.assert_failure(result)
        self.assertIn("evaluation-complete", result.stderr)

    def test_report_rejects_missing_comparison_row(self) -> None:
        data = self._report_data()
        data["comparison"] = data["comparison"][:-1]
        result = self.run_cli("report", "--data", self._write_report_data(data))
        self.assert_failure(result)
        self.assertIn("missing", result.stderr)

    def test_report_rejects_comparison_row_without_evidence(self) -> None:
        data = self._report_data()
        data["comparison"][0]["evidence"] = "unavailable"
        result = self.run_cli("report", "--data", self._write_report_data(data))
        self.assert_failure(result)
        self.assertIn("evidence", result.stderr)

    def test_report_failed_state_exempts_bindings(self) -> None:
        # A failure report (final_state: failed:<stage>) renders even without every binding.
        data = {"run_id": "r1", "final_state": "failed:execute"}
        data_file = self._write_report_data(data)
        result = self.run_cli("report", "--data", data_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## dev:shadow evaluation - r1", result.stdout)

    def test_report_out_writes_file_and_prints_path(self) -> None:
        data_file = self._write_report_data(self._report_data())
        out_path = self.root / "report.md"
        result = self.run_cli(
            "report", "--data", data_file, "--out", str(out_path)
        )
        payload = self.payload(result)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["path"], str(out_path))
        written = out_path.read_text(encoding="utf-8")
        self.assertIn(
            "## dev:shadow evaluation - 20260721T143000Z-abcd1234", written
        )
        for disclosure in REQUIRED_DISCLOSURES:
            self.assertIn(disclosure, written)


    # ----------------------------------------------- validate-invariants binding
    def test_validate_invariants_detects_forced_shadow_base(self) -> None:
        # A force-push moving the immutable shadow-base ref off the historical base fails,
        # even though branch names and PR fields still look correct.
        result = self.run_cli(
            "validate-invariants",
            "--repo",
            REPO,
            "--shadow-issue",
            "99",
            "--shadow-pr",
            "100",
            "--shadow-base",
            "B",
            "--candidate",
            "C",
            "--head-repo",
            REPO,
            "--historical-base",
            "base0",
            "--remote",
            "origin",
            "--repo-path",
            str(self.root),
            gh={
                "issue view": [self.resp(self.clean_issue())],
                "pr view": [self.resp(self.clean_pr())],
            },
            git={"ls-remote": [self.resp("deadbeef\trefs/heads/B")]},
        )
        self.assert_failure(result)
        self.assertIn("base0", result.stderr)

    def test_validate_invariants_binding_pass(self) -> None:
        source_issue = {"state": "CLOSED", "stateReason": "COMPLETED"}
        source_pr = {"merged": True, "mergeCommit": {"oid": "merge9"}}
        result = self.run_cli(
            "validate-invariants",
            "--repo",
            REPO,
            "--shadow-issue",
            "99",
            "--shadow-pr",
            "100",
            "--shadow-base",
            "B",
            "--candidate",
            "C",
            "--head-repo",
            REPO,
            "--historical-base",
            "base0",
            "--remote",
            "origin",
            "--repo-path",
            str(self.root),
            "--source-issue",
            "3",
            "--source-pr",
            "7",
            "--source-merge-sha",
            "merge9",
            "--source-snapshot-sha256",
            "73f5f16364d9770bc2f2ab145e6078e744f11e316682d664d77c78699bf144d4",
            gh={
                "issue view": [
                    self.resp(self.clean_issue()),
                    self.resp(source_issue),
                ],
                "pr view": [
                    self.resp(self.clean_pr()),
                    self.resp(source_pr),
                ],
            },
            git={"ls-remote": [self.resp("base0\trefs/heads/B")]},
        )
        payload = self.payload(result)
        self.assertTrue(payload["ok"])

    def test_validate_invariants_detects_changed_source_merge(self) -> None:
        # A mutated source PR (merge commit changed since preflight) fails the invariant.
        source_issue = {"state": "CLOSED", "stateReason": "COMPLETED"}
        current_pr = {"merged": True, "mergeCommit": {"oid": "different"}}
        result = self.run_cli(
            "validate-invariants",
            "--repo",
            REPO,
            "--shadow-issue",
            "99",
            "--shadow-pr",
            "100",
            "--shadow-base",
            "B",
            "--candidate",
            "C",
            "--head-repo",
            REPO,
            "--source-issue",
            "3",
            "--source-pr",
            "7",
            "--source-merge-sha",
            "merge9",
            "--source-snapshot-sha256",
            "b5da2ba87b7d73bad84e6f28213406a1cff72cbe9e87317910bbf2d6279b4fe4",
            gh={
                "issue view": [
                    self.resp(self.clean_issue()),
                    self.resp(source_issue),
                ],
                "pr view": [
                    self.resp(self.clean_pr()),
                    self.resp(current_pr),
                ],
            },
        )
        self.assert_failure(result)

    def test_validate_invariants_detects_source_content_mutation(self) -> None:
        original_issue = {
            "state": "CLOSED",
            "stateReason": "COMPLETED",
            "title": "Original issue title",
            "body": "Original issue body",
            "labels": [{"name": "enhancement"}],
        }
        changed_issue = {**original_issue, "body": "Edited after preflight"}
        source_pr = {
            "state": "MERGED",
            "merged": True,
            "mergeCommit": {"oid": "merge9"},
            "title": "Original PR title",
            "body": "Original PR body",
        }
        result = self.run_cli(
            "validate-invariants",
            "--repo",
            REPO,
            "--shadow-issue",
            "99",
            "--shadow-pr",
            "100",
            "--shadow-base",
            "B",
            "--candidate",
            "C",
            "--head-repo",
            REPO,
            "--source-issue",
            "3",
            "--source-pr",
            "7",
            "--source-merge-sha",
            "merge9",
            "--source-snapshot-sha256",
            "5a9633438f13551bd8368cb33cef275fb37989be6873d8621f0d5509601c3dae",
            gh={
                "issue view": [
                    self.resp(self.clean_issue()),
                    self.resp(changed_issue),
                ],
                "pr view": [self.resp(self.clean_pr()), self.resp(source_pr)],
            },
        )
        self.assert_failure(result)
        self.assertIn("content changed", result.stderr)

    def test_validate_invariants_binds_refs_to_shadow_issue(self) -> None:
        # A body that references a different issue number no longer counts as the reference.
        result = self._validate(self.clean_issue(), self.clean_pr(body="Refs #4242\n"))
        self.assert_failure(result)

    # ------------------------------------------------------- review-freshness
    def test_review_freshness_accepts_matching_head(self) -> None:
        result = self.run_cli(
            "review-freshness",
            "--repo",
            REPO,
            "--shadow-pr",
            "100",
            "--review-commit",
            "abc123",
            gh={"pr view": [self.resp(self.clean_pr(head_oid="abc123"))]},
        )
        payload = self.payload(result)
        self.assertTrue(payload["fresh"])
        self.assertEqual(payload["head"], "abc123")
        self.assert_gh_repo_targeting(self.gh_calls())

    def test_review_freshness_rejects_stale_approval(self) -> None:
        # A fix push advanced the head; the old approval SHA no longer verifies the head.
        result = self.run_cli(
            "review-freshness",
            "--repo",
            REPO,
            "--shadow-pr",
            "100",
            "--review-commit",
            "oldsha",
            gh={"pr view": [self.resp(self.clean_pr(head_oid="newsha"))]},
        )
        self.assert_failure(result)
        self.assertIn("stale", result.stderr.lower())

    # ---------------------------------------------------------- fix-attempt
    def test_fix_attempt_allows_configured_bound(self) -> None:
        result = self.run_cli("fix-attempt", "--attempt", "3", "--max-attempts", "3")
        payload = self.payload(result)
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["attempt"], 3)

    def test_fix_attempt_rejects_fourth_cycle_when_max_is_three(self) -> None:
        result = self.run_cli("fix-attempt", "--attempt", "4", "--max-attempts", "3")
        self.assert_failure(result)
        self.assertIn("max_fix_attempts=3", result.stderr)


if __name__ == "__main__":
    unittest.main()
