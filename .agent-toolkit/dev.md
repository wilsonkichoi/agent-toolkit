---
tracker: github
github_primary_repo: wilsonkichoi/agent-toolkit
fork_contributions: true
test_command: "uv run tools/generate_codex_agents.py --check && uv run tools/check_repo.py"
ci_workflow: repository-validation.yml
merge_policy: squash
review_action_installed: false
work_in_progress_limit: 3
max_fix_attempts: 3
max_tasks_per_run: 5
auto_merge: false
context_file: AGENTS.md
rules_dir: .agent-toolkit/rules/
---

# Project development conventions

`AGENTS.md` is the authoring-conventions source of truth. The full contributor workflow is in
`CONTRIBUTING.md`; the runtime contracts for the `dev` plugin are in
`plugins/dev/runtime_contracts/` and its operating guide is `plugins/dev/README.md`.

- External contributions use canonical GitHub issues and cross-repository pull requests. They do
  not enter the maintainer's planned queue unless a maintainer explicitly promotes them.
- In fork contribution mode, `wilsonkichoi/agent-toolkit` owns issues and pull requests,
  `upstream/main` supplies the branch base, and `origin` receives contributor branch pushes.
- Only maintainers mutate queue labels, milestones, Actions policy, rulesets, or terminal upstream
  issue and merge state.
- Run both commands in `test_command` before handoff. Agent-source changes must regenerate both
  `.codex/agents/` and `dist/codex/agents/` before the checks run.

## Rules

<!-- Rule files are discovered under `rules_dir`; this section is not a registry.
     Add a rule by writing `<rules_dir>/<slug>.md` with `tier` frontmatter -
     see plugins/dev/runtime_contracts/project-bootstrap.md. -->
