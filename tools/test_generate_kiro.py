#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Network-free regression tests for shared agent parsing and Kiro generation."""

from __future__ import annotations

import contextlib
import io
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import generate_codex_agents as codex
import generate_kiro as kiro
from agent_sources import Agent


class KiroGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.temp = Path(cls.temporary.name)
        cls.first = cls.temp / "first"
        cls.second = cls.temp / "second"
        cls.first.mkdir()
        cls.second.mkdir()
        cls.first_manifest = kiro.build_stage(cls.first)
        cls.second_manifest = kiro.build_stage(cls.second)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_codex_renderer_bytes_are_unchanged_by_shared_parser_extraction(self) -> None:
        agent = Agent(
            source=kiro.ROOT / "plugins/example/agents/sample.md",
            name="sample",
            description="Sample agent",
            instructions="Do the work.\n",
            model="inherit",
            color="cyan",
            tools=("Read",),
        )
        expected = (
            "# Generated from plugins/example/agents/sample.md; edit the source and regenerate.\n"
            'name = "sample"\n'
            'description = "Sample agent"\n'
            'developer_instructions = """\n'
            "Do the work.\n"
            '"""\n'
        ).encode()
        self.assertEqual(codex.render_agent(agent), expected)

    def test_two_fresh_builds_are_byte_identical(self) -> None:
        self.assertEqual(kiro.snapshot(self.first), kiro.snapshot(self.second))
        self.assertEqual(self.first_manifest, self.second_manifest)

    def test_all_sources_have_unique_safe_explicit_names(self) -> None:
        skill_paths = kiro.discover_skill_paths()
        agents = kiro.discover_agents()
        skill_map, agent_map = kiro.load_name_map(skill_paths, agents)
        self.assertEqual(len(skill_map), 20)
        self.assertEqual(len(agent_map), 3)
        self.assertEqual(skill_map["plugins/dev/skills/retro"], "dev-retro")
        self.assertEqual(skill_map["plugins/utils/skills/retro"], "utils-retro")
        self.assertEqual(skill_map["plugins/utils/skills/回顧"], "utils-retro-zh")
        names = [*skill_map.values(), *agent_map.values()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(kiro.KIRO_NAME_RE.fullmatch(name) for name in names))

    def test_generated_schema_and_dependency_closure(self) -> None:
        self.assertEqual(len(self.first_manifest["skills"]), 20)
        self.assertEqual(len(self.first_manifest["agents"]), 3)
        readme = (self.first / "README.md").read_text(encoding="utf-8")
        self.assertIn("single-root Kiro IDE workspaces only", readme)
        self.assertIn("does not install or modify", readme)
        self.assertIn("There is no Kiro marketplace manifest", readme)
        self.assertIn("denied operation", readme)
        self.assertIn('TARGET="$PWD/.kiro"', readme)
        self.assertIn("Repository-root bulk import", readme)
        self.assertIn('"$TARGET/skills/utils-retro-zh"', readme)
        self.assertIn('"$TARGET/agents/dev-verifier.md"', readme)
        self.assertIn("README.md", self.first_manifest["files"])
        setup = self.first / "skills/dev-setup"
        self.assertTrue((setup / "assets/claude-review.yml").is_file())
        self.assertTrue(
            (setup / "references/runtime_contracts/project-bootstrap.md").is_file()
        )
        self.assertTrue((setup / "scripts/resolve_project_rules.py").is_file())
        research = self.first / "skills/utils-research"
        self.assertFalse((research / "agents/openai.yaml").exists())
        security_scan = (self.first / "skills/utils-security-scan/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Only activate on explicit slash command invocation.", security_scan)
        self.assertNotIn("activate automatically", security_scan)
        agent_text = (self.first / "agents/dev-test-writer.md").read_text(encoding="utf-8")
        self.assertIn("runtime_contracts/project-bootstrap.md", agent_text)
        self.assertNotIn("references/runtime_contracts/project-bootstrap.md", agent_text)
        self.assertIn("supported single-root Kiro IDE workspace", agent_text)
        self.assertIn("explicit agent resources are unsupported", agent_text)
        self.assertNotIn("\nresources:", agent_text)
        setup_text = (setup / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "compatibility: Kiro IDE single-root workspace preview; CLI, multi-root, "
            "explicit resources, and dev:shadow unsupported",
            setup_text,
        )
        self.assertIn("supported only in a single-root Kiro IDE workspace", setup_text)
        self.assertIn("safe-stop probes, and bounded", setup_text)
        self.assertIn("`dev:auto`", setup_text)
        self.assertIn("Kiro CLI, multi-root", setup_text)
        self.assertIn("active-folder isolation, explicit agent resources", setup_text)
        for path in self.first.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json", ".py", ".yaml", ".yml"}:
                text = path.read_text(encoding="utf-8")
                for forbidden in kiro.FORBIDDEN_GENERATED_TEXT:
                    self.assertNotIn(forbidden, text, str(path))
        self.assertNotIn(
            "argument-hint:",
            (setup / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1],
        )

    def test_check_detects_missing_changed_and_unexpected_files(self) -> None:
        output = self.temp / "check-output"
        mutations = {
            "missing": lambda: (output / "manifest.json").unlink(),
            "changed": lambda: (output / "manifest.json").write_text("changed\n"),
            "unexpected": lambda: (output / "unexpected.txt").write_text("extra\n"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                if output.exists():
                    shutil.rmtree(output)
                shutil.copytree(self.first, output)
                mutate()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                    io.StringIO()
                ):
                    result = kiro.generate(check=True, output_root=output)
                self.assertEqual(result, 1)

    def test_agent_tool_mapping_deduplicates_and_rejects_unknown_tools(self) -> None:
        agent = Agent(
            source=kiro.ROOT / "plugins/example/agents/sample.md",
            name="sample",
            description="Sample",
            instructions="Work.\n",
            model="inherit",
            color="cyan",
            tools=("Read", "Grep", "Write", "Edit", "Bash"),
        )
        self.assertEqual(kiro.mapped_agent_tools(agent), ("read", "write", "shell"))
        unknown = Agent(
            source=agent.source,
            name=agent.name,
            description=agent.description,
            instructions=agent.instructions,
            model=agent.model,
            color=agent.color,
            tools=("Network",),
        )
        with self.assertRaisesRegex(kiro.KiroGenerationError, "unmapped agent tool"):
            kiro.mapped_agent_tools(unknown)

    def test_skill_parser_rejects_unknown_frontmatter(self) -> None:
        root = self.temp / "fixture"
        source = root / "plugins/demo/skills/example/SKILL.md"
        source.parent.mkdir(parents=True)
        source.write_text(
            "---\nname: example\ndescription: Example\nunknown: value\n---\nBody.\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            kiro.KiroGenerationError, "unsupported skill frontmatter field 'unknown'"
        ):
            kiro.parse_skill(source, "demo-example", root=root)

    def transform(self, text: str, *, source_name: str, emitted_name: str) -> str:
        return kiro.transform_markdown(
            text,
            plugin="dev",
            source_name=source_name,
            emitted_name=emitted_name,
            skill_map={},
            agent_map={},
        )

    def test_slash_rewrite_is_confined_to_invocation_positions(self) -> None:
        cases = (
            ("status", "dev-status", "per-task id/title/status.", "per-task id/title/status."),
            (
                "feedback",
                "dev-feedback",
                "e.g. `plugins/dev/skills/feedback/SKILL.md`",
                "e.g. `plugins/dev/skills/feedback/SKILL.md`",
            ),
            ("verify", "dev-verify", "Awaiting review/verify.", "Awaiting review/verify."),
            (
                "shadow",
                "dev-shadow",
                "see `references/runtime_contracts/shadow.md` first",
                "see `references/runtime_contracts/shadow.md` first",
            ),
            ("verify", "dev-verify", "run `/verify` now", "run `/dev-verify` now"),
            ("verify", "dev-verify", "run /verify now", "run /dev-verify now"),
            ("verify", "dev-verify", "(/verify)", "(/dev-verify)"),
            ("verify", "dev-verify", "/verify at the start", "/dev-verify at the start"),
            ("verify", "dev-verify", "line one\n/verify", "line one\n/dev-verify"),
        )
        for source_name, emitted_name, text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    self.transform(text, source_name=source_name, emitted_name=emitted_name),
                    expected,
                )

    def test_literal_contract_markers_survive_transformation(self) -> None:
        text = "## Work summary (dev:execute - <date>)\n## dev:review-pr - <task-id>\n"
        self.assertEqual(
            self.transform(text, source_name="execute", emitted_name="dev-execute"), text
        )

    def stage_skill(self, label: str, files: dict[str, str]) -> Path:
        stage = self.temp / label
        if stage.exists():
            shutil.rmtree(stage)
        for relative_path, content in files.items():
            path = stage / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return stage

    def test_dangling_bundled_reference_fails_closed(self) -> None:
        stage = self.stage_skill(
            "dangling",
            {
                "skills/demo-one/SKILL.md": (
                    "---\nname: demo-one\n---\nRead `references/runtime_contracts/present.md`\n"
                    "then `references/runtime_contracts/absent.md`.\n"
                ),
                "skills/demo-one/references/runtime_contracts/present.md": "here\n",
            },
        )
        with self.assertRaisesRegex(kiro.KiroGenerationError, "do not resolve") as caught:
            kiro.validate_bundled_references(stage, ["demo-one"])
        message = str(caught.exception)
        self.assertIn("demo-one -> references/runtime_contracts/absent.md", message)
        self.assertNotIn("present.md", message)

    def test_illustrative_paths_are_not_treated_as_citations(self) -> None:
        stage = self.stage_skill(
            "illustrative",
            {
                "skills/demo-two/SKILL.md": (
                    "---\nname: demo-two\n---\n"
                    "- Bare directory mentions: `references/`, `scripts/`, `assets/`\n"
                    "- Single-slash relative paths (`scripts/tool.py`, `config/settings.yml`,\n"
                    "  `src/module.mjs`)\n"
                    "- Run `scripts/present.py validate --file <path>` before handoff.\n"
                ),
                "skills/demo-two/scripts/present.py": "print()\n",
            },
        )
        kiro.validate_bundled_references(stage, ["demo-two"])

    def test_diverging_shared_copy_fails_closed(self) -> None:
        stage = self.stage_skill(
            "divergent",
            {
                "skills/demo-a/SKILL.md": "---\nname: demo-a\n---\nA\n",
                "skills/demo-b/SKILL.md": "---\nname: demo-b\n---\nB differs legitimately\n",
                "skills/demo-c/SKILL.md": "---\nname: demo-c\n---\nC\n",
                "skills/demo-a/scripts/helper.py": "print(1)\n",
                "skills/demo-b/scripts/helper.py": "print(1)\n",
                "skills/demo-c/scripts/helper.py": "print(2)\n",
                "skills/demo-a/references/runtime_contracts/tracker.md": "shared\n",
                "skills/demo-b/references/runtime_contracts/tracker.md": "shared\n",
            },
        )
        with self.assertRaisesRegex(
            kiro.KiroGenerationError, "not byte-identical"
        ) as caught:
            kiro.validate_shared_copies(stage, ["demo-a", "demo-b", "demo-c"])
        message = str(caught.exception)
        self.assertIn("scripts/helper.py", message)
        self.assertIn("[demo-a, demo-b]", message)
        self.assertIn("[demo-c]", message)
        self.assertNotIn("tracker.md", message)
        self.assertNotIn("SKILL.md", message)

    def test_generated_tree_has_no_slash_rewrite_corruption(self) -> None:
        status = (self.first / "skills/dev-status/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("id/title/status.", status)
        self.assertNotIn("id/title/dev-status.", status)
        feedback = (self.first / "skills/dev-feedback/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`plugins/dev/skills/feedback/SKILL.md`", feedback)
        self.assertNotIn("plugins/dev/skills/dev-feedback/SKILL.md", feedback)
        tracker = (
            self.first / "skills/dev-verify/references/runtime_contracts/tracker.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Awaiting review/verify.", tracker)
        self.assertNotIn("review/dev-verify", tracker)
        renderings = set()
        for path in (self.first / "skills").rglob("SKILL.md"):
            renderings.update(
                re.findall(
                    r"render the Kiro invocation as `(/[^`]+)`",
                    path.read_text(encoding="utf-8"),
                )
            )
        self.assertIn("/dev-execute", renderings)
        self.assertIn("/dev-verify", renderings)
        emitted = {f"/{record['name']}" for record in self.first_manifest["skills"]}
        self.assertTrue(renderings)
        self.assertEqual(renderings - emitted, set())

    def test_dev_preamble_states_the_invocation_mapping(self) -> None:
        for name in ("dev-feedback", "dev-merge-pr", "dev-release", "dev-execute"):
            text = (self.first / f"skills/{name}/SKILL.md").read_text(encoding="utf-8")
            self.assertIn(
                "Every bare `dev:<name>` reference below names a source skill whose Kiro",
                text,
                name,
            )
            self.assertIn("invocation is `/dev-<name>`", text, name)
        utils = (self.first / "skills/utils-research/SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("`dev:<name>` reference", utils)

    def test_copy_rejects_symlinked_resources(self) -> None:
        resource_root = self.temp / "symlinks"
        resource_root.mkdir()
        target = resource_root / "target.txt"
        target.write_text("content\n", encoding="utf-8")
        link = resource_root / "link.txt"
        link.symlink_to(target)
        skill = kiro.Skill(
            resource_root,
            "demo",
            "example",
            "demo-example",
            "Example",
            None,
            "Body.\n",
        )
        with self.assertRaisesRegex(kiro.KiroGenerationError, "symlinked source"):
            kiro.copy_file(
                link,
                resource_root / "copy.txt",
                transform=False,
                skill=skill,
                skill_map={},
                agent_map={},
            )


if __name__ == "__main__":
    unittest.main()
