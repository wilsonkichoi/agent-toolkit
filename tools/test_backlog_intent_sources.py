#!/usr/bin/env -S uv run
"""Network-free contract tests for the backlog intent-source resolution algorithm.

Validates that the skill's prose enforces:
- Default docs (PRD/SPEC) used when both present, no prompt needed.
- Stop before mutation when either default doc is absent without approval.
- Explicit alternate sources accepted (conversational or configured).
- Configured sources accepted from the dev.md frontmatter `intent_sources:` key.
- Frontmatter taking precedence over the `## Intent sources` body section.
- Missing, escaping, and revision-mismatched alternates rejected, in every configured form.
- Split-repository layout: tracker-repo PRD/SPEC used with no override prompt.
- Same-repository behavior unchanged when both defaults exist.
- Sufficiency check after loading alternates (triage gates still apply).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import check_repo  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BACKLOG_SKILL = ROOT / "plugins/dev/skills/backlog/SKILL.md"
SETUP_SKILL = ROOT / "plugins/dev/skills/setup/SKILL.md"
DEV_README = ROOT / "plugins/dev/README.md"


class IntentSourceContractTests(unittest.TestCase):
    """Verify the skill's prose carries the required contract language."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = BACKLOG_SKILL.read_text(encoding="utf-8")
        cls.normalized = " ".join(cls.content.split())

    def _assert_contains(self, fragment: str, msg: str | None = None) -> None:
        normalized_fragment = " ".join(fragment.split())
        self.assertIn(
            normalized_fragment,
            self.normalized,
            msg or f"Missing required contract language: {fragment!r}",
        )

    def test_default_path_same_repo_no_prompt(self) -> None:
        self._assert_contains("If both exist, read them. No prompt, no override")

    def test_default_path_split_repo_no_override(self) -> None:
        self._assert_contains(
            "tracker repository's `docs/PRD.md` and `docs/SPEC.md` are the default "
            "intent sources, not alternates"
        )
        self._assert_contains(
            "read them from the tracker repository at its `HEAD`. No prompt, no override"
        )

    def test_stop_before_mutation_when_absent(self) -> None:
        self._assert_contains("stop before any triage mutation")
        self._assert_contains(
            "Never silently treat the issue body, README, or agent judgment as product intent"
        )

    def test_split_repo_both_absent_still_stops(self) -> None:
        """The stop rule must be qualified to both repositories, not just one.

        Without the "in both repositories" qualifier, a split-repository project whose
        tracker repository also lacks PRD/SPEC would read the rule as already satisfied
        by the execution repository's absence alone and could proceed unguarded.
        """
        self._assert_contains(
            "If either default file is absent in both repositories (or the only "
            "resolved repository), stop before any triage mutation"
        )

    def test_explicit_override_accepted(self) -> None:
        self._assert_contains(
            "human may approve alternate intent sources in the current conversation"
        )
        self._assert_contains(
            "project configuration (`.agent-toolkit/dev.md` body) may name approved sources"
        )

    def test_configured_sources_section(self) -> None:
        self._assert_contains("## Intent sources")

    def test_frontmatter_intent_sources_accepted(self) -> None:
        """The frontmatter key is a first-class configured form, not an alias."""
        self._assert_contains(
            "`.agent-toolkit/dev.md` YAML frontmatter may carry an `intent_sources:` key "
            "whose value is a YAML list of repository-relative paths"
        )
        self._assert_contains("intent_sources: - AGENTS.md")
        self._assert_contains(
            "Accept the inline form (`intent_sources: "
            "[AGENTS.md, docs/adr/001-architecture.md]`) equivalently"
        )

    def test_resolution_order_documented(self) -> None:
        self._assert_contains(
            "use the first that supplies sources: configured frontmatter, then the "
            "configured body section, then conversational approval"
        )

    def test_frontmatter_wins_over_body_section(self) -> None:
        """Precedence must be stated, and the run must report which form it used."""
        self._assert_contains("Frontmatter wins over the body section.")
        self._assert_contains(
            "read the frontmatter list and ignore the body section; never merge the two lists"
        )
        self._assert_contains(
            "Report which form supplied the sources instead of silently preferring one, "
            "and name the ignored body section in that report"
        )

    def test_body_section_remains_supported_without_deprecation(self) -> None:
        self._assert_contains("This form is a supported fallback, not a deprecated one")
        self._assert_contains(
            "resolves exactly as it did before the frontmatter key existed, with no "
            "migration and no deprecation warning"
        )

    def test_empty_frontmatter_key_falls_through(self) -> None:
        self._assert_contains(
            "A key that is absent, empty, or an empty list supplies no sources: fall "
            "through to the next form"
        )

    def test_missing_file_rejected(self) -> None:
        self._assert_contains("A missing file (does not exist at the bound revision)")

    def test_frontmatter_missing_file_rejected(self) -> None:
        """A frontmatter path that does not exist is rejected like any other source."""
        self._assert_contains(
            "Every check below applies unchanged to frontmatter entries; supplying a "
            "path as configuration exempts it from nothing"
        )
        self._assert_contains("A missing file (does not exist at the bound revision)")
        self._assert_contains(
            "A rejected source stops the run before any triage mutation, in every form"
        )

    def test_escaping_path_rejected(self) -> None:
        self._assert_contains(
            "A path that escapes the repository (`../`, absolute, symlink outside the tree)"
        )

    def test_frontmatter_escaping_path_rejected(self) -> None:
        """A frontmatter path escaping the tree is rejected, not silently dropped."""
        self._assert_contains(
            "Every check below applies unchanged to frontmatter entries; supplying a "
            "path as configuration exempts it from nothing"
        )
        self._assert_contains(
            "A path that escapes the repository (`../`, absolute, symlink outside the tree)"
        )
        self._assert_contains(
            "Do not drop the offending entry and proceed on the survivors"
        )

    def test_source_in_neither_repo_rejected(self) -> None:
        self._assert_contains(
            "A source in neither the execution repository nor the tracker repository"
        )

    def test_sufficiency_check(self) -> None:
        self._assert_contains(
            "all existing triage gates still apply"
        )
        self._assert_contains(
            "stop and name the unresolved decision"
        )

    def test_durable_diagnostic_intent_sources_entry(self) -> None:
        self._assert_contains("Intent sources:")
        self._assert_contains(
            "naming the repository each came from"
        )

    def test_override_diagnostic_states_defaults_were_absent(self) -> None:
        """An override entry must record that the default docs were absent.

        Listing the approved sources alone does not say why the override was
        permitted, so a later reader cannot distinguish an approved override from
        a normal default read.
        """
        self._assert_contains(
            "it also states that the default `docs/PRD.md` and `docs/SPEC.md` "
            "files were absent, naming which of the two was missing and from "
            "which repository"
        )

    def test_diagnostic_names_frontmatter_as_origin(self) -> None:
        """The durable entry must say which form supplied the sources."""
        self._assert_contains(
            "approved conversationally, through the frontmatter `intent_sources:` key, "
            "or through the configured `## Intent sources` section - it also states that "
            "the default `docs/PRD.md` and `docs/SPEC.md` files were absent"
        )
        self._assert_contains(
            "The entry also names the origin form that supplied the sources: the "
            "frontmatter `intent_sources:` key, the `## Intent sources` body section, "
            "or conversational approval"
        )
        self._assert_contains(
            "When frontmatter took precedence over a present body section, the entry says so"
        )

    def test_split_repo_diagnostic_reports_source_repository(self) -> None:
        self._assert_contains(
            "tracker repository supplied them, the entry states that instead, rather "
            "than reporting an override that did not occur"
        )
        self._assert_contains("that path is a default read, not an override")

    def test_execution_revision_entries_remain_mandatory(self) -> None:
        self._assert_contains(
            "existing `Execution repository:`, `Execution revision:`, and "
            "`Rules loaded:` entries remain mandatory"
        )

    def test_coverage_applies_to_all_operations(self) -> None:
        self._assert_contains(
            "new ticketless intake, existing-task triage, packet repair, promotion, "
            "split, and triage sweeps"
        )

    def test_external_contribution_retains_restrictions(self) -> None:
        self._assert_contains(
            "Read-only external-contribution routing retains its existing mutation "
            "restrictions"
        )

    def test_revision_binding_per_source_repository(self) -> None:
        self._assert_contains(
            "execution-repository sources bind to the execution revision, "
            "tracker-repository sources to the tracker repository's `HEAD`"
        )


class IntentSourceConfigurationSurfaceTests(unittest.TestCase):
    """The producing and documenting surfaces must agree with the skill contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.setup = " ".join(SETUP_SKILL.read_text(encoding="utf-8").split())
        cls.readme = " ".join(DEV_README.read_text(encoding="utf-8").split())

    def _assert_in(self, haystack: str, fragment: str, label: str) -> None:
        self.assertIn(
            " ".join(fragment.split()),
            haystack,
            f"{label} is missing required language: {fragment!r}",
        )

    def test_setup_writes_frontmatter_key_for_non_default_paths(self) -> None:
        self._assert_in(
            self.setup,
            "product-intent documents are not at the default `docs/PRD.md` and "
            "`docs/SPEC.md` paths",
            "setup skill",
        )
        self._assert_in(
            self.setup,
            "add the files `dev:backlog` should read as `intent_sources:` in the same "
            "frontmatter",
            "setup skill",
        )

    def test_setup_omits_key_when_defaults_apply(self) -> None:
        self._assert_in(
            self.setup,
            "Omit the key entirely when the defaults apply; an empty list is not a way "
            'to say "use the defaults"',
            "setup skill",
        )

    def test_setup_does_not_rewrite_an_existing_body_section(self) -> None:
        self._assert_in(
            self.setup,
            "do not rewrite an existing body section into frontmatter on a re-run",
            "setup skill",
        )

    def test_readme_documents_frontmatter_as_recommended(self) -> None:
        self._assert_in(
            self.readme,
            "*Configured sources (recommended):* add an `intent_sources:` key to the "
            "`.agent-toolkit/dev.md` YAML frontmatter",
            "plugin README",
        )
        self._assert_in(
            self.readme,
            "*Configured sources (body-section fallback):*",
            "plugin README",
        )
        self._assert_in(
            self.readme,
            "It is supported, not deprecated; projects that already declare one need no "
            "migration",
            "plugin README",
        )

    def test_readme_documents_precedence(self) -> None:
        self._assert_in(
            self.readme,
            "When both forms are present the frontmatter wins, the body section is "
            "ignored rather than merged, and the run's `Intent sources:` diagnostic "
            "names which form it used",
            "plugin README",
        )

    def test_readme_config_table_lists_the_field(self) -> None:
        self._assert_in(self.readme, "| `intent_sources` |", "plugin README")


class IntentSourceViolationTests(unittest.TestCase):
    """Fixture tests for the regression guard detecting forbidden states."""

    def test_clean_surface_has_no_violations(self) -> None:
        clean = (
            "Triage requires product intent documents. When the resolved execution "
            "repository and the tracker repository are the same, check for docs/PRD.md "
            "and docs/SPEC.md. If both exist, read them. No prompt, no override. "
            "If either default file is absent, stop before any triage mutation. "
            "Never silently treat the issue body as product intent."
        )
        self.assertEqual(
            check_repo.backlog_intent_source_violations({"clean": clean}), []
        )

    def test_forbidden_silent_fallback_to_issue_body(self) -> None:
        text = (
            "If docs/PRD.md is missing, use the issue body as the product intent "
            "source and proceed with triage."
        )
        violations = check_repo.backlog_intent_source_violations(
            {"bad-fallback": text}
        )
        self.assertTrue(
            any("silent fallback" in v for v in violations), violations
        )

    def test_forbidden_readme_as_intent(self) -> None:
        text = (
            "When PRD is absent, use the README as product intent "
            "and proceed with triage decisions."
        )
        violations = check_repo.backlog_intent_source_violations(
            {"bad-readme": text}
        )
        self.assertTrue(
            any("silent fallback" in v for v in violations), violations
        )

    def test_forbidden_agent_judgment_as_intent(self) -> None:
        text = (
            "If no intent documents exist, treat the codebase as product intent "
            "and proceed with the triage."
        )
        violations = check_repo.backlog_intent_source_violations(
            {"bad-infer": text}
        )
        self.assertTrue(
            any("silent fallback" in v for v in violations), violations
        )

    def test_forbidden_skip_stop_when_absent(self) -> None:
        text = (
            "If either docs/PRD.md or docs/SPEC.md is absent, proceed with whatever "
            "context is available and create the task anyway."
        )
        violations = check_repo.backlog_intent_source_violations(
            {"bad-proceed": text}
        )
        self.assertTrue(
            any("proceeds without stopping" in v for v in violations), violations
        )

    def test_real_skill_passes(self) -> None:
        check_repo.check_backlog_intent_sources()


if __name__ == "__main__":
    unittest.main()
