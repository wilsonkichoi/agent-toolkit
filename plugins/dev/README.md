# dev

AI-assisted product development lifecycle for Claude Code: an external tracker (Linear,
GitHub Issues, or local files) is the single source of truth for tasks, execution is
PR-native (worktree → PR → CI → review → verified merge), and every task is a self-contained
packet a fresh session can execute without prior context.

Replaces [agentic_development_workflow](https://github.com/wilsonkichoi/agentic_development_workflow).
Design rationale and roadmap: [DESIGN.md](DESIGN.md). Workflow diagram:
[docs/dev-workflow.drawio](docs/dev-workflow.drawio).

## Status

Phase A (tracker adapter + execution loop) implemented; not yet dogfooded. Phases B-D
(review/verify/backlog, discover/architect, retro/status) are designed but not built - see
the task checklist in DESIGN.md.

## Skills

| Skill | Job |
|---|---|
| `/dev:setup` | Initialize a project (greenfield or brownfield): scaffold `docs/`, pick tracker backend, write `.claude/dev.md`. Brownfield mode offers architecture archaeology into a current-state SPEC.md. |
| `/dev:plan` | Decompose one roadmap milestone into self-contained task packets (objective, why, DoD, dependencies, inlined spec excerpts) and push them to the tracker after a human-approved dry run. |
| `/dev:execute` | Claim one task → git worktree → implement → tests (via the `test-writer` agent, contract-only context) → PR → CI to green → work-summary comment → `In Review`. Never merges. Safeguards: `wip_limit`, `max_fix_attempts`, packet validation for hand-written tickets. |

## Agents

| Agent | Job |
|---|---|
| `test-writer` | Writes tests from the task packet + public interface only, never the implementation diff. Used by `/dev:execute` for test separation. |

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
                  # repeat /dev:execute, or /loop /dev:execute for a supervised batch
```

Review, verified merge (`Done`), backlog management, product discovery, architecture, and
retro skills arrive in Phases B-D.
