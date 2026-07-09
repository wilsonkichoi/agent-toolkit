# CLAUDE.md

## Versioning

All version fields use semver (`major.minor.patch`). Always use the minimum increment:
- Bug fixes, typos, doc updates: patch (`0.0.1` → `0.0.2`)
- New skills, features, non-breaking additions: minor (`0.0.2` → `0.1.0`)
- Breaking changes (renamed skills, removed features, restructured plugin): major

While in pre-release (`0.0.x`), use patch for everything including new features. Save minor/major bumps for after the plugin has real consumers.

Version fields live in, and must stay in sync when bumping:
- `.claude-plugin/marketplace.json` (marketplace version + per-plugin version entries)
- `plugins/<name>/.claude-plugin/plugin.json`
- `plugins/<name>/.codex-plugin/plugin.json` (Codex manifest; mirrors the Claude version)

## Structure

```
.claude-plugin/         # Marketplace manifest
bootstrap/              # Standalone setup script + config (not a plugin)
plugins/<name>/         # Each plugin
  .claude-plugin/       #   Plugin manifest (plugin.json)
  skills/              #   Skill directories, each with SKILL.md
  README.md            #   Plugin docs
```

## Skills

Each skill is a directory under `plugins/<plugin>/skills/<skill-name>/` containing at minimum a `SKILL.md` with YAML frontmatter (`name`, `description`) and markdown body.

Skill directory names can be CJK (e.g. `回顧/`). Use descriptive names.

## Pre-commit checklist

Before any commit that adds, removes, or modifies files under `skills/` or `agents/`:

1. Version bumped in `plugins/<plugin>/.claude-plugin/plugin.json`
2. Same version mirrored in `plugins/<plugin>/.codex-plugin/plugin.json`
3. Version bumped in `.claude-plugin/marketplace.json` (matching entry)
4. `plugins/<plugin>/README.md` updated
5. Agent sources changed? Regenerate `dist/codex/agents/*.toml`
6. `.claude-plugin/marketplace.json` description/keywords updated if needed
7. `README.md` (repo root) and `AGENTS.md` updated if plugin behavior/description changed

Do not commit skill changes without completing this checklist. Read the checklist, don't rely on memory.

Codex authoring conventions live in `AGENTS.md` (harness-neutral). Keep the two files
consistent.
