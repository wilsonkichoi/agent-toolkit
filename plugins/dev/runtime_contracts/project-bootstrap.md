# Project Bootstrap Contract

Task-scoped lifecycle skills use this contract before implementation, review, verification,
or retrospective evidence gathering. It is harness-neutral and does not depend on Claude Code
expanding `@` imports.

## Sequence

1. **Load tracker routing only.** Read the tracker repository's dev configuration using the
   normal fallback chain (`.agent-toolkit/dev.md`, `.agent/dev.md`, `.claude/dev.md`) and
   `runtime_contracts/tracker.md`. Resolve the tracker and GitHub repository roles once. Do not treat the
   tracker repository's project instructions or rules as the execution repository's rules.
2. **Resolve the execution repository.** Fetch the task packet or linked issue/PR only far
   enough to determine where the work runs. An explicit `Execution repo:` packet field wins.
   Otherwise use the PR head repository when it differs from the tracker repository; otherwise
   use the tracker repository. Resolve the expected execution revision before choosing a local
   path:

   - For review, fix, verify, and PR-backed retro, use the PR head OID.
   - For the initial `dev:execute` or `dev:auto` bootstrap before a task worktree exists, use the
     resolved base commit from which step 2 will create the task branch.
   - After isolation, use the task worktree's branch `HEAD`.
   - For a read-only lifecycle with no PR or task worktree, use the selected execution checkout's
     current `HEAD`.

   Resolve the repository identity and expected revision to a local checkout or worktree whose
   `HEAD` is that exact commit. If no matching checkout is available, stop instead of loading
   instructions from another revision or from the tracker repository as a substitute.
3. **Build the rule context.** Run the resolver from the installed plugin, passing the exact
   tracker and execution repository paths, the expected execution revision, task objective,
   Definition of Done, and every known changed path. The resolver verifies that the selected
   checkout's `HEAD` matches the expected revision before reading project files. On Claude Code
   the script is under `${CLAUDE_PLUGIN_ROOT}/scripts/`; on Codex it is
   `../../scripts/resolve_project_rules.py` relative to a dev skill's `SKILL.md`.
4. **Load, do not only list.** Read every file under `Project instructions:` and `Rules loaded:`
   in the resolver output before acting. The execution repository's configured context file and
   dev configuration are mandatory project instructions. Treat resolver failure, a missing
   configured file, invalid rule metadata, an import cycle, or a path escaping the execution
   repository as a hard stop.
5. **Refresh when context changes.** `dev:execute` runs the initial bootstrap at the resolved base
   commit from Objective and Definition of Done, reruns it in the new task worktree before
   implementation, then reruns it after implementation with the complete changed-path list before
   tests and handoff. `dev:auto` follows the same sequence across its orchestrator and worker.
   Review, fix, verify, and retro use the PR or branch diff and therefore pass changed paths on
   their first run; fix mode reruns after edits. When local work advances the branch, refresh the
   expected revision from the new branch `HEAD` before rerunning.
6. **Make loading observable.** Preserve the resolver's exact `Execution repository:`,
   `Execution revision:`, and `Rules loaded:` entries in the lifecycle record: execute work
   summary, review body, verify report, auto task report, or retro comment. A delegated agent
   receives the resolved execution repository and revision, changed paths, and exact loaded-file
   list and must read those files itself.

The CLI contract is:

```text
uv run <plugin-root>/scripts/resolve_project_rules.py \
  --tracker-repo <path> \
  --execution-repo <path> \
  --execution-revision <commit> \
  --objective <text> \
  --definition-of-done <text> \
  [--changed-path <repo-relative-path> ...] \
  [--format text|json]
```

## Rule metadata

Rule files are terminal markdown files reached recursively from `@path` entries under the dev
configuration's `## Rules` section. Imports beginning with `./` or `../` resolve relative to the
importing file; other imports resolve from the execution repository root. Imports must remain
inside the configured `rules_dir`.

Doctrine rules always load:

```markdown
---
tier: doctrine
---

# Run the guard suite

Run the guard suite before citing it as regression evidence.
```

Gotcha rules load when any declared trigger matches. Path triggers use repository-relative glob
patterns; a `**` path segment matches zero or more directories. Objective and Definition of Done
triggers are case-insensitive substrings.

```markdown
---
tier: gotcha
triggers:
  paths:
    - "scripts/**/*.sh"
  objective:
    - "shell script"
  definition_of_done:
    - "POSIX"
---

# Shell script portability

Run shell scripts under every supported shell.
```

A gotcha rule must declare at least one trigger. Every terminal rule with frontmatter must declare
`tier`; missing or invalid tier metadata is a hard stop. A terminal legacy rule without
frontmatter is treated as doctrine so an upgrade cannot silently stop loading an existing rule.
An imported file containing further `@` imports is an index and cannot also declare a tier.
Legacy `.agent/dev.md` or `.claude/dev.md` configurations with neither `context_file` nor
`rules_dir` preserve the pre-port fallback to `CLAUDE.md` and `.claude/rules/`. If no configured
context file and no applicable `AGENTS.md` or `CLAUDE.md` fallback exists, resolution stops.
