# dev

AI-assisted product development lifecycle for Claude Code: an external tracker (Linear,
GitHub Issues, or local files) is the single source of truth for tasks, execution is
PR-native (worktree → PR → CI → review → verified merge), and every task is a self-contained
packet a fresh session can execute without prior context.

Replaces [agentic_development_workflow](https://github.com/wilsonkichoi/agentic_development_workflow).
Design rationale and roadmap: [DESIGN.md](DESIGN.md). Workflow diagram:
[docs/dev-workflow.drawio](docs/dev-workflow.drawio).

## Status

Phases A-B implemented (tracker adapter, execution loop, review/verify/backlog quality loop);
not yet dogfooded. Phases C-D (discover/architect, retro/status) are designed but not built -
see the task checklist in DESIGN.md. End-to-end dogfooding is batched in Phase E.

## Skills

| Skill | Job |
|---|---|
| `/dev:setup` | Initialize a project (greenfield or brownfield): scaffold `docs/`, pick tracker backend, write `.claude/dev.md`. Brownfield mode offers architecture archaeology into a current-state SPEC.md. Optional installer for the auto-review GitHub Action. |
| `/dev:plan` | Decompose one roadmap milestone into self-contained task packets (objective, why, DoD, dependencies, inlined spec excerpts) and push them to the tracker after a human-approved dry run. |
| `/dev:backlog` | Mid-flight change management: intake requests as full packets with impact triage (backlog-only vs spec vs product goal), promote `Backlog → Todo`, split tasks, close as `Wont Do` with rationale, periodic triage sweep. |
| `/dev:execute` | Claim one task → git worktree → implement → tests (via the `test-writer` agent, contract-only context) → PR → CI to green → work-summary comment → `In Review`. Never merges. Safeguards: `wip_limit`, `max_fix_attempts`, packet validation for hand-written tickets. |
| `/dev:review-pr` | Independent review of a task PR against its packet and spec: severity-ranked findings, verdict posted via `gh pr review`. Fix mode applies findings on the same branch and replies per finding. Delegates to the `reviewer` agent when the session implemented the PR. |
| `/dev:verify` | The merge gate: evidence per DoD criterion (run tests, cite CI, perform manual steps), verification report on the PR, then human-approved merge, task → `Done`, worktree cleanup. Only thing allowed to merge. |

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
/dev:plan         # milestone → task packets in the tracker (human-gated dry run)
/dev:execute      # one task per session: claim → PR → CI green → In Review
/dev:review-pr    # independent review; fix mode addresses findings
/dev:verify       # DoD evidence → human-approved merge → Done
/dev:backlog      # anytime: new requests, promotions, wont-do, triage
```

Product discovery (`/dev:discover`), architecture (`/dev:architect`), retro, and status
skills arrive in Phases C-D.
