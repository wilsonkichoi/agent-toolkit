---
name: setup
description: >
  This skill should be used when the user asks to "set up the dev workflow", "initialize this
  project for dev", "run dev setup", "adopt the dev plugin", "configure the tracker", or
  invokes /dev:setup. Initializes a project (greenfield or existing/brownfield) for the dev
  plugin: scaffolds the docs layout, selects the tracker backend, and writes .claude/dev.md.
argument-hint: "[project-dir]"
---

# dev:setup

Initialize a project for the dev plugin lifecycle. Idempotent: safe to re-run; never
overwrite existing files without asking.

Read `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md` (plugin `docs/` directory, two levels above this
skill) before configuring the tracker.

## 1. Detect mode

Inspect the target directory (argument, default cwd):

- **Greenfield:** empty or near-empty (no source tree).
- **Brownfield:** existing code (source dirs, package manifests, git history).

## 2. Interview

Ask with AskUserQuestion, one round, only what cannot be inferred:

1. **Tracker backend:** `linear` / `github` / `local` / `custom`. If `linear`: team key and
   project name (and confirm the Linear MCP server is connected; if not, tell the user to add
   it and stop). If `github`: confirm `gh auth status` succeeds and the repo has a GitHub
   remote. If `custom`: point the user at the "Adding a backend" recipe in `tracker.md` and
   help write the mapping tables.
2. **Test command** (infer from the project if possible; confirm the inference).
3. **CI workflow file name** (brownfield: detect under `.github/workflows/`; greenfield:
   offer to create a minimal lint + test workflow).
4. **Merge policy:** squash (default) or merge commit.

## 3. Scaffold

Create only what is missing:

```
docs/            # PRD.md, SPEC.md, ROADMAP.md arrive via dev:discover / dev:architect
docs/adr/
research/raw/
.claude/rules/
.dev/tasks/      # only when tracker: local
```

Write `.claude/dev.md` with YAML frontmatter:

```markdown
---
tracker: github
test_command: "cd backend && uv run pytest"
ci_workflow: ci.yml
merge_policy: squash
review_action: false
work_in_progress_limit: 3      # max tasks simultaneously In Progress + In Review
max_fix_attempts: 3            # CI-fix or review-fix cycles before a task goes Blocked
max_tasks_per_run: 5           # batch cap for /dev:auto and /loop /dev:execute
auto_merge: false              # standing merge approval for /dev:auto (see that skill)
---
Project conventions the fields cannot capture go here as free text.
```

Add Linear fields (`linear_team`, `linear_project`) when applicable. Do not create
`.claude/dev.local.md`; mention it exists for personal overrides (gitignored).

Backend one-time setup:

- **github:** create the label sets from `tracker.md` (`status:*`, `priority:*`, `size:*`)
  via `gh label create`.
- **local:** add `.dev/tasks/.gitkeep`.

## 4. Seed CLAUDE.md

Greenfield: create a lean `CLAUDE.md` (< 50 lines) stating the project name, pointing to
`docs/PRD.md`, `docs/SPEC.md`, `docs/ROADMAP.md`, `docs/adr/`, and `.claude/rules/`, and
naming the tracker backend. Brownfield: append the pointers section to the existing
`CLAUDE.md` instead; touch nothing else in it.

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
2. Tell the user to add the API key secret: `gh secret set ANTHROPIC_API_KEY`. Warn: each
   auto-review spends API tokens; the manual `/dev:review-pr` path keeps working either way.
3. Set `review_action: true` in `.claude/dev.md` frontmatter.
4. Note that the template should be sanity-checked against the current
   `anthropics/claude-code-action` docs on first run.

## 7. Report

Summarize: mode, tracker backend, files created, one-time backend setup performed. Remind:

- Unattended runs (`/loop /dev:execute`, headless sessions) stall on permission prompts -
  pre-approve the needed commands (git, gh, test command) in `.claude/settings.json` first.
- Next steps: `/dev:discover` (new product), `/dev:architect` (have a PRD), or `/dev:plan`
  (have a spec and roadmap).
