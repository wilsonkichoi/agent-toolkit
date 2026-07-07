# Tracker Contract

The tracker is the single source of truth for task state. Every dev skill that touches tasks
implements the verbs below against the backend configured in the project's `.claude/dev.md`
frontmatter (`tracker:` field). Skills never maintain a parallel status file (no PLAN.md
checkboxes, no PROGRESS.md). Docs (`docs/PRD.md`, `docs/SPEC.md`) are the source of truth for
intent; the tracker only for state.

## Verbs

| Verb | Semantics |
|---|---|
| `next-task` | Return the highest-priority claimable task (see selection algorithm). |
| `get-task <id>` | Return the full task packet: fields, body, comments, status, dependencies. |
| `claim <id>` | Set status `In Progress` and assign to self. Re-read after writing to confirm the claim won (guards against a parallel session claiming simultaneously). |
| `comment <id> <body>` | Append a comment. Never edit or delete existing comments. |
| `transition <id> <status>` | Move the task to a lifecycle status, respecting the ownership rules below. |
| `create-task <packet>` | Create a task from a packet (see DESIGN.md task packet schema). |
| `list <milestone>` | List tasks in a milestone with id, title, status, priority, dependencies. |

## Status lifecycle

`Backlog → Todo → In Progress → In Review → Done`, plus `Blocked` and `Wont Do`.

Ownership rules - who may set what:

| Status | Set by | Meaning |
|---|---|---|
| `Backlog` | `dev:backlog` intake, manual tickets | Captured, not committed. |
| `Todo` | `dev:plan` (approved milestone tasks), human promotion, `dev:backlog` on instruction | Committed. The only status `dev:execute` claims from. |
| `In Progress` | `dev:execute` claim | One session is implementing it. |
| `In Review` | `dev:execute` when PR is up and CI is green | Awaiting review/verify. |
| `Done` | `dev:verify` only, after DoD evidence and merge | Actually done. |
| `Blocked` | `dev:execute` after `max_fix_attempts` failures, or anyone with a reason comment | Needs human attention; always accompanied by a diagnostic comment. |
| `Wont Do` | `dev:backlog` or human, with a rationale comment | Deliberately not doing; the reason must survive. |

`Backlog → Todo` promotion is never automatic.

## next-task selection algorithm

All backends use the same algorithm:

1. **WIP gate first:** count tasks with status `In Progress` or `In Review`. If the count is
   `>= work_in_progress_limit` (from `.claude/dev.md`, default 3), return nothing and report that the WIP
   limit is reached - review/verify must drain the queue before more work starts.
2. **Candidates:** tasks with status `Todo` in the active milestone whose dependencies are all
   `Done`. A dependency in any other status (including `In Review`) blocks the dependent task,
   because "done" means merged.
3. **Order:** priority (highest first), then task id ascending (plan order encodes intent).
4. Return the first candidate.

## Backend: Linear (`tracker: linear`)

Uses the official Linear MCP server (`mcp.linear.app`). Discover exact tool names from the MCP
tool list at runtime (typically `list_issues`, `get_issue`, `create_issue`, `update_issue`,
`create_comment`, `list_comments`); do not assume names not present in the tool list. Scope
all calls with `linear_team` / `linear_project` from `.claude/dev.md`.

**Consistent reads** (found in Linear dogfood DOG-10): an *unfiltered* `list_issues` call
can silently omit issues that a `state`-filtered call returns - one dogfood run claimed a
Medium task while an Urgent one existed because the unfiltered listing missed it. For
`next-task` and `list`, always query with an explicit state filter (one call per status you
need, e.g. `state: "Todo"`, plus `In Progress`/`In Review` for the WIP count); never derive
the candidate set from an unfiltered listing. When a specific issue matters, confirm with
`get_issue <id>` rather than its presence in a list result.

| Contract concept | Linear mapping |
|---|---|
| Task | Issue in the configured team + project |
| Milestone | Linear project milestone (preferred) or label `milestone:<n>` - record the choice in `.claude/dev.md` body |
| Status | Workflow states: `Backlog`, `Todo`, `In Progress`, `In Review`, `Done`. `Wont Do` → `Canceled`. If the team lacks an `In Review` state, ask the human to add one (workflow edits are a human decision) |
| `Blocked` | Keep the workflow state, add label `blocked` + diagnostic comment. Native "blocked by" relations express dependencies, not the Blocked status |
| Dependencies | Linear "blocked by" issue relations; fall back to a `Deps: <ids>` line in the description if relations are unavailable via MCP |
| Priority | Linear priority field (Urgent/High/Medium/Low) |
| Estimate | Linear estimate field; put the rough hours in the packet body |
| Assignee | Linear assignee (claim = assign self; ask the human which Linear user represents the agent if ambiguous) |

## Backend: GitHub Issues (`tracker: github`)

Uses the `gh` CLI. No MCP required.

| Contract concept | GitHub mapping |
|---|---|
| Task | Issue. Task id = issue number |
| Milestone | GitHub milestone (`gh issue create --milestone`) |
| Status | Labels `status:backlog`, `status:todo`, `status:in-progress`, `status:in-review`, `status:blocked` on open issues. `Done` = issue closed as completed (normally auto-closed by the merged PR's `Closes #N`). `Wont Do` = `gh issue close <n> --reason "not planned"` + rationale comment |
| Dependencies | `Blocked by #N` lines in the issue body (one per line). A dep is satisfied when issue N is closed as completed |
| Priority | Labels `priority:high`, `priority:medium`, `priority:low` |
| Estimate | Label `size:S`/`size:M`/`size:L`; rough hours in the body |
| Assignee | `gh issue edit <n> --add-assignee @me` |

`dev:setup` creates the label set once (`gh label create`). Transition = remove old
`status:*` label, add new one, in that order, single `gh issue edit` call:
`gh issue edit <n> --remove-label status:todo --add-label status:in-progress`.

**Terminal transitions strip the label.** For `Done` and `Wont Do` the closed state IS the
status, so the invariant is: a closed issue carries no `status:*` label. A merged PR's
`Closes #N` auto-closes the issue but does not touch labels - whoever performs the terminal
transition (`dev:verify` on merge, `dev:backlog` on `Wont Do`) must also
`gh issue edit <n> --remove-label status:in-review` (or whichever `status:*` label remains),
otherwise the issue lies about its state to label-based queries and `dev:status`.

**Consistent reads.** Every filtered `gh issue list` (`--milestone`, `--label`, `--search`)
routes through GitHub's search API, which is eventually consistent: an issue created or
edited seconds earlier can be missing from the result. Never treat a missing issue in a list
as a creation failure - re-read via the REST issues endpoint, which reads the primary store.
Use REST for `list` and `next-task`:

```
gh api "repos/{owner}/{repo}/issues?state=open&milestone=<number>&labels=status:todo"
```

`milestone` takes the number, not the title; resolve it once via
`gh api repos/{owner}/{repo}/milestones`. Then apply the selection algorithm (parse
`Blocked by #N` deps, check each is closed).

## Backend: Local files (`tracker: local`)

Offline fallback. One file per task in `.dev/tasks/T-NNN-slug.md` - one task is one read and
one write, and per-task files avoid merge conflicts.

```markdown
---
id: T-012
title: CSV export endpoint
type: task            # task | spike
status: todo          # backlog | todo | in-progress | in-review | done | blocked | wont-do
priority: 2           # 3=highest … 0=lowest
estimate: M           # S | M | L
hours: 6
deps: [T-010, T-011]
milestone: 1
assignee: ""
pr: ""
created: 2026-07-05
---

## Objective
…packet body per DESIGN.md schema: Objective, Why, Definition of Done,
Spec references (with inlined excerpts), Suggested steps…

## Comments

### 2026-07-05 dev:execute
…comments are append-only, newest last, one `### <date> <author>` heading each…
```

- Verbs are file operations: `next-task`/`list` = read all frontmatter in `.dev/tasks/`;
  `claim`/`transition` = edit the `status:` field; `comment` = append under `## Comments`.
- `claim` race guard: write `status: in-progress` + `assignee`, re-read the file, confirm the
  assignee is this session.
- New id = max existing NNN + 1, zero-padded to 3 digits.
- Commit `.dev/tasks/` changes to git together with the work they describe.
- **Worktree discipline** (found on dogfood T-001): the claim edit (`todo → in-progress`) is
  made and committed on `main`, because it happens before the task worktree exists. Every
  subsequent edit to that task's file - `in-review` transition, work-summary comment, review
  findings, verification report - is made in the task branch's worktree and merges to `main`
  with the work. Never edit `main`'s copy of the task file while its branch is active:
  `main`'s tracker state must not claim things about work that only exists unmerged on a
  branch.

## Adding a backend (`tracker: custom`)

To adopt any other tracker (Jira, Asana, Shortcut, …) without changing the skills:

1. **Map the seven verbs** to the tool's MCP tools or CLI commands. If an official MCP server
   exists (e.g. Atlassian's for Jira), list which tool implements each verb.
2. **Map the status lifecycle** to the tool's workflow states, one table row per status. Every
   lifecycle status needs a target; reuse the Linear row above as the template. Preserve the
   ownership rules (`Done` only via `dev:verify`, etc.).
3. **Map dependencies, priority, estimate, milestone** to native fields where they exist,
   body-text conventions where they do not (the GitHub backend shows the body-text style).
4. Write the mapping into `.claude/dev.md`: set `tracker: custom` in frontmatter and put the
   two mapping tables in the markdown body. Skills read this file before any tracker call, so
   the body mapping is what makes the custom backend work.
5. Verify by hand before unattended use: create a task, claim it, transition it through the
   full lifecycle, comment on it.
