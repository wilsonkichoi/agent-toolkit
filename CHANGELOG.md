# Changelog

Releases of the plugins in this repository. A release is a `<plugin>-vX.Y.Z` Git tag plus its
matching GitHub Release; the full procedure is in [docs/RELEASING.md](docs/RELEASING.md).

**Convention:** every plugin release adds its tag-named entry to this file *before* the tag is
created. The entry lands in the same pull request as that plugin's three lockstep version-field
changes, so the tagged commit already contains its own release notes. This is enforced, not
advisory: the push-to-`main` tagging workflow refuses to tag a version whose exact
`## <plugin>-vX.Y.Z` heading is missing at the merged commit, and `dev:release` reads its release
notes from that section at the tagged commit.

Entries are newest first. Each release entry is headed by its exact tag name.

## dev-v0.0.72

- Enforced the `dev-v*` and `utils-v*` release-tag namespaces with the active `Immutable plugin
  release tags` repository ruleset. Its `deletion`, `non_fast_forward`, and `update` rules block
  deletion and every tag update while preserving the `Release tags` workflow's ability to create a
  new version tag.
- Documented the ruleset, its exact ref patterns, and a GitHub API verification command in the
  release procedure and release-tag guidance.

## dev-v0.0.71

- `dev:backlog` now supports brownfield and partially adopted repositories that lack
  `docs/PRD.md` or `docs/SPEC.md`. Intent sources are resolved in priority order: both defaults
  present (no prompt), tracker-repository defaults in a split-repository layout (no prompt),
  configured `## Intent sources` in `.agent-toolkit/dev.md`, or explicit conversational approval.
  Absent defaults with no approval still hard-stop before mutation.
- Split-repository projects (execution repo differs from tracker repo) now read `docs/PRD.md`
  and `docs/SPEC.md` from the tracker repository as defaults when the execution repository has
  neither. Each source binds to its own repository's revision.
- Every triage diagnostic includes an `Intent sources:` entry naming the files and their source
  repository.
- Network-free contract tests (`tools/test_backlog_intent_sources.py`) validate the resolution
  algorithm, rejection of missing/escaping/unbound sources, and the split-repository layout.

## dev-v0.0.70

- Added the `.github/actions/check-rules` composite action: one version-pinned `uses:` step that
  enforces the rule-discovery contract on a GitHub-hosted adopter's repository. It installs its own
  SHA-pinned toolchain and runs the `resolve_project_rules.py --check` copy shipped in the action's
  own checkout, so nobody vendors a second checker.
- A repository with no canonical `.agent-toolkit/dev.md` exits 0 with one skip message, installs
  nothing, and has nothing written into its workspace. Any other repository gets the checker's exit
  status and diagnostics verbatim, also exposed as the `result`, `status`, and `report` outputs.
- The mandatory `repository-validation` check now runs the action against this repository and
  against three isolated fixtures - no config, compliant, and a deliberately unclassified rule -
  and fails if the invalid fixture is accepted. `tools/test_check_rules_action.py` enforces the
  same behavior locally.
- Documented the action in `plugins/dev/README.md` with an exact immutable release reference, and
  `dev:setup` now offers it to GitHub Actions projects while keeping the direct `--check` command
  for every other CI system.

## dev-v0.0.69

- Added `plugins/dev/scripts/plugin_release.py`, one dependency-free helper with a `tag` operation
  (compare each plugin's three synchronized version fields between a push event's before and head
  commits, then create one immutable lightweight tag per strictly increased plugin) and a `release`
  operation (create the GitHub Release for one existing tag).
- Added the `Release tags` workflow, which runs on every push to `main` with job-scoped
  `contents: write`, SHA-pinned third-party actions, and a merged-commit validation step, then
  invokes the helper's `tag` operation. Version bumps no longer depend on a maintainer remembering
  to tag.
- Added the `dev:release <tag>` skill: a thin orchestrator that resolves the canonical repository,
  shows the target tag and commit, requires explicit human authorization, and delegates every
  mutation to the helper.
- Tag and release publication is immutable and fail-closed. Desynchronized version fields, invalid
  semver, a version regression, a missing exact changelog heading, or an existing tag at another
  commit all refuse before any mutation. An existing correct tag or release is idempotent success;
  an existing draft, prerelease, mismatched, or empty-notes release fails without being edited or
  deleted.
- Added `tools/test_plugin_release.py` and wired it into `check_repo.py` as the `plugin-release`
  check, so the network-free success, no-op, idempotency, and refusal coverage is a non-optional
  gate.

## Untagged history

The `dev` plugin advanced to these versions on `main` before the release process existed. Neither
carries a tag or GitHub Release, and both are listed here so the gap between the manifest version
and the tag history is explicit rather than silent. Automatic tagging begins with `dev-v0.0.69`.

- `0.0.68` (`d8a1931`) - ship a CI-runnable rules-contract check,
  `resolve_project_rules.py --check`.
- `0.0.67` (`426c0e3`) - remove the legacy `.agent/dev.md` and `.claude/dev.md` configuration path
  fallbacks.

## dev-v0.0.66

The bootstrap release, tagged retroactively at commit
`4167ff1dff46cf105e8239849d662e8f02f50748` when the release process was established. This entry
documents a historical release that predates this file.

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
