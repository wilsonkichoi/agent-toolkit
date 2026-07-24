#!/usr/bin/env -S uv run
"""Fixture tests for the spike artifact lifecycle regression guard.

Exercises both forbidden states the guard must fail on:
  (a) a required repository artifact reaching Done without a merge;
  (b) experimental implementation described as mergeable spike output.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import check_repo  # noqa: E402


CLEAN_SURFACE = """
A spike produces knowledge, not product implementation, but its durable decision artifacts -
the ADR and any directly required documentation or index update - must merge through the
normal review, CI, human-approval, and guarded-merge gate before the task reaches Done. Only
experimental implementation is throwaway: prototype code, fixtures, generated experiments, and
exploratory changes are excluded from the artifact-only PR.
"""

# Forbidden state (a): the required ADR-carrying branch is discarded without merging.
REGRESSION_STATE_A = """
A spike verifies differently: evidence is the ADR in docs/adr/ plus the recommendation comment
on the task. No merge - the spike branch is throwaway. Confirm both artifacts exist, transition
to Done, then remove its worktree and local branch.
"""

# Forbidden state (b): experimental implementation described as mergeable spike output.
REGRESSION_STATE_B = """
The spike branch carries the prototype and the ADR together. Prototype implementation is
mergeable spike output, so verification merges the branch as-is.
"""


class SpikeLifecycleGuardTests(unittest.TestCase):
    def test_clean_surface_has_no_violations(self) -> None:
        self.assertEqual(
            check_repo.spike_lifecycle_violations({"clean": CLEAN_SURFACE}), []
        )

    def test_state_a_artifact_reaches_done_without_merge(self) -> None:
        violations = check_repo.spike_lifecycle_violations(
            {"verify": REGRESSION_STATE_A}
        )
        self.assertTrue(
            any("state (a)" in violation for violation in violations), violations
        )

    def test_state_b_experiment_described_as_mergeable(self) -> None:
        violations = check_repo.spike_lifecycle_violations(
            {"verify": REGRESSION_STATE_B}
        )
        self.assertTrue(
            any("state (b)" in violation for violation in violations), violations
        )

    def test_real_contracts_and_docs_pass(self) -> None:
        check_repo.check_spike_artifact_lifecycle()


if __name__ == "__main__":
    unittest.main()
