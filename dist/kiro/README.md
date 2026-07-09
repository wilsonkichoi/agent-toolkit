# dist/kiro — generated Kiro export

**Do not edit files under `skills/` here by hand.** This tree is generated from the
Claude-source plugins by `tools/export_kiro.py`. Regenerate after any change to
`plugins/*/skills/` or `plugins/dev/docs/tracker.md`:

```
uv run tools/export_kiro.py
```

Transforms applied (see `.local/codex-research/07-implementation-plan.md` §5.1): skills are
copied and renamed (`dev` skills gain a `dev-` prefix, `回顧` becomes `retro-zh`), the tracker
doc is bundled into each `dev` skill as `references/tracker.md`, and Codex-only
`agents/openai.yaml` metadata is stripped.

The `agents/*.md` files in this tree are hand-maintained (not generated) and mirror
`plugins/dev/agents/*.md` for Kiro.

## Skill name map

| Source skill | Kiro skill |
|---|---|
| `dev/architect` | `dev-architect` |
| `dev/auto` | `dev-auto` |
| `dev/backlog` | `dev-backlog` |
| `dev/discover` | `dev-discover` |
| `dev/execute` | `dev-execute` |
| `dev/plan` | `dev-plan` |
| `dev/retro` | `dev-retro` |
| `dev/review-pr` | `dev-review-pr` |
| `dev/setup` | `dev-setup` |
| `dev/status` | `dev-status` |
| `dev/verify` | `dev-verify` |
| `utils/llm-wiki` | `llm-wiki` |
| `utils/research` | `research` |
| `utils/retro` | `retro` |
| `utils/security-scan` | `security-scan` |
| `utils/回顧` | `retro-zh` |

## Install (Kiro)

- Skills: import into project scope `.kiro/skills/` or global `~/.kiro/skills/`. See the repo
  root `README.md` Kiro section for the exact `npx skills add` / URL-import instructions.
- Agents: copy `agents/*.md` into `.kiro/agents/` (project) or `~/.kiro/agents/`.
