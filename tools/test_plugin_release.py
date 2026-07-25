#!/usr/bin/env -S uv run
"""Network-free contract tests for the plugin tag and release CLI."""

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
RELEASE_CLI = REPOSITORY_ROOT / "plugins/dev/scripts/plugin_release.py"
TEST_REPOSITORY = "example/project"


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


scenario_path = Path(os.environ["PLUGIN_RELEASE_TEST_SCENARIO"])
calls_path = Path(os.environ["PLUGIN_RELEASE_TEST_GH_CALLS"])
arguments = sys.argv[1:]

record = {"arguments": arguments}
if "--notes-file" in arguments:
    notes_path = Path(arguments[arguments.index("--notes-file") + 1])
    record["notes"] = notes_path.read_text(encoding="utf-8")
with calls_path.open("a", encoding="utf-8") as calls_file:
    calls_file.write(json.dumps(record) + "\n")

if arguments[:2] == ["release", "view"]:
    operation = "release-view"
elif arguments[:2] == ["release", "create"]:
    operation = "release-create"
elif arguments[:1] == ["api"] and "--method" in arguments:
    operation = "tag-create"
elif arguments[:1] == ["api"] and "/git/ref/tags/" in arguments[1]:
    operation = "tag-read"
elif arguments[:1] == ["api"] and "/compare/" in arguments[1]:
    operation = "compare"
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


NOT_FOUND = {
    "returncode": 1,
    "stderr": "gh: Not Found (HTTP 404)",
    "stdout": "",
}
RELEASE_NOT_FOUND = {
    "returncode": 1,
    "stderr": "release not found",
    "stdout": "",
}


class PluginReleaseTestCase(unittest.TestCase):
    """Fixture: a real git repository plus a scripted fake `gh`."""

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

        self.git(None, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(None, "clone", str(self.remote), str(self.checkout))
        self.git(self.checkout, "config", "user.name", "Release Test")
        self.git(self.checkout, "config", "user.email", "release-test@example.com")

        self.versions = {"dev": "0.0.1", "utils": "0.0.1"}
        self.write_versions(self.versions)
        self.write_changelog(["## dev-v0.0.1", "", "- first dev release."])
        self.base_oid = self.commit("base")

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

    def write_versions(
        self,
        versions: dict[str, str],
        *,
        marketplace_overrides: dict[str, str] | None = None,
    ) -> None:
        overrides = marketplace_overrides or {}
        marketplace = {
            "name": "example",
            "metadata": {"version": "0.0.1"},
            "plugins": [
                {
                    "name": name,
                    "source": f"./plugins/{name}",
                    "version": overrides.get(name, version),
                }
                for name, version in sorted(versions.items())
            ],
        }
        marketplace_path = self.checkout / ".claude-plugin/marketplace.json"
        marketplace_path.parent.mkdir(parents=True, exist_ok=True)
        marketplace_path.write_text(
            json.dumps(marketplace, indent=2) + "\n", encoding="utf-8"
        )
        for name, version in versions.items():
            for manifest in (".claude-plugin", ".codex-plugin"):
                path = self.checkout / "plugins" / name / manifest / "plugin.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps({"name": name, "version": version}, indent=2) + "\n",
                    encoding="utf-8",
                )

    def write_changelog(self, lines: Sequence[str]) -> None:
        content = "# Changelog\n\n" + "\n".join(lines) + "\n"
        (self.checkout / "CHANGELOG.md").write_text(content, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git(self.checkout, "add", "-A")
        self.git(self.checkout, "commit", "-m", message)
        return self.git(self.checkout, "rev-parse", "HEAD").stdout.strip()

    def scenario(self, **responses: list[dict[str, Any]]) -> None:
        self.scenario_path.write_text(
            json.dumps({"responses": responses, "indexes": {}}), encoding="utf-8"
        )
        self.calls_path.write_text("", encoding="utf-8")

    def calls(self) -> list[dict[str, Any]]:
        content = self.calls_path.read_text(encoding="utf-8").strip()
        if not content:
            return []
        return [json.loads(line) for line in content.splitlines()]

    def gh_operations(self) -> list[list[str]]:
        return [call["arguments"] for call in self.calls()]

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.fake_bin}{os.pathsep}{environment['PATH']}"
        environment["PLUGIN_RELEASE_TEST_SCENARIO"] = str(self.scenario_path)
        environment["PLUGIN_RELEASE_TEST_GH_CALLS"] = str(self.calls_path)
        return subprocess.run(
            [
                "uv",
                "run",
                str(RELEASE_CLI),
                *arguments,
                "--repo",
                TEST_REPOSITORY,
                "--checkout",
                str(self.checkout),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

    def run_tag(self, before: str, head: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli("tag", "--before", before, "--head", head)

    def run_release(
        self, tag: str, *, confirm: bool = True
    ) -> subprocess.CompletedProcess[str]:
        arguments = ["release", "--tag", tag]
        if confirm:
            arguments.append("--confirm")
        return self.run_cli(*arguments)

    def receipt(self, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_refused(
        self, result: subprocess.CompletedProcess[str], fragment: str
    ) -> None:
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(fragment, result.stderr)

    def tag_reference(self, commit: str) -> dict[str, Any]:
        return {"stdout": {"object": {"sha": commit, "type": "commit"}}}

    def release_payload(
        self,
        *,
        tag: str = "dev-v0.0.2",
        name: str = "dev plugin v0.0.2",
        draft: bool = False,
        prerelease: bool = False,
        body: str = "- second dev release.",
    ) -> dict[str, Any]:
        return {
            "stdout": {
                "tagName": tag,
                "name": name,
                "isDraft": draft,
                "isPrerelease": prerelease,
                "url": f"https://github.com/{TEST_REPOSITORY}/releases/tag/{tag}",
                "body": body,
            }
        }


class TagOperationTests(PluginReleaseTestCase):
    def bump_dev(self, version: str = "0.0.2", *, changelog: bool = True) -> str:
        self.versions["dev"] = version
        self.write_versions(self.versions)
        if changelog:
            self.write_changelog(
                [
                    f"## dev-v{version}",
                    "",
                    "- second dev release.",
                    "",
                    "## dev-v0.0.1",
                    "",
                    "- first dev release.",
                ]
            )
        return self.commit(f"bump dev to {version}")

    def test_strict_increase_creates_exactly_one_tag(self) -> None:
        head = self.bump_dev()
        self.scenario(
            **{
                "tag-read": [NOT_FOUND, self.tag_reference(head)],
                "tag-create": [{"stdout": ""}],
            }
        )
        receipt = self.receipt(self.run_tag(self.base_oid, head))
        self.assertEqual(receipt["head"], head)
        created = [entry for entry in receipt["tags"] if entry["action"] == "created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["tag"], "dev-v0.0.2")
        self.assertEqual(created[0]["previous_version"], "0.0.1")
        unchanged = [
            entry for entry in receipt["tags"] if entry["plugin"] == "utils"
        ]
        self.assertEqual(unchanged[0]["action"], "unchanged")
        self.assertIsNone(unchanged[0]["tag"])

        posts = [
            arguments
            for arguments in self.gh_operations()
            if "--method" in arguments
        ]
        self.assertEqual(len(posts), 1)
        self.assertEqual(
            posts[0],
            [
                "api",
                "--method",
                "POST",
                f"repos/{TEST_REPOSITORY}/git/refs",
                "-f",
                "ref=refs/tags/dev-v0.0.2",
                "-f",
                f"sha={head}",
            ],
        )

    def test_no_version_change_is_a_successful_no_op(self) -> None:
        (self.checkout / "README.md").write_text("unrelated\n", encoding="utf-8")
        head = self.commit("unrelated change")
        self.scenario()
        receipt = self.receipt(self.run_tag(self.base_oid, head))
        self.assertTrue(all(entry["tag"] is None for entry in receipt["tags"]))
        self.assertTrue(
            all(entry["action"] == "unchanged" for entry in receipt["tags"])
        )
        self.assertEqual(self.gh_operations(), [])

    def test_one_commit_bumping_both_plugins_creates_both_tags(self) -> None:
        self.versions = {"dev": "0.0.2", "utils": "0.0.2"}
        self.write_versions(self.versions)
        self.write_changelog(
            [
                "## utils-v0.0.2",
                "",
                "- second utils release.",
                "",
                "## dev-v0.0.2",
                "",
                "- second dev release.",
            ]
        )
        head = self.commit("bump both plugins")
        self.scenario(
            **{
                "tag-read": [
                    NOT_FOUND,
                    NOT_FOUND,
                    self.tag_reference(head),
                    self.tag_reference(head),
                ],
                "tag-create": [{"stdout": ""}, {"stdout": ""}],
            }
        )
        receipt = self.receipt(self.run_tag(self.base_oid, head))
        created = sorted(
            entry["tag"] for entry in receipt["tags"] if entry["action"] == "created"
        )
        self.assertEqual(created, ["dev-v0.0.2", "utils-v0.0.2"])

    def test_new_plugin_without_baseline_is_tagged(self) -> None:
        self.versions["extra"] = "0.0.1"
        self.write_versions(self.versions)
        self.write_changelog(["## extra-v0.0.1", "", "- first extra release."])
        head = self.commit("add extra plugin")
        self.scenario(
            **{
                "tag-read": [NOT_FOUND, self.tag_reference(head)],
                "tag-create": [{"stdout": ""}],
            }
        )
        receipt = self.receipt(self.run_tag(self.base_oid, head))
        created = [entry for entry in receipt["tags"] if entry["action"] == "created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["tag"], "extra-v0.0.1")
        self.assertIsNone(created[0]["previous_version"])

    def test_desynchronized_version_fields_refuse_before_any_tag(self) -> None:
        self.versions["dev"] = "0.0.2"
        self.write_versions(self.versions, marketplace_overrides={"dev": "0.0.3"})
        self.write_changelog(["## dev-v0.0.2", "", "- second dev release."])
        head = self.commit("desynchronized bump")
        self.scenario()
        result = self.run_tag(self.base_oid, head)
        self.assert_refused(result, "not in lockstep")
        self.assertEqual(self.gh_operations(), [])

    def test_invalid_semver_refuses_before_any_tag(self) -> None:
        self.versions["dev"] = "0.0.2-beta"
        self.write_versions(self.versions)
        self.write_changelog(["## dev-v0.0.2-beta", "", "- prerelease."])
        head = self.commit("invalid semver")
        self.scenario()
        result = self.run_tag(self.base_oid, head)
        self.assert_refused(result, "is not semver")
        self.assertEqual(self.gh_operations(), [])

    def test_version_regression_refuses_before_any_tag(self) -> None:
        head = self.bump_dev("0.0.2")
        self.versions["dev"] = "0.0.1"
        self.write_versions(self.versions)
        regressed = self.commit("regress dev version")
        self.scenario()
        result = self.run_tag(head, regressed)
        self.assert_refused(result, "version regressed from 0.0.2 to 0.0.1")
        self.assertEqual(self.gh_operations(), [])

    def test_missing_changelog_heading_refuses_before_any_tag(self) -> None:
        head = self.bump_dev(changelog=False)
        self.scenario()
        result = self.run_tag(self.base_oid, head)
        self.assert_refused(result, "no exact release heading '## dev-v0.0.2'")
        self.assertEqual(self.gh_operations(), [])

    def test_existing_tag_at_another_commit_refuses_without_mutation(self) -> None:
        head = self.bump_dev()
        self.scenario(**{"tag-read": [self.tag_reference(self.base_oid)]})
        result = self.run_tag(self.base_oid, head)
        self.assert_refused(result, "is immutable and is never moved or replaced")
        self.assertEqual(
            [arguments for arguments in self.gh_operations() if "--method" in arguments],
            [],
        )

    def test_existing_tag_at_the_expected_commit_is_idempotent(self) -> None:
        head = self.bump_dev()
        self.scenario(**{"tag-read": [self.tag_reference(head)]})
        receipt = self.receipt(self.run_tag(self.base_oid, head))
        entry = next(item for item in receipt["tags"] if item["plugin"] == "dev")
        self.assertEqual(entry["action"], "already-tagged")
        self.assertEqual(entry["tag"], "dev-v0.0.2")
        self.assertEqual(
            [arguments for arguments in self.gh_operations() if "--method" in arguments],
            [],
        )

    def test_one_invalid_plugin_blocks_the_valid_plugin_tag(self) -> None:
        self.versions = {"dev": "0.0.2", "utils": "0.0.2"}
        self.write_versions(self.versions)
        self.write_changelog(["## dev-v0.0.2", "", "- second dev release."])
        head = self.commit("bump both, changelog only for dev")
        self.scenario()
        result = self.run_tag(self.base_oid, head)
        self.assert_refused(result, "no exact release heading '## utils-v0.0.2'")
        self.assertEqual(self.gh_operations(), [])

    def test_missing_baseline_commit_is_a_skipped_no_op(self) -> None:
        head = self.bump_dev()
        self.scenario()
        receipt = self.receipt(self.run_tag("0" * 40, head))
        self.assertEqual(receipt["tags"], [])
        self.assertIn("no baseline commit", receipt["skipped"])
        self.assertEqual(self.gh_operations(), [])


class ReleaseOperationTests(PluginReleaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.versions["dev"] = "0.0.2"
        self.write_versions(self.versions)
        self.write_changelog(
            [
                "## dev-v0.0.2",
                "",
                "- second dev release.",
                "- with two bullets.",
                "",
                "## dev-v0.0.1",
                "",
                "- first dev release.",
            ]
        )
        self.tagged_oid = self.commit("bump dev to 0.0.2")
        self.expected_notes = "- second dev release.\n- with two bullets."

    def test_creates_verified_release_from_the_tagged_changelog_section(self) -> None:
        self.scenario(
            **{
                "tag-read": [self.tag_reference(self.tagged_oid)],
                "compare": [{"stdout": "ahead"}],
                "release-view": [RELEASE_NOT_FOUND, self.release_payload()],
                "release-create": [{"stdout": ""}],
            }
        )
        receipt = self.receipt(self.run_release("dev-v0.0.2"))
        self.assertEqual(receipt["action"], "created")
        self.assertEqual(receipt["commit"], self.tagged_oid)
        self.assertEqual(receipt["release"]["name"], "dev plugin v0.0.2")
        self.assertEqual(
            receipt["release"]["url"],
            f"https://github.com/{TEST_REPOSITORY}/releases/tag/dev-v0.0.2",
        )

        creates = [
            call for call in self.calls() if call["arguments"][:2] == ["release", "create"]
        ]
        self.assertEqual(len(creates), 1)
        arguments = creates[0]["arguments"]
        self.assertEqual(arguments[2], "dev-v0.0.2")
        self.assertEqual(arguments[3:5], ["--repo", TEST_REPOSITORY])
        self.assertEqual(arguments[5:7], ["--title", "dev plugin v0.0.2"])
        self.assertIn("--verify-tag", arguments)
        self.assertNotIn("--draft", arguments)
        self.assertNotIn("--prerelease", arguments)
        self.assertEqual(creates[0]["notes"].strip(), self.expected_notes)

        views = [
            call for call in self.calls() if call["arguments"][:2] == ["release", "view"]
        ]
        self.assertEqual(len(views), 2, "the release must be re-read after creation")

    def test_notes_come_from_the_tagged_commit_not_the_checkout(self) -> None:
        self.write_changelog(
            [
                "## dev-v0.0.2",
                "",
                "- rewritten after the tag was created.",
            ]
        )
        self.commit("rewrite the changelog after tagging")
        self.scenario(
            **{
                "tag-read": [self.tag_reference(self.tagged_oid)],
                "compare": [{"stdout": "ahead"}],
                "release-view": [RELEASE_NOT_FOUND, self.release_payload()],
                "release-create": [{"stdout": ""}],
            }
        )
        self.receipt(self.run_release("dev-v0.0.2"))
        creates = [
            call for call in self.calls() if call["arguments"][:2] == ["release", "create"]
        ]
        self.assertEqual(creates[0]["notes"].strip(), self.expected_notes)
        self.assertNotIn("rewritten after the tag", creates[0]["notes"])

    def test_matching_existing_release_is_idempotent(self) -> None:
        self.scenario(
            **{
                "tag-read": [self.tag_reference(self.tagged_oid)],
                "compare": [{"stdout": "identical"}],
                "release-view": [self.release_payload()],
            }
        )
        receipt = self.receipt(self.run_release("dev-v0.0.2"))
        self.assertEqual(receipt["action"], "already-published")
        self.assertEqual(
            [
                call
                for call in self.calls()
                if call["arguments"][:2] == ["release", "create"]
            ],
            [],
        )

    def test_missing_confirmation_refuses_before_mutation(self) -> None:
        self.scenario(
            **{
                "tag-read": [self.tag_reference(self.tagged_oid)],
                "compare": [{"stdout": "ahead"}],
                "release-view": [RELEASE_NOT_FOUND],
            }
        )
        result = self.run_release("dev-v0.0.2", confirm=False)
        self.assert_refused(result, "requires explicit human authorization")
        self.assertEqual(
            [
                call
                for call in self.calls()
                if call["arguments"][:2] == ["release", "create"]
            ],
            [],
        )

    def assert_release_refusal(
        self, payload: dict[str, Any], fragment: str
    ) -> None:
        self.scenario(
            **{
                "tag-read": [self.tag_reference(self.tagged_oid)],
                "compare": [{"stdout": "ahead"}],
                "release-view": [payload],
            }
        )
        result = self.run_release("dev-v0.0.2")
        self.assert_refused(result, fragment)
        for call in self.calls():
            self.assertNotIn(
                call["arguments"][:2],
                (["release", "create"], ["release", "edit"], ["release", "delete"]),
            )

    def test_existing_draft_release_refuses_without_mutation(self) -> None:
        self.assert_release_refusal(self.release_payload(draft=True), "is a draft")

    def test_existing_prerelease_refuses_without_mutation(self) -> None:
        self.assert_release_refusal(
            self.release_payload(prerelease=True), "is a prerelease"
        )

    def test_existing_mismatched_name_refuses_without_mutation(self) -> None:
        self.assert_release_refusal(
            self.release_payload(name="dev 0.0.2"), "expected 'dev plugin v0.0.2'"
        )

    def test_existing_mismatched_tag_refuses_without_mutation(self) -> None:
        self.assert_release_refusal(
            self.release_payload(tag="dev-v0.0.1"), "points at tag 'dev-v0.0.1'"
        )

    def test_existing_empty_notes_refuse_without_mutation(self) -> None:
        self.assert_release_refusal(
            self.release_payload(body="   "), "has empty release notes"
        )

    def test_invalid_tag_syntax_refuses_before_any_github_call(self) -> None:
        for tag in ("v0.0.2", "dev-0.0.2", "dev-v0.0", "bogus-v0.0.2"):
            with self.subTest(tag=tag):
                self.scenario()
                result = self.run_release(tag)
                self.assert_refused(result, "must be exactly")
                self.assertEqual(self.gh_operations(), [])

    def test_missing_remote_tag_refuses(self) -> None:
        self.scenario(**{"tag-read": [NOT_FOUND]})
        result = self.run_release("dev-v0.0.2")
        self.assert_refused(result, "does not exist in")

    def test_commit_unreachable_from_main_refuses(self) -> None:
        for status in ("behind", "diverged"):
            with self.subTest(status=status):
                self.scenario(
                    **{
                        "tag-read": [self.tag_reference(self.tagged_oid)],
                        "compare": [{"stdout": status}],
                    }
                )
                result = self.run_release("dev-v0.0.2")
                self.assert_refused(result, "is not reachable from")

    def test_tagged_version_fields_must_equal_the_tag_version(self) -> None:
        self.scenario(
            **{
                "tag-read": [self.tag_reference(self.base_oid)],
                "compare": [{"stdout": "ahead"}],
            }
        )
        result = self.run_release("dev-v0.0.2")
        self.assert_refused(result, "expected all three to equal 0.0.2")

    def test_missing_changelog_heading_at_the_tagged_commit_refuses(self) -> None:
        self.write_changelog(["## dev-v0.0.1", "", "- first dev release."])
        self.versions["dev"] = "0.0.3"
        self.write_versions(self.versions)
        undocumented = self.commit("bump without a changelog entry")
        self.scenario(
            **{
                "tag-read": [self.tag_reference(undocumented)],
                "compare": [{"stdout": "ahead"}],
            }
        )
        result = self.run_release("dev-v0.0.3")
        self.assert_refused(result, "no exact release heading '## dev-v0.0.3'")


class ImmutabilitySourceTests(unittest.TestCase):
    """The helper must contain no path that removes or moves a published ref."""

    def test_no_destructive_tag_or_release_commands(self) -> None:
        source = RELEASE_CLI.read_text(encoding="utf-8")
        for forbidden in (
            '"--force"',
            '"--delete"',
            '"-d"',
            '"-f", "refs/tags',
            '"release", "edit"',
            '"release", "delete"',
            '"tag", "-d"',
            "--method\",\n            \"PATCH\"",
            "--method\",\n            \"DELETE\"",
        ):
            self.assertNotIn(forbidden, source, f"found destructive fragment {forbidden!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
