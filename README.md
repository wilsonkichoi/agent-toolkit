# agent-toolkit

Personal Claude Code plugin marketplace with research workflows and development utilities.

## Quick Setup

```bash
# Private repo - clone first
gh repo clone wilsonkichoi/agent-toolkit /tmp/agent-toolkit && bash /tmp/agent-toolkit/bootstrap/install.sh

# Public repo (future)
# curl -fsSL https://raw.githubusercontent.com/wilsonkichoi/agent-toolkit/main/bootstrap/install.sh | bash
```

Interactive script that prompts for each marketplace, plugin, and setting.

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
| dev | Development workflow utilities |

## Structure

```
bootstrap/          # Standalone setup script + config (not a plugin)
plugins/utils/      # Utility skills (research, etc.)
plugins/dev/        # Dev plugin
```

## Customizing Bootstrap

Edit yaml files in `bootstrap/config/` to add/remove marketplaces, plugins, or settings, then re-run the install script.
