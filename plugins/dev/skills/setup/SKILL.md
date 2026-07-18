---
name: setup
description: >
  This skill should be used when the user asks to "set up the dev workflow", "initialize this
  project for dev", "run dev setup", "adopt the dev plugin", "configure the tracker", or
  invokes /dev:setup. Initializes a project (greenfield or existing/brownfield) for the dev
  plugin: scaffolds the docs layout, selects the tracker backend, and writes .agent-toolkit/dev.md.
argument-hint: "[project-dir]"
---

# dev:setup

Initialize a project for the dev plugin lifecycle. Idempotent: safe to re-run; never
overwrite existing files without asking.

Skill references like `dev:plan` mean this plugin's `plan` skill; when telling the user to run
one, render your harness's invocation for it (Claude Code: `/dev:plan`; Codex: `$plan`).

Read first: the plugin's `docs/tracker.md` — on Claude Code
`${CLAUDE_PLUGIN_ROOT}/docs/tracker.md` (the plugin's own `docs/` directory, two levels above
this skill), equivalently `../../docs/tracker.md` relative to this skill's directory — before
configuring the tracker. All `tracker.md` references below mean this plugin doc, never a file in
the project. Also read an existing `.agent-toolkit/dev.md` (legacy fallbacks: `.agent/dev.md`, then `.claude/dev.md`) before
making any repository or tracker call; setup must preserve choices the project already made.

## Harness specifics

Setup knows which harness it is running in; use the matching column below (referenced from
steps 2, 4, and 7). Step 6 (claude-review.yml) is unchanged across harnesses — the GitHub Action
runs server-side and only needs `ANTHROPIC_API_KEY`, regardless of the local harness.

| Concern | Claude Code | Codex |
|---|---|---|
| Linear MCP config | `claude mcp add` / plugin MCP | `codex mcp add` (writes `[mcp_servers]` in `~/.codex/config.toml`) |
| Pre-approve commands for unattended runs | `.claude/settings.json` permissions | approvals config + `.rules` command policy |
| Context file receiving the step 4 reference line | `AGENTS.md` default (+ `CLAUDE.md` import shim); `CLAUDE.md` on Claude-only projects | `AGENTS.md` |

## 1. Detect mode

Inspect the target directory (argument, default cwd):

- **Greenfield:** empty or near-empty (no source tree).
- **Brownfield:** existing code (source dirs, package manifests, git history).

## 2. Interview

Ask the user in one structured round (use the harness's question tool, e.g. AskUserQuestion on
Claude Code), only what cannot be inferred:

1. **Tracker backend:** `linear` / `github` / `local` / `custom`. If `linear`: team key and
   project name (and confirm the Linear MCP server is connected — see Harness specifics for how
   each harness configures it; if not, tell the user to add it and stop). If `github`: confirm `gh auth status` succeeds and the repo has a GitHub
   remote. If `custom`: point the user at the "Adding a backend" recipe in `tracker.md` and
   help write the mapping tables.
2. **Test command** (infer from the project if possible; confirm the inference).
3. **CI workflow file name** (brownfield: detect under `.github/workflows/`; greenfield:
   offer to create a minimal lint + test workflow).
4. **Merge policy:** squash (default) or merge commit.
5. **Secondary GitHub intake** (offer only when the primary tracker is not `github` and the
   repo has a GitHub remote): does the project accept isolated GitHub issues/PRs (external bug
   reports, drive-by PRs) worked in place, without a primary-tracker ticket? If yes, record
   `secondary_intake: github` + `github_repo: owner/repo`. See the "Secondary intake channel"
   section in `tracker.md`. Skip the question when the primary tracker already is `github`.
6. **Fork contributions** (offer only for `tracker: github`): does the canonical repository
   accept pull requests from contributor forks through the dev workflow? This is a project-owner
   policy choice, never inferred from the current clone. If yes, ask for and confirm the canonical
   `owner/repo`, then record `github_primary_repo` and `fork_contributions: true`. Validate the
   pair and repository topology using `tracker.md` "GitHub repository resolution". If the
   authenticated user lacks canonical write permission, do not treat their answer as authority to
   change repository settings; write only the selected project configuration and report the
   maintainer-owned setup separately.
7. **Context file:** which file is the project's agent-context entry point? Default
   `AGENTS.md` (Codex reads it natively; Claude Code reaches it through a one-line
   `CLAUDE.md` import - step 4). Choose `CLAUDE.md` for a deliberately Claude-Code-only
   project. A project that already has its own convention (e.g. an `AGENTS.md` that points
   at `CLAUDE.md`, or the reverse) keeps it: set `context_file` to the file every harness
   ultimately reaches, and never invert an existing direction. This decides only where the
   step 4 reference line goes - the plugin's own state always lives in `.agent-toolkit/`.

## 3. Scaffold

Create only what is missing:

```
docs/                  # PRD.md, SPEC.md, ROADMAP.md arrive via dev:discover / dev:architect
docs/adr/
research/raw/
.agent-toolkit/rules/  # promoted learnings (dev:retro), one file per rule
.dev/tasks/            # only when tracker: local
```

Everything the plugin owns lives under `.agent-toolkit/`; the project owns everything else,
its context files included. Add a `.gitkeep` in `.agent-toolkit/rules/` so git tracks the
directory before the first promotion. Removing the plugin from a project is: delete
`.agent-toolkit/` and the step 4 reference line.

**Existing projects:** when a legacy config exists (`.agent/dev.md` or `.claude/dev.md`, or
their `.local.md` variants), offer to `git mv` it to `.agent-toolkit/dev.md` (and
`.agent-toolkit/dev.local.md`, updating the `.gitignore` entry), then grep the repo for the
old path and update operative references (docs that tell agents to read the config) in the
same commit - historical records (changelogs, completed-work logs) stay as they are. Every
dev skill reads `.agent-toolkit/dev.md` first and falls back to the legacy paths, so the
migration is safe but optional. Full consumer-migration steps: "Migrating an existing
consumer" in the plugin's `docs/adoption.md`.

Write `.agent-toolkit/dev.md` with YAML frontmatter:

```markdown
---
tracker: github
test_command: "cd backend && uv run pytest"
ci_workflow: ci.yml
merge_policy: squash
review_action_installed: false # auto PR-review GitHub Action (claude-review.yml) is set up
work_in_progress_limit: 3      # max tasks simultaneously In Progress + In Review
max_fix_attempts: 3            # CI-fix or review-fix cycles before a task goes Blocked
max_tasks_per_run: 5           # batch cap for dev:auto and execute loop/batch mode
auto_merge: false              # standing merge approval for dev:auto (see that skill)
context_file: AGENTS.md        # project file carrying the step 4 reference line; CLAUDE.md on Claude-only projects
rules_dir: .agent-toolkit/rules/  # promoted learnings, one file per rule
---
Project conventions the fields cannot capture go here as free text.

## Rules

<!-- managed by dev:retro: one `@.agent-toolkit/rules/<slug>.md` import line per promoted rule -->
```

When Q6 enables fork contributions, add both fields below. Do not add either field when the
project owner did not opt in, and never repurpose `github_repo` for this role:

```yaml
github_primary_repo: owner/canonical-repo
fork_contributions: true
```

Reject `fork_contributions: true` unless `tracker: github` and `github_primary_repo` are both
present and valid. Reject `github_primary_repo` without `fork_contributions: true`; the pair is
the explicit opt-in boundary.

**Ownership rule (uniform across configs):** the project owns `AGENTS.md` and `CLAUDE.md`;
setup adds at most the single step 4 reference line there and never moves, consolidates, or
rewrites project rules or context-file content. `rules_dir` defaults to
`.agent-toolkit/rules/`; a project with an existing rules convention may point the field
elsewhere instead (e.g. `.claude/rules/`, which Claude Code auto-loads natively) - respect
the project's choice, and never migrate rule files between locations uninvited. When both
`rules_dir` and `context_file` are absent (legacy or hand-written configs), skills fall
back to `.claude/rules/` + `CLAUDE.md` as a safety net - not a recommended config; run
`dev:setup` to write explicit fields.

Add Linear fields (`linear_team`, `linear_project`) when applicable. When the user opted into
a secondary GitHub intake channel (interview Q5), add `secondary_intake: github`,
`github_repo: owner/repo`, and `audit_trail: link`. Do not create
`.agent-toolkit/dev.local.md`; mention it exists for personal overrides (gitignored).

Backend one-time setup:

- **github:** repository labels, milestones, Actions policy, rulesets, secrets, and other
  GitHub settings are canonical-repository state, separate from committed project files. Only an
  authenticated user with upstream write permission may create or reconcile them. Scope every
  command to the resolved canonical repository. Without that permission, create or update local
  files only and report the exact maintainer actions without attempting them. For the normal
  planned queue, create the label sets from `tracker.md` (`status:*`, `priority:*`, `size:*`)
  via `gh label create --repo "$github_primary_repo"` in fork-configured projects, or against
  the existing same-repository target when fork fields are absent. Fork contribution intake
  itself applies none of these labels.
- **local:** add `.dev/tasks/.gitkeep`.

## 4. Add the reference line

Add one line to the configured `context_file` so every session loads the dev config:

```
Dev workflow (agent-toolkit dev plugin): @.agent-toolkit/dev.md
```

On Claude Code the `@` import inlines `dev.md` (config frontmatter, conventions body, and
the rule imports its `## Rules` section carries) at session start; on other harnesses the
same line reads as an instruction with a path to follow. This line is the only edit setup
makes to a project context file. Brownfield: append it; touch nothing else. Greenfield (no
context file at all): create a lean one (< 50 lines) stating the project name, pointing to
`docs/PRD.md`, `docs/SPEC.md`, `docs/ROADMAP.md`, `docs/adr/`, and naming the tracker
backend, with the reference line at the end.

When `context_file: AGENTS.md` and Claude Code is (or may be) in use: Claude Code does not
auto-load `AGENTS.md`, so also ensure `CLAUDE.md` contains an `@AGENTS.md` import line -
seed a one-line `CLAUDE.md` when none exists, append the line when one exists, and never
replace an existing body.

## 5. Brownfield: architecture archaeology

Offer (do not force) to reverse-engineer the current state into `docs/SPEC.md`:

1. Survey the codebase: entry points, components, external services, data stores, contracts
   between components, test layout, build/deploy path.
2. Write `docs/SPEC.md` describing the **current** architecture: components, interfaces, data
   flow, known debt and gaps (marked clearly as debt, not requirements).
3. Do not invent forward-looking requirements - that is `dev:architect`'s job. A current-state
   spec is what makes later `dev:plan` packets honest against existing code.

If the project has an ADW `workflow/` tree or other planning docs, offer to map still-relevant
content into `docs/` and open items into the tracker as `Backlog` tasks.

## 6. Optional: automatic PR review (GitHub Action)

Offer when the repo is GitHub-hosted and a CI workflow exists. If accepted:

1. Copy `assets/claude-review.yml` (relative to this skill) to
   `.github/workflows/claude-review.yml`, replacing `{{CI_WORKFLOW_NAME}}` with the `name:`
   field inside the configured CI workflow (workflow_run matches by workflow name, not file
   name).
2. Tell the user to add the API key secret: `gh secret set ANTHROPIC_API_KEY` (add
   `--repo "$github_primary_repo"` in active fork configuration). Warn: each
   auto-review spends API tokens; the manual `dev:review-pr` path keeps working either way.
3. Set `review_action_installed: true` in `.agent-toolkit/dev.md` frontmatter.
4. Note that the template should be sanity-checked against the current
   `anthropics/claude-code-action` docs on first run.

Writing the workflow file is a local, reviewable change. Setting its secret or changing any
repository Actions setting is canonical-repository state and requires upstream write permission;
without it, leave those actions in the maintainer report and do not attempt them.

## 7. Report

Offer to commit the scaffold and config to `main` - in a fresh repo this creates the root
commit that later task branches need; leaving setup output uncommitted stalls `dev:execute`
mid-run. Then summarize: mode, tracker backend, files created, one-time backend setup
performed. Remind:

- Unattended runs (`dev:execute` loop/batch mode, `dev:auto`) stall on permission prompts -
  pre-approve the needed commands (git, gh, test command) first: on Claude Code in
  `.claude/settings.json`; see Harness specifics for the Codex equivalent. (`dev:auto`
  runs on Claude Code and Codex; `dev:execute` loop/batch mode is Claude-Code-only.)
- Next steps: `dev:discover` (new product), `dev:architect` (have a PRD), or `dev:plan`
  (have a spec and roadmap).
