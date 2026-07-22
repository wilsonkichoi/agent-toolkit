# agent-toolkit

Installable agent workflows for research, knowledge management, security review, and a
tracker-backed software-development lifecycle. The `utils` and `dev` plugins support Claude Code
and Codex.

## Install with Claude Code

Register the marketplace, then install the plugins you want:

```bash
claude plugin marketplace add wilsonkichoi/agent-toolkit
claude plugin install utils@agent-toolkit
claude plugin install dev@agent-toolkit
```

Plugins install at user scope and can be enabled only where they are needed:

```bash
cd /path/to/project
claude plugin enable --scope local utils@agent-toolkit
claude plugin enable --scope local dev@agent-toolkit
```

Invoke Claude Code skills with their plugin namespace, for example `/utils:research` or
`/dev:execute`.

## Install with Codex

Codex installs plugin skills from the marketplace. The `dev` subagent definitions are separate
files and must be available in the user or project agent directory.

```bash
codex plugin marketplace add wilsonkichoi/agent-toolkit
codex plugin add utils@agent-toolkit
codex plugin add dev@agent-toolkit

gh repo clone wilsonkichoi/agent-toolkit /tmp/agent-toolkit
mkdir -p ~/.codex/agents
cp /tmp/agent-toolkit/dist/codex/agents/*.toml ~/.codex/agents/
```

Use `./.codex/agents/` instead of `~/.codex/agents/` for project-scoped agent definitions. This
repository already commits its project-scoped `.codex/agents/*.toml` files. Invoke Codex skills
explicitly with `$<name>`, for example `$research` or `$execute`.

Codex installed plugins are cached. Plugin authors testing working-tree changes must reinstall the
plugin and open a new thread. See [CONTRIBUTING.md](CONTRIBUTING.md#test-codex-working-tree-changes)
for the complete local-marketplace workflow.

## Plugins

| Plugin | Description |
|---|---|
| `utils` | Research, knowledge synthesis, LLM Wiki maintenance, retrospectives, and security scanning |
| `dev` | Product discovery, architecture, tracker-backed planning, implementation, review, verification, standalone GitHub PR merge/cleanup operations, status, retrospectives, historical-replay evaluation, and structured feedback filing |

Plugin-specific documentation is in [plugins/utils/README.md](plugins/utils/README.md) and
[plugins/dev/README.md](plugins/dev/README.md).

## Harness support

| Feature | Claude Code | Codex |
|---|---|---|
| `utils` and `dev` skills | Namespaced slash commands | Explicit `$<name>` invocation |
| `dev` interactive lifecycle | Supported | Supported |
| `dev:auto` | Supported | Supported through sibling-agent orchestration |
| `dev:execute` loop mode | Supported through Claude Code's loop primitive | Not available; run one task or use `dev:auto` |
| Bundled `dev` agents | Loaded from the plugin | Copy TOML files and select them with `agent_type` |
| Implicit `research` and `retro` routing | Description guard | Disabled; invoke explicitly |

Codex's default `agents.max_depth = 1` prevents nested subagent spawning. The `dev:auto` Codex path
therefore dispatches its implementation worker and `test-writer` as siblings. Standalone
`dev:execute` dispatches `test-writer` directly from the root session.

The `dev` plugin's task-scoped lifecycle resolves project instructions and tiered rules from the
task's execution repository with a bundled resolver. Codex does not depend on Claude Code's
`@` import expansion, including for cross-repository tasks.

`dev:shadow` opens its isolated draft PR only after the replay has produced a candidate commit,
and binds the PR head to the resolved push repository for both same-repository and fork routing.

Primary-GitHub lifecycle routing binds execute work summaries to the PR author, URL, branch, and
commit ancestry before review or verification uses their queue classification. Planned reviews
start only after the canonical issue verifies exactly `status:in-review`.

Manual `dev:review-pr` commands are one-pass actions. Review mode posts one verdict and stops;
fix mode applies one current findings batch, pushes and replies, records the need for re-review,
and stops. Only `dev:auto` chains review and fix actions, bounded by `max_fix_attempts`.

For planned GitHub tasks, `dev:execute` validates and verifies each non-terminal `status:*`
transition against the canonical issue. Missing or malformed queue labels stop execution instead
of silently routing planned work as an external contribution.

## Project development

Contributions use the standard GitHub fork and cross-repository pull-request workflow. The
[contributor playbook](CONTRIBUTING.md) covers repository setup, adding or extending plugins,
versioning, generated artifacts, working-tree testing in both harnesses, the `dev` lifecycle, CI,
and the maintainer handoff.

Repository authoring rules and required checks are in [AGENTS.md](AGENTS.md).

## Repository layout

```text
.agent-toolkit/          # this repo's dev-plugin state (dev.md config + rules/)
.claude-plugin/          # Claude Code marketplace manifest
.agents/plugins/         # Codex marketplace manifest
.codex/agents/           # generated project-scoped Codex agents
dist/codex/agents/       # generated copy-me Codex agents for other projects
plugins/utils/           # utility plugin sources
plugins/dev/             # development-lifecycle plugin sources
tools/                   # agent generator and repository validator
```

## OpenAI Build Week 2026

agent-toolkit is a Developer Tools submission for OpenAI Build Week 2026. The submission details
how Codex and GPT-5.6 were used, runtime model use, installation, supported platforms, and judge
testing instructions.

[Read the OpenAI Build Week 2026 submission documentation](OpenAI-Build-Week-2026.md).
