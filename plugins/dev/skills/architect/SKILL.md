---
name: architect
description: >
  This skill should be used when the user asks to "design the architecture", "write the tech
  spec", "create the roadmap", "generate SPEC.md", "make an ADR", "update the spec for this
  change", or invokes /dev:architect. Turns an approved PRD into docs/SPEC.md (architecture,
  contracts, NFRs, negative requirements, diagrams), docs/ROADMAP.md (milestones), and ADRs
  for contested choices. Docs only; writes no product code.
argument-hint: "[delta <change summary>]"
---

# dev:architect

Turn the approved PRD into buildable technical intent: `docs/SPEC.md`, `docs/ROADMAP.md`, and
ADRs. This is the highest-leverage gate in the lifecycle - a bad spec cascades into every
packet `dev:plan` writes. Docs only: produce no product code, no scaffolding.

Skill references like `dev:plan` mean this plugin's `plan` skill; when telling the user to run
one, render your harness's invocation for it (Claude Code: `/dev:plan`).

Preconditions: `docs/PRD.md` exists and is approved (else stop, direct to `dev:discover`).
Brownfield: read the current-state SPEC.md from setup archaeology; the spec being written
here extends or replaces it, and must say which.

## 1. Interview

One structured question round (use the harness's question tool, e.g. AskUserQuestion on Claude
Code) for what the PRD cannot answer: stack preferences and existing
expertise, deploy target and budget ceiling, team size, hard NFR floors (latency, uptime,
data residency), integration constraints. Read the PRD's "Notes for architecture" section
first; do not re-ask what it already answers.

## 2. Decide and record (ADRs)

For each choice with 2+ viable options where the tradeoff is real (database, hosting model,
auth approach, sync vs async pipeline, build-vs-buy), write `docs/adr/NNN-<slug>.md`:

```markdown
# ADR-NNN: <title>
Date / Status: proposed | accepted | superseded by ADR-NNN
## Context
## Options            # table: option, pros, cons, cost
## Decision           # what and why
## Consequences       # what this forecloses, risks accepted
```

Present contested decisions to the user before writing them into the spec; trivial choices
(formatter, directory naming) get no ADR. Spikes are the other escape hatch: a genuine
unknown that analysis cannot settle becomes a spike recommendation for `dev:plan`, noted in
the spec section it blocks.

## 3. Write `docs/SPEC.md`

```markdown
# SPEC: <product>
## Architecture overview    # prose + Mermaid diagram (components, data flow)
## Components               # per component: responsibility, interface, dependencies
## Contracts                # API shapes, schemas, events; frozen enough to plan against
## Data model               # entities, relationships, migrations approach
## Non-functional requirements   # measurable: latency, scale, cost, availability
## Security model           # authn/authz, secrets, data classification
## Negative requirements    # what the system is NOT and must not become (from PRD non-goals)
## Development environment  # language/toolchain, package manager, test runner, lint
## Deployment architecture  # environments, CI/CD shape, rollback
## Current state (brownfield only)  # relation to the archaeology spec: kept/replaced/debt
```

Diagrams in Mermaid inside the markdown. Every PRD goal maps to at least one component or
contract; every PRD non-goal to a negative requirement. Contracts that later tasks build
against must be concrete (fields, types, error shapes), because `dev:plan` inlines them
into packets verbatim.

## 4. Write `docs/ROADMAP.md`

Milestones as deployable increments, each: outcome (user-visible or operationally
verifiable), scope (which spec components/contracts), success criteria, explicit
out-of-scope. Order by risk: the milestone that retires the biggest unknown ships first.
2-5 milestones; a 10-milestone roadmap at this stage is fiction.

## 5. Update the context file and gate

Add or refresh the architecture pointer in the project context file named by `context_file`
in `.agent/dev.md` (legacy fallback: `.claude/dev.md`; safety-net fallback `CLAUDE.md` when the field is absent,
for legacy or hand-written configs; `AGENTS.md` on Codex): 5-10 lines summarizing the architecture
and linking to SPEC/ROADMAP/ADRs; keep the context file lean. Then the human gate: present
the architecture summary, the contested ADRs, and the milestone order. This gate deserves a
line-by-line review; say so. Record approval date in SPEC.md, then commit the approved docs
(SPEC, ROADMAP, ADRs, context-file update) with the user's consent before ending.
Next step: `dev:plan` for milestone 1.

## Delta mode (`delta <change summary>`)

For spec-impacting changes routed from `dev:backlog`: edit only the affected SPEC/ROADMAP
sections, write an ADR when the change reverses or constrains a prior decision, append a
dated change-log entry to SPEC.md, and report which existing tasks (via `list` on the
tracker) now contradict the spec so `dev:backlog` can re-triage them.
