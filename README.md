# agent-toolkit

Personal agent plugin marketplace with research workflows and development utilities. Primary
target is Claude Code; the `utils` and `dev` plugins also install on **Codex**
(see the per-harness install sections and the [harness support matrix](#harness-support) below).

## Quick Setup (Claude Code)

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

## Manual Install (Claude Code)

```bash
claude plugin marketplace add wilsonkichoi/agent-toolkit
claude plugin install utils@agent-toolkit
claude plugin install dev@agent-toolkit
```

## Install on Codex

Skills install via the plugin marketplace; agents are copied files.

```bash
# Register the marketplace and install the plugins
codex plugin marketplace add wilsonkichoi/agent-toolkit
codex plugin add utils@agent-toolkit
codex plugin add dev@agent-toolkit

# Copy the dev agents (reviewer / test-writer / verifier) into Codex
cp dist/codex/agents/*.toml ~/.codex/agents/        # or a project ./.codex/agents/
```

Invoke skills explicitly with `$<name>` (e.g. `$research`, `$execute`). The project context
file is `AGENTS.md` (`dev:setup`'s default config on every harness). Known degradations on Codex:

- **No automatic subagent delegation.** `review-pr` / `verify` independence is advisory
  (prompt-enforced), not tool-enforced; run them in a separate session from the implementer.
- **`dev:auto` and `execute` loop/batch mode are unavailable** (need background subagents +
  a loop primitive); the skills refuse gracefully and point at the one-task-per-session flow.
- **`research` / `retro` do not fire implicitly** (guarded by `agents/openai.yaml`); invoke
  them explicitly.

## Harness support

| Feature | Claude Code | Codex |
|---|---|---|
| utils + dev skills (explicit invoke) | `/utils:research`, `/dev:execute` | `$research`, `$execute` |
| `research` / `retro` implicit-fire guard | description guard | `openai.yaml` policy (verified) |
| dev interactive lifecycle (setup→plan→execute→review→verify→retro) | ✅ | ✅ |
| tracker doc reachable from dev skills | `$CLAUDE_PLUGIN_ROOT` env | relative path |
| retro / architect promotion target (default config) | `AGENTS.md` via the `CLAUDE.md` = `@AGENTS.md` import | `AGENTS.md` natively |
| bundled agents (reviewer/test-writer/verifier) | native (auto-delegated) | copy TOML (advisory) |
| automatic subagent delegation | ✅ | ❌ advisory |
| `dev:auto` / execute loop-batch mode | ✅ | ❌ (deferred) |
| `回顧` CJK skill name | ✅ as-is | ✅ as-is |

`bootstrap/` is Claude Code only. Codex uses the manual steps above.

Kiro support was explored and dropped (2026-07-09): Kiro cannot invoke custom agents, has no
headless verification channel, and the committed export tree was a per-commit maintenance tax.
The mechanical exporter and generated tree live in git history (`de7d72c`) if Kiro matures.

## Plugins

| Plugin | Description |
|--------|-------------|
| utils | Research, investigation, knowledge synthesis, and session retrospectives |
| dev | AI-assisted product development lifecycle: tracker-backed task packets (Linear / GitHub Issues / local) with PR-native execution. All skills implemented (setup, discover, architect, plan, backlog, execute, auto, review, verify, retro, status); dogfooding in progress, see plugins/dev/DESIGN.md |

## Structure

```
.claude-plugin/     # Claude marketplace manifest
.agents/            # Codex-native marketplace manifest
AGENTS.md           # authoring conventions SSOT (Claude Code imports it via CLAUDE.md = @AGENTS.md)
bootstrap/          # Standalone setup script + config (Claude Code only; not a plugin)
dist/codex/agents/  # Codex agent TOMLs (copy-me)
plugins/utils/      # Utility skills (research, etc.)
plugins/dev/        # Dev plugin
```

## Customizing Bootstrap

Edit yaml files in `bootstrap/config/` to add/remove repos, plugins, or settings, then re-run the install script.
