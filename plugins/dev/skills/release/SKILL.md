---
name: release
description: >
  Publish the GitHub Release for an existing plugin version tag. Use when the user says
  "publish the release", "create the GitHub release for dev-v0.0.69", "release the plugin
  version", "cut the release for this tag", or invokes dev:release. The tag itself is created
  automatically when a version bump merges to main; this skill only publishes its release. For
  merging a pull request use dev:merge-pr, and for task verification use dev:verify.
argument-hint: "<plugin>-vX.Y.Z"
---

# Release

Publish one GitHub Release from one already-existing, immutable plugin version tag.

## Scope

Tags are not created here. A push to `main` that strictly increases a plugin's three synchronized
version fields triggers the `Release tags` workflow, which creates `<plugin>-vX.Y.Z` at that merged
commit. This skill takes such a tag and publishes its GitHub Release.

Do not read `.agent-toolkit/dev.md`, task packets, tracker contracts, or project-bootstrap rules,
and do not dispatch reviewer or verifier agents. This is a standalone repository operation, not a
lifecycle step. Never create, move, delete, re-point, or recreate a tag, and never edit or delete an
existing release; a published tag and release are permanent public references.

## Resolve inputs

1. Take the exact tag from the argument. It must be `<plugin>-vX.Y.Z`. Never infer a tag from the
   current version fields, and never invent the next version.
2. Resolve the canonical `OWNER/REPO` from the repository's configured remote, not from the working
   directory's inferred default.
3. Read the tag's commit without mutating anything:

```bash
gh api "repos/<owner/repository>/git/ref/tags/<tag>" --jq .object.sha
```

   A missing tag means the version has not merged to `main` yet, or the `Release tags` workflow
   failed. Report that and stop; do not create the tag by hand.

## Authorize

Creating a GitHub Release publishes a permanent public artifact. Show the user the target tag, its
commit, and the canonical repository, then get explicit authorization for this specific release
before invoking the helper. A general request to "work on releases" is not authorization for a
particular publish. Without it, stop and report what is pending.

## Execute once

On Claude Code the helper is `${CLAUDE_PLUGIN_ROOT}/scripts/plugin_release.py`. On Codex it is
`../../scripts/plugin_release.py` relative to this `SKILL.md`. Invoke it exactly once, after
authorization:

```bash
uv run <plugin-root>/scripts/plugin_release.py release \
  --repo <owner/repository> \
  --tag <plugin>-vX.Y.Z \
  --checkout <repository root> \
  --confirm
```

The helper owns every guard: tag syntax, remote tag existence, reachability from canonical `main`,
the three version fields at the tagged commit, the exact `## <tag>` changelog heading, release-note
extraction from the tagged commit, non-draft and non-prerelease creation, and the verification
re-read. Do not reproduce any part of that `gh` or `git` sequence before or after it, and do not
fall back to a manual `gh release create` when it refuses.

`--confirm` is the authorization gate: without it the helper refuses to create a release. An already
correct release returns `"action": "already-published"` without mutating anything, so a repeated run
is safe.

## Report

Report the helper's verified receipt: the plugin, version, tagged commit, whether the release was
created or already published, and the release URL and name. On refusal, report its exact error and
what has to change. A wrong, draft, or prerelease existing release is corrected by publishing a new
patch version, never by editing or deleting the existing release or moving its tag.
