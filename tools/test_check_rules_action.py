#!/usr/bin/env -S uv run
"""Network-free tests for the check-rules composite action.

The action's shell entrypoint is driven directly against the same three fixtures the
`repository-validation` workflow uses, so its skip, pass, and fail behavior is enforced
locally by `uv run tools/check_repo.py` and not only by a GitHub runner.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import check_repo  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ACTION_DIR = REPOSITORY_ROOT / ".github/actions/check-rules"
ENTRYPOINT = ACTION_DIR / "run-check.sh"
ACTION_MANIFEST = ACTION_DIR / "action.yml"
FIXTURES = REPOSITORY_ROOT / ".github/fixtures/check-rules"
CHECKER_RELATIVE_PATH = "plugins/dev/scripts/resolve_project_rules.py"


def parse_outputs(text: str) -> dict[str, str]:
    """Parse a `$GITHUB_OUTPUT` file, including heredoc-delimited multiline values."""
    outputs: dict[str, str] = {}
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line:
            continue
        heredoc = re.fullmatch(r"(?P<name>[^=<]+)<<(?P<delimiter>.+)", line)
        if heredoc:
            body: list[str] = []
            while index < len(lines) and lines[index] != heredoc.group("delimiter"):
                body.append(lines[index])
                index += 1
            index += 1
            outputs[heredoc.group("name")] = "\n".join(body)
            continue
        name, _, value = line.partition("=")
        outputs[name] = value
    return outputs


def composite_steps() -> list[str]:
    """Split the manifest's composite steps into blocks, with no YAML dependency."""
    lines = ACTION_MANIFEST.read_text(encoding="utf-8").split("\n")
    blocks: list[list[str]] = []
    for line in lines[lines.index("  steps:") + 1 :]:
        if re.match(r"^ {4}- ", line):
            blocks.append([])
        if blocks:
            blocks[-1].append(line)
    return ["\n".join(block) for block in blocks]


class ActionResult:
    def __init__(self, process: subprocess.CompletedProcess[str], outputs: dict[str, str]):
        self.returncode = process.returncode
        self.stdout = process.stdout
        self.stderr = process.stderr
        self.outputs = outputs


def run_entrypoint(
    operation: str,
    *,
    entrypoint: Path = ENTRYPOINT,
    env: dict[str, str] | None = None,
    cwd: Path = REPOSITORY_ROOT,
) -> ActionResult:
    with tempfile.TemporaryDirectory() as scratch:
        output_file = Path(scratch) / "github-output"
        output_file.touch()
        process = subprocess.run(
            ["bash", str(entrypoint), operation],
            cwd=cwd,
            env={**os.environ, **(env or {}), "GITHUB_OUTPUT": str(output_file)},
            text=True,
            capture_output=True,
            check=False,
        )
        return ActionResult(
            process, parse_outputs(output_file.read_text(encoding="utf-8"))
        )


def run_action(fixture: str, **kwargs: object) -> tuple[ActionResult, ActionResult, int]:
    """Replay the action's step sequence: detect, check, then the verdict step's condition."""
    target = str(FIXTURES / fixture)
    detect = run_entrypoint("detect", env={"CHECK_RULES_TARGET": target}, **kwargs)  # type: ignore[arg-type]
    check = run_entrypoint(
        "check",
        env={
            "CHECK_RULES_TARGET": target,
            "CHECK_RULES_CONFIG": detect.outputs.get("config", ""),
        },
        **kwargs,  # type: ignore[arg-type]
    )
    verdict = run_entrypoint(
        "verdict",
        env={"CHECK_RULES_STATUS": check.outputs.get("status", "")},
        **kwargs,  # type: ignore[arg-type]
    )
    return detect, check, verdict.returncode


class FixtureBehaviorTests(unittest.TestCase):
    def test_missing_dev_config_skips_without_failing(self) -> None:
        detect, check, verdict_code = run_action("no-config")
        self.assertEqual(detect.outputs["config"], "absent")
        self.assertEqual(check.returncode, 0)
        self.assertEqual(check.outputs["result"], "skipped")
        self.assertEqual(check.outputs["status"], "0")
        self.assertIn("no .agent-toolkit/dev.md", check.outputs["report"])
        self.assertEqual(verdict_code, 0)

    def test_skip_message_is_emitted_exactly_once(self) -> None:
        _, check, _ = run_action("no-config")
        combined = check.stdout + check.stderr
        self.assertEqual(combined.count("check-rules: skipped"), 1, combined)

    def test_skip_creates_nothing_in_the_target(self) -> None:
        target = FIXTURES / "no-config"
        before = sorted(path.name for path in target.rglob("*"))
        run_action("no-config")
        self.assertEqual(sorted(path.name for path in target.rglob("*")), before)

    def test_skip_needs_no_toolchain(self) -> None:
        """The skip path must not depend on uv, which the action installs conditionally."""
        result = run_entrypoint(
            "check",
            env={
                "CHECK_RULES_TARGET": str(FIXTURES / "no-config"),
                "CHECK_RULES_CONFIG": "absent",
                "PATH": "/usr/bin:/bin",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.outputs["result"], "skipped")

    def test_compliant_fixture_passes(self) -> None:
        detect, check, verdict_code = run_action("compliant")
        self.assertEqual(detect.outputs["config"], "present")
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(check.outputs["result"], "checked")
        self.assertEqual(check.outputs["status"], "0")
        self.assertIn("rules contract ok", check.outputs["report"])
        self.assertIn("doctrine 1, gotcha 1, excluded 1", check.outputs["report"])
        self.assertEqual(verdict_code, 0)

    def test_invalid_rule_fixture_fails_with_the_resolver_diagnostic(self) -> None:
        detect, check, verdict_code = run_action("invalid-rule")
        self.assertEqual(detect.outputs["config"], "present")
        self.assertEqual(check.outputs["result"], "checked")
        self.assertEqual(check.outputs["status"], "1")
        self.assertEqual(verdict_code, 1)
        for expected in (
            "rules_dir contains unclassified Markdown",
            ".agent-toolkit/rules/unclassified.md",
            "Remedy per file",
        ):
            self.assertIn(expected, check.outputs["report"])

    def test_diagnostics_are_not_rewritten(self) -> None:
        """The reported failure must be byte-identical to the checker's own output."""
        _, check, _ = run_action("invalid-rule")
        direct = subprocess.run(
            [
                "uv",
                "run",
                "--no-project",
                "--script",
                str(REPOSITORY_ROOT / CHECKER_RELATIVE_PATH),
                "--check",
                str(FIXTURES / "invalid-rule"),
            ],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(direct.returncode, 1)
        self.assertEqual(check.outputs["report"], direct.stderr.rstrip("\n"))
        self.assertIn(direct.stderr.rstrip("\n"), check.stderr)


class InstalledCopyTests(unittest.TestCase):
    """The action runs its own checker, never one supplied by the repository it checks."""

    def test_checker_is_resolved_relative_to_the_action(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            action_root = Path(scratch) / "installed"
            installed_action = action_root / ".github/actions/check-rules"
            installed_action.mkdir(parents=True)
            shutil.copy2(ENTRYPOINT, installed_action / ENTRYPOINT.name)
            installed_checker = action_root / CHECKER_RELATIVE_PATH
            installed_checker.parent.mkdir(parents=True)
            shutil.copy2(REPOSITORY_ROOT / CHECKER_RELATIVE_PATH, installed_checker)

            # A caller shipping its own checker at the same path must be ignored.
            target = Path(scratch) / "caller"
            shutil.copytree(FIXTURES / "compliant", target)
            sabotaged = target / CHECKER_RELATIVE_PATH
            sabotaged.parent.mkdir(parents=True)
            sabotaged.write_text(
                "#!/usr/bin/env -S uv run --script\n"
                "# /// script\n"
                '# requires-python = ">=3.11"\n'
                "# dependencies = []\n"
                "# ///\n"
                "raise SystemExit(42)\n",
                encoding="utf-8",
            )

            result = run_entrypoint(
                "check",
                entrypoint=installed_action / ENTRYPOINT.name,
                env={"CHECK_RULES_TARGET": str(target), "CHECK_RULES_CONFIG": "present"},
                cwd=target,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.outputs["status"], "0")
            self.assertIn("rules contract ok", result.outputs["report"])

    def test_missing_installed_checker_is_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            installed_action = Path(scratch) / "installed/.github/actions/check-rules"
            installed_action.mkdir(parents=True)
            shutil.copy2(ENTRYPOINT, installed_action / ENTRYPOINT.name)
            result = run_entrypoint(
                "check",
                entrypoint=installed_action / ENTRYPOINT.name,
                env={
                    "CHECK_RULES_TARGET": str(FIXTURES / "compliant"),
                    "CHECK_RULES_CONFIG": "present",
                },
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("installed action copy", result.stderr)


class EntrypointContractTests(unittest.TestCase):
    def test_unknown_operation_is_rejected(self) -> None:
        result = run_entrypoint("bootstrap")
        self.assertEqual(result.returncode, 1)
        self.assertIn("usage: run-check.sh", result.stderr)

    def test_missing_target_is_rejected(self) -> None:
        result = run_entrypoint("detect", env={"CHECK_RULES_TARGET": ""})
        self.assertEqual(result.returncode, 1)
        self.assertIn("CHECK_RULES_TARGET is required", result.stderr)

    def test_non_directory_target_is_rejected(self) -> None:
        result = run_entrypoint(
            "detect", env={"CHECK_RULES_TARGET": str(FIXTURES / "no-such-fixture")}
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not name a directory", result.stderr)

    def test_non_numeric_status_is_rejected(self) -> None:
        result = run_entrypoint("verdict", env={"CHECK_RULES_STATUS": "ok"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be a non-negative integer", result.stderr)

    def test_inherited_cdpath_does_not_corrupt_path_resolution(self) -> None:
        result = run_entrypoint(
            "detect",
            env={
                "CHECK_RULES_TARGET": str(FIXTURES / "compliant"),
                "CDPATH": str(REPOSITORY_ROOT),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.outputs["config"], "present")


class ManifestTests(unittest.TestCase):
    def test_real_manifest_passes_the_repository_guard(self) -> None:
        # Only the static half: check_rules_composite_action() runs this file.
        check_repo.check_rules_composite_action_surfaces()

    def test_toolchain_install_is_conditional_on_the_detected_config(self) -> None:
        """The skip path is install-free only because this step carries its guard.

        Nothing else catches its removal: the entrypoint tests never read the manifest, and
        every no-config workflow assertion holds whether or not the install ran.
        """
        steps = composite_steps()
        self.assertEqual(len(steps), 4, "expected detect, install, check, and verdict")
        install = [index for index, step in enumerate(steps) if "uses: astral-sh/setup-uv@" in step]
        self.assertEqual(len(install), 1, "expected exactly one toolchain install step")
        detect = [
            index
            for index, step in enumerate(steps)
            if re.search(r"run-check\.sh\S* detect\b", step)
        ]
        self.assertEqual(len(detect), 1)
        self.assertLess(detect[0], install[0], "the install must follow detection")
        self.assertIn(
            "if: steps.detect.outputs.config == 'present'", steps[install[0]]
        )

    def test_manifest_pins_third_party_actions_to_a_full_sha(self) -> None:
        manifest = ACTION_MANIFEST.read_text(encoding="utf-8")
        references = re.findall(r"uses: (\S+)@(\S+)", manifest)
        self.assertTrue(references)
        for action, reference in references:
            self.assertRegex(reference, r"^[0-9a-f]{40}$", f"{action} is not SHA-pinned")

    def test_run_bodies_contain_no_expression_interpolation(self) -> None:
        """Inputs reach the shell through `env:`, never through `${{ }}` in a `run:` body."""
        manifest = ACTION_MANIFEST.read_text(encoding="utf-8").split("\n")
        blocks = 0
        for index, line in enumerate(manifest):
            block = re.fullmatch(r"(?P<indent>\s*)run: \|(?P<inline>.*)", line)
            if not block:
                continue
            blocks += 1
            self.assertEqual(block.group("inline"), "")
            indent = len(block.group("indent"))
            for body_line in manifest[index + 1 :]:
                if body_line.strip() and len(body_line) - len(body_line.lstrip()) <= indent:
                    break
                self.assertNotIn("${{", body_line)
        self.assertEqual(blocks, 3, "expected one run body per shell step")


if __name__ == "__main__":
    unittest.main(verbosity=2)
