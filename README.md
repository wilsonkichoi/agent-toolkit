# agent-toolkit

Personal Claude Code plugin marketplace with research workflows and development utilities.

## Quick Setup

```bash
# Private repo - clone first
gh repo clone wilsonkichoi/agent-toolkit /tmp/agent-toolkit && bash /tmp/agent-toolkit/bootstrap/install.sh

# Public repo (future)
# curl -fsSL https://raw.githubusercontent.com/wilsonkichoi/agent-toolkit/main/bootstrap/install.sh | bash
```

The bootstrap script walks through three steps, prompting for each item individually (skip any you don't want):

1. **Register repos** - adds plugin sources (marketplaces) so Claude Code can discover plugins from them
2. **Install plugins** - installs individual plugins from registered repos (AWS tools, Playwright, draw.io, etc.)
3. **Apply settings** - configures Claude Code settings (permissions, MCP servers, preferences)

Everything is opt-in per item. Re-run anytime to add things you skipped.

All installed plugins are **disabled globally by default**. Enable them where needed:

```bash
# Enable for the current project only (writes to project's .claude/settings.local.json)
claude plugin enable --scope local <name>@<marketplace>

# Or enable globally for all projects
claude plugin enable --scope user <name>@<marketplace>
```

> **Do not use the `/plugins` command inside Claude Code to enable a plugin for one project.** It enables globally (user scope), not locally. For per-project enablement, use `claude plugin enable --scope local` from the project directory.

## Manual Install

```bash
claude plugin marketplace add wilsonkichoi/agent-toolkit
claude plugin install utils@agent-toolkit
claude plugin install dev@agent-toolkit
```

## Plugins

| Plugin | Description |
|--------|-------------|
| utils | Research, investigation, knowledge synthesis, and session retrospectives |
| dev | AI-assisted product development lifecycle: tracker-backed task packets (Linear / GitHub Issues / local) with PR-native execution. Phases A-C (setup, discover, architect, plan, backlog, execute, review, verify) implemented; see plugins/dev/DESIGN.md |

## Structure

```
bootstrap/          # Standalone setup script + config (not a plugin)
plugins/utils/      # Utility skills (research, etc.)
plugins/dev/        # Dev plugin
```

## Customizing Bootstrap

Edit yaml files in `bootstrap/config/` to add/remove repos, plugins, or settings, then re-run the install script.
