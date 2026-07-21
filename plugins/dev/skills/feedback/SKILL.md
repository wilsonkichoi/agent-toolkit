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

Before rendering any draft, strip:

- Secrets and credentials (API keys, tokens, passwords, connection strings)
- Private repository names and URLs (replace with `<private-repo>`)
- Private issue and PR content (titles, bodies) from the current project
- Local usernames and home directory paths (replace `/Users/<name>/` with `~/`)
- Unnecessary absolute paths (use relative paths or `<project-root>/`)

Preserve:

- Public `wilsonkichoi/agent-toolkit` links (issues, PRs, files)
- Public repository names when their visibility is confirmed
- Error messages and stack traces (after secret stripping)
- Skill names, command invocations, and configuration field names

If a piece of context is needed for the report but cannot be safely included, describe
its shape without revealing the value (e.g. "a Linear project key" instead of the actual
key).

## 3. Search for duplicates

Search open and recently closed issues in `wilsonkichoi/agent-toolkit` for likely
duplicates. Run at least two queries with different keyword strategies:

```bash
gh search issues --repo wilsonkichoi/agent-toolkit --state open "<keywords from title>"
gh search issues --repo wilsonkichoi/agent-toolkit "<keywords from symptoms>"
```

Also check closed issues for recent fixes that may have regressed:

```bash
gh search issues --repo wilsonkichoi/agent-toolkit --state closed "<keywords>"
```

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

Render the complete issue as it would appear when filed:

```
Title: <concise title>
Labels: <category label>
Template: external-contribution

---
## Objective
<filled>

## Why
<filled>

## Definition of Done
<filled>

## Relevant references
<filled, or "None">

## Suggested implementation
<filled, or "None">
```

Present the draft to the user. State clearly: "This will create an issue in
`wilsonkichoi/agent-toolkit`. Approve to submit, or request changes."

## 6. Submit

**Requires explicit human approval.** Do not submit on silence, ambiguity, or implicit
confirmation. The user must clearly say yes, approve, submit, file it, or equivalent.

If GitHub authentication is unavailable or write access is denied:
- Present the complete issue draft in a copyable fenced block.
- Include the `gh` command that would create it.
- Stop. Do not retry or error-loop.

On approval with working access:

```bash
gh issue create --repo wilsonkichoi/agent-toolkit \
  --title "<title>" \
  --label "<label>" \
  --body "<body>"
```

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
