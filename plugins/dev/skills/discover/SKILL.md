---
name: discover
description: >
  This skill should be used when the user asks to "organize my research", "turn this research
  into a PRD", "clarify the product idea", "figure out what we're building and why", "define
  the north star", "update the PRD", or invokes /dev:discover. Ingests raw research materials,
  closes gaps by interviewing the user, and produces docs/PRD.md: goal, why, customer value,
  north star, and non-goals. Business clarity only; no technical design.
argument-hint: "[delta <change summary>]"
---

# dev:discover

Turn raw research plus the user's head-knowledge into `docs/PRD.md`. The objective is
clarity about what the product is for, who it serves, and why it should exist. Explicitly
out of scope: architecture, stack, schemas, technical feasibility beyond obvious
deal-breakers - `/dev:architect` owns those. When technical topics come up, capture them as
notes for the architect and steer back.

## 1. Ingest

Inventory `research/raw/` (and `wiki/` if the project keeps an LLM wiki): markdown, PDFs,
images, exports. Read everything; for large collections, skim structure first and read
depth-first where the product intent lives. Build a working map: recurring themes, claimed
problems, competitor observations, constraints, contradictions between sources, and what the
materials do NOT establish. If `research/raw/` is empty, say so and interview from zero
rather than refusing.

## 2. Interview

Close the gaps with AskUserQuestion, in rounds of at most 4 questions, most load-bearing
first. Required coverage before drafting:

- **Problem:** what pain, for whom, how is it handled today?
- **Customer:** who exactly; who is it NOT for?
- **Value:** what changes for the customer; why would they switch or pay?
- **North star:** the single metric (or observable outcome) that says the product is
  working.
- **Non-goals:** what this product deliberately will not do or be.
- **Constraints:** budget, timeline, regulatory, distribution.

Challenge weak answers once ("competitor X already does this; what is different?") - the PRD
is worthless if it records wishes instead of decisions. Accept the user's call after the
challenge.

## 3. Draft `docs/PRD.md`

```markdown
# PRD: <product>
## Problem
## Target customer          # and who it is not for
## Value proposition
## North star               # one metric/outcome, how it would be observed
## Goals                    # ranked, outcome-phrased
## Non-goals
## Constraints & assumptions
## Open questions           # unresolved, owner-tagged
## Notes for architecture   # technical topics parked during discovery
## Sources                  # research/raw files this PRD draws on
```

Every claim that came from research cites its source file; every decision that came from the
interview stands on its own. Keep it under ~200 lines: a PRD that nobody re-reads is ADW's
retro problem again.

## 4. Human gate

Present a summary (problem, customer, value, north star, top non-goals) and the open
questions. Iterate on feedback in place. The PRD is approved when the user says so; record
the approval date at the top of the file. Next step: `/dev:architect`.

## Delta mode (`delta <change summary>`)

For goal-impacting changes routed from `/dev:backlog`: re-open only the affected sections,
interview for the specific change, update the PRD with a dated `## Change log` entry (what
changed, why, what it invalidates), and flag downstream impact: SPEC sections and existing
tasks that now contradict the PRD, handed back to `/dev:backlog` triage and `/dev:architect`.
