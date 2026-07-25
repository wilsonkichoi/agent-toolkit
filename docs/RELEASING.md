# Releasing the `dev` plugin

Maintainer procedure for cutting a `dev` plugin release. A release is a Git tag plus a matching
GitHub Release, both created from a commit that already merged through the protected `main` pull
request gate.

Consumers pin a release instead of `main` or a bare commit SHA, so a published tag is a permanent
public reference.

## Tag scheme

The tag for a `dev` plugin release is exactly:

```text
dev-vX.Y.Z
```

`X.Y.Z` is the synchronized `dev` plugin manifest version at the tagged commit, with no `v`-only
form and no other prefix. `dev-v0.0.66` is the bootstrap release and the first tag in this scheme.

Other plugins follow the same shape with their own name, for example `utils-vX.Y.Z`. The plugin
name in the tag is what keeps two independently versioned plugins from colliding in one tag
namespace.

## Version fields

`AGENTS.md` defines three authoritative version fields that must be equal for a release. All three
are what `X.Y.Z` refers to:

| Field | Path |
|---|---|
| Claude marketplace catalog entry for `dev` | `.claude-plugin/marketplace.json`, the `dev` entry's `version` |
| Claude plugin manifest | `plugins/dev/.claude-plugin/plugin.json`, `version` |
| Codex plugin manifest | `plugins/dev/.codex-plugin/plugin.json`, `version` |

The marketplace-level `.claude-plugin/marketplace.json` `metadata.version` is an **independent**
catalog version. It tracks changes to the catalog itself, is not required to match any plugin
release version, and is never used in a `dev-vX.Y.Z` tag. `.agents/plugins/marketplace.json`
intentionally carries no version field.

`uv run tools/check_repo.py` validates that the three release fields agree and are valid semver.

## Immutability

A pushed release tag is immutable. Never move, replace, or delete a published tag to reuse its
name. A consumer that pinned `dev-v0.0.66` must resolve the same commit forever; retargeting a tag
silently changes code under every pin, and caches and forks can keep serving the old object, so the
tag stops identifying anything at all.

This applies to the GitHub Release attached to a tag as well: correct a release by publishing a new
one, not by repointing an existing tag.

## Release procedure

Perform these steps in order. Do not create the tag before the version change has merged.

1. **Change and validate the three lockstep version fields.** Apply the minimum semver increment
   per `AGENTS.md` (patch while the plugin is `0.0.x`) to all three fields on a feature branch, then
   run both repository checks:

```bash
uv run tools/generate_codex_agents.py --check
uv run tools/check_repo.py
```

2. **Add the changelog entry in the same pull request** as the version change. `CHANGELOG.md`
   records every `dev` plugin release, and its entry lands before the tag exists.

3. **Merge through the protected `main` pull request gate.** Direct pushes to `main` are rejected by
   the `main pull request gate` ruleset; the change merges as a pull request like any other.

4. **Confirm `repository-validation` is green on the merged commit**, not only on the pre-merge
   branch head:

```bash
git fetch origin
MERGE_SHA=$(git rev-parse origin/main)
gh api "repos/wilsonkichoi/agent-toolkit/commits/${MERGE_SHA}/check-runs" \
  --jq '.check_runs[] | {name, conclusion}'
```

5. **Create and push the immutable tag at that merged commit.** Tag the exact SHA, never a local
   branch tip that may differ:

```bash
VERSION=0.0.66
MERGE_SHA=<verified merged commit sha>
git tag "dev-v${VERSION}" "$MERGE_SHA"
git push origin "dev-v${VERSION}"
```

6. **Create the GitHub Release from that exact tag.** It is non-draft and non-prerelease, names the
   plugin and version, and links or summarizes what changed:

```bash
gh release create "dev-v${VERSION}" \
  --repo wilsonkichoi/agent-toolkit \
  --title "dev plugin v${VERSION}" \
  --notes-file <notes-file>
```

7. **Verify both the remote tag and the release** resolve as expected:

```bash
git ls-remote --tags origin "refs/tags/dev-v${VERSION}"
gh release view "dev-v${VERSION}" --repo wilsonkichoi/agent-toolkit
```

The remote tag must resolve to the merged commit from step 4, and the release must be non-draft and
non-prerelease.

## Rollback

There is no rollback that edits a published release in place. To correct a shipped release:

1. Fix the problem on a branch and merge it through the normal `main` pull request gate.
2. Bump the three version fields by a patch increment and add a `CHANGELOG.md` entry describing the
   correction.
3. Run the release procedure again for the new patch version.

Never retarget, delete, or recreate an existing tag to ship a correction. If a release must be
discouraged from use, note the superseding version in its GitHub Release description and in the
changelog entry; the tag itself stays where it is.
