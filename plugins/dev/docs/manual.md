# dev plugin manual

Operating guide for the `dev` plugin. The [README](../README.md) is the index (what exists,
typical flow); this manual is how to run it: prerequisites, configuration, lifecycle rules,
human gates, unattended operation, and platform constraints. Related references:
[tracker.md](tracker.md) (tracker contract and backend mappings) and
[adoption.md](adoption.md) (brownfield adoption, custom trackers, third-party memory).

## Mental model

Four rules explain every skill's behavior:

1. **The tracker is the single source of truth for task state.** Skills query and update it;
   nothing maintains a parallel status file. Docs (`docs/PRD.md`, `docs/SPEC.md`) are the
   source of truth for intent; the tracker only for state.
2. **Every task is a self-contained packet.** Objective, why, Definition of Done, dependencies,
   and inlined spec excerpts travel with the task, so a fresh session can execute it without
   prior context.
3. **The quality loop is PR-native.** PR + CI + PR review comments are the review medium; no
   custom review files. `dev:execute` never merges; `dev:verify` is the only merger.
4. **The memory loop is closed.** Execution produces evidence (PR threads, CI history,
   work-summary comments); `dev:retro` distills it; approved learnings land in
   `.claude/rules/` or CLAUDE.md and load automatically in every future session.

## Prerequisites

- **All backends:** a git repository. Each approval gate commits its artifacts, and
  `dev:execute` branches from `main`, so an empty repo gains its root commit at `dev:setup`.
- **`github` backend:** `gh auth status` must succeed and the repo needs a GitHub remote.
  `dev:setup` creates the `status:*` / `priority:*` / `size:*` labels once.
- **`linear` backend:** the official Linear MCP server:
  `claude mcp add --scope local --transport http linear https://mcp.linear.app/mcp` (browser OAuth on first
  call). The team needs an `In Review` workflow state; `dev:setup` asks a human to add it if
  missing.
- **`local` backend:** nothing beyond git. Tasks live in `.dev/tasks/`, one file per task.
- **Optional auto-review GitHub Action:** repo secret `ANTHROPIC_API_KEY`
  (`gh secret set ANTHROPIC_API_KEY`); each auto-review spends API tokens. The manual
  `/dev:review-pr` path works without it.

## Configuration: `.claude/dev.md`

Written by `dev:setup`, committed and team-shared. Structured fields live in YAML
frontmatter; the markdown body holds free-text conventions skills cannot parse (e.g. "all API
changes need a migration note in the PR body"). `.claude/dev.local.md` (gitignored) overrides
fields per developer.

| Field | Default | Read by | Meaning |
|---|---|---|---|
| `tracker` | required | every task-touching skill | `linear` \| `github` \| `local` \| `custom` |
| `linear_team`, `linear_project` | - | tracker calls | Linear scope; only with `tracker: linear` |
| `test_command` | required | `execute`, `verify`, `review-pr` fix mode | How to run the test suite (e.g. `cd backend && uv run pytest`) |
| `ci_workflow` | required with a remote | `execute`, `verify` | CI workflow file name under `.github/workflows/` |
| `merge_policy` | `squash` | `verify` | `squash` or merge commit |
| `review_action_installed` | `false` | record only | Whether `dev:setup` installed the auto-review Action (`claude-review.yml`) |
| `work_in_progress_limit` | `3` | `execute`, `auto`, `status` | Max tasks simultaneously `In Progress` + `In Review`; claims refuse past it |
| `max_fix_attempts` | `3` | `execute`, `auto` | CI-fix or review-fix cycles before the task goes `Blocked` with a diagnostic comment |
| `max_tasks_per_run` | `5` | `execute` loop mode, `auto` | Batch cap per unattended run |
| `auto_merge` | `false` | `auto`, `verify` | Standing merge approval for `/dev:auto`; see Unattended operation |
| `memory_target` | `files` | `retro` | Where promotions land: `.claude/rules/`/CLAUDE.md, or a memory MCP system (see adoption.md §5) |
| `secondary_intake` | - | `execute`, `review-pr`, `verify`, `backlog`, `status` | Opt into GitHub as an isolated-work channel on a non-github-primary project (`github`); see Secondary intake channel below |
| `github_repo` | - | secondary-channel skills | `owner/repo` the secondary issues/PRs live in; only with `secondary_intake: github` |
| `audit_trail` | `link` | secondary-channel skills | `link`: the PR/issue is the record. `mirror` (per-merge primary ticket) is reserved, not built |

## Task lifecycle and ownership

`Backlog → Todo → In Progress → In Review → Done`, plus `Blocked` and `Wont Do`.

| Status | Set by | Meaning |
|---|---|---|
| `Backlog` | `dev:backlog` intake, manual tickets | Captured, not committed |
| `Todo` | `dev:plan`, human promotion, `dev:backlog` on instruction | Committed; the only status `dev:execute` claims from |
| `In Progress` | `dev:execute` claim | One session is implementing it |
| `In Review` | `dev:execute` when the PR is up and CI is green | Awaiting review and verify |
| `Done` | `dev:verify` only, after DoD evidence and merge | Merged and verified |
| `Blocked` | `dev:execute` after `max_fix_attempts`, or anyone with a reason comment | Needs a human; always carries a diagnostic comment |
| `Wont Do` | `dev:backlog` or human, with rationale comment | Deliberately dropped; the reason survives |

Rules that surprise people:

- **Dependencies unblock only at `Done`.** A dependency sitting at `In Review` still blocks
  its dependents, because "done" means merged. This is why `/loop /dev:execute` cannot
  advance a dependency chain and `/dev:auto` exists.
- **`Backlog → Todo` promotion is never automatic.** It is a human decision, made in the
  tracker UI or by asking `/dev:backlog`.
- **Hand-written tickets are validated at claim time.** If a manually created ticket lacks an
  objective or DoD, `dev:execute` does not guess - executing an underspecified ticket would
  mean the agent inventing its own scope. It drafts the missing fields from the docs, posts
  them on the ticket for confirmation, and (unattended) releases the claim and skips to the
  next valid task. The ticket stays `Todo`; once a human confirms or edits the drafted
  packet on the ticket, the next claim proceeds normally.

Backend mappings, the next-task selection algorithm, and the claim race guard are in
[tracker.md](tracker.md).

## Human gates

Every gate commits its artifacts on approval (uncommitted gate output strands the next skill,
which branches from `main`).

| Gate | Skill | Approval unblocks |
|---|---|---|
| PRD review | `discover` | `/dev:architect` |
| Spec + roadmap review | `architect` | `/dev:plan` |
| Plan dry run | `plan` | Packets pushed to the tracker at `Todo` |
| Merge | `verify` | Merge per policy, task → `Done`, cleanup (carve-out: `auto_merge`, below) |
| Rule promotion | `retro` | Learnings written to `.claude/rules/` / CLAUDE.md |
| `Backlog → Todo`, `Wont Do` | `backlog` | Task enters or leaves the committed queue |

## Unattended operation

Two modes with different destinations:

- **`/loop /dev:execute` fills the review queue.** Each iteration lands one task at
  `In Review`; humans review and verify at their own pace. On a dependency chain it advances
  exactly one task. The session stays a thin orchestrator and delegates implementation to one
  background subagent per task in that task's worktree; for true fresh context per task,
  prefer a shell loop of headless sessions (`claude -p "/dev:execute"`).
- **`/dev:auto` drains a milestone to `Done`.** Per task: execute → independent review →
  bounded fix loop → verify → merge → record-only retro, then the next task. Single-flight.

`/dev:auto` merges only when ALL hold: `auto_merge: true` (standing, revocable human
approval), the independent review verdict is approve, every DoD criterion is met, and every
criterion is mechanically evidenced (test run or CI check). A manual DoD criterion always
stops the pipeline for a live human, regardless of config. Unattended retro never writes
rules; promotions accumulate as proposals for a human retro pass.

Safeguards (all config-backed): `work_in_progress_limit` stops claims when the review queue
is full (review capacity is the throttle); `max_fix_attempts` sends a stuck task to `Blocked`
with a diagnostic comment instead of iterating forever; `max_tasks_per_run` caps the batch.

Note which safeguard belongs to which mode: the WIP limit is `/loop /dev:execute`'s
throttle, because that mode parks every task at `In Review` until a human drains the queue.
`/dev:auto` cannot trip it through its own activity - single-flight means at most one task
is `In Progress`/`In Review` at a time - but the check lives in the shared claim step, so
`auto` still refuses to start if a previous loop left the queue at the limit.

Unattended runs stall on the first permission prompt: pre-approve git, `gh`, and the
`test_command` in `.claude/settings.json` before starting a loop.

## Parallel operation

What is safe to run simultaneously, and why:

- **Parallel `/dev:execute` sessions on independent tasks** - the supported way to
  parallelize implementation (one terminal or headless `claude -p "/dev:execute"` per task).
  The tracker claim step is the mutex; worktrees isolate the filesystem. There is no
  intra-session fan-out: a `/loop` orchestrator runs ONE implementation subagent at a time,
  deliberately.
- **Parallel reviews** - safe; reviews are stateless reads, and PRs simultaneously
  `In Review` are dependency-free by construction (dependencies unblock at `Done`, so a
  dependent can never have an open PR alongside its dependency's).
- **Parallel `/dev:verify`** - evidence gathering is safe in parallel; the merges themselves
  serialize, and sibling PRs that branched before an earlier merge may need a rebase (a
  rebase that resolves real conflicts in reviewed hunks warrants a re-review).
- **`/dev:auto`** - single-flight by design; run one at a time.

The rule that makes all of this safe: no skill ever checks out a task branch in the main
working copy. Branch-file operations (tests, reading beyond the diff) happen in that task's
worktree; the main checkout's HEAD only moves at merge time.

## Secondary intake channel (GitHub-native work)

When your primary tracker is Linear (or local) but the project still gets GitHub issues and
drive-by PRs that are isolated - not part of a milestone, not in the backlog - forcing each
into the primary tracker recreates dual state and pollutes its metrics. Set
`secondary_intake: github` + `github_repo: owner/repo` in `.claude/dev.md` to accept them as a
second channel. Every incoming GitHub issue or PR gets exactly one fate:

```
Incoming GitHub issue or PR
│
├─ Needs design / touches the spec / belongs to a milestone / blocks tracked work?
│     → /dev:backlog #N  →  PROMOTE: full primary-tracker packet, issue linked and
│                            closed as transferred. Only here do discover/architect/plan apply.
│
├─ Isolated and self-contained (typo, drive-by bug, external-contributor PR)?
│     → WORK IN PLACE. GitHub owns the item; no primary ticket.
│        /dev:execute #N     claim (self-assign) → worktree → PR (Closes #N) → CI → In place
│        /dev:review-pr #PR   review against the issue's acceptance criteria + spec
│        /dev:verify #PR      CI + approving review → merge; issue auto-closes. No primary write.
│     A pure drive-by PR with no issue: skip execute; /dev:review-pr <pr> then /dev:verify <pr>.
│
└─ Not worth doing?
      → /dev:backlog #N  →  DECLINE: Wont Do, issue closed with rationale.
```

Routing is by argument shape: `#N` hits the GitHub channel, a primary key (`NOVA-123`) the
primary tracker. An argument-less `/dev:execute` (or `next-task`) only ever pulls from the
primary queue, so in-place items never jump ahead of planned work. In-place items skip the
`status:*` label lifecycle entirely - their state is just open → PR → review → merged. The
merged PR plus its review and verify report is the audit trail (`audit_trail: link`); no
primary-tracker row is ever created for in-place work. Full contract: tracker.md "Secondary
intake channel".

## Working without a GitHub remote

Local-only projects degrade gracefully: `dev:execute` records a branch instead of a PR and
the `test_command` run stands in for CI; `dev:review-pr` reviews
`git diff main...task/<id>-<slug>` and posts the review as a task comment; `dev:verify`
merges locally per policy and deletes the branch.

## Known platform constraints

- **No self-approval on GitHub.** GitHub rejects `APPROVE`/`REQUEST_CHANGES` review types on
  the author's own PR, and the reviewer agent inherits the session's `gh` auth, so solo repos
  never get a formal `APPROVED` state. The `Verdict:` line in the structured review body is
  the verdict of record; `dev:verify` accepts it.
- **Filtered `gh issue list` is eventually consistent.** `--milestone`/`--label`/`--search`
  route through GitHub's search API; a just-created issue can be missing from the result.
  Skills use the REST issues endpoint for reads that must be current (see tracker.md).
- **Unfiltered Linear `list_issues` can omit issues.** An issue absent from an unfiltered
  listing can still be returned by a `state`-filtered query. Skills query per state and
  confirm specific issues with `get_issue` (see tracker.md).

## Project layout

```
project/
├── CLAUDE.md              # lean; links to docs/; updated by dev:architect and dev:retro
├── research/raw/          # human research dumps consumed by dev:discover
├── docs/
│   ├── PRD.md             # dev:discover output
│   ├── SPEC.md            # dev:architect output
│   ├── ROADMAP.md         # milestones with outcomes
│   └── adr/               # decision records (spikes, architecture choices)
├── .claude/
│   ├── dev.md             # plugin config (committed)
│   ├── dev.local.md       # personal overrides (gitignored)
│   └── rules/             # promoted retro learnings
└── .dev/tasks/            # only with tracker: local
```
