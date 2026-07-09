---
name: dev-execute
description: >
  This skill should be used when the user asks to "execute the next task", "pick up a task",
  "work on task <id>", "start the execution loop", "implement the next ticket", or invokes
  /dev:execute. Claims one task from the tracker, implements it in an isolated worktree,
  opens a PR, drives CI to green, and hands off at In Review. Never merges.
metadata:
  argument-hint: "[task-id]"
---

# dev:execute

Execute exactly one task: claim → worktree → implement → PR → CI green → In Review → stop.
Merging is `dev:verify`'s job; never merge, even if asked mid-run - point at `dev:verify`.

Skill references like `dev:verify` mean this plugin's `verify` skill; when telling the user to
run one, render your harness's invocation for it (Claude Code: `/dev:verify`).

Read first: `.claude/dev.md` (config) and the plugin's `references/tracker.md` (tracker verbs,
backend mapping, next-task algorithm) (bundled with this skill).

## 1. Claim

- No argument: run `next-task`. It enforces the WIP gate (`work_in_progress_limit`) and dependency rules.
  If nothing is claimable, report why (WIP limit reached / no unblocked Todo tasks) and stop.
- With a task id: `get-task`, then check the same gates by hand - status is `Todo`, all
  dependencies `Done`, WIP below `work_in_progress_limit`. Refuse (with the reason) if any gate fails; the
  user can override explicitly.
- With a `#N` GitHub issue (secondary intake channel, primary tracker not github): this is
  isolated work GitHub owns - skip the primary-queue gates and see **In-place GitHub item**
  below.
- `claim` the task and confirm the claim won (re-read; see `references/tracker.md` race guard).

**Packet validation.** A claimable packet has at minimum an Objective and a Definition of
Done. If either is missing (typical for hand-written tickets), do not guess and do not
implement:

- Draft the missing fields from `docs/PRD.md` / `docs/SPEC.md` and post them as a comment on
  the task for confirmation.
- Interactive: ask the user to confirm the drafted packet, then proceed.
- Unattended: release the claim (transition back to `Todo`), comment why it was skipped, and
  claim the next valid task instead.

**In-place GitHub item (`#N`, secondary intake channel).** When the argument is a GitHub issue
number and `secondary_intake: github` is set with a non-github primary tracker, GitHub owns
this item (`references/tracker.md` "Secondary intake channel"). Same worktree → PR → CI → review → verify
path, with these deltas only:

- Claim: no WIP / dependency / `Todo` gate and no `status:*` label. `gh issue view <n>` for
  the packet, run the packet validation above (draft missing Objective/DoD from the issue body
  + `docs/`). Lightweight claim = `gh issue edit <n> --add-assignee @me`; the opened PR is the
  real collision signal.
- All comments (approach notes, CI-fix cycles, work summary) go on the issue via
  `gh issue comment <n>`, not a primary-tracker task.
- Step 4 PR body includes `Closes #<n>`; record the PR URL as an issue comment.
- Step 7 hand-off: refresh the PR body and post the work-summary on the issue, then stop -
  there is **no `In Review` transition** (in-place items carry no status labels). Report the
  PR number and point at `dev:review-pr #<pr>`.

A drive-by PR with no issue behind it does not go through `dev:execute` at all - review and
verify it directly (`dev:review-pr <pr>`, `dev:verify <pr>`).

## 2. Isolate

Bring `main` up to date first: `git fetch origin`, and if local `main` has commits origin
lacks (approved gate artifacts, applied retro promotions), push them before branching -
the worktree branches from local `main`, so unpushed commits silently ride into the task's
PR diff. Then create a git worktree on a fresh branch `task/<id>-<slug>` at the pinned
path `../<repo>-worktrees/<id>-<slug>` (sibling container dir, one per repo - do not invent
a different naming scheme per session):
`git worktree add -b task/<id>-<slug> ../<repo>-worktrees/<id>-<slug> main`. All work
happens there. Do not use the
harness's built-in worktree-isolation feature for subagents (on Claude Code: Agent tool
`isolation: worktree` / EnterWorktree) for this:
it creates its own `worktree-agent-*` branch that no cleanup step knows about, leaking one
dead branch per task.

## 3. Implement

The packet is the contract: read its inlined spec excerpts and follow the linked
`docs/SPEC.md` sections. Scope discipline:

- Implement this task only. No unrelated refactors, no features beyond the DoD, no drive-by
  cleanup outside the task's files.
- Spec gap discovered (needed behavior the spec does not define): comment it on the task,
  flag it in the work summary, implement the narrowest reasonable interpretation only if the
  task is otherwise blocked - otherwise leave the gap for `dev:backlog` triage.
- Stuck: `comment` each genuinely different approach as you abandon it (`## Approach <n>/3
  attempt (dev:execute - <date>)` with what you tried and why it failed), so the dead ends are
  visible on the task, not only in this session. After 3 fail, stop burning tokens - transition
  to `Blocked` with a final comment giving the best root-cause hypothesis (the per-approach
  comments are the trail; do not repeat them), and stop (unattended: move to the next task).

**Tests.** For non-trivial tasks, delegate test authoring to the `dev:test-writer` agent,
giving it ONLY: the task packet, the spec excerpts, and the public interface (signatures,
schemas, endpoints). Never show it the implementation diff - it tests the contract, not the
code. Trivial tasks (config, docs, one-liners) may test inline. Run the full
`test_command` from `.claude/dev.md`; everything passes before pushing.

## 4. PR

Push the branch and open a PR:

- Title: `<task-id>: <task title>`.
- Body: Objective, the DoD as a checklist, spec references, and the task link - for the
  GitHub backend include `Closes #<n>` (safe: only `dev:verify` merges, so auto-close cannot
  bypass verification). For Linear, the `task/<id>-` branch prefix auto-links the issue.
- Record the PR URL on the task (comment, or `pr:` field on the local backend).

**No GitHub remote:** skip the PR. Commit on the task branch and record the branch name on
the task instead; `git diff main...task/<id>-<slug>` becomes the review surface for
`dev:review-pr`, and `dev:verify` merges locally.

## 5. CI to green

Watch checks (`gh pr checks --watch`). On failure, diagnose from the CI logs, fix, push to
the same branch, re-watch. Count attempts.

**Comment every cycle** so the iteration is visible on the task itself, not only in PR
check-runs a reader has to reconstruct. Before re-watching, `comment` on the task:

```
## CI fix attempt <n>/<max_fix_attempts> (dev:execute - <date>)
- Failing checks: <check names> (run: <ci run url>)
- Diagnosis: <root cause from the logs>
- Fix: <what changed>  Pushed: <commit sha>
```

After `max_fix_attempts` (config, default 3) failed cycles, stop: transition to `Blocked` and
post a final comment with the best root-cause hypothesis and what a human needs to unblock
(the per-attempt comments above are the diagnostic trail; do not repeat them). No CI
configured (`ci_workflow` empty): the local `test_command` run is the gate, and each failed
fix cycle is commented the same way (`Failing tests:` in place of `Failing checks:`).

## 6. Visual verification instructions

When any DoD criterion requires visual/UI judgment (screenshots, side-by-side, design
parity, UI appearance): add a "Local preview" section to the PR body with instructions for
the reviewer to run the dev server and interact with the UI. Production is not updated
until after verify merges, and most projects have no deploy preview on PRs, so a local dev
server is the only way to see the new version.

The instructions are for the human gate; the first check is yours. Before hand-off, run
the dev server in the task worktree and inspect every touched page yourself - browser
tools or screenshots when available, at minimum fetching the routes and reading the
rendered output - side-by-side against the comparison target when the criterion names one.
Obvious parity gaps (missing sections, stray icons or arrows, broken layout, features
dropped as "dead code" that the target still renders) are implementation defects: fix them
now, before the PR. CI and the build check correctness, not completeness; the human gate
judges what remains, it is not the first pair of eyes on the page.

Include: the worktree path (or branch + checkout command), the dev command, the port, the
comparison target and its serve command (if the criterion requires side-by-side), and which
pages/routes to check. Example:

```
### Local preview
- **New version:** `cd <worktree-path> && <dev_command>` → localhost:<port>
- **Comparison:** `cd <comparison-path> && <dev_command> -- --port <alt-port>` → localhost:<alt-port>
- **Check:** / (home), /about
```

If no visual criteria exist in the DoD, skip to step 7.

## 7. Hand off

1. Refresh the PR body: any DoD checklist written at PR-open time was written before CI and
   lifecycle facts existed - set each box to its now-verified state (`gh pr edit`). Stale
   unchecked boxes misreport the PR to reviewers. Exception: never check a box for a manual
   or visual/UI criterion - those record human sign-off and are set only by `dev:verify`
   after the human confirms. An unchecked human-gate box must reliably mean "not yet signed
   off".
2. Post the work-summary comment on the task:

   ```
   ## Work summary (dev:execute - <date>)
   - PR: <url>  Branch: task/<id>-<slug>
   - Implemented: <1-2 sentences>
   - Key decisions: <non-trivial choices, or "none">
   - Obstacles: <what failed and how it was resolved, or "none">
   - Spec gaps found: <list, or "none">
   ```

   This comment is the primary input for `dev:review-pr` and `dev:retro` - write it for a
   reader with zero context from this session.

3. Transition the task to `In Review`.
4. Report: task, PR URL, CI status, spec gaps. Next step: `dev:review-pr`, then
   `dev:verify`. **Stop. Do not merge. Do not start another task in this session** (fresh
   context per task) - except in loop mode below.

## Loop / batch mode

When invoked repeatedly in one session (`/loop /dev:execute`) or asked to "drain the queue":
keep this session a thin orchestrator. Per iteration: claim (step 1) here, then delegate
steps 2-7 to ONE background subagent, passing it the full packet and this skill's
instructions; it creates and works in the task worktree per step 2. Spawn it without
harness worktree isolation (see step 2) and without a `model` parameter, so it inherits the
session model; never downgrade to a smaller model to route around a model-availability
error - stop and report instead. Wait for it to finish, relay its report, then iterate.
Never implement in the orchestrator session - context accumulated across tasks is how
mid-task compaction corrupts work. Stop when the WIP gate closes or after `max_tasks_per_run`
tasks (config, default 5); report and idle. For true fresh context per task, the human runs
a new interactive session per task; never script headless sessions (`claude -p`) or suggest
them - they run without the human's session config and oversight.

Harness notes: loop/batch mode needs a harness with both a loop/repeat-invocation mechanism
(`/loop` on Claude Code) and background subagents. On a harness without them (e.g. Kiro IDE),
do not attempt loop mode - run one task per session and tell the user that batch mode is
unavailable there. A Codex outer loop (`codex exec` per task) is deferred pending a design
pass; until then treat batch mode as Claude-Code-only.

Scope note: this mode only fills the review queue - every task stops at `In Review`, so a
dependency chain will not advance past its first task (deps unblock at `Done`, and `Done`
needs `dev:verify`). To drive tasks all the way to `Done` unattended, including merge and
per-task retro, use `dev:auto`.
