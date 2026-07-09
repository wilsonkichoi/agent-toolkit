# AGENTS.md

Authoring conventions for this repository, written harness-neutral so they apply whether you
work in Claude Code or Codex. Claude Code reads both this file and `CLAUDE.md`; keep
the two consistent. Claude-Code-specific install and invocation details live in `CLAUDE.md`
and the repo `README.md`.

## Versioning

All version fields use semver (`major.minor.patch`). Always use the minimum increment:
- Bug fixes, typos, doc updates: patch (`0.0.1` → `0.0.2`)
- New skills, features, non-breaking additions: minor (`0.0.2` → `0.1.0`)
- Breaking changes (renamed skills, removed features, restructured plugin): major

While in pre-release (`0.0.x`), use patch for everything including new features. Save
minor/major bumps for after the plugin has real consumers.

Version fields live in, and must stay in lockstep:
- `.claude-plugin/marketplace.json` (marketplace version + per-plugin version entries)
- `plugins/<name>/.claude-plugin/plugin.json`
- `plugins/<name>/.codex-plugin/plugin.json` (mirror of the Claude manifest version)

## Structure

```
.claude-plugin/         # Claude marketplace manifest
.agents/                # Codex-native marketplace manifest (plugins/marketplace.json)
AGENTS.md               # this file (read by Claude Code and Codex)
CLAUDE.md               # Claude-Code-specific conventions + install
bootstrap/              # Standalone setup script + config (Claude-only; not a plugin)
dist/                   # generated / copy-me artifacts, not plugin-installable
  codex/agents/         #   Codex agent TOMLs (copy to ~/.codex/agents/ or project .codex/agents/)
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
Claude-Code-only capability (background subagents, `/loop`, worktree isolation) behind a
harness-note so other harnesses degrade gracefully.

## Pre-commit checklist

Before any commit that adds, removes, or modifies files under `skills/`:

1. Version bumped in `plugins/<plugin>/.claude-plugin/plugin.json`
2. Same version mirrored in `plugins/<plugin>/.codex-plugin/plugin.json`
3. Version bumped in `.claude-plugin/marketplace.json` (matching entry)
4. `plugins/<plugin>/README.md` updated
5. Agent sources changed? Regenerate `dist/codex/agents/*.toml`
6. `.claude-plugin/marketplace.json` description/keywords updated if needed
7. `README.md` (repo root) and `AGENTS.md` updated if plugin behavior/description changed

Do not commit skill changes without completing this checklist. Read the checklist, don't rely
on memory.
