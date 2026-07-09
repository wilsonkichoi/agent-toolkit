---
name: dev-setup
description: >
  This skill should be used when the user asks to "set up the dev workflow", "initialize this
  project for dev", "run dev setup", "adopt the dev plugin", "configure the tracker", or
  invokes /dev:setup. Initializes a project (greenfield or existing/brownfield) for the dev
  plugin: scaffolds the docs layout, selects the tracker backend, and writes .claude/dev.md.
metadata:
  argument-hint: "[project-dir]"
---

# dev:setup

Initialize a project for the dev plugin lifecycle. Idempotent: safe to re-run; never
overwrite existing files without asking.

Skill references like `dev:plan` mean this plugin's `plan` skill; when telling the user to run
one, render your harness's invocation for it (Claude Code: `/dev:plan`).

Read first: the plugin's `references/tracker.md` (bundled with this skill) — before
configuring the tracker. All `tracker.md` references below mean this plugin doc, never a file in
the project.

## Harness specifics

Setup knows which harness it is running in; use the matching column below (referenced from
steps 2 and 7). Step 6 (claude-review.yml) is unchanged across harnesses — the GitHub Action
runs server-side and only needs `ANTHROPIC_API_KEY`, regardless of the local harness.

| Concern | Claude Code | Codex | Kiro |
|---|---|---|---|
| Linear MCP config | `claude mcp add` / plugin MCP | `[mcp_servers]` in `~/.codex/config.toml` | `.kiro/settings/mcp.json` |
| Pre-approve commands for unattended runs | `.claude/settings.json` permissions | approvals config + `.rules` command policy | agent `permissions.rules` |
| Context file seeded in step 4 | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md` |

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
6. **Multiple harnesses?** Will this project be worked from more than one agent harness
   (some teammates on Claude Code, others on Codex or Kiro; or you alternating harnesses per
   task)? Default no. This decides the memory target in step 3.

## 3. Scaffold

Create only what is missing:

```
docs/            # PRD.md, SPEC.md, ROADMAP.md arrive via dev:discover / dev:architect
docs/adr/
research/raw/
.claude/rules/   # the configured rules_dir (this Claude Code default; .kiro/steering/ on Kiro; omitted on Codex)
.dev/tasks/      # only when tracker: local
```

Create the configured `rules_dir` (see the `dev.md` template below) rather than hardcoding
`.claude/rules/`; skip it on a harness where `rules_dir` is omitted (Codex).

Write `.claude/dev.md` with YAML frontmatter:

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
rules_dir: .claude/rules/      # dir for promoted rule files; omit on Codex (no auto-loaded rules dir); .kiro/steering/ on Kiro
context_file: CLAUDE.md        # project context file; AGENTS.md on Codex and Kiro
---
Project conventions the fields cannot capture go here as free text.
```

Set `rules_dir` and `context_file` to the values for the harness setup is running in (Claude
Code: `.claude/rules/` + `CLAUDE.md`; Codex: omit `rules_dir`, use `AGENTS.md`; Kiro:
`.kiro/steering/` + `AGENTS.md`). `dev:retro` reads these when promoting learnings and, when
they are absent, defaults to `.claude/rules/` and `CLAUDE.md`.

**Mixed-harness projects (interview Q6 = yes):** override those per-harness defaults with
`context_file: AGENTS.md` and omit `rules_dir`, whichever harness setup runs in. `AGENTS.md`
is read natively by Claude Code, Codex, and Kiro, so promoted learnings (`dev:retro`) and the
architecture pointer (`dev:architect`) reach every harness; a `.claude/rules/` or
`.kiro/steering/` target would close the memory loop for one harness only. This is the
recommended config for any project touched by more than one harness.

Add Linear fields (`linear_team`, `linear_project`) when applicable. When the user opted into
a secondary GitHub intake channel (interview Q5), add `secondary_intake: github`,
`github_repo: owner/repo`, and `audit_trail: link`. Do not create
`.claude/dev.local.md`; mention it exists for personal overrides (gitignored).

Backend one-time setup:

- **github:** create the label sets from `tracker.md` (`status:*`, `priority:*`, `size:*`)
  via `gh label create`.
- **local:** add `.dev/tasks/.gitkeep`.

## 4. Seed the context file

Seed the `context_file` chosen in step 3 (`CLAUDE.md` on Claude Code, `AGENTS.md` on
Codex/Kiro). Greenfield: create a lean context file (< 50 lines) stating the project name,
pointing to `docs/PRD.md`, `docs/SPEC.md`, `docs/ROADMAP.md`, `docs/adr/`, and the configured
`rules_dir` (`.claude/rules/` on Claude Code), and naming the tracker backend. Brownfield:
append the pointers section to the existing context file instead; touch nothing else in it.

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
   auto-review spends API tokens; the manual `dev:review-pr` path keeps working either way.
3. Set `review_action_installed: true` in `.claude/dev.md` frontmatter.
4. Note that the template should be sanity-checked against the current
   `anthropics/claude-code-action` docs on first run.

## 7. Report

Offer to commit the scaffold and config to `main` - in a fresh repo this creates the root
commit that later task branches need; leaving setup output uncommitted stalls `dev:execute`
mid-run. Then summarize: mode, tracker backend, files created, one-time backend setup
performed. Remind:

- Unattended runs (`dev:execute` loop/batch mode, `dev:auto`) stall on permission prompts -
  pre-approve the needed commands (git, gh, test command) first: on Claude Code in
  `.claude/settings.json`; see Harness specifics for the Codex and Kiro equivalents. (Loop/batch
  and `dev:auto` are Claude-Code-only today; on Kiro run one task per session.)
- Next steps: `dev:discover` (new product), `dev:architect` (have a PRD), or `dev:plan`
  (have a spec and roadmap).
