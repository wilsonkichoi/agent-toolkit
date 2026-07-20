---
name: auto
description: >
  This skill should be used when the user asks to "auto-run the milestone", "auto-run a
  named task", "run the full pipeline per task", "drive tasks to done hands-free", "execute
  review verify and merge automatically", or invokes /dev:auto. Chains execute → review →
  fix → verify → merge → retro per task so dependency chains progress unattended. Merges
  only under the auto_merge conditions; stops on anything requiring human judgment.
argument-hint: "[milestone N [max N tasks] | task-id]"
---

# dev:auto

Drive a selected task or a milestone's tasks to `Done`, one at a time: execute → independent
review → fix → verify → merge → retro. A task-id run stops after that exact task; a
milestone run then claims the next eligible task. This is what `/loop /dev:execute` cannot
do: that loop stops every task at `In Review`, so a dependency chain never advances past
its first task. Use `/loop /dev:execute` to fill the review queue for human-paced review;
use `dev:auto` to complete one named task or drain a milestone.

Skill references like `dev:execute` mean this plugin's `execute` skill; when telling the user
to run one, render your harness's invocation for it (Claude Code: `/dev:execute`; Codex: `$execute`).

Read first: `.agent-toolkit/dev.md` (tracker routing config; legacy fallbacks:
`.agent/dev.md`, then `.claude/dev.md` when absent), the plugin's `docs/tracker.md`, and the
plugin's `docs/project-bootstrap.md`. On Claude Code these plugin docs are under
`${CLAUDE_PLUGIN_ROOT}/docs/`; equivalently they are under `../../docs/` relative to this
skill's directory.

Before any repository or tracker call, resolve repository context once using `tracker.md`
"GitHub repository resolution". If primary-GitHub fork routing is active and the authenticated
user lacks upstream write permission, refuse external contribution work before checking
`auto_merge` or dispatching an agent. The pipeline cannot cross the required maintainer merge
and terminal-transition boundary. Report the manual contributor flow:
`dev:execute` → `dev:review-pr` → `dev:verify` evidence → maintainer decision. A maintainer
working from a fork retains the resolved `upstream` base, `origin` push, and canonical GitHub
targets; topology does not remove authority. Existing non-fork and maintainer-owned planned
queue behavior remains unchanged.

Requires a harness that can spawn fresh-context subagents and wait on their results, with
this plugin's named agents (`reviewer`, `verifier`, `test-writer`) resolvable - Claude Code
natively; Codex via `spawn_agent`/`wait_agent` with the `dist/codex/agents/*.toml` files
copied into `~/.codex/agents/` or the project's `.codex/agents/`. On Codex, selecting a
named agent means passing `agent_type: "<agent name>"` on `spawn_agent` (e.g.
`agent_type: "reviewer"`); `task_name` only labels the spawned thread and does NOT load the
agent definition - a spawn with `task_name` alone runs a generic subagent. Check by use,
not by config archaeology: a named agent fails to resolve when the spawn tool's schema has
no `agent_type` parameter or rejects the agent name - that is a stop; report it with the
copy/install instructions from the repo README. Refuse to run only on a
harness with no subagent mechanism at all, pointing at the one-task-at-a-time flow:
dev:execute → dev:review-pr → dev:verify → dev:retro.

## Standing authorization (`auto_merge`)

Unattended merging requires `auto_merge: true` in `.agent-toolkit/dev.md` frontmatter. That flag is
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
Orchestrator does: claim, subagent dispatch, artifact validation between steps, merge,
status transitions, tracker writes the agents cannot make, reporting. Subagents do:
implementation, review, fixes, verification evidence.

**Fresh context, never forked:** every subagent starts with fresh context. Never fork or
copy this session's history into one (Codex: always pass `fork_turns: "none"` on
`spawn_agent` - never omit it; the omitted-parameter default is undocumented, and only
`"none"` guarantees a fresh child). Everything the agent
needs is passed as text per the delegation contracts in `dev:review-pr` / `dev:verify`.
In active fork routing, every dispatch also carries the already-resolved canonical repository,
base remote, push remote, issue/PR identity, and upstream permission. Subagents must not infer
repository roles again from their worktree.

For each claimed task, fetch only enough packet/PR identity to resolve the execution repository,
then follow `docs/project-bootstrap.md` at the resolved base commit before dispatch. The task
worktree does not exist yet, so this initial bootstrap does not require its branch `HEAD`. The
implementation worker reruns the bootstrap in the new task worktree before implementation, then
refreshes it after implementation exposes the complete changed-path list. Pass the resolved
execution repository and revision, changed paths when known, and exact project-instruction /
loaded-rule paths to every worker and named agent; each child reads those files itself. Preserve
the exact `Execution repository:`, `Execution revision:`, and `Rules loaded:` entries in the work
summary, review, verification report, and final task report.

**Model discipline:** spawn every subagent with NO `model` parameter - the dev agents pin
`model: inherit` and generic subagents inherit the session model by default, and an explicit
`model` on the spawn call overrides both. Never pass a model alias to "match" the session
(aliases resolve to the newest model of that family, which the account may not have), and
never downgrade to a smaller model to route around a model-availability error - that
silently runs implementation and review on a weaker model than the human chose. If a spawn
fails on the inherited model, retry once with no override; if it fails again, stop and
report the error as an environment problem.

**Reviewer/verifier dispatch:** dispatch the `reviewer` and `verifier` agents and wait for
the result before advancing, so the verdict or report arrives as the tool result (Claude
Code: `run_in_background: false`; Codex: `spawn_agent` with `agent_type: "reviewer"` /
`agent_type: "verifier"`, then `wait_agent`). A review
or verify agent that errors, goes idle, or returns without a verdict/report is a stop
condition - the orchestrator never substitutes its own inline review or verification;
auto_merge condition 1 and `dev:verify`'s independence rule both forbid it, and the
orchestrator holds the implementer's report, so it is not independent.

## Target selection

- **Task id:** run `get-task`, then apply `dev:execute` step 1's targeted-task contract:
  require `Todo`, all dependencies `Done`, WIP below `work_in_progress_limit`, a valid packet,
  and a successful race-guarded claim. For a primary-GitHub numeric id, this includes the shared
  verified `validate-todo` and `claim` commands from `tracker.md`; missing or malformed lifecycle
  labels never reroute the task to external contribution handling. Refuse and report the exact
  failed gate; unattended auto never overrides eligibility. Run only this task and stop after its
  record-only retro.
  Never fall through to another task if the target is missing, ineligible, has an invalid
  packet, becomes `Blocked`, or otherwise stops. `max N tasks` is invalid with a task id.
- **Milestone N:** restrict `next-task` to that milestone. Process eligible tasks sequentially
  until a stop condition. An explicit `max N tasks` overrides `max_tasks_per_run`; otherwise
  use the configured value (default 5).
- **No target:** use `next-task` without a milestone filter and the configured
  `max_tasks_per_run`. This preserves the existing active-queue behavior.

## Per-task pipeline

1. **Claim** - follow the selected mode above. Queue modes use `next-task` (WIP gate,
   dependency rules, packet validation; invalid packets are skipped with a comment).
   Task-id mode gets and claims only the named task; an invalid packet stops instead of
   skipping to another task.
2. **Implement** - never inline in the orchestrator session, on any harness. Two shapes,
   by whether the implementation subagent can itself spawn `test-writer` (nested
   delegation):
   - **Nested delegation available** (Claude Code): one fresh subagent follows
     `dev:execute` steps 2-7 (worktree → implement → tests via `test-writer` → PR or
     branch → CI green → local preview instructions when the DoD has visual criteria →
     work-summary comment → `In Review`); it creates the task worktree itself per execute
     step 2, so spawn it without harness worktree isolation.
   - **Nested delegation unavailable** (Codex: the default `agents.max_depth = 1` blocks
     grandchild spawns - no configuration change needed): the orchestrator dispatches the
     phases as siblings. First judge triviality from the packet per execute step 3's
     exception (config, docs, one-liners); a trivial task runs as ONE worker dispatch of
     execute steps 2-7 testing inline. Non-trivial (borderline counts as non-trivial):
     1. Worker (Codex built-in) runs execute steps 2-3: worktree, implement - no push or
        PR yet. Its report must return the worktree path, branch, and the public interface
        (signatures, CLI surface, schemas) for the test-writer briefing.
     2. `test-writer` (named agent), briefed with ONLY the packet, spec excerpts, public
        interface, worktree path, `test_command`, and the bootstrap's resolved project
        instruction / loaded-rule paths - never the implementation diff or the worker's
        rationale. It reads the supplied bootstrap files, writes and runs contract tests,
        and reports pass/fail verbatim.
     3. Worker (fresh, given the worktree path and the test results) reconciles failures
        (code vs contract), runs the full `test_command`, then executes steps 4-7: PR, CI
        to green, work summary, `In Review`.

   `max_fix_attempts` applies inside the implementation phase; a `Blocked` result stops
   the pipeline. Before review, validate the execute work summary through `tracker.md` "Trusted
   GitHub work-summary routing"; never accept a bare `Queue classification:` field from the latest
   comment. For planned primary-GitHub work, re-read the canonical issue and require exactly
   `status:in-review`. A missing, untrusted, unbound, or failed handoff record stops the pipeline;
   review never repairs execute-owned state.
3. **Review** - fresh `reviewer` agent, exactly as `dev:review-pr` delegation (the dispatch
   message embeds the packet + work-summary text verbatim, the review body format, the
   solo-repo `--comment` fallback, and the current-HEAD `Commit:` requirement), dispatched
   per the reviewer/verifier discipline above (waited-on, no model override, no verdict →
   stop). **Validate the artifact before advancing:** fetch the PR reviews and require one
   (native or comment-form) whose body contains `## dev:review-pr - <id>`, an exact
   `Verdict:` line, and `Commit:` equal to the current `headRefOid`; and require the
   tracker verdict record - on backends the agent cannot write to, post it from the
   agent's returned body (same proxy rule as verify). Artifact missing or malformed
   despite an approve-in-substance result: respawn the reviewer ONCE with the full
   embedded contract; still malformed → stop. Never conclude a different GitHub account is
   needed - the comment-form review is the designed solo-repo path (`dev:review-pr`
   step 3).
4. **Fix loop** - on request-changes, the `dev:auto` orchestrator dispatches one subagent to
   apply the single-batch `dev:review-pr` fix mode, waits for that invocation to stop, then
   dispatches a separate fresh review pass. Manual `dev:review-pr` review and fix invocations
   never perform this chaining themselves. The automated sequence is one fix invocation, then a
   fresh review pass, both dispatched by the orchestrator. **Comment every cycle** on the task so
   the review iteration is visible on the issue, not only in PR review threads:

   ```
   ## Review fix cycle <n>/<max_fix_attempts> (dev:auto - <date>)
   - Findings addressed: <1-line each>
   - Re-review verdict: <approve | request-changes: remaining findings>
   ```

   At most `max_fix_attempts` review-fix cycles; still not approved → transition to `Blocked`
   with a final comment listing the unresolved findings (the per-cycle comments are the trail),
   stop.
5. **Verify + merge** - fresh `verifier` agent runs `dev:verify` sections 1-3
   (preconditions, evidence per criterion, report), per `dev:verify`'s independence rule
   and delegation contract (the dispatch message embeds the packet + task-comment text
   verbatim, the approving-review definition, and the report format), dispatched per the
   reviewer/verifier discipline above (waited-on, no model override, no report → stop).
   Validate the artifact: confirm the report landed as a PR comment with the exact
   `## dev:verify - <id>` heading, `Commit:` equal to the current PR `headRefOid`,
   `Merge authorization: required`, the full criterion table, and `Final result:`. Post the
   tracker copy from the agent's returned body on backends the agent cannot write to. A stale
   or malformed report is a stop, never merge evidence. All criteria met, each
   mechanically evidenced or carrying a recorded human sign-off → merge per `merge_policy`,
   transition `Done`, clean up worktree (remove the task worktree before any branch
   deletion - a branch checked out in a worktree cannot be deleted, so `--delete-branch`
   on the merge fails until the worktree is gone). Any criterion unmet, or manual without
   a recorded sign-off → post the verification report, leave `In Review`, stop and tell
   the human exactly what needs them.
6. **Retro (record-only)** - run `dev:retro` for the task with promotions in proposal mode:
   post the retro comment including proposed rule promotions, but never write to the
   configured `rules_dir` or `.agent-toolkit/dev.md` (legacy safety-net fallback when both
   memory fields are absent: `.claude/rules/` and `CLAUDE.md`) unattended. Standing
   instructions change only with a human in the loop; proposals accumulate for a later
   `dev:retro milestone N` pass.
7. **Next** - for milestone/no-target queue mode, loop to step 1. For task-id mode, stop
   successfully after the retro; never claim another task.

## Stop conditions

Stop and report (never push past these): the targeted task completed; nothing claimable
(milestone/queue drained, or all remaining tasks blocked by non-`Done` deps);
`max_tasks_per_run` reached in queue mode (config, default 5; overridable by the
`max N tasks` argument in milestone mode); any task `Blocked`; verify stop (unmet
criterion, or manual criterion without recorded sign-off); review or verify agent failure
(error, idle, or no verdict/report returned - never substitute orchestrator-inline review
or verification); review artifact still missing or malformed after the one respawn; a named
agent unresolvable at spawn (agent definitions not installed); subagent spawn failure after
the one no-override retry (model availability included); merge conflict; tracker write
failure.

Report on stop, whatever the reason. Every field below is required with its stated meaning
(reason, tasks completed to `Done`, where it stopped and what needs the human, pending
retro proposal count, the single next action); exact wording may vary:

```
# dev:auto - stopped: <reason>
Completed to Done: <ids>
Stopped at: <id> - <what needs the human>
Pending retro proposals: <count> (run dev:retro task <id> or dev:retro milestone N to review)
Next: <the single next human action>
```

Successful task-id completion is a normal terminal condition: use `completed: <id>` as the
reason, say that nothing needs the human in `Stopped at`, and use `Next: none - requested
task completed`. Do not imply that another task will be claimed.

## Constraints

- Single-flight: one task at a time, sequentially. Parallelism is a human decision made by
  running parallel `dev:execute` sessions, not something this skill does.
- Never applies rule promotions, never overrides `Blocked`, never merges around a failed
  condition, never re-plans; defects in packets go to `dev:backlog`, not silent edits.
