# agent-toolkit

Personal Claude Code plugin marketplace with research workflows and development utilities.

## Quick Setup

```bash
curl -fsSL https://raw.githubusercontent.com/wilsonkichoi/agent-toolkit/main/bootstrap/install.sh | bash
```

Interactive script that prompts for each marketplace, plugin, and setting.

## Manual Install

```bash
claude plugin marketplace add wilsonkichoi/agent-toolkit
claude plugin install research@agent-toolkit
claude plugin install dev@agent-toolkit
```

## Plugins

| Plugin | Description |
|--------|-------------|
| research | Research workflow skills |
| dev | Development workflow utilities |

## Structure

```
bootstrap/          # Standalone setup script + config (not a plugin)
plugins/research/   # Research plugin
plugins/dev/        # Dev plugin
```

## Customizing Bootstrap

Edit yaml files in `bootstrap/config/` to add/remove marketplaces, plugins, or settings, then re-run the install script.
