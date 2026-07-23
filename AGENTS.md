# AGENTS.md

Authoring conventions for this repository - the single source of truth for every harness.
Codex reads this file natively; Claude Code loads it through the one-line `@AGENTS.md`
import that is `CLAUDE.md`'s entire body (Claude Code does not auto-load `AGENTS.md`
directly). Do not add content to `CLAUDE.md`; it belongs here. Install and invocation
details live in the repo `README.md`.

Dev workflow (agent-toolkit dev plugin): @.agent-toolkit/dev.md

## Versioning

All version fields use semver (`major.minor.patch`). Always use the minimum increment:
- Bug fixes, typos, doc updates: patch (`0.0.1` → `0.0.2`)
- New skills, features, non-breaking additions: minor (`0.0.2` → `0.1.0`)
- Breaking changes (renamed skills, removed features, restructured plugin): major

While in pre-release (`0.0.x`), use patch for everything including new features. Save
minor/major bumps for after the plugin has real consumers.

Each plugin's release version lives in exactly three fields, which must stay in lockstep:
- the plugin entry in `.claude-plugin/marketplace.json`
- `plugins/<name>/.claude-plugin/plugin.json`
- `plugins/<name>/.codex-plugin/plugin.json`

The marketplace-level `.claude-plugin/marketplace.json` `metadata.version` is an independent
semver catalog version. It is not required to match any plugin release version. The
Codex-native `.agents/plugins/marketplace.json` has no version field.

## Structure

```
.agent-toolkit/         # this project's dev-plugin state (dev.md config + rules/)
.claude-plugin/         # Claude marketplace manifest
.agents/                # Codex-native marketplace manifest (plugins/marketplace.json)
AGENTS.md               # this file - conventions SSOT for all harnesses
CLAUDE.md               # one-line @AGENTS.md import (Claude Code entry point)
dist/                   # generated / copy-me artifacts, not plugin-installable
  codex/agents/         #   Codex agent TOMLs (copy to ~/.codex/agents/ or project .codex/agents/)
.codex/agents/          # generated project-scoped Codex agents
plugins/<name>/         # Each plugin
  .claude-plugin/       #   Claude plugin manifest (plugin.json)
  .codex-plugin/        #   Codex plugin manifest (plugin.json)
  skills/               #   Skill directories, each with SKILL.md
  README.md             #   Plugin docs
```

## Skills

Each skill is a directory under `plugins/<plugin>/skills/<skill-name>/` containing at minimum
a `SKILL.md` with YAML frontmatter (`name`, `description`) and markdown body.

Skill directory names can be CJK (e.g. `回顧/`); Claude Code and Codex load them as-is.
Never rename a skill in `plugins/`.

Skill prose must stay harness-neutral: refer to skills as `dev:verify` (not `/dev:verify`),
render harness-specific invocations only when addressing the user, and gate any
Claude-Code-only capability (`/loop`, worktree isolation, `run_in_background`) behind a
harness-note so other harnesses degrade gracefully. Subagent spawning exists on both
harnesses (Claude Code: Agent tool; Codex: `spawn_agent`/`wait_agent` with `agent_type`
selecting a copied agent TOML, default nesting depth 1) - express orchestration as
"dispatch and wait", not in one harness's parameters.

Task-scoped lifecycle skills share `plugins/dev/runtime_contracts/project-bootstrap.md`. Do not duplicate its
execution-repository or rule-selection algorithm inside individual skills. Promoted rule files
use `tier: doctrine` for unconditional loading or `tier: gotcha` with deterministic `paths`,
`objective`, and/or `definition_of_done` triggers. Codex correctness must not depend on `@`
import expansion. Resolver failure, including an execution-revision mismatch, is a hard stop that
every skill invoking the bootstrap must state at its point of use: a skill that only references
the contract cannot be relied on to carry its stop conditions. Keep the stop clause, the
resolver's own error text, and `resolve_project_rules.py` in lockstep; never substitute another
revision to get past the resolver.

GitHub work-summary classification must follow `plugins/dev/runtime_contracts/tracker.md` "Trusted GitHub
work-summary routing". Do not treat the latest comment containing `Queue classification:` as
authoritative without its author, PR identity, branch, and revision binding. Planned review must
also require exactly `status:in-review`; review reports other states without repairing them.

Primary-GitHub planned-task lifecycle writes share
`plugins/dev/scripts/github_task_lifecycle.py` and the contract in `plugins/dev/runtime_contracts/tracker.md`.
Do not duplicate label validation or treat a missing `status:*` label as external-contribution
routing inside individual skills.

Standalone GitHub PR merge and branch cleanup share `plugins/dev/scripts/github_pr.py` and the
`dev:merge-pr` skill. The helper exposes independent `merge`, `cleanup`, and `merge-cleanup`
operations and has no tracker dependency. `dev:verify` may call the same helper only after its own
evidence and approval gates. Do not reproduce the helper's guarded `gh`/`git` sequence in skills
or agent instructions.

Manual `dev:review-pr` invocations are single-pass lifecycle actions. Review mode posts one
verdict and stops; fix mode applies one current findings batch, requests or records the need for
re-review, and stops. Only `dev:auto` may chain separate review and fix invocations, and its loop
must remain bounded by `max_fix_attempts`.

`dev:review-pr` and the `reviewer` agent share one BLOCKER-severity discipline; keep the skill
rubric and the agent's Quality Standards in lockstep. A BLOCKER must cite the DoD/spec clause the
diff violates or a regression it introduces, and state a concrete failure scenario; a scenario
mapping to no clause and no regression is at most a SUGGESTION. DoD criteria are judged at their
stated bar (for a qualitative criterion, the common and enumerated cases); residual completeness
gaps are SUGGESTIONs unless they defeat the criterion's core purpose. A defect fully caught by a
mandatory downstream gate the task ships (human approval, `dev:verify`) is at most a SUGGESTION
unless it defeats that gate. On a re-review, prior findings bound the pass: raise regressions,
genuinely new findings, or still-unaddressed prior findings, never a fresh edge case of a category
already pushed on, and never a resolution that contradicts a prior pass.

Definition-of-Done quality is a shared contract across `dev:plan`, `dev:backlog`, and
`dev:execute`. `dev:plan` and `dev:backlog` author DoD criteria that are checkable, evidence-named,
and carry a decidable acceptance bar - a qualitative or completeness criterion (redaction,
validation, error handling) must enumerate the classes or cases it covers. `dev:execute`'s
claim-time packet validation rejects a missing DoD, a "works correctly"-class criterion, or an
open-ended bar the same way it rejects a missing Objective. Keep the three in lockstep: an
unbounded DoD admitted at claim time is what prevents review from converging downstream.

`dev:shadow` is an evaluation surface, not a lifecycle skill. Its deterministic steps live in
`plugins/dev/scripts/shadow_replay.py` and its contract in `plugins/dev/runtime_contracts/shadow.md`; the
skill never merges a shadow PR, never mutates the source issue or original PR, and never enters
the planned-task queue. Shadow issues carry `experiment:shadow`, no `status:*` label, and no
milestone; the candidate PR stays draft and `do-not-merge`, targets its `shadow-base` branch, and
references the shadow issue with `Refs`, never `Closes`. Do not label a shadow item `planned`,
`external`, or `secondary` to satisfy a `reviewer`/`verifier` planned-task contract; carry the
review or verify contract into a fresh generic worker instead. `check_repo.py` runs
`tools/test_shadow_replay.py`; keep those network-free fixture tests green.
Open the shadow PR only after the first candidate commit is pushed; bind and re-read the exact
head repository so fork-qualified candidate branches cannot be confused with same-named upstream
branches.

`dev:feedback` is not a lifecycle skill. It files issues only in `wilsonkichoi/agent-toolkit`,
never mutates the current project's tracker, and does not use the project bootstrap sequence.
Its deterministic helpers live in `plugins/dev/scripts/feedback_redact.py`; `check_repo.py` runs
`tools/test_feedback_redact.py`. The draft helper applies redaction to all fields including the
title; never pass untrusted text as shell arguments to the helper.

## Repository tools

Agent Markdown files under `plugins/*/agents/` are authoritative. Regenerate both the
project-scoped `.codex/agents/` files and distributable `dist/codex/agents/` files with:

```bash
uv run tools/generate_codex_agents.py
```

Check generated-file drift without writing, then validate manifests, marketplaces, versions,
skill frontmatter, agent sources, and shared authoring invariants with:

```bash
uv run tools/generate_codex_agents.py --check
uv run tools/check_repo.py
```

Both tools are dependency-free PEP 723 scripts. Do not add a project `pyproject.toml`,
`.python-version`, `uv.lock`, or script lockfile for them.

## Git workflow

Never commit or push directly to `main`, on any harness, even with admin rights. The canonical
repository's `main pull request gate` ruleset blocks direct pushes for everyone (its `bypass_actors`
list is empty), so a direct push is rejected and any commit landed on a local `main` has to be
unwound. Always:

1. Branch from an up-to-date `main` (`git checkout -b <type>/<slug>`, e.g. `docs/...`, `feat/...`).
2. Commit on the branch, push it, open a pull request against `main`.
3. Let the `repository-validation` check pass and keep the branch current; the ruleset requires a
   strict, non-stale branch, so merge or rebase `origin/main` in whenever GitHub reports the branch
   out of date.

Merging is a human decision. An AI agent may prepare the branch, PR, and green checks, but must not
merge to `main` unless the human explicitly asks. Full ruleset behavior and the one-time maintainer
setup live in `CONTRIBUTING.md`.

## Pre-commit checklist

Before any commit that adds, removes, or modifies files under `skills/` or `agents/`:

1. Version bumped in `plugins/<plugin>/.claude-plugin/plugin.json`
2. Same version mirrored in `plugins/<plugin>/.codex-plugin/plugin.json`
3. Version bumped in `.claude-plugin/marketplace.json` (matching entry)
4. `plugins/<plugin>/README.md` updated
5. Agent sources changed? Regenerate `.codex/agents/*.toml` and `dist/codex/agents/*.toml`
6. `.claude-plugin/marketplace.json` description/keywords updated if needed
7. `README.md` (repo root) and `AGENTS.md` updated if plugin behavior/description changed

Do not commit skill changes without completing this checklist. Read the checklist, don't rely
on memory.
