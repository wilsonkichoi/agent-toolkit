---
name: merge-pr
description: >
  Merge a GitHub pull request, clean up a merged PR's local worktree and branches, or do both.
  Use when the user says "merge PR", "merge the pull request", "clean up the PR branch",
  "delete the merged branch", "merge and clean the branch", or invokes dev:merge-pr.
  This is a lightweight standalone GitHub operation. If the user explicitly asks for task DoD
  verification, tracker transitions, or the dev lifecycle, use dev:verify instead.
argument-hint: "[merge|cleanup|merge-cleanup] [PR number or URL]"
---

# Merge PR

Run one deterministic GitHub PR operation without entering the tracker-backed dev workflow.

## No dev lifecycle

Do not read `.agent-toolkit/dev.md`, task packets, tracker contracts, project-bootstrap rules, or
`dev:verify`. Do not dispatch reviewer or verifier agents. Do not post verification reports,
change task status, close linked tasks manually, or run retrospectives. This skill exists for
standalone PR operations that do not need that process.

## Authorization

A user's explicit request to merge in the current conversation authorizes the merge. A cleanup-only
request authorizes cleanup of a PR GitHub already reports as merged. Do not add another confirmation
gate. Repository rules remain authoritative; the helper refuses PRs GitHub does not report as clean
and mergeable.

## Resolve inputs

1. Select `merge`, `cleanup`, or `merge-cleanup` from the request. Default "merge and clean up" to
   `merge-cleanup`, never to two hand-written command sequences.
2. Resolve the canonical `OWNER/REPO` and PR number. Use an explicit number or URL when supplied.
   Otherwise use the current branch's PR only when `gh pr view` resolves exactly one PR; ambiguity
   requires a concise question.
3. For `cleanup` and `merge-cleanup`, resolve the repository's clean base checkout, base remote,
   PR head branch, and registered worktrees. If the PR branch is checked out in a separate
   worktree, pass its exact path with `--worktree`. If the current repository root itself has the
   PR branch checked out, omit `--worktree`; the helper switches it to the base after merge.
4. Pass `--delete-remote-branch --push-remote <remote>` only when branch cleanup was requested and
   that remote resolves to the PR head repository. Omit remote deletion for an external
   contributor's branch. Use `upstream` as `--base-remote` when it carries the canonical base.

## Execute once

On Claude Code the helper is `${CLAUDE_PLUGIN_ROOT}/scripts/github_pr.py`. On Codex it is
`../../scripts/github_pr.py` relative to this `SKILL.md`. Invoke exactly one operation:

```bash
uv run <plugin-root>/scripts/github_pr.py <merge|cleanup|merge-cleanup> \
  --repo <owner/repository> \
  --pr <number> \
  <resolved operation arguments>
```

The helper owns all mergeability, check-state, SHA, worktree, base-update, and branch-deletion
guards. Do not repeat its `gh` or `git` sequence before or after it. Do not fall back to manual
merge or cleanup commands when it fails. Report its exact error and the state needed to retry.

On success, report the operation, PR URL, merge commit when present, whether the base was updated,
and which worktree/local/remote branches were removed from the JSON receipt. Nothing else changes.
