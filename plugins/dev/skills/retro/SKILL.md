---
name: retro
description: >
  This skill should be used when the user asks to "run a retro", "retrospective on task
  <id>", "retro the milestone", "what did we learn", "update the rules from what happened",
  or invokes /dev:retro. Mines the evidence trail of completed tasks (PR review threads, CI
  history, tracker comments, session transcripts) and closes the memory loop: distilled
  learnings are promoted into .claude/rules/ or CLAUDE.md so future sessions start smarter.
argument-hint: "[task <id> | milestone <n>]"
---

# dev:retro

Close the memory loop. A retro that only produces a summary is ADW's dead RETRO-*.md problem;
this skill's deliverable is the **promotion**: concrete additions to the project's standing
instructions, applied on approval, that change how the next session behaves.

Read first: `.claude/dev.md` and `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md`. Scope: one task
(`task <id>`) or all `Done`/`Wont Do`/`Blocked` tasks in a milestone (`milestone <n>`).

If the target task is not yet terminal (e.g. `In Review` awaiting merge), do not close it
out yourself - merging and `Done` belong to `dev:verify`, even if the user approves the
merge in this session. Direct them to run `/dev:verify`, then retro after it finishes.

## 1. Gather evidence

Per task, in this order of value:

1. **Tracker comments:** the work-summary comment (decisions, obstacles, spec gaps), Blocked
   diagnostics, verification report, Wont Do rationales.
2. **PR review threads:** every finding is a signal - what did the reviewer catch that the
   executor should have known up front?
3. **CI history:** failure runs on the task branch (`gh run list --branch task/<id>-*`);
   recurring failure classes (env setup, flaky test, missing migration) matter more than
   one-offs.
4. **Session transcripts** (best effort): search `~/.claude/projects/<project-slug>/` for the
   task id; use to reconstruct why something took N attempts. Skip silently if absent.

## 2. Distill

For each friction point or success, ask: root cause, and would a future session hit it again?
Classify each learning:

- **Project rule** - generalizable constraint or convention ("integration tests need
  `docker compose up db` first", "API errors follow shape X"): candidate for promotion.
- **Packet-quality lesson** - the packet was wrong/thin (untestable DoD, missing dependency):
  candidate for the planning conventions in the `.claude/dev.md` body.
- **Process tuning** - config change (`work_in_progress_limit`, `max_fix_attempts`, test command).
- **One-off** - bad luck, no generalization: record in the retro comment, promote nothing.
- **Follow-up work** - a defect or gap in already-merged work, or new work the evidence
  exposes (e.g. a parity check reveals an earlier task diverged from spec): not a rule, a
  task. Route it through `/dev:backlog` intake so it lands in the tracker with a packet.
  A memory note or a mention in the retro comment is not a destination for work - an
  untracked follow-up is exactly the state-outside-the-tracker failure this plugin exists
  to prevent.

## 3. Promote (the point of this skill)

Promotion targets, by `memory_target` in `.claude/dev.md` (default `files`):

- **`files`:** one atomic rule per file in `.claude/rules/<slug>.md` (a rule future sessions
  must obey), or a line in the relevant CLAUDE.md section for pointers/summaries. Check
  existing rules first - update or strengthen rather than duplicate; delete rules the
  evidence now contradicts.
- **MCP memory** (`mem0`, `openbrain`, `memsearch`, …): store each learning via that system's
  MCP tool; recall is that system's job. Still write rules that gate correctness to
  `.claude/rules/` - files are the only target every future session is guaranteed to load.

Standards for a promotable learning: evidence-cited (link the PR finding / CI run / comment),
generalizable beyond the one task, and actionable as an instruction ("run X before Y"), never
vibes ("be careful with the database"). Propose the exact diff per promotion. Post the retro
comment (section 4) BEFORE asking for approval, with each promotion listed as "proposed, not
applied" - stopping the turn to ask is how a drafted retro ends up existing only in chat.
Apply on approval, then append the follow-up comment per section 4.

**Commit applied promotions immediately** (with the user's consent, as with every gate): one
dedicated commit on `main` for the rule/CLAUDE.md changes, before any next task starts -
and with a remote, push it: task worktrees branch from local `main`, so an unpushed
promotion commit silently rides into the next task's PR diff. Task
worktrees check out `main`'s committed HEAD, so an uncommitted rule is invisible to the next
executor - the loop you just closed silently stays open - and the stray file eventually gets
swept into an unrelated commit by whatever writes to `main` next.

## 4. Record

Post a retro comment on the task (or each milestone task): what worked, what did not, root
causes, learnings promoted (with rule file names), learnings recorded-only. Milestone scope:
also summarize across tasks - estimate accuracy, review-finding density, recurring blockers -
and recommend process tuning with the evidence.

**The record is unconditional.** Post the retro comment even when the promotions are
declined, deferred, or still awaiting the user's answer - list pending ones as "proposed,
not applied". Never leave a drafted retro existing only in the chat while waiting on the
promotion gate: a session that ends there loses the whole retro, which is exactly the dead
RETRO-*.md failure this skill replaces. If promotions are approved after the comment is
posted, append a short follow-up comment naming the applied rule files (comments are
append-only, never edited).

The loop-closure test before finishing: for each promoted rule, name the concrete past
failure it would have prevented. A rule that prevents nothing is noise; drop it.
