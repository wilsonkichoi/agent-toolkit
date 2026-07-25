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

Skill references like `dev:architect` mean this plugin's `architect` skill; when telling the
user to run one, render your harness's invocation for it (Claude Code: `/dev:architect`; Codex: `$architect`).

Read first: `.agent-toolkit/dev.md` (tracker routing config), the plugin's
`runtime_contracts/tracker.md`, and the
plugin's `runtime_contracts/project-bootstrap.md`. On Claude Code these plugin docs are under
`${CLAUDE_PLUGIN_ROOT}/runtime_contracts/`; equivalently they are under `../../runtime_contracts/` relative to this
skill's directory.

Before any repository or tracker call, resolve the repository context once using
`tracker.md` "GitHub repository resolution". In active fork routing, every issue read,
creation, comment, edit, or close explicitly targets `github_primary_repo`. Do not substitute
the secondary-intake `github_repo` field.

For operations on an existing task (`#N`, `promote`, `wont-do`, `split`, or `triage`), fetch
only enough task identity to resolve its execution repository, then follow
`runtime_contracts/project-bootstrap.md` before reading project intent or making a triage decision. Changed
paths are empty unless a linked PR supplies them. Read every reported project instruction and
loaded rule, and include the exact `Execution repository:`, `Execution revision:`, and
`Rules loaded:` entries in the triage diagnostic or task comment. Resolver failure, including an
execution-revision mismatch, is a hard stop: check out the expected revision, rerun, and never
substitute another revision. New ticketless `add` requests
have no execution repository yet and
continue to use the current project's instructions. After that resolution, resolve intent
sources before any triage decision (see **Intent source resolution** below); triage is
impossible without knowing current product intent.

## Intent source resolution

Triage requires product intent documents. Resolve them in order:

1. **Default path (same repository).** When the resolved execution repository and the tracker
   repository are the same, check for `docs/PRD.md` and `docs/SPEC.md` in that repository at the
   execution revision. If both exist, read them. No prompt, no override.
2. **Default path (split repository).** When the resolved execution repository differs from the
   tracker repository, the tracker repository's `docs/PRD.md` and `docs/SPEC.md` are the default
   intent sources, not alternates. If present there and absent in the execution repository, read
   them from the tracker repository at its `HEAD`. No prompt, no override. Containment and
   revision binding apply per source repository: execution-repository sources bind to the
   execution revision, tracker-repository sources to the tracker repository's `HEAD`.
3. **Stop before mutation.** If either default file is absent in both repositories (or the only
   resolved repository), stop before any triage mutation. Never silently treat the issue body,
   README, or agent judgment as product intent. Report which files are missing and from which
   repository.
4. **Explicit override.** The human may approve alternate intent sources in the current
   conversation, or the project configuration (`.agent-toolkit/dev.md` body) may name approved
   sources under an `## Intent sources` section:

   ```markdown
   ## Intent sources
   - AGENTS.md
   - docs/adr/001-architecture.md
   ```

   Each approved source must be a repository-relative file inside the resolved execution
   repository (at the exact execution revision) or the tracker repository (at `HEAD`). Read
   every approved source before triage. Reject:
   - A missing file (does not exist at the bound revision).
   - A path that escapes the repository (`../`, absolute, symlink outside the tree).
   - A source in neither the execution repository nor the tracker repository.

5. **Sufficiency check.** After loading alternate sources, all existing triage gates still apply
   (goal-impacting, spec-impacting, backlog-only, packet-completeness, bidirectional-dependency,
   promotion). If the approved sources do not decide one of those questions, stop and name the
   unresolved decision.

**Durable diagnostic.** Every triage diagnostic or task comment using alternate sources (or the
split-repository default path) includes an `Intent sources:` entry listing the exact
repository-relative files and naming the repository each came from. When the execution repository
has no PRD/SPEC and the tracker repository supplied them, the entry states that, rather than
reporting an override that did not occur. The existing `Execution repository:`, `Execution
revision:`, and `Rules loaded:` entries remain mandatory.

**Coverage.** This resolution applies to new ticketless intake, existing-task triage, packet
repair, promotion, split, and triage sweeps. Read-only external-contribution routing retains its
existing mutation restrictions.

## External contribution intake (`add <request>` in read-only fork mode)

When primary-GitHub fork routing is active and the authenticated user lacks upstream write
permission, `add` creates an external contribution proposal, not a maintainer-queue task. Triage
the request against PRD/SPEC as usual, then create one packet-complete issue in the canonical
repository with:

- `## Objective`
- `## Why`
- `## Definition of Done`
- `## Relevant references`
- `## Suggested implementation`

The `## Definition of Done` must meet the same standard `dev:plan` requires: checkable,
evidence-named criteria with a decidable acceptance bar (qualitative criteria enumerate the
cases they cover), so `dev:execute`'s packet-validation gate admits it without a round of
tightening. Use `gh issue create --repo "$github_primary_repo"`. Apply no `status:*`, priority, or size
label, no milestone, no dependency relation, and no assignee. The contributor does not need
assignment, queue promotion, milestone placement, or maintainer approval before running
`dev:execute #<n>`. Report the canonical issue URL and stop. If goal or spec triage requires a
document change, the contributor may make that local change through `dev:discover` or
`dev:architect` and submit it through the fork PR path, but must not mutate the maintainer queue.

Existing queue triage, reprioritization, `promote`, `wont-do`, and `split` are maintainer
operations in fork-configured projects. If upstream write permission is absent, stop before the
first mutation and provide a maintainer handoff containing the requested operation and evidence.
Read-only users may still read and comment on canonical contribution issues when GitHub permits;
they never apply queue metadata or terminal state.

## Intake (`add <request>`, or a batch of requests)

For each request:

1. **Triage impact** against the docs:
   - **Goal-impacting** - it changes what the product is for, who it serves, or a non-goal in
     `docs/PRD.md`. Stop: summarize the needed PRD delta and direct the user to
     `dev:discover`; re-run intake after the PRD is updated. Do not create the task first.
   - **Spec-impacting** - it needs new architecture, contracts, or contradicts `docs/SPEC.md`
     (including PRD non-goals' technical enforcement). Stop: summarize the needed SPEC/ROADMAP
     delta and the ADR it warrants, direct to `dev:architect`, re-run intake after.
   - **Backlog-only** - fits current PRD and SPEC. Proceed.

   At a goal- or spec-impacting verdict, always offer declining the request as the
   alternative to running the doc delta: the human may not want the change at all once its
   real cost is visible. Declining an existing ticket = `Wont Do` with the triage rationale;
   declining a ticketless request = record the decision in the triage summary.
2. **Write a full task packet** (task packet schema in runtime_contracts/tracker.md: objective, why with PRD/SPEC link, DoD
   with evidence paths and a decidable acceptance bar per `dev:plan` - qualitative criteria
   enumerate the cases they cover, dependencies, estimate, inlined spec excerpts, suggested
   steps).
   Model implicit ordering as a real dependency, checked in **both directions**: does this
   request build on existing `Backlog`/`Todo` tickets, and do existing tickets build on it?
   Ordering that lives only in the ticket prose is invisible to the next-task algorithm -
   unmodeled ordering is how tasks execute out of order and parallel sessions produce
   conflicting PRs. Ask the user only for what the docs cannot answer. Genuine unknown
   blocking the packet → create a spike instead.
3. **Create at `Backlog`** via `create-task`, wiring dependencies as native relations per
   the backend section of `runtime_contracts/tracker.md` (both directions from
   step 2, including new relations on *existing* tickets that this task blocks) - not as
   packet text alone. Create at `Todo` only when the user explicitly commits it to the
   current milestone in this conversation; say which status was used.

After intake (and after any doc delta returns from `discover`/`architect`), commit the
new/changed files - local-backend task files and doc deltas - to `main` with the user's
consent; approved-but-uncommitted artifacts strand downstream skills.

## GitHub issue intake (`#N`, secondary channel)

Only when `secondary_intake: github` is set with a non-github primary tracker
(`runtime_contracts/tracker.md` "Secondary intake channel"). `gh issue view <n>` for the request, then run the same triage
above and route to exactly one of three fates:

- **Promote** - real planned work (needs design, touches the spec, belongs to a milestone, or
  blocks tracked work; any goal- or spec-impacting verdict lands here after its doc delta).
  Write a full primary-tracker packet, link the issue in it, and close the issue as transferred
  with a comment naming the new ticket. From here it is a normal primary-tracker task. If a PR
  already exists for the item, link the new ticket to that PR rather than opening a second one.
- **Work in place** - isolated and self-contained. Do not create a primary ticket; recommend
  `dev:execute #<n>`. GitHub owns it end to end.
- **Decline** - `Wont Do`: close the issue with the triage rationale (`gh issue close`).

Promotion is the *only* path that pulls a GitHub issue into `discover`/`architect`/`plan`; an
in-place item never runs them.

This secondary-channel path is unchanged by primary-GitHub fork support. Its repository is
`github_repo`, not `github_primary_repo`; the two fields have distinct ownership semantics.

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
the remaining `status:*` label - closed issues carry none, see `runtime_contracts/tracker.md`). The reason
must survive; a bare closure is not acceptable. If the task encodes a spec requirement being
abandoned, flag that `docs/SPEC.md` needs a matching edit and offer the delta summary for
`dev:architect`.

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
