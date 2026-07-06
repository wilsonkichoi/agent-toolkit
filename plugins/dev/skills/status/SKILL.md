---
name: status
description: >
  This skill should be used when the user asks "where are we", "project status", "what's next
  to work on", "show the board", "dev status", or invokes /dev:status. One read-only screen:
  milestone progress from the tracker, open PRs with CI state, WIP against the limit, blocked
  tasks, and the next claimable tasks. Changes nothing.
argument-hint: "[milestone N]"
---

# dev:status

One screen answering "where are we and what should happen next". Strictly read-only: no
transitions, no comments, no fixes - flag problems, point at the skill that fixes them.

Read first: `.claude/dev.md` and `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md`. Scope: the given
milestone, else the active one.

## Gather

1. **Tracker:** `list <milestone>` - counts by status, plus per-task id/title/status.
2. **PRs:** open PRs on `task/*` branches (`gh pr list`), each with CI state
   (`gh pr checks`) and review verdict. Skip when no GitHub remote.
3. **Next up:** apply the next-task algorithm; show the top 3 claimable tasks with priority
   and estimate.
4. **WIP:** In Progress + In Review count vs `work_in_progress_limit`.
5. **Worktrees:** `git worktree list` for task worktrees.

## Report format

```
# dev status - milestone <n>
Progress: <done>/<total> done | <in-review> in review | <in-progress> in progress
          | <todo> todo | <blocked> blocked | <backlog> backlog
WIP: <n>/<work_in_progress_limit>  <"(gate closed - review/verify to unblock)" when full>

## Needs human action
- <task> In Review, PR #<n> CI green, review approved  -> /dev:verify <id>
- <task> In Review, PR #<n> review requested changes   -> /dev:review-pr <n> fix
- <task> Blocked: <one-line diagnostic>                -> human
## In flight
- <task> In Progress (PR #<n>: CI running | no PR yet)
## Next up
1. <id> <title> (priority, estimate)
```

Order "needs human action" by what unblocks the most: verify-ready first (frees WIP), then
review fixes, then blocked tasks.

## Consistency checks

Flag, do not fix:

- Task `In Review` but its PR is merged or closed → `/dev:verify` was skipped or died
  mid-run; the task state is lying.
- Task `In Progress` with no matching branch/worktree, or claimed hours ago with no PR →
  likely an abandoned claim; suggest releasing it to `Todo`.
- Open `task/*` PR with no task in `In Progress`/`In Review` → work outside the tracker.
- Worktree for a `Done` task → cleanup missed; suggest `git worktree remove`.
- Dependency cycles or a `Todo` task depending on a `Wont Do` task → planning error; route
  to `/dev:backlog`.
