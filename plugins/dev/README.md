# dev

AI-assisted product development lifecycle for Claude Code and Codex, plus lightweight standalone
GitHub PR merge and cleanup operations. For lifecycle tasks, an external tracker (Linear, GitHub
Issues, or local files) is the single source of truth, execution is PR-native (worktree → PR → CI
→ review → verified merge), and every task is a self-contained packet a fresh session can execute
without prior context.

Replaces [agentic_development_workflow](https://github.com/wilsonkichoi/agentic_development_workflow).
This README is the complete guide: the index (what exists, typical flow) up front, then the
operating manual (prerequisites, `.agent-toolkit/dev.md` config reference, lifecycle and
ownership rules, human gates, unattended operation) and the adoption guide. The contracts
skills and agents read at runtime live in
[runtime_contracts/](runtime_contracts/): tracker, project bootstrap, and shadow replay.

## Status

All skills implemented on both harnesses. Dogfooding: the full
lifecycle passed end-to-end on the local, GitHub Issues, and Linear backends (2026-07-06,
Linear milestone runs through 2026-07-14), `dev:auto` completed real tasks on Claude Code
and Codex, and the 0.0.54 encapsulated-config migration is dogfooded in this repository
(`.agent-toolkit/dev.md` drives its own contribution workflow). Brownfield adoption is
untested - expect rough edges there.

Adopting into an existing project (partial adoption, Jira/custom trackers, Mem0/OB1/MemSearch
memory): see [Adopting into an existing project](#adopting-into-an-existing-project) below.

## Invocation across harnesses

Skill names below are written Claude-Code style (`/dev:execute`). Render your harness's form:

| Harness | Invoke | Notes |
|---|---|---|
| Claude Code | `/dev:execute` | full feature set (agents auto-delegate, `dev:auto` + loop mode) |
| Codex | `$execute` | agents copied from `dist/codex/agents/`, selected via `spawn_agent`'s `agent_type` parameter; `dev:auto` supported (sibling test-writer orchestration); no `execute` loop mode |

Install per harness: see the repo-root [README](../../README.md). All plugin state is
encapsulated in `.agent-toolkit/` (legacy `.agent/dev.md` and `.claude/dev.md` still read):
`dev.md` holds the config frontmatter, free-text conventions, and the architecture pointer;
`rules/` holds promoted learnings, one file per rule, each imported from `dev.md`. The
project's own context file (`AGENTS.md` or `CLAUDE.md` - the project's choice) carries a
single reference line to `dev.md` and is never otherwise touched: installing, using, or
removing the plugin does not change how a project's context files work.

Task-scoped lifecycle skills do not rely on that import chain expanding automatically. They
resolve the task's execution repository first, run the bundled deterministic
[project bootstrap](runtime_contracts/project-bootstrap.md), require that checkout's `HEAD` to match the
expected task or PR revision, read its context/config files, load every doctrine rule, select
gotcha rules from declared path/objective/DoD triggers, and record the exact execution revision
and `Rules loaded:` list in lifecycle artifacts. A revision mismatch is a hard stop, not a
signal to retry against whatever revision is checked out: the resolver refuses to read project
files, names the remedy (detach a worktree at the expected revision), and every skill repeats
that stop condition at its point of use.

## Skills

| Skill | Job |
|---|---|
| `/dev:discover` | Ingest `research/raw/`, interview the user to close gaps, produce `docs/PRD.md`: problem, customer, value, north star, non-goals. Business clarity only; delta mode for goal-impacting changes. |
| `/dev:architect` | Approved PRD → `docs/SPEC.md` (architecture, contracts, NFRs, negative requirements, Mermaid diagrams), `docs/ROADMAP.md` (risk-ordered milestones), ADRs for contested choices. Docs only; delta mode for spec-impacting changes. |
| `/dev:setup` | Initialize a project (greenfield or brownfield): scaffold `docs/`, pick tracker backend, write `.agent-toolkit/dev.md`. Brownfield mode offers architecture archaeology into a current-state SPEC.md. Optional installer for the auto-review GitHub Action. |
| `/dev:plan` | Decompose one roadmap milestone into self-contained task packets (objective, why, DoD, dependencies, inlined spec excerpts) and push them to the tracker after a human-approved dry run. |
| `/dev:backlog` | Mid-flight change management: intake requests as full packets with impact triage (backlog-only vs spec vs product goal) and dependency wiring as native tracker relations (both directions against existing tickets), promote `Backlog → Todo`, split tasks, close as `Wont Do` with rationale, periodic triage sweep. |
| `/dev:execute` | Claim one task → git worktree → implement → tests (via the `test-writer` agent, contract-only context) → PR → CI to green → visual self-check + local preview instructions (when DoD has visual criteria; the executor inspects touched pages against the comparison target before hand-off) → work-summary comment → `In Review`. Never merges. Safeguards: `work_in_progress_limit`, `max_fix_attempts`, packet validation for hand-written tickets, and verified write-then-read lifecycle transitions for planned GitHub tasks. |
| `/dev:auto` | Unattended per-task pipeline: target one task (`/dev:auto DOG-14`) or drain a milestone (`/dev:auto milestone 2 [max N tasks]`) through execute → independent review → bounded fix loop → verify → merge → record-only retro. A task target is strictly single-task and never falls through. Requires `auto_merge: true` (standing approval); merges only review-approved work whose criteria are mechanically evidenced or carry a recorded human sign-off; a manual DoD criterion with neither stops for a human. |
| `/dev:review-pr` | Independent one-pass review of a task PR against its packet and spec: severity-ranked findings, verdict posted via `gh pr review`, then stop. Each manual fix invocation snapshots and applies one current findings batch on the same branch, tests, pushes, replies per finding, requests or records the need for re-review, then stops. It never runs the fresh review itself. Delegates review to the `reviewer` agent when the session implemented the PR. Automatic review/fix chaining belongs only to `/dev:auto` and is bounded by `max_fix_attempts`. |
| `/dev:merge-pr` | Lightweight standalone GitHub operation: merge a PR, clean up an already-merged PR's worktree/branches, or do both. It does not read tracker state, task packets, DoD, project-bootstrap rules, or `dev:verify`; it calls one deterministic helper and returns its JSON receipt. |
| `/dev:verify` | The lifecycle merge gate: evidence per DoD criterion (run tests, cite CI, perform manual steps), verification report on the PR, then human-approved merge, task → `Done`, worktree cleanup. It is the only lifecycle skill allowed to merge or set `Done`; standalone operations use `/dev:merge-pr` outside the lifecycle. Human-gate (manual/visual) criteria pass only on a recorded sign-off (a comment authored by the human) or live confirmation - PR-body checkboxes are display only, checked solely by verify. Rejects stale approvals: the approving review must target the current PR HEAD, so a post-review fix push forces a fresh review before merge. Delegates evidence gathering to the `verifier` agent when the session implemented the PR; the human gate and merge stay in the session. Approval never waives the record: the report and checkbox updates land on the PR before the merge. |
| `/dev:retro` | Mines PR review threads, CI history, tracker comments, session transcripts, and lifecycle-contract compliance (did each step produce what its skill mandates, including steps run in the current session) for completed tasks, then closes the memory loop: evidence-cited learnings promoted into the configured memory (`rules_dir` files, `.agent-toolkit/rules/` by default, or a `memory_target` MCP system), applied on approval. Defects or follow-up work the retro uncovers route to the tracker via `/dev:backlog`, never to memory notes; the retro comment posts before the promotion gate so the record survives an abandoned session. |
| `/dev:status` | Read-only dashboard: milestone progress, open PRs + CI state, WIP vs limit, blocked tasks, next claimable tasks, plus consistency checks (state lies, abandoned claims, missed cleanups). |
| `/dev:shadow` | Unattended historical-replay evaluation (`/dev:shadow #<issue> [pr <n>]`): reconstruct a completed issue's historical base, re-implement it with the active session's model through execute → review → bounded fix → verify, then compare against the original on tests, DoD coverage, review findings, scope, time, tokens, and estimated API-equivalent cost. The draft PR opens only after the first candidate commit and binds the resolved head repository, including fork-qualified heads. Posts an audit report on an isolated `[SHADOW]` issue. Never merges; never mutates the source issue or original PR. GitHub source only in v0. |
| `/dev:feedback` | File structured feedback (bugs, enhancements, docs gaps, workflow friction) against the agent-toolkit plugin repository. Gathers diagnostic context, redacts secrets and private data, searches for duplicates, renders a draft using the repository's issue template, and submits only after explicit human approval. Never mutates the current project's tracker. |

## Agents

| Agent | Job |
|---|---|
| `test-writer` | Writes tests from the task packet + public interface only, never the implementation diff. Used by `/dev:execute` for test separation. |
| `reviewer` | Independent PR review with its own context: fetches packet, diff, CI, spec; posts verdict. Used by `/dev:review-pr` when the calling session implemented the PR. |
| `verifier` | Independent DoD evidence gathering with its own context: preconditions, evidence per criterion, verification report. Never merges or asks the human. Used by `/dev:verify` when the calling session implemented the PR, and by `/dev:auto`'s verify step. |

All agents pin `model: inherit` and are spawned without a `model` override, so they run at
the same model as the session that invoked them. A model-availability failure on spawn stops
the pipeline; it is never routed around by downgrading to a smaller model.

## Tracker backends

Configured per project in `.agent-toolkit/dev.md` frontmatter (`tracker:` field). Contract and
backend mappings: [runtime_contracts/tracker.md](runtime_contracts/tracker.md).

| Backend | Mechanism |
|---|---|
| `linear` | Official Linear MCP server; native priorities, estimates, blocked-by relations |
| `github` | `gh` CLI; `status:*` labels, milestones, `Blocked by #N` dependencies |
| `local` | `.dev/tasks/T-NNN-slug.md`, one file per task, YAML frontmatter |
| `custom` | Bring your own (Jira, etc.) via the "Adding a backend" recipe in `runtime_contracts/tracker.md` |

**Primary GitHub fork contributions.** GitHub-primary projects can opt into canonical
repository routing for external contributors:

```yaml
tracker: github
github_primary_repo: owner/canonical-repo
fork_contributions: true
```

The canonical repository owns issues and PRs, `upstream/main` supplies the base, and `origin`
receives contributor branches. Authenticated upstream permission, not remote topology, controls
merge and queue authority. Read-only contributors can create packet-complete canonical issues,
execute from a fork, post independent review and SHA-bound verification evidence, and then stop
for a maintainer decision. A maintainer's canonical clone remains valid with the fork fields
committed: `origin` supplies both base and push, and `upstream` is optional. Existing projects
without both fields behave exactly as before. See
[Primary GitHub fork contributions](#primary-github-fork-contributions) below and the
[repository resolution contract](runtime_contracts/tracker.md#github-repository-resolution).

A maintainer's explicit numeric issue id is planned work and must carry exactly `status:todo`;
external handling requires `external #N`. Planned claim, handoff, and blocked transitions use the
bundled verified lifecycle command, and the execute record preserves the queue classification for
review and verify. GitHub routing accepts that record only when its author, PR URL, branch, and
execution revision bind it to the current PR; later comments from other issue participants cannot
reclassify planned work. Planned review also requires the canonical issue to have exactly
`status:in-review`; review never repairs an incomplete execute handoff.

## GitHub PR merge and cleanup

`scripts/github_pr.py` exposes independent `merge`, `cleanup`, and `merge-cleanup` operations.
The `dev:merge-pr` skill is the lightweight ad hoc entry point; it does not enter the tracker-backed
dev lifecycle. `dev:verify` calls the same executable only after its evidence report and human
approval are complete.

The helper validates the PR state, mergeability, checks, exact HEAD SHA, repository remotes,
worktrees, and branch SHAs. `merge` never touches local worktrees or branches. `cleanup` requires
GitHub to report the PR as merged. `merge-cleanup` validates cleanup inputs before merging and is
safe to rerun after an interrupted cleanup. Every operation emits a compact JSON receipt.

Direct human use from an agent-toolkit checkout.

Merge only:

```bash
uv run plugins/dev/scripts/github_pr.py merge \
  --repo owner/repository \
  --pr 123 \
  --merge-policy squash
```

Clean up only after the PR is merged:

```bash
uv run plugins/dev/scripts/github_pr.py cleanup \
  --repo owner/repository \
  --pr 123 \
  --checkout /path/to/repository \
  --delete-remote-branch \
  --push-remote origin
```

Merge and clean up:

```bash
uv run plugins/dev/scripts/github_pr.py merge-cleanup \
  --repo owner/repository \
  --pr 123 \
  --checkout /path/to/repository \
  --merge-policy squash \
  --delete-remote-branch \
  --push-remote origin
```

Add `--worktree /path/to/pr-worktree` when the PR branch is checked out in a separate worktree.
Use `--base-remote upstream` when the canonical base lives on `upstream`. Omit remote deletion for
an external contributor's branch. `--expected-head <full-sha>` adds an explicit caller-supplied
revision binding; every merge still uses GitHub's `--match-head-commit` guard.

**Secondary intake channel.** A non-`github`-primary project can accept isolated GitHub issues
and drive-by PRs as a second channel (`secondary_intake: github`): promote them into the
primary tracker, or work them in place (`/dev:execute #N` → `/dev:review-pr #PR` →
`/dev:verify #PR`) with no primary ticket. See "An incoming GitHub issue or PR" in
[Secondary intake channel](#secondary-intake-channel-github-native-work) below and
"Secondary intake channel" in [runtime_contracts/tracker.md](runtime_contracts/tracker.md).

## Typical flow

```
/dev:setup        # once per project
/dev:discover     # research + interview → PRD (human gate)
/dev:architect    # PRD → SPEC + ROADMAP + ADRs (human gate)
/dev:plan         # milestone → task packets in the tracker (human-gated dry run)
/dev:execute      # one task per session: claim → PR → CI green → In Review
/dev:review-pr    # one review; each manual fix invocation addresses one findings batch
/dev:verify       # DoD evidence → human-approved merge → Done
/dev:backlog      # anytime: new requests, promotions, wont-do, triage
/dev:status       # anytime: where are we, what needs human action
/dev:retro        # per task or milestone: learnings → .agent-toolkit/rules/ (configured memory)
/dev:auto DOG-14  # unattended: complete exactly this task; never fall through
/dev:auto milestone 2 max 1 tasks  # unattended milestone drain, capped at one task
```

## Mental model

Four rules explain every skill's behavior:

1. **The tracker is the single source of truth for task state.** Skills query and update it;
   nothing maintains a parallel status file. Docs (`docs/PRD.md`, `docs/SPEC.md`) are the
   source of truth for intent; the tracker only for state.
2. **Every task is a self-contained packet.** Objective, why, Definition of Done, dependencies,
   and inlined spec excerpts travel with the task, so a fresh session can execute it without
   prior context.
3. **The quality loop is PR-native.** PR + CI + PR review comments are the review medium; no
   custom review files. `dev:execute` never merges; `dev:verify` is the only lifecycle merger.
4. **The memory loop is closed.** Execution produces evidence (PR threads, CI history,
   work-summary comments); `dev:retro` distills it; approved learnings land as rule files
   under `rules_dir` (default `.agent-toolkit/rules/`). Task-scoped lifecycle skills resolve
   the execution repository at the expected task or PR revision and load those rules through
   the deterministic [project bootstrap](runtime_contracts/project-bootstrap.md), independent of harness import
   expansion.

## Prerequisites

- **All backends:** a git repository. Each approval gate commits its artifacts, and
  `dev:execute` branches from `main`, so an empty repo gains its root commit at `dev:setup`.
- **`github` backend:** `gh auth status` must succeed and the repo needs a GitHub remote.
  `dev:setup` creates the `status:*` / `priority:*` / `size:*` labels once.
  Fork contributions additionally require the committed canonical repository configuration
  and a validated fork `origin` plus canonical `upstream`; see Primary GitHub fork
  contributions below.
- **`linear` backend:** the official Linear MCP server — Claude Code:
  `claude mcp add --scope local --transport http linear https://mcp.linear.app/mcp` (browser OAuth on first
  call); Codex: `codex mcp add linear --url https://mcp.linear.app/mcp`, then
  `codex mcp login linear` (writes `[mcp_servers.linear]` to `~/.codex/config.toml`,
  machine-global). The team needs an `In Review` workflow state; `dev:setup` asks a human to
  add it if missing.
- **`local` backend:** nothing beyond git. Tasks live in `.dev/tasks/`, one file per task.
- **Optional auto-review GitHub Action:** repo secret `ANTHROPIC_API_KEY`
  (`gh secret set ANTHROPIC_API_KEY`); each auto-review spends API tokens. The manual
  `dev:review-pr` path works without it.

## Configuration: `.agent-toolkit/dev.md`

Written by `dev:setup`, committed and team-shared. Structured fields live in YAML
frontmatter; the markdown body holds free-text conventions skills cannot parse (e.g. "all API
changes need a migration note in the PR body") plus a `## Rules` section importing the
promoted rule files under `rules_dir`. `.agent-toolkit/dev.local.md` (gitignored) overrides
fields per developer. Everything the plugin owns lives under `.agent-toolkit/`; the project's
context file carries a single reference line to `dev.md` and is otherwise never touched.
Legacy locations: `.agent/dev.md`, then `.claude/dev.md` - every skill reads
`.agent-toolkit/dev.md` first and falls back to them, and `dev:setup` offers a `git mv`
migration on existing projects. The `.local.md` override is read next to whichever config
location resolves: a legacy `.agent/dev.local.md` or `.claude/dev.local.md` keeps applying
until its config file migrates.

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
| `auto_merge` | `false` | `auto`, `verify` | Standing merge approval for `dev:auto`; see Unattended operation |
| `rules_dir` | `.agent-toolkit/rules/` | task-scoped lifecycle skills, `retro`, `status` | Directory of promoted rule files, one per rule, each registered from the dev config's `## Rules` section and selected by the project-bootstrap tier/trigger contract; point it at an existing convention (e.g. `.claude/rules/`) when the project already has one |
| `context_file` | `AGENTS.md` | task-scoped lifecycle skills, `setup`, `status` | Project-owned context file loaded from the resolved execution repository; it carries the single `@.agent-toolkit/dev.md` reference line (`CLAUDE.md` on Claude-only projects), and the plugin writes nothing else there |
| `memory_target` | `files` | `retro` | Where promotions land: the configured `rules_dir` files, or a memory MCP system (see Third-party memory systems below) |
| `github_primary_repo` | - | every skill in fork-configured projects | Canonical `owner/repo` that owns primary GitHub issues and PRs; only valid with `tracker: github` and `fork_contributions: true` |
| `fork_contributions` | `false` | every skill | Explicit project-owner opt-in to primary-GitHub fork routing; must be `true` with `github_primary_repo`, otherwise omit both fields |
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
  advance a dependency chain and `dev:auto` exists.
- **`Backlog → Todo` promotion is never automatic.** It is a human decision, made in the
  tracker UI or by asking `dev:backlog`.
- **Hand-written tickets are validated at claim time.** If a manually created ticket lacks an
  objective or DoD, `dev:execute` does not guess - executing an underspecified ticket would
  mean the agent inventing its own scope. It drafts the missing fields from the docs, posts
  them on the ticket for confirmation, and (unattended) releases the claim and skips to the
  next valid task. The ticket stays `Todo`; once a human confirms or edits the drafted
  packet on the ticket, the next claim proceeds normally.

Backend mappings, the next-task selection algorithm, and the claim race guard are in
[runtime_contracts/tracker.md](runtime_contracts/tracker.md).

## Human gates

Every gate commits its artifacts on approval (uncommitted gate output strands the next skill,
which branches from `main`).

| Gate | Skill | Approval unblocks |
|---|---|---|
| PRD review | `discover` | `dev:architect` |
| Spec + roadmap review | `architect` | `dev:plan` |
| Plan dry run | `plan` | Packets pushed to the tracker at `Todo` |
| Merge | `verify` | Merge per policy, task → `Done`, cleanup (carve-out: `auto_merge`, below) |
| Rule promotion | `retro` | Learnings written to the configured `rules_dir` and registered in `dev.md` (legacy safety-net fallback when both memory fields are absent: `.claude/rules/` / CLAUDE.md) |
| `Backlog → Todo`, `Wont Do` | `backlog` | Task enters or leaves the committed queue |

## Manual review action boundaries

Manual `dev:review-pr` commands preserve one action per user command:

- `dev:review-pr <pr>` gathers the current evidence, posts one verdict, records it on the
  tracker when applicable, and stops. A `request-changes` verdict reports
  `dev:review-pr <pr> fix` as the next manual command; it does not start fix mode.
- `dev:review-pr <pr> fix` snapshots the currently recorded findings, applies that one batch,
  runs tests, pushes, replies per finding, requests re-review when GitHub accepts an eligible
  reviewer, and stops. In a solo repository, it records that re-review is needed and reports
  that a fresh manual `dev:review-pr <pr>` command is required. It does not execute that
  command, review the pushed commit, or begin another fix pass.
- `dev:auto` is the only workflow that automatically dispatches a fresh review after a fix and
  another fix after a new `request-changes` verdict. Its loop stops after
  `max_fix_attempts`.

## Unattended operation

`/loop /dev:execute` is Claude-Code-specific: it needs the `/loop` primitive (an outer
`codex exec` loop is deferred pending a design pass). `dev:auto` runs on both Claude Code
and Codex - it needs subagents, not a loop primitive. On Codex, copy the agent TOMLs per
the repo README first (they are selected by passing `agent_type: "<agent name>"` on
`spawn_agent`; `task_name` alone does not load them); because Codex's default
`agents.max_depth = 1` blocks nested
spawns, the `dev:auto` orchestrator dispatches the implementation worker and `test-writer`
as siblings (specified in the skill; no configuration needed).

Two modes with different destinations:

- **`/loop /dev:execute` fills the review queue.** Each iteration lands one task at
  `In Review`; humans review and verify at their own pace. On a dependency chain it advances
  exactly one task. The session stays a thin orchestrator and delegates implementation to one
  background subagent per task in that task's worktree; for true fresh context per task,
  run a new interactive session per task instead of looping one.
- **`dev:auto` completes a named task or drains a milestone to `Done`.** `dev:auto DOG-14`
  validates the same Todo/dependency/WIP/packet gates as targeted `dev:execute`, runs only
  DOG-14, and never falls through. `dev:auto milestone 2 [max N tasks]` processes eligible
  milestone tasks sequentially. Per task: execute → independent review → bounded fix loop →
  verify → merge → record-only retro. Both modes are single-flight.

`dev:auto` merges only when ALL hold: `auto_merge: true` (standing, revocable human
approval), the independent review verdict is approve, every DoD criterion is met, and every
criterion is either mechanically evidenced (test run or CI check) or carries a recorded
human sign-off (a task/PR comment authored by the human approving that criterion). A manual
DoD criterion with neither stops the pipeline for a live human, regardless of config;
PR-body checkboxes are display only and never count as sign-off. Unattended retro never writes
rules; promotions accumulate as proposals for a human retro pass.

Safeguards (all config-backed): `work_in_progress_limit` stops claims when the review queue
is full (review capacity is the throttle); `max_fix_attempts` sends a stuck task to `Blocked`
with a diagnostic comment instead of iterating forever; `max_tasks_per_run` caps milestone
and no-target queue runs. A task-id run always has an implicit cap of one.

Note which safeguard belongs to which mode: the WIP limit is `/loop /dev:execute`'s
throttle, because that mode parks every task at `In Review` until a human drains the queue.
`dev:auto` cannot trip it through its own activity - single-flight means at most one task
is `In Progress`/`In Review` at a time - but the check lives in the shared claim step, so
`auto` still refuses to start if a previous loop left the queue at the limit.

Unattended runs stall on the first permission prompt: pre-approve git, `gh`, and the
`test_command` in `.claude/settings.json` before starting a loop.

## Parallel operation

What is safe to run simultaneously, and why:

- **Parallel `dev:execute` sessions on independent tasks** - the supported way to
  parallelize implementation (one interactive session per task).
  The tracker claim step is the mutex; worktrees isolate the filesystem. There is no
  intra-session fan-out: a `/loop` orchestrator runs ONE implementation subagent at a time,
  deliberately.
- **Parallel reviews** - safe; reviews are stateless reads, and PRs simultaneously
  `In Review` are dependency-free by construction (dependencies unblock at `Done`, so a
  dependent can never have an open PR alongside its dependency's).
- **Parallel `dev:verify`** - evidence gathering is safe in parallel; the merges themselves
  serialize, and sibling PRs that branched before an earlier merge may need a rebase (a
  rebase that resolves real conflicts in reviewed hunks warrants a re-review).
- **`dev:auto`** - single-flight by design; run one at a time.

The rule that makes all of this safe: no skill ever checks out a task branch in the main
working copy. Branch-file operations (tests, reading beyond the diff) happen in that task's
worktree; the main checkout's HEAD only moves at merge time.

## Primary GitHub fork contributions

Fork support is opt-in and applies only to a GitHub primary tracker:

```yaml
tracker: github
github_primary_repo: owner/canonical-repo
fork_contributions: true
```

Do not use `github_repo` here. That field remains the secondary GitHub intake repository for
projects whose primary tracker is Linear, local, or custom.

The resolver separates three destinations: canonical issues and PRs live in
`github_primary_repo`, branches start from `upstream/main`, and contributor branches push to
`origin`. `origin` must be a GitHub fork whose parent is the configured canonical repository;
`upstream` must resolve to that canonical repository. A canonical clone uses its existing
same-repository behavior and does not require `upstream`. Every GitHub operation names the
canonical repository explicitly, so the current working directory cannot redirect a call to
the fork.

Authority is a separate check. `ADMIN`, `MAINTAIN`, or `WRITE` on the canonical repository
allows maintainer queue and terminal operations. Read-only contributors get the external path:
no assignment, queue label, milestone, dependency gate, WIP accounting, terminal issue mutation,
or merge. The canonical issue, cross-repository PR, structured review, and SHA-bound verification
report form the audit trail. A maintainer working from a fork keeps the same upstream/origin/
canonical destinations but retains maintainer authority.

For a maintainer, an explicit numeric primary-GitHub task id is planned queue work. It must have
exactly `status:todo` before claim; a missing, duplicate, or different `status:*` label is an
error, not an implicit external-contribution route. Use `dev:execute external #N` to select the
external path explicitly. Planned-task claim, green handoff, and blocked writes run through the
bundled verified lifecycle command, which targets the canonical repository, performs each label
change, then re-reads and rejects any result that does not contain exactly the expected status.
The execute work summary records `Queue classification: planned | external | secondary`, so
review and verify do not reclassify a planned task from a damaged label. Neither skill repairs
execute-owned `In Progress`, `In Review`, or `Blocked` state.

| Skill | Fork-mode behavior |
|---|---|
| `dev:setup` | Writes and validates the opt-in fields only after a project-owner choice; local files are separate from maintainer-owned labels, milestones, Actions policy, secrets, and rulesets. |
| `dev:discover` | Unchanged local PRD authoring; no tracker or GitHub mutation. |
| `dev:architect` | Unchanged local spec, roadmap, ADR, and context-file authoring; no tracker or GitHub mutation. |
| `dev:plan` | Produces the full local dry run; a read-only contributor stops before pushing packets or queue metadata and hands the approved plan to a maintainer. |
| `dev:backlog` | Read-only `add` creates a packet-complete canonical contribution issue with no queue metadata; triage, promotion, reprioritization, split, and `Wont Do` remain maintainer-only. |
| `dev:execute` | Planned maintainer tasks require verified `status:todo → status:in-progress → status:in-review` or `status:blocked` writes. External work rejects incomplete intake or an active linked PR unless explicitly overridden, branches from `upstream/main`, pushes to `origin`, and opens the canonical cross-repository PR without queue transitions. |
| `dev:review-pr` | Reviews and comments on the canonical PR and issue; fixes push to `origin`; the structured review remains bound to the reviewed HEAD SHA. |
| `dev:verify` | A read-only contributor posts complete SHA-bound evidence and stops at `ready for maintainer decision`; a maintainer reuses current evidence, rechecks gates, then merges and cleans up canonical state. |
| `dev:status` | Reads the canonical repository and lists external contributions separately from planned queue progress, WIP, and next-task selection. |
| `dev:auto` | Refuses external contribution work without upstream write permission because it cannot cross the maintainer merge boundary. |
| `dev:retro` | Reads and comments on canonical artifacts; promotions are local fork-PR changes and retro gains no merge or terminal authority. |

The exact validation, repair commands, and command-targeting contract are in
[runtime_contracts/tracker.md](runtime_contracts/tracker.md#github-repository-resolution).

## Secondary intake channel (GitHub-native work)

When your primary tracker is Linear (or local) but the project still gets GitHub issues and
drive-by PRs that are isolated - not part of a milestone, not in the backlog - forcing each
into the primary tracker recreates dual state and pollutes its metrics. Set
`secondary_intake: github` + `github_repo: owner/repo` in `.agent-toolkit/dev.md` to accept them as a
second channel. Every incoming GitHub issue or PR gets exactly one fate:

```
Incoming GitHub issue or PR
│
├─ Needs design / touches the spec / belongs to a milestone / blocks tracked work?
│     → dev:backlog #N  →  PROMOTE: full primary-tracker packet, issue linked and
│                            closed as transferred. Only here do discover/architect/plan apply.
│
├─ Isolated and self-contained (typo, drive-by bug, external-contributor PR)?
│     → WORK IN PLACE. GitHub owns the item; no primary ticket.
│        dev:execute #N     claim (self-assign) → worktree → PR (Closes #N) → CI → In place
│        dev:review-pr #PR   review against the issue's acceptance criteria + spec
│        dev:verify #PR      CI + approving review → merge; issue auto-closes. No primary write.
│     A pure drive-by PR with no issue: skip execute; dev:review-pr <pr> then dev:verify <pr>.
│
└─ Not worth doing?
      → dev:backlog #N  →  DECLINE: Wont Do, issue closed with rationale.
```

Routing is by argument shape: `#N` hits the GitHub channel, a primary key (`NOVA-123`) the
primary tracker. An argument-less `dev:execute` (or `next-task`) only ever pulls from the
primary queue, so in-place items never jump ahead of planned work. In-place items skip the
`status:*` label lifecycle entirely - their state is just open → PR → review → merged. The
merged PR plus its review and verify report is the audit trail (`audit_trail: link`); no
primary-tracker row is ever created for in-place work. Full contract: runtime_contracts/tracker.md "Secondary
intake channel".

## Working without a GitHub remote

Local-only projects degrade gracefully: `dev:execute` records a branch instead of a PR and
the `test_command` run stands in for CI; `dev:review-pr` reviews
`git diff main...task/<id>-<slug>` and posts the review as a task comment; `dev:verify`
merges locally per policy and deletes the branch.

**Packet visibility with `tracker: local`.** Task packets are repo files under `.dev/tasks/`,
so a packet's state travels with the branch that edits it. `dev:execute` flips a task's
`status` (to `in-review`) and appends the work-summary on the **task branch**, not on `main`.
Until the task merges, those updates are invisible from `main`: `dev:status` run on `main`
will show the task at its pre-execute status (e.g. `in-progress`), while the same packet in the
task's worktree shows `in-review` with the work-summary. To see current in-flight state,
run `dev:status` from the task worktree, or read the packet on the branch. State becomes
visible on `main` when `dev:verify` merges. This is inherent to storing packets in-repo;
the Linear and GitHub backends do not have it, since their packets live outside the repo.

## Known platform constraints

- **No self-approval on GitHub.** GitHub rejects `APPROVE`/`REQUEST_CHANGES` review types on
  the author's own PR, and the reviewer agent inherits the session's `gh` auth, so solo repos
  never get a formal `APPROVED` state. The `Verdict:` line in the structured review body is
  the verdict of record; `dev:verify` accepts it.
- **Filtered `gh issue list` is eventually consistent.** `--milestone`/`--label`/`--search`
  route through GitHub's search API; a just-created issue can be missing from the result.
  Skills use the REST issues endpoint for reads that must be current (see runtime_contracts/tracker.md).
- **Unfiltered Linear `list_issues` can omit issues.** An issue absent from an unfiltered
  listing can still be returned by a `state`-filtered query. Skills query per state and
  confirm specific issues with `get_issue` (see runtime_contracts/tracker.md).

## Project layout

```
project/
├── AGENTS.md              # project-owned context file; carries the @.agent-toolkit/dev.md reference line
├── CLAUDE.md              # Claude Code entry: @AGENTS.md import (or itself the context file on Claude-only projects)
├── research/raw/          # human research dumps consumed by dev:discover
├── docs/
│   ├── PRD.md             # dev:discover output
│   ├── SPEC.md            # dev:architect output
│   ├── ROADMAP.md         # milestones with outcomes
│   └── adr/               # decision records (spikes, architecture choices)
├── .agent-toolkit/
│   ├── dev.md             # plugin config + conventions + architecture pointer + rule imports (committed)
│   ├── dev.local.md       # personal overrides (gitignored)
│   └── rules/             # promoted retro learnings, one file per rule
└── .dev/tasks/            # only with tracker: local
```

## Adopting into an existing project

Greenfield adoption is `dev:setup` and go. This section covers everything else: partial
adoption, existing codebases, existing backlogs, trackers this plugin does not ship a
backend for, and memory systems beyond plain files.

The one architectural fact that makes all of this possible: **the tracker is the only shared
state between skills.** Docs (`docs/PRD.md`, `docs/SPEC.md`) carry intent, the tracker
carries task state, and every skill reads both fresh each run. There is no pipeline state,
so any subset of skills works alone.

### Incremental adoption paths

| You want | Adopt | Skip | Notes |
|---|---|---|---|
| Only the execution loop | `setup`, `execute`, `review-pr`, `verify` | `discover`, `architect`, `plan` | Your existing backlog feeds `execute` directly. Tickets must survive packet validation (Objective + DoD); `execute` drafts missing fields from whatever docs exist and asks. The thinner your docs, the more it asks. |
| Planning discipline, own review process | `setup`, `plan`, `backlog`, `execute` | `review-pr`, `verify` | You lose the `Done`-means-verified guarantee. Decide who sets `Done` and record it in `.agent-toolkit/dev.md` body, or `In Review` tasks pile up forever. |
| Product docs only | `discover`, `architect` | everything tracker-side | PRD/SPEC/ADRs are useful standalone. `tracker: local` in config satisfies setup without adopting task flow. |
| Everything | all | - | Run `setup` in brownfield mode first; see below. |

Rules of thumb: `verify` without `review-pr` is fine (evidence still gathered); `review-pr`
without `verify` means merges go unguarded - a human must own the merge decision. `retro`
works with any subset that produces PR/tracker evidence.

### Brownfield setup and architecture archaeology

`dev:setup` detects an existing codebase and offers archaeology: reverse-engineering the
**current** state into `docs/SPEC.md` (components, interfaces, data flow, known debt marked
as debt). Do not skip it if you plan to use `dev:plan` - packets against undocumented code
force the planner to guess, and guessed spec excerpts are worse than none.

Order for a full brownfield onboarding:

1. `dev:setup` - config, scaffold, archaeology into a current-state SPEC.
2. `dev:discover` - only if product intent is fuzzy or undocumented; else write a minimal
   PRD by hand (problem, customer, north star, non-goals) so triage has an anchor.
3. `dev:architect` - forward-looking spec sections on top of the current-state spec; the
   spec must say what is kept, replaced, and debt.
4. Import the backlog (next section), then `dev:plan` for new milestone work.

### Importing existing docs and backlogs

**Docs:** map what exists into the layout: product intent → `docs/PRD.md`, technical design
→ `docs/SPEC.md`, decisions → `docs/adr/`, raw research → `research/raw/`. Import is a copy
plus an honesty pass: mark stale sections rather than silently keeping them.

**Backlogs:** import tickets into the configured tracker at `Backlog` status, then run
`dev:backlog triage` - it re-checks every imported item against the current docs and flags
stale ones for `Wont Do`. Do not import straight to `Todo`; committed status should survive
a triage, not a copy-paste.

**Migrating from agentic_development_workflow (ADW):**

- Finish in-flight ADW milestones with ADW; switch at a milestone boundary.
- `workflow/spec/SPEC.md` → `docs/SPEC.md` (drop HANDOFF.md; packets replace it).
- `workflow/decisions/DR-*.md` → `docs/adr/` (renumber, keep statuses).
- `workflow/plan/PLAN.md` unfinished tasks → tracker `Backlog` via `dev:backlog` intake, so
  each gets a real packet; do NOT bulk-copy checkbox lines.
- `workflow/plan/reviews/task-*.md` and `RETRO-*.md` → keep as history in `research/raw/` if
  useful; run `dev:retro` conventions going forward. PROGRESS.md dies; the tracker is the
  progress.

### Third-party trackers (`tracker: custom`)

The plugin ships Linear, GitHub Issues, and local-file backends. Anything else follows the
"Adding a backend" recipe at the end of [runtime_contracts/tracker.md](runtime_contracts/tracker.md): map the seven verbs and the
status lifecycle, write both tables into the `.agent-toolkit/dev.md` body, set `tracker: custom`.
Skills read that file before every tracker call; the body mapping is the implementation.

#### Worked example: Jira via the Atlassian MCP server

> **Not verified.** Only the shipped Linear, GitHub Issues, and local-file backends are
> tested. This Jira/Atlassian mapping is an illustrative template that has never been run
> end to end - tool names and transitions are best-guess. Verify every verb by hand (see the
> lifecycle check below) before any unattended use.

Connect the official Atlassian Remote MCP server, then discover exact tool names from the
runtime tool list (they change; typical names shown). `.agent-toolkit/dev.md` body:

```markdown
## Tracker mapping (Jira)

| Verb | Implementation |
|---|---|
| next-task | search issues via JQL: project=<KEY> AND status="To Do" AND fixVersion=<milestone>, then apply the selection algorithm from tracker.md |
| get-task <id> | get issue (fields + comments + issue links) |
| claim <id> | assign self + transition to "In Progress"; re-read to confirm assignee |
| comment | add comment to issue |
| transition | get available transitions for the issue, then apply the matching one |
| create-task | create issue (type Task; spikes as type Spike or label `spike`) |
| list <milestone> | JQL: project=<KEY> AND fixVersion=<milestone> |

| Lifecycle status | Jira status |
|---|---|
| Backlog | Backlog |
| Todo | To Do / Selected for Development |
| In Progress | In Progress |
| In Review | In Review (add to workflow if missing - human decision) |
| Done | Done |
| Blocked | flag "Impediment" or label `blocked` + diagnostic comment (keep workflow status) |
| Wont Do | Done with resolution "Won't Do", rationale comment first |

Dependencies: issue links "is blocked by". Priority: Jira priority. Estimate: story points
(rough hours in description). Milestone: fixVersion (or sprint - pick one, record it here).
```

Verify by hand before unattended use: create, claim, transition through the full lifecycle,
comment. The same shape covers Asana, Shortcut, Notion databases, etc.

### Third-party memory systems (`memory_target`)

The plugin's only memory integration point is `dev:retro`'s promotion step. Default
(`memory_target: files`, or field absent): learnings become `<rules_dir>/<slug>.md` files
(default `.agent-toolkit/rules/`), each registered as an import line in
`.agent-toolkit/dev.md` and reached by every session through the context file's single
reference line - git-shared, zero latency.

Teams already running a memory system set `memory_target` in `.agent-toolkit/dev.md` frontmatter
and retro stores learnings through that system's MCP tools instead:

| `memory_target` | System | Storage | Recall path | Tradeoff vs files |
|---|---|---|---|---|
| `files` (default) | plain markdown | `rules_dir` (default `.agent-toolkit/rules/`) | task-scoped lifecycle skills run the deterministic project bootstrap against the execution repository; harness import expansion is optional | in git, zero latency, project-scoped only |
| `mem0` | Mem0 managed API | Mem0 cloud | Mem0 plugin injection / MCP search | cross-tool + cross-machine; data off-machine; managed service |
| `openbrain` | OB1 / OpenBrain | self-owned Supabase pgvector | MCP search from any connected tool | cross-tool, self-owned; setup cost, query latency |
| `memsearch` | MemSearch (Zilliz) | local markdown + Milvus shadow index | hook-injected semantic matches per prompt | local + cross-CLI-tool; machine-local only |

> **Not verified.** Only `files` is exercised by this plugin's tests. The `mem0`/`openbrain`/
> `memsearch` rows describe the *intended* integration - `dev:retro` emits a generic "store
> this via that system's MCP tool" instruction - but no config ships bundled and none has been
> run end to end. Adopt at your own risk: wire up the MCP server yourself and confirm a real
> promotion lands through it before relying on it.

Two rules regardless of target:

1. **Correctness-gating rules always also go to the `rules_dir` files.** Files are the only
   target every future session is guaranteed to load; semantic recall is probabilistic, and
   a rule that must never be missed cannot depend on it.
2. Recall is the memory system's job, not the plugin's: rely on that system's own hooks or
   MCP injection at session start. The plugin only writes.
