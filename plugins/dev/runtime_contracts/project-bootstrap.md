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
   `HEAD` is that exact commit. If no matching checkout is available, create one - fetch the
   revision when it is not local (`git fetch <remote> refs/pull/<n>/head` for a PR head), then
   `git worktree add --detach <path> <revision>` - and remove it afterwards. Otherwise stop
   instead of loading instructions from another revision or from the tracker repository as a
   substitute. Never substitute another revision to get past the resolver, including the merge
   commit of the PR under review: an identical tree today is not a guarantee, and the
   substitution is invisible in the lifecycle record.
3. **Build the rule context.** Run the resolver from the installed plugin, passing the exact
   tracker and execution repository paths, the expected execution revision, task objective,
   Definition of Done, and every known changed path. The resolver verifies that the selected
   checkout's `HEAD` matches the expected revision before reading project files. On Claude Code
   the script is under `${CLAUDE_PLUGIN_ROOT}/scripts/`; on Codex it is
   `../../scripts/resolve_project_rules.py` relative to a dev skill's `SKILL.md`.
4. **Load, do not only list.** Read every file under `Project instructions:` and `Rules loaded:`
   in the resolver output before acting. The execution repository's configured context file and
   dev configuration are mandatory project instructions. Treat resolver failure, a missing
   configured file, an unclassified rule file, invalid rule metadata, or a path escaping the
   execution repository as a hard stop. Entries under `Rules excluded:` are files their author
   marked as non-rules; do not read them as instructions.
5. **Refresh when context changes.** `dev:execute` runs the initial bootstrap at the resolved base
   commit from Objective and Definition of Done, reruns it in the new task worktree before
   implementation, then reruns it after implementation with the complete changed-path list before
   tests and handoff. `dev:auto` follows the same sequence across its orchestrator and worker.
   Review, fix, verify, and retro use the PR or branch diff and therefore pass changed paths on
   their first run; fix mode reruns after edits. When local work advances the branch, refresh the
   expected revision from the new branch `HEAD` before rerunning.
6. **Make loading observable.** Preserve the resolver's exact `Execution repository:`,
   `Execution revision:`, and `Rules loaded:` entries in the lifecycle record: execute work
   summary, review body, verify report, auto task report, or retro comment. Carry any entry the
   resolver reports under `Warnings:` in the same record, so an over-inclusion caveat travels with
   the run that hit it. A delegated agent receives the resolved execution repository and revision,
   changed paths, and exact loaded-file list and must read those files itself.

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

## Rule discovery

**Discovery completeness.** Every Markdown file under the configured `rules_dir`, at any depth, is
a discovered rule file. There is no registry: nothing has to point at a rule for the resolver to
find it, and dropping a file into `rules_dir` is the whole act of adding a rule. A rule that exists
on disk can therefore never be silently absent from resolution, which is the failure the retired
`## Rules` import graph allowed. Rule files are terminal by construction: an `@` import line
anywhere inside a discovered file is a hard stop, because its target would load unclassified.

**Every discovered file is classified, or resolution stops.** The resolver reads each file's own
frontmatter and places it in exactly one bucket:

| Frontmatter | Outcome |
|---|---|
| `tier: doctrine` | Loaded unconditionally, reported under `Rules loaded:`. |
| `tier: gotcha` with at least one declared trigger | Loaded when a trigger matches, otherwise reported under `Rules skipped:`. |
| `tier: none` | Excluded, reported under `Rules excluded:`. |
| anything else | Hard stop. |

**`tier: none` is the only way to keep non-rule Markdown in `rules_dir`.** A README, an index, or
maintainer notes declare it in their own frontmatter, where the exclusion is visible in review.
There is no implicit ignore: no ignore file, no filename special case, no directory-name
convention. Silence is never read as consent, so an unmarked file is always a hard stop.

**Under-inclusion is a hard stop; over-inclusion is a reported warning.** A rule that should have
loaded and did not is a silent correctness hole. A rule that loaded when it need not have costs
context and nothing else. That asymmetry decides every case below.

Hard stops, each naming every offending repository-relative path in deterministic sort order and
stating both remedies (declare a `tier`, or mark the file `tier: none`):

- a discovered file with no frontmatter;
- frontmatter that does not declare `tier`;
- malformed frontmatter (an unterminated block);
- an unknown `tier` value;
- `tier: gotcha` declaring no trigger;
- an `@` import line inside a discovered file;
- a symlink under `rules_dir` whose target resolves outside the execution repository;
- a missing configured context file, or a `rules_dir` resolving outside the execution repository.

Reported warnings, which never stop resolution:

- `rules_dir` resolving inside a harness's native auto-load path (`.claude/rules/`,
  `~/.claude/rules/`). The harness loads those files at session start regardless of tier, so
  skipped gotchas and `tier: none` files may still be in context. `.agent-toolkit/rules/` is the
  location that gives every harness the same answer.
- `@` import lines left under the dev configuration's `## Rules` section. Discovery ignores them,
  but a harness that expands imports still loads their targets unconditionally. `dev:setup`
  removes them.

A `rules_dir` that is absent, empty, or entirely `tier: none` resolves to zero rules and succeeds:
every file there was a recorded decision, so there is nothing to fail on.

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

Non-rule Markdown declares itself out, and stays where it is:

```markdown
---
tier: none
---

# Rules directory conventions

Notes for human maintainers; not an agent instruction.
```

A repository whose rule files predate this contract carries no `tier` and hard-stops until every
file is classified; `dev:setup` performs that migration and reports every file it changes. Legacy
`.agent/dev.md` or `.claude/dev.md` configurations with neither `context_file` nor
`rules_dir` preserve the pre-port fallback to `CLAUDE.md` and `.claude/rules/`. If no configured
context file and no applicable `AGENTS.md` or `CLAUDE.md` fallback exists, resolution stops.
