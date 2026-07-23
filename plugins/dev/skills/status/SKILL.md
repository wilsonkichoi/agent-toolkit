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

Skill references like `dev:verify` mean this plugin's `verify` skill; when telling the user to
run one, render your harness's invocation for it (Claude Code: `/dev:verify`; Codex: `$verify`).

Read first: `.agent-toolkit/dev.md` (legacy fallbacks: `.agent/dev.md`, then `.claude/dev.md` when absent) and the plugin's `runtime_contracts/tracker.md` — on Claude Code
`${CLAUDE_PLUGIN_ROOT}/runtime_contracts/tracker.md`, equivalently `../../runtime_contracts/tracker.md` relative to this
skill's directory. Scope: the given milestone, else the active one.

Before any repository or tracker read, resolve repository context once using `tracker.md`
"GitHub repository resolution". This skill remains strictly read-only. In active fork
routing, every GitHub read explicitly targets `github_primary_repo`; missing or inconsistent
remote topology produces the documented stop reason and no mutation.

The fork fields enable a project capability; they do not require every checkout to be a fork.
When `origin` is `github_primary_repo` and the authenticated user has upstream write permission,
the checkout is valid maintainer mode: `origin` supplies both the base and push destination, an
`upstream` remote is optional, and normal planned-queue behavior applies. Do not describe this
topology as misconfigured or recommend removing the fork fields. Their committed canonical value
must remain available to contributors who inherit the configuration in their forks.

## Gather

1. **Tracker:** `list <milestone>` - counts by status, plus per-task id/title/status.
2. **PRs:** open PRs on `task/*` branches (`gh pr list`), each with CI state
   (`gh pr checks`) and review verdict. Skip when no GitHub remote. When
   `secondary_intake: github` is set (`runtime_contracts/tracker.md`), a `task/*` PR that links a `#N` issue but
   matches no primary task is legitimate in-place work - list it separately as github-native,
   not as a violation.
   In primary-GitHub fork mode, also list open contribution issues with no `status:*` queue
   label, including issues not yet linked to a PR, plus open cross-repository contribution PRs,
   in a separate **External contributions** section. Do not count them as planned-queue WIP,
   include them in milestone progress, or select them as next tasks. A maintainer working from
   a fork sees the same separation; permission does not turn external PRs into queue tasks.
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
- <task> In Review, PR #<n> CI green, review approved  -> dev:verify <id>
- <task> In Review, PR #<n> review requested changes   -> dev:review-pr <n> fix
- <task> Blocked: <one-line diagnostic>                -> human
## In flight
- <task> In Progress (PR #<n>: CI running | no PR yet)
## External contributions (excluded from queue WIP)
- Issue #<n> <title>, no PR | PR #<n>
- PR #<n> from <fork-owner>:<branch>, issue #<n>, CI <state>, review <state>
## Next up
1. <id> <title> (priority, estimate)
```

Order "needs human action" by what unblocks the most: verify-ready first (frees WIP), then
review fixes, then blocked tasks.

## Consistency checks

Flag, do not fix:

- Task `In Review` but its PR is merged or closed → `dev:verify` was skipped or died
  mid-run; the task state is lying.
- GitHub backend: closed issue still carrying a `status:*` label → stale terminal
  transition (auto-close does not touch labels); suggest
  `gh issue edit <n> --remove-label status:<x>`.
- Task `In Progress` with no matching branch/worktree, or claimed hours ago with no PR →
  likely an abandoned claim; suggest releasing it to `Todo`.
- Open `task/*` PR with no task in `In Progress`/`In Review` → work outside the tracker -
  unless `secondary_intake: github` is set and the PR links a `#N` issue, which is legitimate
  in-place work (report it as github-native, above).
- Worktree for a `Done` task → cleanup missed; suggest `git worktree remove`.
- Empty `../<repo>-worktrees/` container dir (or a stray sibling dir from an old ad-hoc
  worktree path) with no worktrees in it → cleanup missed the container; suggest `rmdir`.
- Local branch matching neither `task/*` nor the default branch (e.g. a leftover
  `worktree-agent-*` from harness isolation) → orphan; suggest `git branch -d` if it has no
  unique commits.
- Dependency cycles or a `Todo` task depending on a `Wont Do` task → planning error; route
  to `dev:backlog`.
- More than one of `.agent-toolkit/dev.md`, legacy `.agent/dev.md`, legacy `.claude/dev.md`
  exists → duplicate config that will drift; suggest deleting the legacy file(s) after
  confirming `.agent-toolkit/dev.md` is the maintained one.
- Missing reference line: the configured `context_file` contains no reference to
  `.agent-toolkit/dev.md` → sessions start without the dev config and rules; suggest
  re-running `dev:setup` (it adds the single line and touches nothing else).
- Unregistered rules: files exist in `rules_dir` that the `## Rules` section of
  `.agent-toolkit/dev.md` does not import → invisible to future sessions; suggest adding
  the missing import lines.
- Invalid rule graph or metadata: run the plugin's `scripts/resolve_project_rules.py` with
  empty task text and no changed paths. Import cycles, imports outside `rules_dir`, invalid
  tiers, and trigger-free gotchas are configuration errors; report them. Unmatched gotchas
  in `Rules skipped:` are healthy, not missing rules.
- Legacy memory config: `context_file` set with no `rules_dir` (the 0.0.42-0.0.53 mixed
  config, rules consolidated inside the context file) → reads keep working, but `dev:retro`
  holds new promotions as proposals until the config migrates (no import chain exists for
  rule files); suggest running `dev:setup` to migrate and write explicit fields.
