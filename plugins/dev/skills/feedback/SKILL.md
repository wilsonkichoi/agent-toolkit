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

```bash
uv run <plugin-root>/scripts/feedback_redact.py redact --text "<field value>"
```

For multiple fields, pipe the assembled text via stdin:

```bash
echo "<assembled text>" | uv run <plugin-root>/scripts/feedback_redact.py redact
```

Add `--public-repo <owner/repo>` for any repository whose visibility has been confirmed
public. The helper strips:

- Secrets and credentials (API keys, tokens, passwords, connection strings)
- Private repository names and URLs (replace with `<private-repo>`)
- Local usernames and home directory paths (replace `/Users/<name>/` with `~/`)

Preserve (handled automatically by the helper):

- Public `wilsonkichoi/agent-toolkit` links (issues, PRs, files)
- Declared public repository names
- Error messages and stack traces (after secret stripping)
- Skill names, command invocations, and configuration field names

Additionally, when assembling context, do not include:

- Private issue and PR content (titles, bodies) from the current project
- Unnecessary absolute paths (use relative paths or `<project-root>/`)

If a piece of context is needed for the report but cannot be safely included, describe
its shape without revealing the value (e.g. "a Linear project key" instead of the actual
key).

## 3. Search for duplicates

Use the bundled search helper to find likely duplicates across open and closed issues:

```bash
uv run <plugin-root>/scripts/feedback_redact.py search "<keywords from title>" "<keywords from symptoms>"
```

The helper searches both open and closed issues in `wilsonkichoi/agent-toolkit`,
deduplicates results, and returns JSON with number, title, state, and url per match.
If the search fails (rate limit, auth error, network), the helper exits nonzero with an
error message. Do not proceed to draft or submit if the duplicate search could not
complete; report the failure to the user.

Present any likely matches to the user with their number, title, state, and URL.
If a match is confirmed as a duplicate:
- Ask whether to add a comment to the existing issue instead of filing a new one.
- If commenting, draft the comment (new evidence, reproduction context) and submit
  only after explicit approval.
- Stop. Do not file a new issue.

## 4. Select template

Choose the issue template based on the target repository's `.github/ISSUE_TEMPLATE/`:

- Bug reports or regressions: use `external-contribution.yml` with a clear reproduction
  framing in the Objective.
- Enhancements, docs gaps, workflow improvements: use `external-contribution.yml` with
  a proposal framing.

The external-contribution template is the correct choice because feedback issues are
contributions to agent-toolkit, not maintainer-planned tasks. They enter through the
external contribution channel and may be promoted to the planned queue by a maintainer
later.

Fill the template fields:

| Template field | Content |
|---|---|
| Objective | Concrete outcome: what the fix or improvement delivers |
| Why | The problem, its impact, and the context in which it was discovered |
| Definition of Done | Verifiable completion criteria |
| Relevant references | Links to related issues, relevant code paths, specs |
| Suggested implementation | Optional: proposed approach if the reporter has one |

## 5. Draft

Use the bundled draft helper to render the complete issue body:

```bash
echo '<json>' | uv run <plugin-root>/scripts/feedback_redact.py draft
```

The JSON input must contain: `title`, `category`, `objective`, `why`,
`definition_of_done`, and optionally `references` and `implementation`. The helper
returns JSON with `title`, `label`, `body`, and `command` fields.

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

Before attempting submission, check access:

```bash
uv run <plugin-root>/scripts/feedback_redact.py access
```

If GitHub authentication is unavailable or write access is denied (the helper returns
`has_write: false`):
- Present the complete issue draft in a copyable fenced block.
- Include the `command` field from the draft helper output.
- Stop. Do not retry or error-loop.

On approval with working access, write the draft body to a temporary file and run the
command from the draft helper output (which uses `--body-file <draft-file>`). Replace
`<draft-file>` with the actual path.

Return the created issue URL.

## 7. Optional: link back

After successful submission, offer (do not auto-execute) to add the created issue URL as
a reference comment on the originating task in the current project's tracker. This
requires a second explicit approval because it writes to the current project's tracker.

If declined or if there is no originating task, skip silently.

## Unavailable GitHub access

If `gh auth status` fails or the user lacks write access to `wilsonkichoi/agent-toolkit`:

1. Complete steps 1-5 normally (gather, redact, search, template, draft).
2. Present the final draft in a fenced code block.
3. Include the exact `gh issue create` command that would file it.
4. Stop. Report that GitHub access is unavailable and the user can file manually.

## Scope boundaries

- This skill NEVER creates or mutates tasks in the current project's primary tracker
  (no labels, no status changes, no comments on project tasks, except the optional
  link-back in step 7 with explicit approval).
- This skill targets only `wilsonkichoi/agent-toolkit`. It does not file issues in
  other repositories.
- This skill does not implement fixes. It files the report and stops.
- This skill does not require or use the project bootstrap sequence (it does not
  execute task work in the current project).
