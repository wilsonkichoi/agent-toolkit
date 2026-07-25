# check-rules composite action fixtures

Three isolated repositories the `repository-validation` workflow runs
`.github/actions/check-rules` against, one per outcome the action must produce:

| Fixture | Contents | Expected action result |
|---|---|---|
| `no-config/` | no `.agent-toolkit/dev.md` | success, `result=skipped`, nothing installed or written |
| `compliant/` | config plus one doctrine, one gotcha, and one `tier: none` rule | success, `result=checked` |
| `invalid-rule/` | config plus a rule file with no frontmatter | failure, with the resolver's unclassified-Markdown diagnostic |

They are plain directories, not git checkouts, because `resolve_project_rules.py --check`
validates no revision. Nothing outside this directory reads them: the repository's own
`rules_dir` is `.agent-toolkit/rules/`, so a fixture rule is never discovered as a real rule.

`tools/test_check_rules_action.py` drives the same fixtures through the action's entrypoint
without a runner, so the contract is enforced locally by `uv run tools/check_repo.py` as well
as in CI.
