# dev

AI-assisted product development lifecycle for Claude Code: an external tracker (Linear,
GitHub Issues, or local files) is the single source of truth for tasks, execution is
PR-native (worktree → PR → CI → review → verified merge), and every task is a self-contained
packet a fresh session can execute without prior context.

Replaces [agentic_development_workflow](https://github.com/wilsonkichoi/agentic_development_workflow).
Design rationale and roadmap: [DESIGN.md](DESIGN.md). Workflow diagram:
[docs/dev-workflow.drawio](docs/dev-workflow.drawio).

## Status

All skills implemented (Phases A-D: tracker adapter, execution loop, review/verify/backlog
quality loop, discover/architect upstream phases, retro/status memory loop); **not yet
dogfooded** - end-to-end testing is Phase E in the DESIGN.md checklist. Expect rough edges
until it lands.

Adopting into an existing project (partial adoption, Jira/custom trackers, Mem0/OB1/MemSearch
memory): see [docs/adoption.md](docs/adoption.md).

## Skills

| Skill | Job |
|---|---|
| `/dev:discover` | Ingest `research/raw/`, interview the user to close gaps, produce `docs/PRD.md`: problem, customer, value, north star, non-goals. Business clarity only; delta mode for goal-impacting changes. |
| `/dev:architect` | Approved PRD → `docs/SPEC.md` (architecture, contracts, NFRs, negative requirements, Mermaid diagrams), `docs/ROADMAP.md` (risk-ordered milestones), ADRs for contested choices. Docs only; delta mode for spec-impacting changes. |
| `/dev:setup` | Initialize a project (greenfield or brownfield): scaffold `docs/`, pick tracker backend, write `.claude/dev.md`. Brownfield mode offers architecture archaeology into a current-state SPEC.md. Optional installer for the auto-review GitHub Action. |
| `/dev:plan` | Decompose one roadmap milestone into self-contained task packets (objective, why, DoD, dependencies, inlined spec excerpts) and push them to the tracker after a human-approved dry run. |
| `/dev:backlog` | Mid-flight change management: intake requests as full packets with impact triage (backlog-only vs spec vs product goal), promote `Backlog → Todo`, split tasks, close as `Wont Do` with rationale, periodic triage sweep. |
| `/dev:execute` | Claim one task → git worktree → implement → tests (via the `test-writer` agent, contract-only context) → PR → CI to green → work-summary comment → `In Review`. Never merges. Safeguards: `wip_limit`, `max_fix_attempts`, packet validation for hand-written tickets. |
| `/dev:review-pr` | Independent review of a task PR against its packet and spec: severity-ranked findings, verdict posted via `gh pr review`. Fix mode applies findings on the same branch and replies per finding. Delegates to the `reviewer` agent when the session implemented the PR. |
| `/dev:verify` | The merge gate: evidence per DoD criterion (run tests, cite CI, perform manual steps), verification report on the PR, then human-approved merge, task → `Done`, worktree cleanup. Only thing allowed to merge. |
| `/dev:retro` | Mines PR review threads, CI history, tracker comments, and session transcripts for completed tasks, then closes the memory loop: evidence-cited learnings promoted into `.claude/rules/` / CLAUDE.md (or a `memory_target` MCP system), applied on approval. |
| `/dev:status` | Read-only dashboard: milestone progress, open PRs + CI state, WIP vs limit, blocked tasks, next claimable tasks, plus consistency checks (state lies, abandoned claims, missed cleanups). |

## Agents

| Agent | Job |
|---|---|
| `test-writer` | Writes tests from the task packet + public interface only, never the implementation diff. Used by `/dev:execute` for test separation. |
| `reviewer` | Independent PR review with its own context: fetches packet, diff, CI, spec; posts verdict. Used by `/dev:review-pr` when the calling session implemented the PR. |

## Tracker backends

Configured per project in `.claude/dev.md` frontmatter (`tracker:` field). Contract and
backend mappings: [docs/tracker.md](docs/tracker.md).

| Backend | Mechanism |
|---|---|
| `linear` | Official Linear MCP server; native priorities, estimates, blocked-by relations |
| `github` | `gh` CLI; `status:*` labels, milestones, `Blocked by #N` dependencies |
| `local` | `.dev/tasks/T-NNN-slug.md`, one file per task, YAML frontmatter |
| `custom` | Bring your own (Jira, etc.) via the "Adding a backend" recipe in `docs/tracker.md` |

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
/dev:retro        # per task or milestone: learnings → .claude/rules/
```
