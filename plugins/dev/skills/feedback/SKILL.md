---
name: feedback
description: >
  This skill should be used when the user says "file a bug against agent-toolkit",
  "report this issue to the plugin", "feedback for agent-toolkit", "this is a dev plugin
  bug", "submit an enhancement request", or invokes /dev:feedback. Turns problems and
  improvement ideas discovered during dev lifecycle runs into structured, deduplicated
  GitHub issues in the agent-toolkit repository.
argument-hint: "[bug | enhancement | docs | workflow] <description>"
---

# dev:feedback

File structured feedback (bugs, enhancements, documentation gaps, workflow friction)
against the agent-toolkit plugin repository without leaving the current project session.
The skill drafts, deduplicates, redacts, and submits, but never writes without explicit
human approval.

This skill does NOT create or mutate any task in the current project's primary tracker.
It targets only `wilsonkichoi/agent-toolkit`.

## Constants

- **Target repository:** `wilsonkichoi/agent-toolkit`
- **Labels by category:**
  - bug: `bug`
  - enhancement: `enhancement`
  - docs: `documentation`
  - workflow: `enhancement`

## 1. Gather context

Collect diagnostic information from the active session. Every field is best-effort; missing
values are omitted, never fabricated.

| Field | Source |
|---|---|
| agent-toolkit version | Read the installed plugin's `plugin.json` version field |
| harness | Claude Code or Codex (infer from the session environment) |
| invoked skill | The dev skill that surfaced the problem (e.g. `dev:execute`, `dev:verify`) |
| tracker backend | `.agent-toolkit/dev.md` `tracker:` field of the current project |
| tracker repository | Resolved canonical repository from the current project config |
| execution repository | The repository where the problem occurred |
| task or PR identifier | The task id or PR number being worked when the issue arose |
| expected behavior | What should have happened |
| actual behavior | What actually happened |
| impact | How this affected the workflow (blocked, workaround needed, minor friction) |

Ask the user to confirm or fill in any fields that cannot be gathered automatically.
The category (bug, enhancement, docs, workflow) can be inferred from context or the
argument; ask if ambiguous.

## 2. Redact

Before rendering any draft, run the bundled redaction helper on every text field that will
appear in the issue body. On Claude Code the script is under
`${CLAUDE_PLUGIN_ROOT}/scripts/feedback_redact.py`; on Codex it is
`../../scripts/feedback_redact.py` relative to this skill's directory.

**Always pass text via stdin, never as shell arguments.** Write the text to a temporary
file and redirect, or pipe it directly from the tool output. This avoids shell
interpretation of untrusted content (quotes, `$()`, backticks).

```bash
uv run <plugin-root>/scripts/feedback_redact.py redact < /tmp/field.txt
```

Or pipe via heredoc when the text is known safe (no unmatched quotes):

```bash
uv run <plugin-root>/scripts/feedback_redact.py redact <<'REDACT_EOF'
<text to redact>
REDACT_EOF
```

A bare `owner/repo` name whose visibility is not established is redacted to `<private-repo>`
by default; false positives are acceptable because you review the draft before filing, a
leaked private repository name is not. Add `--public-repo <owner/repo>` for any repository
whose visibility has been confirmed public so the helper preserves it. Add
`--private-repo <owner/repo>` for any repository known to be private (the current project's
tracker repository, execution repository, etc.); all occurrences of that name in the text
will be replaced. The helper strips:

- Secrets and credentials (API keys, tokens, passwords, PEM private keys, connection strings)
- Private repository URLs on any git hosting platform (GitHub, GitLab, Bitbucket, etc.)
- Explicitly declared private repository names (all occurrences)
- Bare `owner/repo` names of unestablished visibility (redacted by default; declare
  confirmed-public ones with `--public-repo` to keep them)
- Unix home paths (`/Users/<name>/`, `/home/<name>/`) replaced with `~/`
- Windows user paths (`C:\Users\<name>\...`) replaced with `<redacted-path>`
- Sensitive absolute paths (`/opt/`, `/var/`, `/etc/`, `/srv/`, `/tmp/`, `/usr/local/`)

Preserve (handled automatically by the helper):

- Public `wilsonkichoi/agent-toolkit` links (issues, PRs, files)
- Declared public repository names
- Ordinary two-segment technical terms (`client/server`, `read/write`) and git refs /
  branch names (`origin/main`, `task/<id>-<slug>`)
- Error messages and stack traces (after secret stripping)
- Skill names, command invocations, and configuration field names

Additionally, when assembling context, do not include:

- Private issue and PR content (titles, bodies) from the current project
- Unnecessary absolute paths (use relative paths or `<project-root>/`)

If a piece of context is needed for the report but cannot be safely included, describe
its shape without revealing the value (e.g. "a Linear project key" instead of the actual
key).

## 3. Check access and search for duplicates

First, check GitHub access:

```bash
uv run <plugin-root>/scripts/feedback_redact.py access
```

The access check returns `authenticated`, `has_write`, and `permission`.

- If `authenticated: false`: skip the duplicate search (no `gh` access at all).
  Note that the workflow will end with an offline draft in step 6.
- If `authenticated: true` but `has_write: false`: the user can still search
  (the target repo is public). Proceed with the duplicate search below.
  Submission will use the offline draft path (step 6) since the user cannot write.
- If `authenticated: true` and `has_write: true`: full online path.

When authenticated, search for duplicates. Use only short, agent-chosen search terms
derived from the title and symptoms (never raw user text as an argument):

```bash
uv run <plugin-root>/scripts/feedback_redact.py search 'keyword1 keyword2' 'symptom phrase'
```

The helper searches both open and closed issues in `wilsonkichoi/agent-toolkit`,
deduplicates results, and returns JSON with number, title, state, and url per match.
If the search fails despite authentication (rate limit, transient error), the helper
exits nonzero. Report the failure to the user and ask whether to proceed without
duplicate checking or retry.

Present any likely matches to the user with their number, title, state, and URL.
If a match is confirmed as a duplicate:
- Ask whether to add a comment to the existing issue instead of filing a new one.
- If commenting, draft the comment (new evidence, reproduction context) and submit
  only after explicit approval.
- Stop. Do not file a new issue.

## 4. Select template

If step 3 determined that `gh` is authenticated, fetch the current issue templates:

```bash
gh api repos/wilsonkichoi/agent-toolkit/contents/.github/ISSUE_TEMPLATE \
  --jq '.[].name'
```

Select the template whose name indicates external contributions (currently
`external-contribution.yml`). Feedback issues are contributions, not
maintainer-planned tasks; they enter through the external contribution channel and may
be promoted by a maintainer later.

If the template set has changed (renamed, removed, new templates added), pick the
closest match for a contribution.

If `gh` is not authenticated (offline path), or if the template fetch fails, use
the default fields below directly without a template fetch.

Read the selected template (when available) to discover its current field names.
Map the gathered context to those fields. The expected mapping:

| Template field | Content |
|---|---|
| Objective | Concrete outcome: what the fix or improvement delivers |
| Why | The problem, its impact, and the context in which it was discovered |
| Definition of Done | Verifiable completion criteria |
| Relevant references | Links to related issues, relevant code paths, specs |
| Suggested implementation | Optional: proposed approach if the reporter has one |

## 5. Draft

Use the bundled draft helper to render the complete issue body. **Write the JSON input
to a temporary file** and pass it with `--input` to avoid shell interpolation:

```bash
uv run <plugin-root>/scripts/feedback_redact.py draft --input /tmp/feedback-draft.json
```

The JSON input must contain: `title`, `category`, `objective`, `why`,
`definition_of_done`, and optionally `references`, `implementation`,
`public_repos` (list of confirmed-public repository names), and `private_repos`
(list of known-private repository names to redact). The helper applies redaction to
all fields (including the title) and returns JSON with `title`, `label`, `body`, and
`command` fields.

Present the rendered draft to the user showing:

```
Title: <from helper output>
Labels: <from helper output>
Template: external-contribution

---
<body from helper output>
```

State clearly: "This will create an issue in `wilsonkichoi/agent-toolkit`. Approve to
submit, or request changes."

## 6. Submit

**Requires explicit human approval.** Do not submit on silence, ambiguity, or implicit
confirmation. The user must clearly say yes, approve, submit, file it, or equivalent.

If step 3 determined that the user cannot write (`authenticated: false` or
`has_write: false`):
- Present the complete issue draft in a copyable fenced block.
- Include the `command` field from the draft helper output.
- Stop. Report that GitHub write access is unavailable and the user can file manually.
  Do not retry or error-loop.

On approval with `has_write: true`, write the draft body to a temporary file and run
the command from the draft helper output (which uses `--body-file <draft-file>`).
Replace `<draft-file>` with the actual temporary file path.

Return the created issue URL.

## 7. Optional: link back

After successful submission, offer (do not auto-execute) to add the created issue URL as
a reference comment on the originating task in the current project's tracker. This
requires a second explicit approval because it writes to the current project's tracker.

If declined or if there is no originating task, skip silently.

## Scope boundaries

- This skill NEVER creates or mutates tasks in the current project's primary tracker
  (no labels, no status changes, no comments on project tasks, except the optional
  link-back in step 7 with explicit approval).
- This skill targets only `wilsonkichoi/agent-toolkit`. It does not file issues in
  other repositories.
- This skill does not implement fixes. It files the report and stops.
- This skill does not require or use the project bootstrap sequence (it does not
  execute task work in the current project).
