---
name: retro
description: >
  This skill should be used when the user asks to "run a retro", "retrospective on task
  <id>", "retro the milestone", "what did we learn", "update the rules from what happened",
  or invokes /dev:retro. Mines the evidence trail of completed tasks (PR review threads, CI
  history, tracker comments, session transcripts) and closes the memory loop: distilled
  learnings are promoted into the project's configured rules directory
  (.agent-toolkit/rules/ by default) so future sessions start smarter.
argument-hint: "[task <id> | milestone <n>]"
---

# dev:retro

Close the memory loop. A retro that only produces a summary is ADW's dead RETRO-*.md problem;
this skill's deliverable is the **promotion**: concrete additions to the project's standing
instructions, applied on approval, that change how the next session behaves.

Skill references like `dev:verify` mean this plugin's `verify` skill; when telling the user to
run one, render your harness's invocation for it (Claude Code: `/dev:verify`; Codex: `$verify`).

Read first: `.agent-toolkit/dev.md` (tracker routing config; legacy fallbacks:
`.agent/dev.md`, then `.claude/dev.md` when absent), the plugin's `runtime_contracts/tracker.md`, and the
plugin's `runtime_contracts/project-bootstrap.md`. On Claude Code these plugin docs are under
`${CLAUDE_PLUGIN_ROOT}/runtime_contracts/`; equivalently they are under `../../runtime_contracts/` relative to this
skill's directory. Scope: one task (`task <id>`) or all `Done`/`Wont Do`/`Blocked` tasks in a
milestone (`milestone <n>`).

Before any repository or tracker call, resolve repository context once using `tracker.md`
"GitHub repository resolution". For an external contribution, read the canonical PR, linked
issue, review threads, CI, and comments explicitly from `github_primary_repo`; post the retro
comment there when GitHub permits. Local rule or context-file promotions remain ordinary file
changes submitted through the contributor's fork PR. Retro gains no merge, issue-closure,
queue-label, dependency, milestone, or other terminal-transition authority, regardless of the
authenticated permission.

For each task, fetch only enough task/PR identity to resolve its execution repository, then
follow `runtime_contracts/project-bootstrap.md` before mining evidence. Pass the completed diff's changed
paths, read every reported project instruction and loaded rule, and record the exact
`Execution repository:`, `Execution revision:`, and `Rules loaded:` entries in the retro comment.
Resolver failure, including an execution-revision mismatch, is a hard stop: check out the expected
revision, rerun, and never substitute another revision.

If the target task is not yet terminal (e.g. `In Review` awaiting merge), do not close it
out yourself - merging and `Done` belong to `dev:verify`, even if the user approves the
merge in this session. Direct them to run `dev:verify`, then retro after it finishes.

## 1. Gather evidence

Per task, in this order of value:

1. **Tracker comments:** the work-summary comment (decisions, obstacles, spec gaps), Blocked
   diagnostics, verification report, Wont Do rationales.
2. **PR review threads:** every finding is a signal - what did the reviewer catch that the
   executor should have known up front?
3. **CI history:** failure runs on the task branch (`gh run list --branch task/<id>-*`, with
   `--repo "$github_primary_repo"` in active fork routing);
   recurring failure classes (env setup, flaky test, missing migration) matter more than
   one-offs.
4. **Session transcripts** (best effort, current harness only): grep this harness's own
   session store by content for the task id, to reconstruct why something took N attempts -
   Claude Code: content-grep the `*.jsonl` under this repo's own slug in `~/.claude/projects/`
   AND under any sibling slug sharing this repo's path prefix - `dev:execute` runs the task in
   a worktree whose slug is a distinct directory (e.g. `<repo-slug>-worktrees-<branch>` or
   `<repo-slug>-.claude-worktrees-...`), so the execution transcript lives outside the
   repo-root slug and a repo-root-only search misses it; do NOT widen to unrelated projects'
   slugs, whose task ids can collide with yours. Codex: content-grep
   `~/.codex/sessions/**/*.jsonl` for the task id (flat date-partitioned tree with no
   per-project split; grep the entire tree). Skip silently if the store is
   absent or unreadable. This source is **machine-local and single-harness**: do not try to
   read another provider's session store (Codex `~/.codex/sessions/` under Claude, or vice
   versa) - bridging proprietary, undocumented session formats across providers is not worth
   it. A retro on a different machine, or after the work ran under a different harness, simply
   won't have transcripts, and that is fine: the promoted rules plus the durable server/git
   evidence (tracker comments, PR threads, CI, contract compliance) and the mandatory
   `dev:execute` work-summary comment carry the important signal.
5. **Lifecycle-contract compliance:** check what each lifecycle step actually produced
   against its skill's contract - verification report present on the PR, human-gate DoD
   boxes checked, work-summary comment posted, `status:*` labels stripped at terminal
   states, worktree/branch cleanup done. This includes steps that ran in the current
   session: a retro that audits the task but not the process running around it misses
   exactly the failures no other step will catch. A skipped contract step is a finding
   even when the outcome looks fine.

## 2. Distill

For each friction point or success, ask: root cause, and would a future session hit it again?
Classify each learning:

- **Project rule** - generalizable constraint or convention ("integration tests need
  `docker compose up db` first", "API errors follow shape X"): candidate for promotion.
- **Packet-quality lesson** - the packet was wrong/thin (untestable DoD, missing dependency):
  candidate for the planning conventions in the `.agent-toolkit/dev.md` body.
- **Process tuning** - config change (`work_in_progress_limit`, `max_fix_attempts`, test command).
- **One-off** - bad luck, no generalization: record in the retro comment, promote nothing.
- **Follow-up work** - a defect or gap in already-merged work, or new work the evidence
  exposes (e.g. a parity check reveals an earlier task diverged from spec): not a rule, a
  task. Route it through `dev:backlog` intake so it lands in the tracker with a packet.
  A memory note or a mention in the retro comment is not a destination for work - an
  untracked follow-up is exactly the state-outside-the-tracker failure this plugin exists
  to prevent.
- **Skill-contract violation** - a lifecycle step skipped or botched something its skill
  already mandates (section 1 item 5): never a project-rule candidate. The instruction
  already exists in the skill; promoting a rule that restates it creates a second source
  of truth that drifts, and masks the real defect - the skill let the step be skipped.
  Record the violation in the retro comment and route the defect upstream to the dev
  plugin (fix or file against the skill), not into the rules directory. Only
  project-specific knowledge the skill cannot know belongs in a rule.

## 3. Promote (the point of this skill)

Promotion targets, by `memory_target` in `.agent-toolkit/dev.md` (default `files`):

- **`files`:** write one atomic rule per file in `<rules_dir>/<slug>.md` (a rule future
  sessions must obey; `rules_dir` from `.agent-toolkit/dev.md`, default
  `.agent-toolkit/rules/` when the field is absent). Writing the file with `tier` frontmatter
  is the whole promotion - the resolver discovers every Markdown file under `rules_dir`, so
  there is no registration step and never an `@` import line to append. Do not edit the
  `## Rules` section; it is not a registry. Pointers and summaries that are not
  rules go in the `dev.md` conventions body. Never write rules or summaries into
  `AGENTS.md`/`CLAUDE.md` themselves - those files are project-owned, and the plugin's only
  line there is the `dev:setup` reference line. Legacy configs: when the config still lives
  at `.agent/dev.md` or `.claude/dev.md` with both memory fields absent, fall back to
  `.claude/rules/` + `CLAUDE.md` (the pre-port behavior, kept as a safety net); when it
  sets `context_file` but omits `rules_dir` (the 0.0.42-0.0.53 mixed config that
  consolidated rules inside the context file), do NOT write rule files: no
  `.agent-toolkit/dev.md` exists there, so `rules_dir` is undefined and a new rule file has
  no discoverable home. Leave existing consolidated rules
  where they are, list the promotions in the retro comment as "proposed, blocked on config
  migration", and tell the user to run `dev:setup` (it performs the migration); apply the
  promotions only once the migrated config exists.
  Check existing rules first - update or strengthen rather than duplicate; delete rules the
  evidence now contradicts.
- **MCP memory** (`mem0`, `openbrain`, `memsearch`, …): store each learning via that system's
  MCP tool; recall is that system's job. Still write rules that gate correctness to the file
  target (`rules_dir`, legacy fallback `.claude/rules/`) - files are the only target every
  future session is guaranteed to load.

Every new or updated file rule follows `runtime_contracts/project-bootstrap.md` discovery. Use
`tier: doctrine` only when the rule applies to every lifecycle invocation. Otherwise use
`tier: gotcha` with the narrowest deterministic `paths`, `objective`, and/or
`definition_of_done` triggers that cover the cited failure. Do not create a trigger-free
gotcha, and never write an unclassified file into `rules_dir`: discovery hard-stops on it, so
an unclassified promotion breaks every later lifecycle run in the project.

Standards for a promotable learning: evidence-cited (link the PR finding / CI run / comment),
generalizable beyond the one task, and actionable as an instruction ("run X before Y"), never
vibes ("be careful with the database"). Propose the exact diff per promotion. Post the retro
comment (section 4) BEFORE asking for approval, with each promotion listed as "proposed, not
applied" - stopping the turn to ask is how a drafted retro ends up existing only in chat.
Apply on approval, then append the follow-up comment per section 4.

**Commit applied promotions immediately** (with the user's consent, as with every gate): one
dedicated commit on `main` for the rule files, before any next task starts -
and with a remote, push it: task worktrees branch from local `main`, so an unpushed
promotion commit silently rides into the next task's PR diff. Task
worktrees check out `main`'s committed HEAD, so an uncommitted rule is invisible to the next
executor - the loop you just closed silently stays open - and the stray file eventually gets
swept into an unrelated commit by whatever writes to `main` next.

## 4. Record

Post a retro comment on the task (or each milestone task): execution repository and revision,
exact `Rules loaded:` list, what worked, what did not, root causes, learnings promoted (with rule
file names), learnings recorded-only. Milestone scope:
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
