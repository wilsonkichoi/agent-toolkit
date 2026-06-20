# CLAUDE.md

## Versioning

All version fields use semver (`major.minor.patch`). Always use the minimum increment:
- Bug fixes, typos, doc updates: patch (`0.0.1` → `0.0.2`)
- New skills, features, non-breaking additions: minor (`0.0.2` → `0.1.0`)
- Breaking changes (renamed skills, removed features, restructured plugin): major

While in pre-release (`0.0.x`), use patch for everything including new features. Save minor/major bumps for after the plugin has real consumers.

Version fields live in:
- `.claude-plugin/marketplace.json` (marketplace version + per-plugin version entries)
- `plugins/<name>/.claude-plugin/plugin.json`

Keep all version references in sync when bumping.

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

## Docs to update when adding a skill

1. `plugins/<plugin>/skills/<name>/SKILL.md` - the skill itself
2. `plugins/<plugin>/.claude-plugin/plugin.json` - description, keywords, version bump
3. `plugins/<plugin>/README.md` - add skill section
4. `README.md` (repo root) - update plugin description if needed
5. `.claude-plugin/marketplace.json` - update plugin description/keywords if needed
