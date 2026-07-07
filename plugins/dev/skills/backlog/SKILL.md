---
name: backlog
description: >
  This skill should be used when the user asks to "add a ticket", "add a task for X", "we got
  a new request", "reprioritize", "pull task <id> into this milestone", "mark <id> as won't
  do", "split this task", "triage the backlog", or invokes /dev:backlog. Mid-flight change
  management: intake requests with full task packets, triage their impact (backlog-only vs
  spec vs product goal), promote Backlog to Todo, and close tasks as Wont Do with rationale.
argument-hint: "[add <request> | #N | promote <id> | wont-do <id> | split <id> | triage]"
---

# dev:backlog

Change management between planning cycles. The product recalibrates here instead of
re-running the whole pipeline. Docs stay the source of truth for intent, the tracker for
state; this skill's job is keeping the two consistent while requests arrive.

Read first: `.claude/dev.md`, `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md`, and skim `docs/PRD.md`
and `docs/SPEC.md` headings; triage is impossible without knowing current intent.

## Intake (`add <request>`, or a batch of requests)

For each request:

1. **Triage impact** against the docs:
   - **Goal-impacting** - it changes what the product is for, who it serves, or a non-goal in
     `docs/PRD.md`. Stop: summarize the needed PRD delta and direct the user to
     `/dev:discover`; re-run intake after the PRD is updated. Do not create the task first.
   - **Spec-impacting** - it needs new architecture, contracts, or contradicts `docs/SPEC.md`
     (including PRD non-goals' technical enforcement). Stop: summarize the needed SPEC/ROADMAP
     delta and the ADR it warrants, direct to `/dev:architect`, re-run intake after.
   - **Backlog-only** - fits current PRD and SPEC. Proceed.

   At a goal- or spec-impacting verdict, always offer declining the request as the
   alternative to running the doc delta: the human may not want the change at all once its
   real cost is visible. Declining an existing ticket = `Wont Do` with the triage rationale;
   declining a ticketless request = record the decision in the triage summary.
2. **Write a full task packet** (DESIGN.md schema: objective, why with PRD/SPEC link, DoD
   with evidence paths, dependencies, estimate, inlined spec excerpts, suggested steps).
   Ask the user only for what the docs cannot answer. Genuine unknown blocking the packet →
   create a spike instead.
3. **Create at `Backlog`** via `create-task`. Create at `Todo` only when the user explicitly
   commits it to the current milestone in this conversation; say which status was used.

After intake (and after any doc delta returns from `discover`/`architect`), commit the
new/changed files - local-backend task files and doc deltas - to `main` with the user's
consent; approved-but-uncommitted artifacts strand downstream skills.

## GitHub issue intake (`#N`, secondary channel)

Only when `secondary_intake: github` is set with a non-github primary tracker
(`${CLAUDE_PLUGIN_ROOT}/docs/tracker.md` "Secondary intake channel"). `gh issue view <n>` for the request, then run the same triage
above and route to exactly one of three fates:

- **Promote** - real planned work (needs design, touches the spec, belongs to a milestone, or
  blocks tracked work; any goal- or spec-impacting verdict lands here after its doc delta).
  Write a full primary-tracker packet, link the issue in it, and close the issue as transferred
  with a comment naming the new ticket. From here it is a normal primary-tracker task. If a PR
  already exists for the item, link the new ticket to that PR rather than opening a second one.
- **Work in place** - isolated and self-contained. Do not create a primary ticket; recommend
  `/dev:execute #<n>`. GitHub owns it end to end.
- **Decline** - `Wont Do`: close the issue with the triage rationale (`gh issue close`).

Promotion is the *only* path that pulls a GitHub issue into `discover`/`architect`/`plan`; an
in-place item never runs them.

## Promote (`promote <id>`)

`Backlog → Todo` is always an explicit human decision; this is its skill-side path.

1. Re-check the packet is still complete and consistent with the current SPEC (docs may have
   moved since intake).
2. Check dependencies: every dep is `Done`, or at least planned in the current milestone.
   Missing dep → tell the user what must be created or promoted alongside.
3. Set milestone/priority per the user's instruction, `transition <id> Todo`, and report
   where it lands in the next-task order.

## Wont Do (`wont-do <id>`)

Require a rationale (ask if not given). Comment the rationale on the task, then transition to
`Wont Do` (backend mapping: Linear `Canceled`, GitHub closed as "not planned" plus removing
the remaining `status:*` label - closed issues carry none, see `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md`). The reason
must survive; a bare closure is not acceptable. If the task encodes a spec requirement being
abandoned, flag that `docs/SPEC.md` needs a matching edit and offer the delta summary for
`/dev:architect`.

## Split (`split <id>`)

When a task is too big or half-blocked: write full packets for the children, wire their
dependencies, create them at the parent's status, cross-reference parent and children by
comment, then close the parent as `Wont Do` with rationale "split into <ids>" (or keep it
open as a tracking parent only if the backend has real sub-task support and the user wants
that).

## Triage sweep (`triage`)

Periodic hygiene over everything in `Backlog`: for each task, re-run the intake triage
against the current docs. Report per task: still valid / needs PRD delta / needs SPEC delta /
stale (candidate for `Wont Do`) / missing packet fields. Propose actions; apply only what the
user approves. This is also the check that catches manually created tickets drifting from the
spec.
