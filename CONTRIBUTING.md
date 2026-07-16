# Contributing to agent-toolkit

External contributors use a normal public GitHub fork workflow. They do not need assignment,
milestone placement, a `status:todo` label, or maintainer approval before starting. Maintainers
alone control the internal queue, repository settings, and upstream merge.

## Set up a fork

Create the fork, clone it as `origin`, and add the canonical repository as `upstream`:

```bash
CONTRIBUTOR=$(gh api user --jq .login)
gh repo fork wilsonkichoi/agent-toolkit --clone=false
git clone "git@github.com:${CONTRIBUTOR}/agent-toolkit.git"
cd agent-toolkit
git remote add upstream git@github.com:wilsonkichoi/agent-toolkit.git
git fetch upstream
git remote -v
```

The required topology has three distinct destinations:

| Role | Destination |
|---|---|
| Canonical issues and pull requests | `wilsonkichoi/agent-toolkit` |
| Base branch | `upstream/main` |
| Contributor branch pushes | `origin` |

Do not merge a feature branch into the fork's `main`. The contribution is a pull request directly
from the fork feature branch to `wilsonkichoi/agent-toolkit:main`.

Maintainers with upstream write permission may clone the canonical repository and push feature
branches there. Fork topology does not grant or remove maintainer authority; the `dev` plugin also
checks the authenticated account's upstream permission.

## Choose and describe work

For non-trivial work, create an
[external contribution proposal](https://github.com/wilsonkichoi/agent-toolkit/issues/new?template=external-contribution.yml)
in the canonical repository. A complete issue contains an objective, why the change matters,
verifiable Definition of Done criteria, relevant references, and any suggested implementation.
Contributors can also ask `dev:backlog` to create this packet-complete canonical issue.

External contribution issues receive no queue labels, priority, size, milestone, dependency, or
assignee. Small drive-by fixes can start as a pull request; its description must provide the
objective and Definition of Done that the review and verification steps will use.

## Use the dev lifecycle

Use the released `dev` plugin for normal contribution work. Invoke these skills as
`/dev:<name>` in Claude Code or `$<name>` in Codex.

1. Run `dev:execute #N` for a canonical issue. It validates the packet and remote topology,
   rejects an issue already linked to an active pull request unless duplicate work is explicitly
   authorized, branches from `upstream/main`, pushes the feature branch to `origin`, and opens the
   canonical cross-repository pull request with `Closes #N`.
2. Run `dev:review-pr <PR URL>`. Address every finding and repeat review until the current pull
   request HEAD has an approving structured verdict. The verdict records the issue, commit SHA,
   DoD coverage, and findings.
3. Run `dev:verify <PR URL>`. It posts evidence for every DoD criterion, binds the report to the
   current HEAD SHA, and stops at `ready for maintainer decision`.
4. Stop. A contributor must not merge the upstream pull request, close the canonical issue,
   perform terminal tracker transitions, or delete an upstream branch.
5. A maintainer checks the current SHA-bound review and verification artifacts, canonical
   `repository-validation` result, and security-sensitive changes. The maintainer requests changes
   or explicitly authorizes and performs the upstream merge and issue cleanup.

A new commit makes prior review and verification evidence stale. Repeat both loops against the new
HEAD before maintainer handoff. `dev:auto` refuses external contributions because it cannot cross
the maintainer merge boundary.

After merge, synchronize the fork and delete the contributor-owned branch:

```bash
git fetch upstream
git switch main
git merge --ff-only upstream/main
git push origin main
BRANCH=task/123-short-description
git branch -d "$BRANCH"
git push origin --delete "$BRANCH"
```

## Authoritative sources and generated artifacts

| Path | Status | Responsibility |
|---|---|---|
| `plugins/<plugin>/skills/<skill>/SKILL.md` | Authoritative | Skill frontmatter and workflow |
| `plugins/<plugin>/agents/*.md` | Authoritative | Shared agent definitions |
| `plugins/<plugin>/.claude-plugin/plugin.json` | Authoritative | Claude Code plugin manifest and release version |
| `plugins/<plugin>/.codex-plugin/plugin.json` | Authoritative | Codex plugin manifest and release version |
| `.claude-plugin/marketplace.json` | Authoritative | Claude marketplace catalog and the third lockstep plugin version |
| `.agents/plugins/marketplace.json` | Authoritative | Codex marketplace catalog; it intentionally has no version field |
| `plugins/<plugin>/README.md` and plugin docs | Authoritative | User and maintainer documentation |
| `.codex/agents/*.toml` | Generated, committed | Project-scoped Codex agents loaded in this repository |
| `dist/codex/agents/*.toml` | Generated, committed | Copy-me Codex agents for unrelated projects or `~/.codex/agents/` |

`plugins/*/agents/*.md` is the only agent-authoring location. The generator writes both TOML
directories from those sources, and matching files must have identical bytes. Do not edit either
generated directory directly.

`dist/codex/` exists because installing a Codex plugin supplies its skills but does not install the
named Codex agent definitions. Users copy the distributable TOMLs into an unrelated project's
`.codex/agents/` or their user-level `~/.codex/agents/`. Contributors working in this clone receive
the project-scoped `.codex/agents/` through `git pull` and do not copy them manually.

## Add a plugin

Use a stable kebab-case plugin name.

1. Create the plugin directories and at least one skill:

```bash
PLUGIN=my-plugin
SKILL=my-skill
mkdir -p "plugins/${PLUGIN}/.claude-plugin" \
  "plugins/${PLUGIN}/.codex-plugin" \
  "plugins/${PLUGIN}/skills/${SKILL}"
```

2. Write `plugins/<plugin>/skills/<skill>/SKILL.md` with delimited YAML frontmatter. The `name`
   must exactly equal the skill directory name, including CJK names, and `description` must be
   non-empty. Keep the body harness-neutral. Name skills as `plugin:skill` in authoring text, and
   put harness-specific invocation syntax only in user-facing examples.
3. Add `plugins/<plugin>/.claude-plugin/plugin.json`. At minimum, use the plugin directory name as
   `name`, set a semver `version`, and provide `description`, `author`, `repository`, `homepage`,
   and `keywords` consistent with the existing manifests.

```json
{
  "name": "my-plugin",
  "description": "One-sentence plugin description.",
  "version": "0.0.1",
  "author": {
    "name": "Contributor Name"
  },
  "repository": "https://github.com/wilsonkichoi/agent-toolkit",
  "homepage": "https://github.com/wilsonkichoi/agent-toolkit",
  "keywords": ["relevant-keyword"]
}
```

4. Add `plugins/<plugin>/.codex-plugin/plugin.json` with the same `name`, `version`, and
   `description`, plus `"skills": "./skills/"`.

```json
{
  "name": "my-plugin",
  "version": "0.0.1",
  "description": "One-sentence plugin description.",
  "skills": "./skills/"
}
```

5. Add the plugin to both catalogs. The Claude entry in `.claude-plugin/marketplace.json` uses
   `"source": "./plugins/<plugin>"` and carries the same release version. The Codex entry in
   `.agents/plugins/marketplace.json` uses a local source object whose path is
   `./plugins/<plugin>` and has no version field.

```json
{
  "name": "my-plugin",
  "source": "./plugins/my-plugin",
  "category": "productivity",
  "description": "One-sentence plugin description.",
  "keywords": ["relevant-keyword"],
  "version": "0.0.1"
}
```

```json
{
  "name": "my-plugin",
  "source": {
    "source": "local",
    "path": "./plugins/my-plugin"
  },
  "policy": {
    "installation": "AVAILABLE"
  },
  "category": "Productivity"
}
```

6. Add `plugins/<plugin>/README.md`, add the plugin to the root README table, and update the Claude
   marketplace description and keywords when the new capability changes catalog discovery.
7. If the plugin contains agents, author them under `plugins/<plugin>/agents/*.md` and generate the
   two TOML destinations.
8. Use `0.0.1` for a new pre-release plugin unless the repository already reserves another version.
   Patch-bump the independent `.claude-plugin/marketplace.json` `metadata.version` because adding a
   plugin changes the catalog.
9. Run the generation and validation commands below. The checker validates both manifest formats,
   both marketplaces, semver, skill and agent frontmatter, catalog-to-directory correspondence,
   TOML parsing, and generated-file drift.

## Extend an existing plugin

The `dev` plugin is the concrete model:

1. Change the authoritative skill under `plugins/dev/skills/<skill>/SKILL.md`.
2. Update every contract surface the behavior affects. For `dev`, these can include
   `plugins/dev/docs/manual.md`, `plugins/dev/docs/tracker.md`, `plugins/dev/DESIGN.md`, and
   `plugins/dev/README.md`. Update root `README.md` and `AGENTS.md` when repository-wide behavior or
   authoring rules change.
3. If reviewer, verifier, or test-writer behavior changes, edit the corresponding Markdown source
   under `plugins/dev/agents/`, then regenerate. Never patch generated TOML directly.
4. Bump the plugin by the minimum semver increment. While versions are `0.0.x`, every change uses a
   patch bump. Keep exactly these three values equal: the plugin entry in
   `.claude-plugin/marketplace.json`, `plugins/dev/.claude-plugin/plugin.json`, and
   `plugins/dev/.codex-plugin/plugin.json`.
5. Treat the marketplace-level `.claude-plugin/marketplace.json` `metadata.version` as an
   independent catalog version. Bump it when the catalog itself changes. Never add versions to
   `.agents/plugins/marketplace.json`.
6. Reread the pre-commit checklist in `AGENTS.md`, regenerate when an agent source changed, update
   documentation, and run both repository checks.

Never rename a skill directory under `plugins/`. Keep changes surgical and do not rewrite unrelated
documentation or generated files.

## Generate and validate

Generate Codex agents after any authoritative agent change:

```bash
uv run tools/generate_codex_agents.py
```

Before every handoff, run drift detection and the complete repository validator:

```bash
uv run tools/generate_codex_agents.py --check
uv run tools/check_repo.py
```

These are dependency-free PEP 723 scripts. Do not add `pyproject.toml`, `.python-version`,
`uv.lock`, or a script lockfile for them. Use `uv run`, not a direct Python invocation.

## Test Claude Code working-tree changes

An installed released plugin is appropriate for normal contribution work. To test changes to the
`dev` plugin itself, keep that installation and load the worktree for the current Claude Code
session:

```bash
cd /Users/someuser/code/agent-toolkit-worktrees/some-gh-issue-123
claude --plugin-dir "$PWD/plugins/dev"
```

The explicit `--plugin-dir` copy takes precedence over an installed plugin with the same name for
that session. After editing the worktree plugin, run `/reload-plugins` in the same session before
testing again. This does not uninstall or overwrite the released copy. The precedence and reload
behavior were verified with Claude Code 2.1.210 using a temporary marker in the working-tree skill.

## Test Codex working-tree changes

Codex has no `--plugin-dir` equivalent. It installs and caches a plugin from a marketplace. Replace
the released marketplace with the worktree, reinstall `dev`, copy agent definitions only when the
target is an unrelated project, and start a new thread:

```bash
codex plugin remove dev@agent-toolkit
codex plugin marketplace remove agent-toolkit
codex plugin marketplace add /Users/someuser/code/agent-toolkit-worktrees/some-gh-issue-123
codex plugin add dev@agent-toolkit

mkdir -p /Users/someuser/code/some-dog-food/.codex/agents
cp /Users/someuser/code/agent-toolkit-worktrees/some-gh-issue-123/dist/codex/agents/*.toml \
  /Users/someuser/code/some-dog-food/.codex/agents/

cd /Users/someuser/code/some-dog-food
codex
```

Contributors running Codex in the `agent-toolkit` clone use its committed `.codex/agents/*.toml`
directly and omit the copy step. An unrelated target can also omit the copy when the agents are
already installed under `~/.codex/agents/`.

After each skill edit, refresh the cached plugin and open a new Codex thread:

```bash
codex plugin remove dev@agent-toolkit
codex plugin add dev@agent-toolkit
```

If an authoritative agent source changed, first regenerate both destinations, then repeat the
target-project copy before opening the new thread. Do not alter `.codex-plugin/plugin.json` with a
local cachebuster; its version must remain in lockstep with the Claude manifest and marketplace
entry.

Restore the released marketplace after testing:

```bash
codex plugin remove dev@agent-toolkit
codex plugin marketplace remove agent-toolkit
codex plugin marketplace add wilsonkichoi/agent-toolkit
codex plugin add dev@agent-toolkit
```

The current official Codex plugin-authoring reference is
[Build plugins](https://learn.chatgpt.com/docs/build-plugins).

## CI and maintainer handoff

Run the two repository checks locally before pushing. A contributor may also run Actions in their
fork as preflight, but the fork run is not the merge gate because the contributor controls that
workflow definition.

The authoritative check is `repository-validation` from the canonical repository's
`pull_request` workflow. It runs untrusted fork code on a GitHub-hosted runner with read-only
contents permission, no repository secrets, no persisted checkout credentials, and no privileged
`pull_request_target` path. A maintainer can be required to select `Approve workflows to run`; that
approves restricted CI execution, not the contribution.

Maintainer-only actions are:

- Creating or reconciling internal queue labels and the `Dogfood` milestone.
- Changing Actions approval policy or the active `main` ruleset.
- Promoting external work into the planned queue.
- Authorizing and performing the upstream merge and terminal canonical issue cleanup.

The active `main pull request gate` ruleset requires a pull request, zero approving reviews, the
current `repository-validation` status check, and an up-to-date branch. `CODEOWNERS` routes changes
under
`.github/workflows/` to `@wilsonkichoi` for scrutiny, but code-owner approval is not a merge
requirement. Before merge, the maintainer also reviews workflow, dependency, secret-exposure, and
security-scan risk. Privileged automation must never execute or trust fork code, caches, or
artifacts.

## Maintainer repository setup

One-time configuration of the canonical repository so the fork-contribution gates described above
are actually enforced. Run as a maintainer with `ADMIN` on `wilsonkichoi/agent-toolkit`. Every step
is idempotent; re-running reconciles rather than duplicates.

```bash
REPO=wilsonkichoi/agent-toolkit
```

### Internal queue labels

Five `status:*`, three `priority:*`, three `size:*`. Do not attach any of them to the external
contribution issue template; they are internal-queue only.

```bash
gh label create status:backlog     --repo "$REPO" --force --color ededed --description "Captured, not committed"
gh label create status:todo        --repo "$REPO" --force --color c2e0c6 --description "Committed, unclaimed"
gh label create status:in-progress --repo "$REPO" --force --color fbca04 --description "Claimed, being worked"
gh label create status:in-review   --repo "$REPO" --force --color 0e8a16 --description "PR up, CI green"
gh label create status:blocked     --repo "$REPO" --force --color d93f0b --description "Stuck, needs human"
gh label create priority:high      --repo "$REPO" --force --color b60205 --description "High priority"
gh label create priority:medium    --repo "$REPO" --force --color fbca04 --description "Medium priority"
gh label create priority:low       --repo "$REPO" --force --color 0e8a16 --description "Low priority"
gh label create size:S             --repo "$REPO" --force --color c5def5 --description "Small estimate"
gh label create size:M             --repo "$REPO" --force --color bfd4f2 --description "Medium estimate"
gh label create size:L             --repo "$REPO" --force --color a2c4c9 --description "Large estimate"
```

### Dogfood milestone

```bash
gh api --method POST "repos/$REPO/milestones" -f title=Dogfood || \
  gh api "repos/$REPO/milestones?state=all&per_page=100" \
    --jq '.[] | select(.title=="Dogfood") | {number,title,state}'
```

### Fork pull-request workflow approval

Choose an approval policy for fork-PR workflow runs. `first_time_contributors` is the GitHub default
and the standing choice here: a contributor's first PR needs a maintainer to press **Approve
workflows to run** before CI executes, then their runs proceed automatically once they have a merged
PR. Because `repository-validation` carries no secrets and read-only contents (see above), the
stricter `all_external_contributors` (approval on *every* fork push, forever) is rarely worth its
friction; use it only during a hardening window.

```bash
gh api --method PUT "repos/$REPO/actions/permissions/fork-pr-contributor-approval" \
  -f approval_policy=first_time_contributors
gh api "repos/$REPO/actions/permissions/fork-pr-contributor-approval"
#   expect: {"approval_policy":"first_time_contributors"}
```

### `main pull request gate` ruleset

Requires a PR, zero approving reviews, a strict (up-to-date) `repository-validation` status check,
and no bypass actors. `CODEOWNERS` already routes `.github/workflows/` to `@wilsonkichoi`, but
code-owner approval is deliberately not required to merge.

> **Target format warning.** The `conditions.ref_name.include` value must be exactly
> `refs/heads/main`. Entering `refs/heads/main` into the UI's branch-target box (which prepends its
> own `refs/heads/`) can store the doubled value `refs/heads/refs/heads/main`, which silently targets
> a nonexistent branch and disables the gate. Always verify the stored value after creating or
> editing the ruleset.

Create via API with the correct target (`integration_id` 15368 is GitHub Actions):

```bash
gh api --method POST "repos/$REPO/rulesets" --input - <<'JSON'
{
  "name": "main pull request gate",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/main"], "exclude": [] } },
  "bypass_actors": [],
  "rules": [
    { "type": "pull_request", "parameters": {
        "required_approving_review_count": 0,
        "require_code_owner_review": false,
        "dismiss_stale_reviews_on_push": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["merge", "squash", "rebase"] } },
    { "type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": false,
        "required_status_checks": [ { "context": "repository-validation", "integration_id": 15368 } ] } }
  ]
}
JSON
```

Verify the stored target and the required check:

```bash
gh api "repos/$REPO/rulesets" --jq '.[] | select(.name=="main pull request gate") | .id'
RULESET_ID=$(gh api "repos/$REPO/rulesets" --jq '.[] | select(.name=="main pull request gate") | .id')
gh api "repos/$REPO/rulesets/$RULESET_ID" --jq '{
  enforcement,
  include: .conditions.ref_name.include,
  strict: (.rules[] | select(.type=="required_status_checks").parameters.strict_required_status_checks_policy),
  checks: [.rules[] | select(.type=="required_status_checks").parameters.required_status_checks[].context],
  approvals: (.rules[] | select(.type=="pull_request").parameters.required_approving_review_count)
}'
#   expect: include ["refs/heads/main"], enforcement active, strict true,
#           checks ["repository-validation"], approvals 0
```

Create the ruleset only after `repository-validation.yml` is on `main` and has produced at least one
check run, so the required-status-check context resolves.
