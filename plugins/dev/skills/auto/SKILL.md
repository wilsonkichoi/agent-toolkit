---
name: auto
description: >
  This skill should be used when the user asks to "auto-run the milestone", "run the full
  pipeline per task", "drive tasks to done hands-free", "execute review verify and merge
  automatically", or invokes /dev:auto. Chains execute → review → fix → verify → merge →
  retro per task so dependency chains progress unattended. Merges only under the auto_merge
  conditions; stops on anything requiring human judgment.
argument-hint: "[milestone N] [max N tasks]"
---

# dev:auto

Drive tasks to `Done` one at a time: execute → independent review → fix → verify → merge →
retro, then claim the next. This is what `/loop /dev:execute` cannot do: that loop stops
every task at `In Review`, so a dependency chain never advances past its first task. Use
`/loop /dev:execute` to fill the review queue for human-paced review; use `/dev:auto` to
drain a milestone.

Read first: `.claude/dev.md` and `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md`.

## Standing authorization (`auto_merge`)

Unattended merging requires `auto_merge: true` in `.claude/dev.md` frontmatter. That flag is
the human's standing, revocable approval for merges meeting ALL of:

1. Independent review verdict is approve (from the `reviewer` agent, never self-review).
2. Every DoD criterion is met, with artifact evidence.
3. Every DoD criterion is either mechanically evidenced (test run or CI check) or carries a
   recorded human sign-off (`dev:verify` section 2: a task/PR comment authored by the human
   approving that criterion; PR-body checkboxes never count). A manual criterion with
   neither stops the pipeline for a human, no matter what the config says.

`auto_merge` absent or false: refuse to run, explain the flag, and point at the manual flow.
Do not fall back to a silent stop-at-verify mode.

## Orchestration discipline

The session stays a thin orchestrator; every heavy step runs in a fresh subagent so no
implementation context accumulates (mid-task compaction is how work gets corrupted).
Orchestrator does: claim, subagent dispatch, artifact checks between steps, merge, status
transitions, reporting. Subagents do: implementation, review, fixes, verification evidence.

## Per-task pipeline

1. **Claim** - as `dev:execute` step 1: `next-task` (WIP gate, dependency rules, packet
   validation; invalid packets are skipped with a comment).
2. **Implement** - background subagent following `dev:execute` steps 2-7 (worktree →
   implement → tests via `test-writer` → PR or branch → CI green → local preview
   instructions when the DoD has visual criteria → work-summary comment →
   `In Review`); it creates the task worktree itself per execute step 2, so spawn it
   without harness worktree isolation. `max_fix_attempts` applies inside; a `Blocked`
   result stops the pipeline.
3. **Review** - fresh `reviewer` agent, exactly as `dev:review-pr` delegation.
4. **Fix loop** - on request-changes: subagent applies `dev:review-pr` fix mode, then a fresh
   review pass. **Comment every cycle** on the task so the review iteration is visible on the
   issue, not only in PR review threads:

   ```
   ## Review fix cycle <n>/<max_fix_attempts> (dev:auto - <date>)
   - Findings addressed: <1-line each>
   - Re-review verdict: <approve | request-changes: remaining findings>
   ```

   At most `max_fix_attempts` review-fix cycles; still not approved → transition to `Blocked`
   with a final comment listing the unresolved findings (the per-cycle comments are the trail),
   stop.
5. **Verify + merge** - fresh `verifier` agent runs `dev:verify` sections 1-3
   (preconditions, evidence per criterion, report), per `dev:verify`'s independence rule;
   the orchestrator posts the tracker copy of the report on backends the agent cannot
   write to. All criteria met, each
   mechanically evidenced or carrying a recorded human sign-off → merge per `merge_policy`,
   transition `Done`, clean up worktree. Any criterion unmet, or manual without a recorded
   sign-off → post the verification report, leave `In Review`, stop and tell the human
   exactly what needs them.
6. **Retro (record-only)** - run `dev:retro` for the task with promotions in proposal mode:
   post the retro comment including proposed rule promotions, but never write to
   `.claude/rules/` or CLAUDE.md unattended. Standing instructions change only with a human
   in the loop; proposals accumulate for a later `/dev:retro milestone N` pass.
7. **Next** - loop to step 1.

## Stop conditions

Stop and report (never push past these): nothing claimable (milestone drained, or all
remaining tasks blocked by non-`Done` deps); `max_tasks_per_run` reached (config, default 5;
overridable by the `max N tasks` argument); any task `Blocked`; verify stop (unmet
criterion, or manual criterion without recorded sign-off); merge conflict; tracker write
failure.

Report on stop, whatever the reason:

```
# dev:auto - stopped: <reason>
Completed to Done: <ids>
Stopped at: <id> - <what needs the human>
Pending retro proposals: <count> (run /dev:retro milestone N to review)
Next: <the single next human action>
```

## Constraints

- Single-flight: one task at a time, sequentially. Parallelism is a human decision made by
  running parallel `/dev:execute` sessions, not something this skill does.
- Never applies rule promotions, never overrides `Blocked`, never merges around a failed
  condition, never re-plans; defects in packets go to `/dev:backlog`, not silent edits.
