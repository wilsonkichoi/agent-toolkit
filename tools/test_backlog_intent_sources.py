#!/usr/bin/env -S uv run
"""Network-free contract tests for the backlog intent-source resolution algorithm.

Validates that the skill's prose enforces:
- Default docs (PRD/SPEC) used when both present, no prompt needed.
- Stop before mutation when either default doc is absent without approval.
- Explicit alternate sources accepted (conversational or configured).
- Missing, escaping, and revision-mismatched alternates rejected.
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

    def test_missing_file_rejected(self) -> None:
        self._assert_contains("A missing file (does not exist at the bound revision)")

    def test_escaping_path_rejected(self) -> None:
        self._assert_contains(
            "A path that escapes the repository (`../`, absolute, symlink outside the tree)"
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
