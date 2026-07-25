# Changelog

Releases of the plugins in this repository. A release is a `<plugin>-vX.Y.Z` Git tag plus its
matching GitHub Release; the full procedure is in [docs/RELEASING.md](docs/RELEASING.md).

**Convention:** every future `dev` plugin release adds its entry to this file *before* its tag is
created. The entry lands in the same pull request as the three lockstep version-field changes, so
the tagged commit already contains its own changelog entry. A version that reaches `main` without
an entry here is not a release.

Entries are newest first. Each release entry is headed by its tag name and the commit the tag
points at.

## Unreleased

The `dev` plugin advanced to `0.0.67` and `0.0.68` on `main` before this release process existed.
Neither version carries a tag or GitHub Release, and both are listed here so the gap between the
manifest version and the newest tag is explicit rather than silent.

- `0.0.68` (`d8a1931`) - ship a CI-runnable rules-contract check,
  `resolve_project_rules.py --check`.
- `0.0.67` (`426c0e3`) - remove the legacy `.agent/dev.md` and `.claude/dev.md` configuration path
  fallbacks.

## dev-v0.0.66

Commit `4167ff1dff46cf105e8239849d662e8f02f50748` - the bootstrap release, tagged retroactively when
the release process was established. This entry documents a historical release that predates this
file.

- Resolved the contradictory spike contracts: a spike's durable decision artifacts (the ADR under
  `docs/adr/` and any directly required documentation or index update) are repository content and
  merge through the normal current-head review, CI, human-approval, and guarded-merge gate before
  the task reaches `Done`. Only experimental implementation stays throwaway and is excluded from the
  artifact-only pull request.
- `dev:verify` now fails closed on a spike branch that mixes experimental implementation into the
  artifact pull request, instead of merging the experiment or discarding the required artifact.
- Added a network-free regression guard for both forbidden states
  (`check_repo.py spike-artifact-lifecycle` plus `tools/test_spike_lifecycle.py`).
- Updated the spike contract across `plugins/dev/runtime_contracts/tracker.md`, `dev:plan`,
  `dev:execute`, `dev:verify`, both READMEs, and the `AGENTS.md` authoring conventions.

See [#33](https://github.com/wilsonkichoi/agent-toolkit/pull/33) and
[#30](https://github.com/wilsonkichoi/agent-toolkit/issues/30).
