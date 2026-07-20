# dev

AI-assisted product development lifecycle for Claude Code and Codex: an external tracker (Linear,
GitHub Issues, or local files) is the single source of truth for tasks, execution is
PR-native (worktree → PR → CI → review → verified merge), and every task is a self-contained
packet a fresh session can execute without prior context.

Replaces [agentic_development_workflow](https://github.com/wilsonkichoi/agentic_development_workflow).
This README is the index; the operating guide (prerequisites, `.agent-toolkit/dev.md` config
reference, lifecycle and ownership rules, human gates, unattended operation) is
[docs/manual.md](docs/manual.md). Design rationale and build history: [DESIGN.md](DESIGN.md).
Workflow diagram: [docs/dev-workflow.drawio](docs/dev-workflow.drawio).

## Status

All skills implemented on both harnesses. Dogfooding (Phase E in DESIGN.md): the full
lifecycle passed end-to-end on the local, GitHub Issues, and Linear backends (2026-07-06,
Linear milestone runs through 2026-07-14), `dev:auto` completed real tasks on Claude Code
and Codex, and the 0.0.54 encapsulated-config migration is dogfooded in this repository
(`.agent-toolkit/dev.md` drives its own contribution workflow). Brownfield adoption is
untested - expect rough edges there.

Adopting into an existing project (partial adoption, Jira/custom trackers, Mem0/OB1/MemSearch
memory): see [docs/adoption.md](docs/adoption.md).

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
[project bootstrap](docs/project-bootstrap.md), require that checkout's `HEAD` to match the
expected task or PR revision, read its context/config files, load every doctrine rule, select
gotcha rules from declared path/objective/DoD triggers, and record the exact execution revision
and `Rules loaded:` list in lifecycle artifacts.

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
| `/dev:review-pr` | Independent review of a task PR against its packet and spec: severity-ranked findings, verdict posted via `gh pr review`. Fix mode applies findings on the same branch and replies per finding. Delegates to the `reviewer` agent when the session implemented the PR. |
| `/dev:verify` | The merge gate: evidence per DoD criterion (run tests, cite CI, perform manual steps), verification report on the PR, then human-approved merge, task → `Done`, worktree cleanup. Only thing allowed to merge. Human-gate (manual/visual) criteria pass only on a recorded sign-off (a comment authored by the human) or live confirmation - PR-body checkboxes are display only, checked solely by verify. Rejects stale approvals: the approving review must target the current PR HEAD, so a post-review fix push forces a fresh review before merge. Delegates evidence gathering to the `verifier` agent when the session implemented the PR; the human gate and merge stay in the session. Approval never waives the record: the report and checkbox updates land on the PR before the merge. |
| `/dev:retro` | Mines PR review threads, CI history, tracker comments, session transcripts, and lifecycle-contract compliance (did each step produce what its skill mandates, including steps run in the current session) for completed tasks, then closes the memory loop: evidence-cited learnings promoted into the configured memory (`rules_dir` files, `.agent-toolkit/rules/` by default, or a `memory_target` MCP system), applied on approval. Defects or follow-up work the retro uncovers route to the tracker via `/dev:backlog`, never to memory notes; the retro comment posts before the promotion gate so the record survives an abandoned session. |
| `/dev:status` | Read-only dashboard: milestone progress, open PRs + CI state, WIP vs limit, blocked tasks, next claimable tasks, plus consistency checks (state lies, abandoned claims, missed cleanups). |

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
backend mappings: [docs/tracker.md](docs/tracker.md).

| Backend | Mechanism |
|---|---|
| `linear` | Official Linear MCP server; native priorities, estimates, blocked-by relations |
| `github` | `gh` CLI; `status:*` labels, milestones, `Blocked by #N` dependencies |
| `local` | `.dev/tasks/T-NNN-slug.md`, one file per task, YAML frontmatter |
| `custom` | Bring your own (Jira, etc.) via the "Adding a backend" recipe in `docs/tracker.md` |

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
[the manual](docs/manual.md#primary-github-fork-contributions) and
[repository resolution contract](docs/tracker.md#github-repository-resolution).

A maintainer's explicit numeric issue id is planned work and must carry exactly `status:todo`;
external handling requires `external #N`. Planned claim, handoff, and blocked transitions use the
bundled verified lifecycle command, and the execute record preserves the queue classification for
review and verify. GitHub routing accepts that record only when its author, PR URL, branch, and
execution revision bind it to the current PR; later comments from other issue participants cannot
reclassify planned work.

**Secondary intake channel.** A non-`github`-primary project can accept isolated GitHub issues
and drive-by PRs as a second channel (`secondary_intake: github`): promote them into the
primary tracker, or work them in place (`/dev:execute #N` → `/dev:review-pr #PR` →
`/dev:verify #PR`) with no primary ticket. See "An incoming GitHub issue or PR" in
[docs/manual.md](docs/manual.md) and "Secondary intake channel" in
[docs/tracker.md](docs/tracker.md).

## Typical flow

```
/dev:setup        # once per project
/dev:discover     # research + interview → PRD (human gate)
/dev:architect    # PRD → SPEC + ROADMAP + ADRs (human gate)
/dev:plan         # milestone → task packets in the tracker (human-gated dry run)
/dev:execute      # one task per session: claim → PR → CI green → In Review
/dev:review-pr    # independent review; fix mode addresses findings
/dev:verify       # DoD evidence → human-approved merge → Done
/dev:backlog      # anytime: new requests, promotions, wont-do, triage
/dev:status       # anytime: where are we, what needs human action
/dev:retro        # per task or milestone: learnings → .agent-toolkit/rules/ (configured memory)
/dev:auto DOG-14  # unattended: complete exactly this task; never fall through
/dev:auto milestone 2 max 1 tasks  # unattended milestone drain, capped at one task
```
