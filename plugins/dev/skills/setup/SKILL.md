---
name: setup
description: >
  This skill should be used when the user asks to "set up the dev workflow", "initialize this
  project for dev", "run dev setup", "adopt the dev plugin", "configure the tracker", or
  invokes /dev:setup. Initializes a project (greenfield or existing/brownfield) for the dev
  plugin: scaffolds the docs layout, selects the tracker backend, and writes .agent/dev.md.
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
the project. Also read an existing `.agent/dev.md` (legacy fallback: `.claude/dev.md`) before
making any repository or tracker call; setup must preserve choices the project already made.

## Harness specifics

Setup knows which harness it is running in; use the matching column below (referenced from
steps 2 and 7). Step 6 (claude-review.yml) is unchanged across harnesses — the GitHub Action
runs server-side and only needs `ANTHROPIC_API_KEY`, regardless of the local harness.

| Concern | Claude Code | Codex |
|---|---|---|
| Linear MCP config | `claude mcp add` / plugin MCP | `codex mcp add` (writes `[mcp_servers]` in `~/.codex/config.toml`) |
| Pre-approve commands for unattended runs | `.claude/settings.json` permissions | approvals config + `.rules` command policy |
| Context file seeded in step 4 | `AGENTS.md` default (+ `CLAUDE.md` import); `CLAUDE.md` on Claude-only config | `AGENTS.md` |

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
7. **Multiple harnesses?** Will this project ever be worked from more than one agent harness
   (some teammates on Claude Code, others on Codex; or you alternating harnesses per
   task)? Default yes - the mixed-harness config below works identically on every harness,
   so it is the safe default. Answer no only for a deliberately Claude-Code-only project.
   This decides the memory target in step 3.

## 3. Scaffold

Create only what is missing:

```
docs/            # PRD.md, SPEC.md, ROADMAP.md arrive via dev:discover / dev:architect
docs/adr/
research/raw/
.claude/rules/   # only with the Claude-only config (Q6 = no); the default config has no rules_dir
.dev/tasks/      # only when tracker: local
```

Create the configured `rules_dir` only when the interview chose the Claude-only config; the
default (mixed-harness) config omits `rules_dir` entirely.

**Existing projects:** when a legacy `.claude/dev.md` (or `.claude/dev.local.md`) exists,
offer to `git mv` it to `.agent/dev.md` (and `.agent/dev.local.md`, updating the
`.gitignore` entry). Every dev skill reads `.agent/dev.md` first and falls back to the
legacy path, so the migration is safe but optional.

Write `.agent/dev.md` with YAML frontmatter:

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
context_file: AGENTS.md        # single shared context file (default); Claude-only config uses CLAUDE.md + rules_dir
---
Project conventions the fields cannot capture go here as free text.
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

**Default config (Q7 = yes, mixed-harness):** `context_file: AGENTS.md` and no `rules_dir`,
whichever harness setup runs in - a single shared file carries promoted learnings
(`dev:retro`) and the architecture pointer (`dev:architect`). Codex reads `AGENTS.md`
natively. Claude Code does NOT auto-load `AGENTS.md` (it loads `CLAUDE.md`), so also seed a
one-line `CLAUDE.md` whose entire body is the import `@AGENTS.md` - Claude Code then pulls
the shared file into context through its native import, and the memory loop closes for both
harnesses through one file. If the project already has promoted rules in `.claude/rules/`
(or another legacy `rules_dir`), offer a one-time migration: move each rule's content into a
clearly-marked rules section of `AGENTS.md`, then delete the migrated rule files - leaving
both in place splits the memory between harnesses.

**Claude-only config (Q7 = no):** set `rules_dir: .claude/rules/` and
`context_file: CLAUDE.md`. `dev:retro` reads these when promoting learnings and, when both
fields are absent (legacy or hand-written configs), falls back to these same values as a
safety net - not a recommended config; run `dev:setup` to write explicit fields.

Add Linear fields (`linear_team`, `linear_project`) when applicable. When the user opted into
a secondary GitHub intake channel (interview Q5), add `secondary_intake: github`,
`github_repo: owner/repo`, and `audit_trail: link`. Do not create
`.agent/dev.local.md`; mention it exists for personal overrides (gitignored).

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

## 4. Seed the context file

Seed the `context_file` chosen in step 3 (`AGENTS.md` by default; `CLAUDE.md` on the
Claude-only config). Greenfield: create a lean context file (< 50 lines) stating the project
name, pointing to `docs/PRD.md`, `docs/SPEC.md`, `docs/ROADMAP.md`, `docs/adr/`, the
configured `rules_dir` when one exists, and naming the tracker backend. Brownfield: append
the pointers section to the existing context file instead; touch nothing else in it.

Default config (`context_file: AGENTS.md`): also seed a `CLAUDE.md` whose entire body is
`@AGENTS.md` so Claude Code imports the shared file; if a `CLAUDE.md` already exists, add
the `@AGENTS.md` import line rather than replacing it.

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
3. Set `review_action_installed: true` in `.agent/dev.md` frontmatter.
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
