# agent-toolkit

Installable agent workflows for research, knowledge management, security review, and a
tracker-backed software-development lifecycle. The `utils` and `dev` plugins support Claude Code
and Codex; a generated distribution supports the proven single-root Kiro IDE preview scope.

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

## Install with Kiro IDE (single-root preview)

Kiro uses the generated copy-only distribution under [`dist/kiro/`](dist/kiro/README.md), not the
Claude Code or Codex plugin marketplaces. Clone this repository, copy `dist/kiro/skills/` and
`dist/kiro/agents/` into either `<project>/.kiro/` or `~/.kiro/`, then open a fresh single-root Kiro
window. The generated README contains exact `ditto` update commands and manifest-owned uninstall
paths. Clone/copy is the supported repeatable installation path; there is no Kiro marketplace
manifest, Power, or installer.

The preview supports all utility skills, the named dev agents, the human-gated
`setup → plan → execute → review-pr → verify` lifecycle, and bounded `dev:auto`; the probes behind
that scope, the Kiro build they ran on, and the outcomes they did *not* establish are recorded in
[docs/kiro-preview-validation.md](docs/kiro-preview-validation.md). Kiro CLI, multi-root workspaces,
and explicit agent `resources:` are unsupported; generated agents use Kiro's default steering
inheritance and intentionally omit `resources:`.

It ships a subset of the dev plugin: `dev:feedback` and `dev:release` act on the agent-toolkit
repository rather than your project, and `dev:shadow` is unsupported in Kiro, so none of the three
is generated. Use Claude Code or Codex for those. Because Kiro follows the
[Agent Skills](https://agentskills.io/specification) standard, where a skill directory is the unit
of distribution and references resolve relative to `SKILL.md`, each generated skill bundles only the
shared contracts and helpers it needs; `dist/kiro/manifest.json` records that set per skill. The
reasoning is in [docs/adr/0002](docs/adr/0002-kiro-generated-distribution.md).

Kiro owns permission and trust decisions; installation does not modify them. Start in a disposable
or trusted project, keep wildcard command trust disabled, and approve only expected operations.
Lifecycle skills can create files, commits, branches, worktrees, tracker updates, and merges after
their documented gates. Treat denied tools and unavailable required named agents as safe stops:
do not retry with another tool, substitute inline work, or bypass the denial.

## Updating

### Codex

Upgrade the plugin and verify the installed version:

```bash
codex plugin marketplace upgrade agent-toolkit
codex plugin list | grep agent-toolkit
```

### Claude Code

Refresh the marketplace and update each installed plugin. The update command targets a
specific plugin by name; scope it to match however you installed it.

Marketplace refresh:

```bash
claude plugin marketplace update agent-toolkit
```

User-scope update:

```bash
claude plugin update dev@agent-toolkit
```

Local-scope update:

```bash
claude plugin update --scope local dev@agent-toolkit
```

## Plugins

| Plugin | Description |
|---|---|
| `utils` | Research, knowledge synthesis, LLM Wiki maintenance, retrospectives, and security scanning |
| `dev` | Product discovery, architecture, tracker-backed planning, implementation, review, verification, standalone GitHub PR merge/cleanup operations, plugin release publication, status, retrospectives, historical-replay evaluation, and structured feedback filing |

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
| Implicit `research`, `retro`, `security-scan` routing | Description guard | Disabled; invoke explicitly |

Kiro's generated preview is a separate copy-only distribution, not a third plugin marketplace.
Its supported surface is single-root Kiro IDE workspaces: utility skills, named dev agents, the
manual lifecycle, and bounded `dev:auto`. Invoke generated names such as `/utils-research` and
`/dev-execute`; the non-ASCII retrospective alias is `/utils-retro-zh`. `dev:feedback`,
`dev:release`, and `dev:shadow` are not generated for Kiro. CLI, multi-root, and explicit-resource
behavior are outside the supported surface.

Codex's default `agents.max_depth = 1` prevents nested subagent spawning. The `dev:auto` Codex path
therefore dispatches its implementation worker and `test-writer` as siblings. Standalone
`dev:execute` dispatches `test-writer` directly from the root session.

The `dev` plugin's task-scoped lifecycle resolves project instructions and tiered rules from the
task's execution repository with a bundled resolver. Codex does not depend on Claude Code's
`@` import expansion, including for cross-repository tasks. The same resolver enforces the
rule-discovery contract in CI through
`resolve_project_rules.py --check <repo>`, which needs only a repository path, so adopters do not
vendor a second checker; `dev:setup` offers to wire it into a project's CI workflow. GitHub-hosted
projects can use the `.github/actions/check-rules` composite action instead of writing that step
themselves, pinned to an immutable release tag:

```yaml
- uses: wilsonkichoi/agent-toolkit/.github/actions/check-rules@dev-v0.0.70
```

`dev:shadow` opens its isolated draft PR only after the replay has produced a candidate commit,
and binds the PR head to the resolved push repository for both same-repository and fork routing.

A spike's durable decision artifacts merge; only its experiment is throwaway. The ADR and any
directly required documentation or index update are repository content, so `dev:verify` merges
an artifact-only spike PR through the normal review, CI, human-approval, and merge gate before
`Done`, and fails closed when the branch mixes in prototype or exploratory implementation.

Primary-GitHub lifecycle routing binds execute work summaries to the PR author, URL, branch, and
commit ancestry before review or verification uses their queue classification. Planned reviews
start only after the canonical issue verifies exactly `status:in-review`.
The shared `plugins/dev/scripts/work_summary.py` validator checks the exact heading, required
fields, supported classification, and full 40-character execution revision before that binding;
the planned execute handoff receives the canonical current PR URL, verifies the comment's author,
URL, branch, revision ancestry, and exact posted body before changing the status label.

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

Plugin versions are released as immutable `<plugin>-vX.Y.Z` tags plus matching GitHub Releases, so a
consumer can pin a human-readable version instead of `main` or a commit SHA. `dev` and `utils` are
versioned and tagged independently. The active `Immutable plugin release tags` ruleset protects
`refs/tags/dev-v*` and `refs/tags/utils-v*` from deletion and every update through its `deletion`,
`non_fast_forward`, and `update` rules. Tag creation is automatic: a push to `main` that strictly
increases a plugin's three synchronized version fields
creates that plugin's tag at the merged commit, and refuses before creating anything when the fields
disagree, the version is not semver or decreases, the exact changelog heading is missing, or the tag
already exists elsewhere. Publishing the GitHub Release stays an explicit maintainer action through
`/dev:release <tag>`. Published tags and releases are never moved, edited, or deleted; corrections
ship as a new patch release.

The maintainer procedure is in [docs/RELEASING.md](docs/RELEASING.md) and shipped versions are
listed in [CHANGELOG.md](CHANGELOG.md).

## Repository layout

```text
.agent-toolkit/          # this repo's dev-plugin state (dev.md config + rules/)
.claude-plugin/          # Claude Code marketplace manifest
.agents/plugins/         # Codex marketplace manifest
.codex/agents/           # generated project-scoped Codex agents
dist/codex/agents/       # generated copy-me Codex agents for other projects
dist/kiro/               # generated single-root Kiro IDE skills, agents, install guide, manifest
plugins/utils/           # utility plugin sources
plugins/dev/             # development-lifecycle plugin sources
tools/                   # agent generator and repository validator
```
