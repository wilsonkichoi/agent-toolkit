# Releasing a plugin

Maintainer procedure for shipping a plugin release. A release is a Git tag plus a matching GitHub
Release, both bound to a commit that already merged through the protected `main` pull request gate.

Consumers pin a release instead of `main` or a bare commit SHA, so a published tag is a permanent
public reference.

The work is split in two:

| Step | Who performs it | Trigger |
|---|---|---|
| Create the `<plugin>-vX.Y.Z` tag | The `Release tags` workflow, automatically | A push to `main` that strictly increases that plugin's synchronized version |
| Create the GitHub Release | A maintainer, explicitly | `dev:release <tag>` after the tag exists |

Tagging is automatic because a version bump that merges without its tag is easy to forget and hard
to notice. Release publication stays explicit because it is the outward-facing, permanent artifact.

## Tag scheme

A plugin release tag is exactly:

```text
<plugin>-vX.Y.Z
```

`<plugin>` is the plugin's directory name under `plugins/`, and `X.Y.Z` is that plugin's
synchronized manifest version at the tagged commit. There is no `v`-only form and no other prefix.
`dev` and `utils` are versioned independently and occupy the namespace independently: `dev-v0.0.69`
and `utils-v0.0.4` are unrelated releases. The plugin name in the tag is what keeps two
independently versioned plugins from colliding in one tag namespace.

`dev-v0.0.66` is the bootstrap release and the first tag in this scheme.

## Version fields

`AGENTS.md` defines three authoritative version fields per plugin that must be equal for a release.
All three are what `X.Y.Z` refers to:

| Field | Path |
|---|---|
| Claude marketplace catalog entry | `.claude-plugin/marketplace.json`, that plugin's entry `version` |
| Claude plugin manifest | `plugins/<plugin>/.claude-plugin/plugin.json`, `version` |
| Codex plugin manifest | `plugins/<plugin>/.codex-plugin/plugin.json`, `version` |

The marketplace-level `.claude-plugin/marketplace.json` `metadata.version` is an **independent**
catalog version. It tracks changes to the catalog itself, is not required to match any plugin
release version, and is never used in a `<plugin>-vX.Y.Z` tag. `.agents/plugins/marketplace.json`
intentionally carries no version field.

`uv run tools/check_repo.py` validates that the three release fields agree and are valid semver.

## Immutability

A pushed release tag is immutable. Never move, replace, or delete a published tag to reuse its name.
A consumer that pinned `dev-v0.0.66` must resolve the same commit forever; retargeting a tag
silently changes code under every pin, and caches and forks can keep serving the old object, so the
tag stops identifying anything at all.

This applies to the GitHub Release attached to a tag as well: correct a release by publishing a new
one, not by repointing an existing tag.

Immutability is enforced, not just documented. The active `Immutable plugin release tags` repository
ruleset targets `refs/tags/dev-v*` and `refs/tags/utils-v*` and applies the `deletion` and
`non_fast_forward` rules. It has no bypass actors. The ruleset intentionally does not apply the
`creation` rule, so the `Release tags` workflow can create a new release tag with its
`GITHUB_TOKEN`, while no actor can delete or retarget an existing matching tag.

Confirm the active protection from any checkout with GitHub read access:

```bash
gh api repos/wilsonkichoi/agent-toolkit/rulesets --jq '.[] | select(.name == "Immutable plugin release tags") | {id, target, enforcement}'
```

`plugins/dev/scripts/plugin_release.py` also creates tags through `POST /repos/{repo}/git/refs`,
which GitHub rejects when the ref already exists, and it contains no code path that deletes,
force-updates, or moves a tag or edits a release.

## Release procedure

### 1. Merge the version bump

1. **Change and validate the three lockstep version fields.** Apply the minimum semver increment
   per `AGENTS.md` (patch while a plugin is `0.0.x`) to all three fields on a feature branch, then
   run both repository checks:

```bash
uv run tools/generate_codex_agents.py --check
uv run tools/check_repo.py
```

2. **Add the changelog entry in the same pull request** as the version change. The heading must be
   exactly `## <plugin>-vX.Y.Z`; the tagging workflow refuses to tag a version whose heading is
   missing at the merged commit, and `dev:release` uses that section as the release notes.

3. **Merge through the protected `main` pull request gate.** Direct pushes to `main` are rejected by
   the `main pull request gate` ruleset; the change merges as a pull request like any other.

### 2. The tag is created automatically

The `Release tags` workflow (`.github/workflows/release-tags.yml`) runs on every push to `main`. It
validates the merged commit, then invokes `plugins/dev/scripts/plugin_release.py tag`, which for
each plugin compares the three synchronized version fields at the push event's before and head
commits:

- strictly increased: create exactly one immutable lightweight `<plugin>-vX.Y.Z` tag at the merged
  commit;
- unchanged: create nothing, and succeed;
- one commit bumping both plugins: create both tags.

It refuses, before creating any tag, when the changed plugin's three version fields disagree, the
new value is not semver, the version decreases, the exact `## <plugin>-vX.Y.Z` changelog heading is
missing at the merged commit, or the tag already exists at a different commit. A tag that already
exists at the expected commit is idempotent success.

Confirm the tag after the merge:

```bash
git fetch origin --tags
git ls-remote --tags origin "refs/tags/dev-v0.0.69"
```

If the workflow refused, fix the cause in a new pull request and merge it. Do not create the tag by
hand and do not move an existing one.

### 3. Publish the GitHub Release

Run the release skill with the exact tag (Claude Code: `/dev:release dev-v0.0.69`; Codex:
`$release dev-v0.0.69`). It shows the target tag and commit, requires explicit authorization for the
public mutation, and then invokes the helper once:

```bash
uv run plugins/dev/scripts/plugin_release.py release \
  --repo wilsonkichoi/agent-toolkit \
  --tag dev-v0.0.69 \
  --confirm
```

Before mutating anything the helper validates that the tag syntax is a known plugin's
`<plugin>-vX.Y.Z`, the remote tag exists, its commit is reachable from canonical `main`, all three
version fields at that tagged commit equal `X.Y.Z`, and the tagged `CHANGELOG.md` has the exact
matching heading. It then creates a non-draft, non-prerelease release named `<plugin> plugin vX.Y.Z`
with notes read from that changelog section **at the tagged commit**, and re-reads GitHub to verify
the tag, name, flags, URL, and non-empty notes.

An already correct release is idempotent success. An existing draft, prerelease, mismatched-name,
mismatched-tag, or empty-notes release fails without being edited or deleted, because repairing a
published release in place is exactly what the immutability rule forbids.

### 4. Verify

```bash
git ls-remote --tags origin "refs/tags/dev-v0.0.69"
gh release view dev-v0.0.69 --repo wilsonkichoi/agent-toolkit
```

The remote tag must resolve to the merged commit, and the release must be non-draft and
non-prerelease.

## Rollback and failure recovery

There is no rollback that edits a published release in place, and no recovery that moves a tag. To
correct a shipped release:

1. Fix the problem on a branch and merge it through the normal `main` pull request gate.
2. Bump the three version fields by a patch increment and add the matching `CHANGELOG.md` entry
   describing the correction.
3. The workflow tags the new version on merge; publish its release with `dev:release`.

Never retarget, delete, or recreate an existing tag to ship a correction. If a release must be
discouraged from use, note the superseding version in its GitHub Release description and in the
changelog entry; the tag itself stays where it is.

A failure before the tag exists needs no recovery beyond a follow-up pull request: nothing public
was created. A failure after the tag exists but before the release is published is resolved by
rerunning `dev:release <tag>`, which is safe to repeat.
