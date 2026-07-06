# dev Plugin Design

AI-assisted product development lifecycle for Claude Code. Replaces
[agentic_development_workflow](https://github.com/wilsonkichoi/agentic_development_workflow) (ADW).
This document is the implementation plan; delete or archive it once the plugin is built and dogfooded.

## Why ADW is being replaced

Diagnosis from building novascan with ADW:

1. **Task state lived in markdown the LLM had to keep consistent.** PLAN.md checkboxes,
   PROGRESS.md statuses, and review files were three copies of the same state, synced by hand
   by the model. Executing agents forgot the task list existed or skipped the spec because the
   state was buried in files they were never forced to read. Markdown state also cannot scale
   past one developer.
2. **Skills were procedure monoliths.** `execute` (274 lines) and `auto` (285 lines) spent most
   of their context on branch choreography (task branch, feature branch, fix branch, worktree
   tracking branch cleanup). The procedure competed with the actual task for attention; agents
   dropped whichever half did not fit.
3. **The review loop reinvented pull requests.** `wave-mM-N.md` review files with append-only
   sections replicated what PR review comments and CI checks do natively.
4. **Retros went nowhere.** RETRO-*.md files accumulated but nothing promoted learnings into
   CLAUDE.md or rules, so every new session re-lost the big picture.

## Design principles

1. **The tracker is the single source of truth for task state.** Skills query and update it;
   no skill maintains a parallel status file. Ever.
2. **Self-contained task packets.** Every task must be executable by a fresh agent given only
   the task content plus the doc sections it links to. This is the primary defense against
   context rot: agents do not need to remember the big picture if the packet carries the
   relevant slice of it.
3. **PR-native quality loop.** PR + CI + PR review comments are the review medium. No custom
   review file format. The work-summary that ADW put in `task-X.Y.md` becomes a comment on the
   issue/PR.
4. **Small skills, one job each.** Composable and individually invocable. No monolithic auto
   pipeline; unattended looping is achieved by running `/dev:execute` repeatedly (e.g. via
   `/loop`), because the tracker makes each iteration stateless.
5. **Lean project CLAUDE.md that links out.** Product docs, spec, ADRs live in `docs/`;
   CLAUDE.md stays under ~200 lines and points to them.
6. **Closed memory loop.** "Memory loop" means: execution produces evidence (PR review
   threads, CI history, work-summary comments) → `dev:retro` distills learnings from that
   evidence → learnings are promoted into `.claude/rules/` or project CLAUDE.md → every future
   session loads them automatically at start. The loop is closed because the output of one
   cycle changes the standing instructions of the next. ADW's RETRO-*.md files were an open
   loop: nothing ever read them again.

## Tracker adapter

One interface, three backends. The interface is a markdown contract at
`${CLAUDE_PLUGIN_ROOT}/docs/tracker.md`; every skill that touches tasks reads it and the
project's configured backend.

**Verbs:** `next-task` (highest-priority unblocked task in the active milestone),
`get-task <id>`, `claim <id>` (status → In Progress, assign self), `comment <id> <body>`,
`transition <id> <status>`, `create-task <packet>`, `list <milestone>`.

**Status lifecycle:** `Backlog → Todo → In Progress → In Review → Done` (+ `Blocked`,
`Wont Do`). `Backlog` means captured but not committed: intake items from `dev:backlog` and
manual tickets land here. `Todo` means committed: `dev:plan` creates approved milestone tasks
directly at `Todo`, and `Backlog → Todo` promotion is otherwise an explicit human decision,
made in the tracker UI or by asking `dev:backlog` to pull a task into the current milestone
(which also checks dependencies and spec impact). It is never automatic. `dev:execute` claims
only from `Todo`; `In Review` is set by `dev:execute` when the PR is up and CI is green;
`Done` is set only by `dev:verify` after DoD verification and merge; `Wont Do` is set by
`dev:backlog` with a comment recording why, so the decision survives.

**Backends:**

| Backend | Mechanism | Notes |
|---|---|---|
| Linear | Official Linear MCP server (`mcp.linear.app`) | Native priorities, estimates, blocked-by relations, cycles. Preferred for multi-dev. Config stores team + project IDs. |
| GitHub Issues | `gh` CLI | Status via labels (`status:todo` etc.) or Projects v2; dependencies as `Blocked by #N` lines in the body; PR links issues natively (`Closes #N`). |
| Local | `.dev/tasks/T-NNN-slug.md`, one file per task, YAML frontmatter (`id`, `status`, `deps`, `estimate`, `type`) | Offline fallback. One file per task (not one big PLAN.md) so a single task is a single read and a single write. |

**Project config:** `.claude/dev.md` (committed, team-shared). All structured fields live in
YAML frontmatter: backend choice, Linear team/project IDs or repo labels, test command, CI
workflow name, merge policy (merge commit / squash), whether the review Action is installed.
The markdown body is for free-text conventions the fields cannot capture. Frontmatter is YAML,
so skills parse it mechanically; the `.md` wrapper follows the Claude Code
`.claude/<plugin>.md` settings convention and leaves room for human notes.
`.claude/dev.local.md` (gitignored) for personal overrides. Written by `dev:setup`.

```markdown
---
tracker: linear            # linear | github | local | custom
linear_team: NOVA
linear_project: novascan-v2
test_command: "cd backend && uv run pytest"
ci_workflow: ci.yml
merge_policy: squash
review_action: true
wip_limit: 3
max_fix_attempts: 3
---
Free-text conventions, e.g. "all API changes need a migration note in the PR body".
```

## Task packet schema

What `dev:plan` must produce for every task, regardless of backend:

- **Title** and **Type**: `task` or `spike`.
- **Objective**: what exists when this is done (1-3 sentences).
- **Why**: the problem it solves, linking to the PRD/SPEC section that motivates it.
- **Definition of Done**: checkable criteria, each phrased so `dev:verify` can gather evidence
  (a test command, a CI check name, or an explicit manual verification step).
- **Dependencies**: task IDs that must be Done first.
- **Estimate**: S/M/L plus rough hours.
- **Spec references**: links to `docs/SPEC.md#section` etc., with the load-bearing excerpt
  inlined in the packet so the executor cannot skip it.
- **Suggested steps**: 3-8 bullets, advisory not binding.

**Manually created tasks.** Humans adding tickets directly in the tracker (Linear UI, `gh issue
create`, a new file in `.dev/tasks/`) is a supported entry point; the tracker is the SSOT for
task state, so no sync step exists or is needed. The safeguard is at claim time: `dev:execute`
validates the packet before implementing. If objective or DoD is missing, it does not guess -
it drafts the missing fields from `docs/PRD.md`/`docs/SPEC.md`, posts them to the ticket for
human confirmation, and (in unattended mode) skips to the next valid task with a comment
explaining why. Semantic conflicts between a manual ticket and the spec (docs are the SSOT for
intent; the tracker only for state) are `dev:backlog` triage's job, run on demand.

**Spikes** additionally carry: the question to answer, a timebox, and the required output
(an ADR in `docs/adr/` plus a tracker comment with the recommendation). Spikes produce
knowledge, not merged code; their branches are throwaway.

## Project layout for consuming projects

```
project/
├── CLAUDE.md              # lean; links to docs/; updated by dev:architect and dev:retro
├── research/raw/          # human research dumps: pdf, md, images, exports (step 2)
├── docs/
│   ├── PRD.md             # dev:discover output: goal, why, customer value, north star, non-goals
│   ├── SPEC.md            # dev:architect output: architecture, contracts, NFRs, negative reqs
│   ├── ROADMAP.md         # milestones with outcomes
│   └── adr/               # decision records (spike outputs, architecture choices)
├── .claude/
│   ├── dev.md             # plugin config (committed)
│   └── rules/             # promoted retro learnings
└── .dev/tasks/            # only when local tracker backend is used
```

Heavy research synthesis can use `utils:llm-wiki` (raw/ + wiki/ pattern); `dev:discover`
consumes either raw files or an existing wiki. Do not duplicate wiki functionality here.

## Skills

| Skill | Lifecycle step | Job |
|---|---|---|
| `dev:setup` | 1-2 | Scaffold layout, choose tracker backend, write `.claude/dev.md`, seed lean CLAUDE.md, optionally install the review GitHub Action and CI workflow. |
| `dev:discover` | 3 | Ingest `research/raw/`, interview the user (AskUserQuestion loops) to close gaps, produce `docs/PRD.md`. Business clarity only, no tech design. Human gate: PRD review. |
| `dev:architect` | 4 | PRD → `docs/SPEC.md` (architecture, contracts, NFRs, negative requirements, Mermaid diagrams), `docs/ROADMAP.md` (milestones), ADRs for contested choices. Human gate: spec review. |
| `dev:plan` | 5 | Milestone → task packets. Creates spikes for genuine unknowns. Dry-run: present the full packet list for human approval, then push to the tracker via the adapter. |
| `dev:backlog` | ongoing | Mid-flight change management. Intake new requests and priority changes at any point: triage each request, then route it. Backlog-only change → create/re-prioritize/split tasks in the tracker. Spec-impacting → run a `dev:architect` delta (SPEC/ROADMAP update + ADR) before touching tasks. Goal-impacting → `dev:discover` delta (PRD update) first. Also the preferred way to add one-off tickets (it writes a full, immediately executable packet, unlike a hand-written ticket), to promote `Backlog → Todo`, and to close tasks as `Wont Do` with rationale. This is how the product recalibrates without re-running the whole pipeline. |
| `dev:execute` | 6 | The core loop, one task per session. Claim next unblocked task (or a given ID) → worktree + branch → implement per packet → tests → push → PR linking the task → watch CI (`gh run watch`), fix failures → post work-summary comment (what/decisions/obstacles/spec gaps) on the issue → transition to In Review → **stop; never merges**. |
| `dev:review-pr` | 6 | Fresh-session reviewer. Fetches PR diff + CI results + linked task packet; checks DoD compliance, spec compliance, code quality; posts a structured PR review via `gh` with verdict (approve / request changes). Also invocable as the fix loop: read review comments, apply fixes, push. |
| `dev:verify` | 7 | Merge gate. For each DoD criterion, gather evidence (run the test, cite the CI check, or walk the manual step) and post a verification report to the PR. On human approval: merge per policy, transition task to Done, clean up worktree/branch. |
| `dev:retro` | 8 | Per task or milestone. Sources: PR review threads, CI history, tracker comments (the work-summary comment is the primary input), and local session transcripts under `~/.claude/projects/` when available. Output: retro comment on the tracker + **promotion step**: propose concrete additions to `.claude/rules/` or CLAUDE.md, apply on approval. |
| `dev:status` | glue | One screen: milestone progress from the tracker, open PRs and their CI state, next available tasks. |

**Test separation** (kept from ADW, it worked): inside `dev:execute`, tests for non-trivial tasks
are written by the `dev:test-writer` agent, which receives only the task packet, spec excerpt,
and public interface, never the implementation diff.

## Agents

Three, not thirteen. ADW's role agents were mostly flavor text; the packet carries the context
that matters.

- `dev:reviewer` - used by `dev:review-pr`; spec-compliance and correctness focus.
- `dev:test-writer` - contract-only context, used by `dev:execute` for test separation.
- `dev:planner` - used by `dev:plan` to draft packets from the spec (optional; may fold into the skill).

## Automatic PR review (GitHub Action)

`dev:setup` optionally writes `.github/workflows/claude-review.yml` using
`anthropics/claude-code-action`, triggered via `workflow_run` after the CI workflow succeeds,
with a prompt that fetches the linked task packet and applies the same rubric as
`dev:review-pr`. Requires `ANTHROPIC_API_KEY` (or OAuth token) in repo secrets. The manual
skill is the default path; the Action is opt-in for repos that want review-on-green with no
human trigger.

## Unattended operation

No `auto` skill in v1, deliberately: ADW's `auto` existed to shuttle state between steps, and
the tracker now does that. Each `/dev:execute` run is stateless (claim → execute → PR → stop), so
unattended batches are `/loop /dev:execute` or several parallel sessions on different unblocked
tasks; the tracker's claim step prevents collisions. Waves are gone: dependency edges +
priority ordering in the tracker replace wave grouping, and parallelism falls out of "any
unblocked task can be claimed". If a dedicated orchestrator proves necessary after dogfooding,
add it as `dev:auto` in v2; the statuses and adapter verbs are already sufficient for it.

Unattended batches over a large `Todo` list have three failure modes, and `dev:execute` must
carry safeguards for all of them:

1. **Context accumulation.** `/loop` iterates in one session, so naive looping stacks every
   task's diffs and CI logs into one window until compaction corrupts the current task. In
   loop/batch mode, `dev:execute` keeps the session as a thin orchestrator and delegates the
   implementation to a background subagent inside the task's worktree; the main window carries
   only claim/PR/status traffic. The alternative for true fresh context per task is a shell
   loop of headless sessions (`claude -p "/dev:execute"`), documented in the adoption guide.
2. **Runaway spend on a stuck task.** A CI loop that never goes green must not iterate
   forever: after `max_fix_attempts` (config, default 3) CI-fix cycles, mark the task
   `Blocked`, post a diagnostic comment (attempts, failure modes, hypothesis), and move on.
3. **Unbounded WIP.** Human gates cannot be skipped (`dev:execute` never merges; `Done` only
   via `dev:verify`), so the failure mode is a pile of unreviewed PRs that conflict because
   later tasks branched from a `main` missing earlier unmerged work. `dev:execute` refuses to
   claim when `wip_limit` (config, default 3) tasks are already `In Review`; the loop idles
   until review/verify drains the queue. Review capacity is the throttle.

Config fields `max_fix_attempts` and `wip_limit` live in `.claude/dev.md` frontmatter.
`dev:setup` must also remind that unattended runs need pre-approved permissions, or the loop
stalls on the first prompt.

## Dropped from ADW, and why

- **PLAN.md / PROGRESS.md / review files** - replaced by tracker + PR comments.
- **Waves and feature branches per wave** - replaced by dependency edges; task branches PR
  straight to main behind CI.
- **13 role agents** - replaced by 3 agents + packet context.
- **`auto` pipeline** - replaced by stateless `dev:execute` + `/loop` (see above).
- **Multi-CLI support (Copilot/Gemini)** - Claude Code only, per decision; frees the design to
  use hooks, subagents, worktrees, and MCP.
- **Cost-arbitrage guidance** - out of scope for the plugin.

## Brownfield adoption

Greenfield is the easy case; the plugin must adopt cleanly into existing projects. Deliverable:
a comprehensive guide at `plugins/dev/docs/adoption.md` covering:

1. **Incremental adoption.** Skills are independently adoptable because the tracker is the only
   shared state. An existing project can start with just `dev:execute` + `dev:review-pr` +
   `dev:verify` against its existing backlog and never run `dev:discover`/`dev:architect`.
   The guide maps common entry points: "I only want the execution loop", "I want planning but
   have my own review process", "full lifecycle".
2. **Architecture archaeology.** `dev:setup` in brownfield mode detects an existing codebase
   and offers to reverse-engineer the current state into `docs/SPEC.md` (current architecture,
   contracts, known debt) before any forward-looking roadmap is written. `dev:plan` needs an
   accurate current-state spec to write honest packets against existing code.
3. **Existing docs and backlog import.** Map whatever exists (old PLAN.md, Notion docs, an ADW
   `workflow/` tree) into `docs/` and the tracker. For ADW projects specifically (novascan):
   finish in-flight milestones on ADW, then adopt at the next milestone boundary via
   `dev:setup` brownfield mode + `dev:plan` against the existing SPEC.md.
4. **Third-party trackers (not implemented here, documented).** The tracker contract
   (`docs/tracker.md`) ends with an "Adding a backend" recipe: map the seven verbs to the
   tool's MCP tools or CLI, provide a status-mapping table, set `tracker: custom` plus the
   mapping in `.claude/dev.md` frontmatter. Worked example in the guide: Jira via the official
   Atlassian MCP server (verb → tool mapping, status mapping to a Jira workflow). The same
   recipe covers Asana, Shortcut, etc.
5. **Third-party memory systems (not implemented here, documented).** `dev:retro`'s promotion
   step is the single memory integration point; the default target is files
   (`.claude/rules/`, CLAUDE.md). Teams already on Mem0, OpenBrain/OB1, or MemSearch point the
   promotion step at their memory MCP tool instead (config field `memory_target`), and rely on
   that system's own injection/recall for session start. The guide documents the tradeoff:
   file-based is git-shared and zero-latency; MCP-based memory is cross-tool and cross-machine.

## Build order

Hard core first. Each phase ends with a version bump and the repo pre-commit checklist
(plugin.json, marketplace.json, plugin README, root README).

1. **Phase A - tracker adapter + execution loop** (the part that failed in ADW):
   `docs/tracker.md` contract (including the "Adding a backend" recipe), `dev:setup`
   (greenfield + brownfield modes), `dev:plan`, `dev:execute`, `dev:test-writer`.
   Remove `skills/placeholder/`.
2. **Phase B - quality loop + backlog:** `dev:review-pr`, `dev:reviewer`, `dev:verify`,
   `dev:backlog`, Action installer in `dev:setup`.
3. **Phase C - upstream phases:** `dev:discover`, `dev:architect`.
4. **Phase D - memory loop + glue:** `dev:retro`, `dev:status`, `docs/adoption.md` (the
   brownfield guide; written last because it documents the full skill set).
5. **Phase E - dogfood everything:** all end-to-end testing, batched after authoring
   completes, so one dogfood project exercises the full lifecycle in order (setup → discover
   → architect → plan → execute → review → verify → backlog → retro) instead of testing
   fragments per phase. Accepted risk of batching: a defect found here in a foundation piece
   (tracker contract, packet schema) ripples fixes back through already-authored skills;
   accepted because skills are prose contracts, cheap to revise, and a full-lifecycle test is
   a more honest signal than per-phase fragments.

## Task checklist

Cross-session progress tracker for building this plugin. Update checkboxes as work lands; any
session can resume from here. (Yes, this is markdown task state - the bootstrap exception:
single doc, single dev, and the plugin's own tracker does not exist yet. Once Phase A ships,
consider eating our own dogfood and moving remaining phases into it.)

### Phase A - tracker adapter + execution loop

- [x] `docs/tracker.md`: seven verbs, status lifecycle, backend mappings (Linear MCP, GitHub
      `gh`, local `.dev/tasks/`), "Adding a backend" recipe
- [x] `skills/setup/SKILL.md`: greenfield scaffold, brownfield mode (architecture
      archaeology), tracker selection, write `.claude/dev.md`, permissions reminder for
      unattended runs
- [x] `skills/plan/SKILL.md`: milestone → task packets per schema, spike creation, dry-run
      human gate, push via adapter
- [x] `skills/execute/SKILL.md`: claim from Todo only, packet validation (draft missing
      DoD/objective, skip in unattended mode), worktree + branch, implement, PR linking task,
      CI watch with `max_fix_attempts` → Blocked, work-summary comment, transition In Review,
      `wip_limit` refusal, loop mode via background subagent, never merges
- [x] `agents/test-writer.md`: contract-only context (packet + spec excerpt + public
      interface, no implementation diff)
- [x] Remove `skills/placeholder/`
- [x] Release: pre-commit checklist (plugin.json + marketplace.json versions, plugin README,
      root README)

### Phase B - quality loop + backlog

- [x] `skills/review-pr/SKILL.md`: PR diff + CI + packet → structured review with verdict;
      fix-loop mode (read review comments, apply, push)
- [x] `agents/reviewer.md`: spec-compliance and correctness focus
- [x] `skills/verify/SKILL.md`: per-DoD-criterion evidence report on PR, human merge gate,
      merge per policy, transition Done, cleanup worktree/branch
- [x] `skills/backlog/SKILL.md`: intake (one-off tickets get full packets), triage routing
      (backlog-only / spec delta / goal delta), Backlog → Todo promotion, Wont Do with
      rationale
- [x] Action installer in `dev:setup`: `.github/workflows/claude-review.yml` via
      `anthropics/claude-code-action` on `workflow_run`
- [x] Release: pre-commit checklist

### Phase C - upstream phases

- [ ] `skills/discover/SKILL.md`: ingest `research/raw/` (or existing wiki), user interview
      loop, produce `docs/PRD.md`; human gate
- [ ] `skills/architect/SKILL.md`: PRD → SPEC.md + ROADMAP.md + ADRs, Mermaid diagrams,
      CLAUDE.md update; human gate
- [ ] Release: pre-commit checklist

### Phase D - memory loop + glue

- [ ] `skills/retro/SKILL.md`: mine PR threads, CI history, tracker comments, session
      transcripts; retro comment on tracker; promotion step to `.claude/rules/` / CLAUDE.md;
      `memory_target` config for third-party memory (Mem0, OB1, MemSearch)
- [ ] `skills/status/SKILL.md`: milestone progress, open PRs + CI state, next available tasks
- [ ] `docs/adoption.md`: incremental adoption paths, brownfield archaeology, ADW migration,
      Jira worked example, third-party memory tradeoffs
- [ ] Release: pre-commit checklist

### Phase E - dogfood everything

One dogfood project driven through the full lifecycle, then backend and brownfield variants.
Fix defects as found; re-run the affected flow before ticking the box.

- [ ] Full lifecycle on a toy project, local backend: `setup` (greenfield) → `discover`
      (research dumped in `research/raw/`; PRD answers goal/why/value/north star) →
      `architect` (SPEC + ROADMAP sufficient for planning without gap-guessing) → `plan` →
      `execute` → `review-pr` → `verify` → `status`
- [ ] GitHub Issues backend on a real repo: real issues, real PR, real CI, including a
      deliberately failing CI run (exercises `max_fix_attempts` → Blocked) and a deliberately
      unmet DoD criterion (verify must refuse to merge); Action installer + auto-review on
      `workflow_run`
- [ ] Linear backend end-to-end: live workspace + MCP, full task lifecycle including claim
      race guard and In Review / Done transitions
- [ ] `backlog` flows: one-off ticket intake (full packet), a manually created ticket caught
      by packet validation, Backlog → Todo promotion, a `Wont Do` closure with rationale, and
      a spec-impacting request routed through an `architect` delta
- [ ] Unattended safeguards: `/loop /dev:execute` batch run hits the `wip_limit` gate and
      idles; stuck task lands in `Blocked` with a diagnostic comment
- [ ] `retro` on completed tasks proposes ≥1 rules/CLAUDE.md promotion from real PR/CI/comment
      evidence; a following `dev:execute` session demonstrably benefits
- [ ] Brownfield: `setup` brownfield mode on an existing repo, architecture archaeology into a
      current-state SPEC.md, backlog import
- [ ] Final release: pre-commit checklist; archive or delete this DESIGN.md
