# agent-toolkit

Personal agent plugin marketplace with research workflows and development utilities. Primary
target is Claude Code; the `utils` and `dev` plugins also install on **Codex** and **Kiro**
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

Invoke skills explicitly with `$<name>` (e.g. `$research`, `$execute`). Set the project
context file to `AGENTS.md` (`dev:setup` does this on Codex). Known degradations on Codex:

- **No automatic subagent delegation.** `review-pr` / `verify` independence is advisory
  (prompt-enforced), not tool-enforced; run them in a separate session from the implementer.
- **`dev:auto` and `execute` loop/batch mode are unavailable** (need background subagents +
  a loop primitive); the skills refuse gracefully and point at the one-task-per-session flow.
- **`research` / `retro` do not fire implicitly** (guarded by `agents/openai.yaml`); invoke
  them explicitly.

## Install on Kiro

Kiro uses the generated, renamed export under `dist/kiro/` (Kiro's flat namespace requires
`dev-<name>` prefixes and a spec-conformant `retro-zh` name).

```bash
# Skills (primary): bulk-add the exported skill tree
npx skills add wilsonkichoi/agent-toolkit/dist/kiro/skills

# Fallback: import an individual skill by GitHub URL, e.g. dist/kiro/skills/dev-execute,
# or clone the repo and import dist/kiro/skills/<skill> as a local folder.

# Agents: copy the exported markdown agents
cp dist/kiro/agents/*.md .kiro/agents/               # project scope; or ~/.kiro/agents/ global
```

Skills land in `.kiro/skills/` (project) or `~/.kiro/skills/` (global) and appear in the `/`
picker as `/dev-execute`, `/research`, etc. Context lives in `AGENTS.md` (read natively);
`dev:setup` on Kiro sets `rules_dir: .kiro/steering/` so retro promotions land as steering
rules. Known degradations on Kiro: `dev:auto` and execute loop/batch mode are unavailable (no
loop/background-subagent primitive in Kiro IDE); the skills refuse gracefully.

## Harness support

| Feature | Claude Code | Codex | Kiro |
|---|---|---|---|
| utils + dev skills (explicit invoke) | `/utils:research`, `/dev:execute` | `$research`, `$execute` | `/research`, `/dev-execute` |
| `research` / `retro` implicit-fire guard | description guard | `openai.yaml` policy (verified) | description guard (weaker) |
| dev interactive lifecycle (setup→plan→execute→review→verify→retro) | ✅ | ✅ | ✅ |
| tracker doc reachable from dev skills | `$CLAUDE_PLUGIN_ROOT` env | relative path | bundled `references/tracker.md` |
| retro / architect promotion target | `.claude/rules/` + `CLAUDE.md` | `AGENTS.md` | `.kiro/steering/` + `AGENTS.md` |
| bundled agents (reviewer/test-writer/verifier) | native (auto-delegated) | copy TOML (advisory) | copy markdown (advisory) |
| automatic subagent delegation | ✅ | ❌ advisory | ❌ advisory |
| `dev:auto` / execute loop-batch mode | ✅ | ❌ (deferred) | ❌ |
| `回顧` CJK skill name | ✅ as-is | ✅ as-is | renamed `retro-zh` |

`bootstrap/` is Claude Code only. Codex and Kiro use the manual steps above.

## Plugins

| Plugin | Description |
|--------|-------------|
| utils | Research, investigation, knowledge synthesis, and session retrospectives |
| dev | AI-assisted product development lifecycle: tracker-backed task packets (Linear / GitHub Issues / local) with PR-native execution. All skills implemented (setup, discover, architect, plan, backlog, execute, auto, review, verify, retro, status); dogfooding in progress, see plugins/dev/DESIGN.md |

## Structure

```
.claude-plugin/     # Claude marketplace manifest
.agents/            # Codex-native marketplace manifest
AGENTS.md           # harness-neutral authoring conventions (Codex/Kiro; Claude reads CLAUDE.md)
bootstrap/          # Standalone setup script + config (Claude Code only; not a plugin)
tools/export_kiro.py  # regenerates dist/kiro/ from plugins/ (uv run tools/export_kiro.py)
dist/codex/agents/  # Codex agent TOMLs (copy-me)
dist/kiro/          # generated Kiro skill + agent tree (committed; copy-me / npx skills add)
plugins/utils/      # Utility skills (research, etc.)
plugins/dev/        # Dev plugin
```

## Customizing Bootstrap

Edit yaml files in `bootstrap/config/` to add/remove repos, plugins, or settings, then re-run the install script.
