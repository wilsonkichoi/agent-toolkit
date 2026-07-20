# OpenAI Build Week 2026

agent-toolkit is a Developer Tools submission that turns product requirements into tracker-backed
tasks, isolated implementation work, reviewed pull requests, evidence-based verification, and
project rules that improve future agent sessions.

### How Codex and GPT-5.6 were used

Codex was the primary implementation and dogfooding environment for the Build Week work. Recorded
project sessions used GPT-5.6 Sol and GPT-5.6 Terra.

Codex and GPT-5.6 were used to:

- Research Codex plugin packaging, agent loading, caching, context behavior, and delegation limits.
- Design the contributor workflow and the canonical-repository, upstream-base, and fork-push trust
  model.
- Implement the Codex agent generator, repository validator, project-rule resolver, and verified
  GitHub lifecycle command.
- Generate and run focused regression tests for repository rules and GitHub task transitions.
- Execute independent implementation, review, fix, and verification sessions against real project
  issues and pull requests.
- Dogfood `dev:execute`, `dev:review-pr`, `dev:verify`, and `dev:auto` on projects using the toolkit.

Codex accelerated repository-wide research, implementation, review, and verification. The project
owner made the key product and engineering decisions: use the tracker as the single source of task
truth, use pull requests and CI as the quality record, keep merging behind a human gate by default,
separate implementation from review and verification, and enforce critical lifecycle invariants
with deterministic programs instead of prompt text alone.

Representative Build Week pull requests:

- [PR #12: deterministic project-rule loading](https://github.com/wilsonkichoi/agent-toolkit/pull/12)
- [PR #15: verified GitHub lifecycle gates](https://github.com/wilsonkichoi/agent-toolkit/pull/15)
- [PR #16: bounded manual review fixes](https://github.com/wilsonkichoi/agent-toolkit/pull/16)

The primary foundational Codex implementation thread used GPT-5.6 Sol. Its session ID is
`019f641e-f48e-7581-a4d7-ce45f5ac2201`.

### Runtime model use

agent-toolkit does not require an OpenAI API key and does not make direct OpenAI API calls. Codex
powered by GPT-5.6 was both the development environment and the agent runtime used to execute and
dogfood the submitted workflows. The installed skills inherit the model selected for the active
Codex session, and bundled agents explicitly inherit that same model rather than silently
downgrading.

## Installation, platforms, and testing

### Prerequisites

- Codex CLI
- Git
- GitHub CLI (`gh`)
- `uv` for repository validation
- An authenticated GitHub account for workflows that create issues or pull requests
- Optional Linear MCP configuration when using the Linear tracker backend

### Install with Codex

Install the plugins from the marketplace:

```bash
codex plugin marketplace add wilsonkichoi/agent-toolkit
codex plugin add utils@agent-toolkit
codex plugin add dev@agent-toolkit
```

Install the pre-generated Codex agent definitions:

```bash
gh repo clone wilsonkichoi/agent-toolkit /tmp/agent-toolkit
mkdir -p ~/.codex/agents
cp /tmp/agent-toolkit/dist/codex/agents/*.toml ~/.codex/agents/
```

Open a new Codex thread after installation. Invoke skills explicitly, for example `$status`,
`$execute`, `$review-pr`, and `$verify`.

### Supported platforms

Supported agent platform:

- Codex CLI

Supported trackers:

- GitHub Issues
- Linear
- Local Markdown task files
- Custom backends implemented against the documented tracker contract

Tested host environments:

- macOS 26.5 on Apple Silicon for interactive Codex workflows
- Ubuntu GitHub-hosted runners for automated repository validation

Native Windows execution has not been tested. The Build Week version was validated with Codex CLI
0.144.6.

### Test without rebuilding

Clone the public repository and run the validation suite:

```bash
git clone https://github.com/wilsonkichoi/agent-toolkit.git
cd agent-toolkit
uv run tools/generate_codex_agents.py --check
uv run tools/check_repo.py
uv run tools/test_github_task_lifecycle.py
uv run tools/test_resolve_project_rules.py
```

Expected result:

- Three generated Codex agents pass byte-for-byte drift validation.
- All 11 repository validation checks pass.
- All 29 focused unit tests pass.

To test the installed plugin without changing repository state, open Codex from the repository clone
and invoke `$status`. It is read-only and reports milestone progress, open pull requests, CI state,
the work-in-progress limit, blocked tasks, and consistency problems.

For a local mutation sandbox, create an empty Git repository, open Codex, invoke `$setup`, and
select the local tracker backend. This exercises project scaffolding without requiring a remote
repository, Linear account, or external service.
