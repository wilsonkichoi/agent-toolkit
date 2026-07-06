---
name: plan
description: >
  This skill should be used when the user asks to "plan the milestone", "break down the
  milestone into tasks", "create task packets", "generate the backlog from the spec", or
  invokes /dev:plan. Decomposes a roadmap milestone into self-contained task packets and
  pushes them to the configured tracker after a human-approved dry run.
argument-hint: "[milestone N]"
---

# dev:plan

Decompose one milestone into task packets in the tracker. One milestone per run; do not plan
ahead of the next milestone - later milestones get better packets after earlier ones ship.

Read first:

1. `.claude/dev.md` - tracker backend and config.
2. `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md` - verbs and backend mapping.
3. `docs/SPEC.md`, `docs/ROADMAP.md`, and `docs/PRD.md` - intent. If SPEC.md or ROADMAP.md is
   missing, stop and direct the user to `/dev:architect`.
4. `list <milestone>` on the tracker - never create duplicates of tasks that already exist.

## 1. Draft packets

For the target milestone (argument, or the first roadmap milestone with unplanned scope),
draft tasks against the packet schema. Every packet:

- **Title**, **Type** (`task` | `spike`).
- **Objective** - what exists when done, 1-3 sentences.
- **Why** - the problem it solves, naming the PRD/SPEC section that motivates it.
- **Definition of Done** - checkable criteria only. Each criterion must name its evidence: a
  test command, a CI check, or an explicit manual verification step. "Works correctly" is not
  a criterion.
- **Dependencies** - task ids that must be `Done` first. Model implicit ordering (B builds on
  A's code) as a real dependency; unmodeled ordering is how parallel sessions produce
  conflicting PRs.
- **Estimate** - S/M/L plus rough hours.
- **Spec references** - links to `docs/SPEC.md#section`, with the load-bearing excerpt
  (contract, schema, constraint) inlined verbatim so a fresh executor cannot skip it.
- **Suggested steps** - 3-8 advisory bullets.

Scope rules: single concern, independently verifiable, describable in 2-3 sentences. Split
anything that fails these.

**Spikes:** create a spike (not a task) where the spec leaves a genuine unknown that blocks
estimation or design. A spike packet carries the question, a timebox, and the required
output: an ADR in `docs/adr/` plus a tracker comment with the recommendation. Spikes produce
knowledge, not merged code.

If drafting reveals a spec gap (needed behavior the spec does not define), stop drafting that
task and list the gap in the dry run under "Spec gaps - needs /dev:architect"; do not guess.

## 2. Dry run (human gate)

Present the complete draft before touching the tracker: every packet in full, the dependency
edges (as a list or Mermaid graph), spike rationale, and any spec gaps. Iterate on feedback.
Do not create anything until the user approves.

## 3. Push

On approval, `create-task` each packet at status `Todo` (plan approval is the commitment
gate), with dependencies, priority, estimate, and milestone mapped per the backend section of
`tracker.md`. Order priorities so the intended execution order falls out of the next-task
selection algorithm.

Verify by running `list <milestone>` and comparing against the approved draft. Report: tasks
created, spikes created, dependency count, and any spec gaps deferred to `/dev:architect`.
