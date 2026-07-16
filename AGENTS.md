# AGENTS.md

Authoring conventions for this repository - the single source of truth for every harness.
Codex reads this file natively; Claude Code loads it through the one-line `@AGENTS.md`
import that is `CLAUDE.md`'s entire body (Claude Code does not auto-load `AGENTS.md`
directly). Do not add content to `CLAUDE.md`; it belongs here. Install and invocation
details live in the repo `README.md`.

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
.claude-plugin/         # Claude marketplace manifest
.agents/                # Codex-native marketplace manifest (plugins/marketplace.json)
AGENTS.md               # this file - conventions SSOT for all harnesses
CLAUDE.md               # one-line @AGENTS.md import (Claude Code entry point)
bootstrap/              # Standalone setup script + config (Claude-only; not a plugin)
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
