# Adopting the dev Plugin in an Existing Project

Greenfield adoption is `dev:setup` and go. This guide covers everything else: partial
adoption, existing codebases, existing backlogs, trackers this plugin does not ship a
backend for, and memory systems beyond plain files.

Skill references are written `dev:<skill>` (e.g. `dev:setup`); invoke them with your harness's
mechanism — `/dev:setup` on Claude Code, `$setup` / `dev:setup` on Codex.

The one architectural fact that makes all of this possible: **the tracker is the only shared
state between skills.** Docs (`docs/PRD.md`, `docs/SPEC.md`) carry intent, the tracker
carries task state, and every skill reads both fresh each run. There is no pipeline state,
so any subset of skills works alone.

## 1. Incremental adoption paths

| You want | Adopt | Skip | Notes |
|---|---|---|---|
| Only the execution loop | `setup`, `execute`, `review-pr`, `verify` | `discover`, `architect`, `plan` | Your existing backlog feeds `execute` directly. Tickets must survive packet validation (Objective + DoD); `execute` drafts missing fields from whatever docs exist and asks. The thinner your docs, the more it asks. |
| Planning discipline, own review process | `setup`, `plan`, `backlog`, `execute` | `review-pr`, `verify` | You lose the `Done`-means-verified guarantee. Decide who sets `Done` and record it in `.agent-toolkit/dev.md` body, or `In Review` tasks pile up forever. |
| Product docs only | `discover`, `architect` | everything tracker-side | PRD/SPEC/ADRs are useful standalone. `tracker: local` in config satisfies setup without adopting task flow. |
| Everything | all | - | Run `setup` in brownfield mode first; see below. |

Rules of thumb: `verify` without `review-pr` is fine (evidence still gathered); `review-pr`
without `verify` means merges go unguarded - a human must own the merge decision. `retro`
works with any subset that produces PR/tracker evidence.

## 2. Brownfield setup and architecture archaeology

`dev:setup` detects an existing codebase and offers archaeology: reverse-engineering the
**current** state into `docs/SPEC.md` (components, interfaces, data flow, known debt marked
as debt). Do not skip it if you plan to use `dev:plan` - packets against undocumented code
force the planner to guess, and guessed spec excerpts are worse than none.

Order for a full brownfield onboarding:

1. `dev:setup` - config, scaffold, archaeology into a current-state SPEC.
2. `dev:discover` - only if product intent is fuzzy or undocumented; else write a minimal
   PRD by hand (problem, customer, north star, non-goals) so triage has an anchor.
3. `dev:architect` - forward-looking spec sections on top of the current-state spec; the
   spec must say what is kept, replaced, and debt.
4. Import the backlog (next section), then `dev:plan` for new milestone work.

## 3. Importing existing docs and backlogs

**Docs:** map what exists into the layout: product intent → `docs/PRD.md`, technical design
→ `docs/SPEC.md`, decisions → `docs/adr/`, raw research → `research/raw/`. Import is a copy
plus an honesty pass: mark stale sections rather than silently keeping them.

**Backlogs:** import tickets into the configured tracker at `Backlog` status, then run
`dev:backlog triage` - it re-checks every imported item against the current docs and flags
stale ones for `Wont Do`. Do not import straight to `Todo`; committed status should survive
a triage, not a copy-paste.

**Migrating from agentic_development_workflow (ADW):**

- Finish in-flight ADW milestones with ADW; switch at a milestone boundary.
- `workflow/spec/SPEC.md` → `docs/SPEC.md` (drop HANDOFF.md; packets replace it).
- `workflow/decisions/DR-*.md` → `docs/adr/` (renumber, keep statuses).
- `workflow/plan/PLAN.md` unfinished tasks → tracker `Backlog` via `dev:backlog` intake, so
  each gets a real packet; do NOT bulk-copy checkbox lines.
- `workflow/plan/reviews/task-*.md` and `RETRO-*.md` → keep as history in `research/raw/` if
  useful; run `dev:retro` conventions going forward. PROGRESS.md dies; the tracker is the
  progress.

## 4. Third-party trackers (`tracker: custom`)

The plugin ships Linear, GitHub Issues, and local-file backends. Anything else follows the
"Adding a backend" recipe at the end of [tracker.md](tracker.md): map the seven verbs and the
status lifecycle, write both tables into the `.agent-toolkit/dev.md` body, set `tracker: custom`.
Skills read that file before every tracker call; the body mapping is the implementation.

### Worked example: Jira via the Atlassian MCP server

> **Not verified.** Only the shipped Linear, GitHub Issues, and local-file backends are
> tested. This Jira/Atlassian mapping is an illustrative template that has never been run
> end to end - tool names and transitions are best-guess. Verify every verb by hand (see the
> lifecycle check below) before any unattended use.

Connect the official Atlassian Remote MCP server, then discover exact tool names from the
runtime tool list (they change; typical names shown). `.agent-toolkit/dev.md` body:

```markdown
## Tracker mapping (Jira)

| Verb | Implementation |
|---|---|
| next-task | search issues via JQL: project=<KEY> AND status="To Do" AND fixVersion=<milestone>, then apply the selection algorithm from tracker.md |
| get-task <id> | get issue (fields + comments + issue links) |
| claim <id> | assign self + transition to "In Progress"; re-read to confirm assignee |
| comment | add comment to issue |
| transition | get available transitions for the issue, then apply the matching one |
| create-task | create issue (type Task; spikes as type Spike or label `spike`) |
| list <milestone> | JQL: project=<KEY> AND fixVersion=<milestone> |

| Lifecycle status | Jira status |
|---|---|
| Backlog | Backlog |
| Todo | To Do / Selected for Development |
| In Progress | In Progress |
| In Review | In Review (add to workflow if missing - human decision) |
| Done | Done |
| Blocked | flag "Impediment" or label `blocked` + diagnostic comment (keep workflow status) |
| Wont Do | Done with resolution "Won't Do", rationale comment first |

Dependencies: issue links "is blocked by". Priority: Jira priority. Estimate: story points
(rough hours in description). Milestone: fixVersion (or sprint - pick one, record it here).
```

Verify by hand before unattended use: create, claim, transition through the full lifecycle,
comment. The same shape covers Asana, Shortcut, Notion databases, etc.

## 5. Third-party memory systems (`memory_target`)

The plugin's only memory integration point is `dev:retro`'s promotion step. Default
(`memory_target: files`, or field absent): learnings become `<rules_dir>/<slug>.md` files
(default `.agent-toolkit/rules/`), each registered as an import line in
`.agent-toolkit/dev.md` and reached by every session through the context file's single
reference line - git-shared, zero latency.

Teams already running a memory system set `memory_target` in `.agent-toolkit/dev.md` frontmatter
and retro stores learnings through that system's MCP tools instead:

| `memory_target` | System | Storage | Recall path | Tradeoff vs files |
|---|---|---|---|---|
| `files` (default) | plain markdown | `rules_dir` (default `.agent-toolkit/rules/`) | context-file reference line loads `dev.md` + its rule imports each session | in git, zero latency, project-scoped only |
| `mem0` | Mem0 managed API | Mem0 cloud | Mem0 plugin injection / MCP search | cross-tool + cross-machine; data off-machine; managed service |
| `openbrain` | OB1 / OpenBrain | self-owned Supabase pgvector | MCP search from any connected tool | cross-tool, self-owned; setup cost, query latency |
| `memsearch` | MemSearch (Zilliz) | local markdown + Milvus shadow index | hook-injected semantic matches per prompt | local + cross-CLI-tool; machine-local only |

> **Not verified.** Only `files` is exercised by this plugin's tests. The `mem0`/`openbrain`/
> `memsearch` rows describe the *intended* integration - `dev:retro` emits a generic "store
> this via that system's MCP tool" instruction - but no config ships bundled and none has been
> run end to end. Adopt at your own risk: wire up the MCP server yourself and confirm a real
> promotion lands through it before relying on it.

Two rules regardless of target:

1. **Correctness-gating rules always also go to the `rules_dir` files.** Files are the only
   target every future session is guaranteed to load; semantic recall is probabilistic, and
   a rule that must never be missed cannot depend on it.
2. Recall is the memory system's job, not the plugin's: rely on that system's own hooks or
   MCP injection at session start. The plugin only writes.

## 6. Migrating an existing consumer to the encapsulated layout

Projects configured by dev 0.0.53 or earlier use one of two legacy shapes: the pre-port
config (`.claude/dev.md`, rules in `.claude/rules/`, promotions into `CLAUDE.md`) or the
0.0.42-0.0.53 mixed config (`.agent/dev.md`, `context_file: AGENTS.md`, rules consolidated
inside `AGENTS.md`). Both keep working unchanged - every skill falls back to the legacy
paths, and retro keeps its safety net. Migrating gets you the encapsulated layout: all
plugin state under `.agent-toolkit/`, the project's context files untouched beyond one
reference line.

Run `dev:setup` (idempotent) and it walks the migration; the steps, for review or a manual
pass:

1. `git mv` the config to `.agent-toolkit/dev.md` (and the `.local.md` variant, updating
   its `.gitignore` entry).
2. Grep the repo for the old path. Update operative references (docs that tell agents to
   read the config) in the same commit; leave historical records (changelogs,
   completed-work logs) as they are.
3. Set `rules_dir` explicitly. Default `.agent-toolkit/rules/`; keep an existing location
   (e.g. `.claude/rules/`) as the value instead when the project - or anything downstream
   of it, such as a template it ships - already depends on that path. Moving rule files is
   optional; registering them is not.
4. Register every rule file as an import line in the `## Rules` section of
   `.agent-toolkit/dev.md`.
5. Ensure the configured `context_file` carries the single reference line
   (`@.agent-toolkit/dev.md`). Rules previously consolidated into `AGENTS.md` may stay
   there (the project owns that file and its content) or move back out to `rules_dir`
   files - the project's call, never the plugin's.
6. Verify with `dev:status`: its consistency checks cover duplicate configs, a missing
   reference line, unregistered rules, and the legacy mixed config.

**Template and framework repos:** a repo that others clone or instantiate (a project
template, a framework with a "use this template" flow) must not ship its own dev-plugin
state to consumers - adopting this plugin is each project's decision, never inherited. Keep
the plugin's footprint to `.agent-toolkit/` plus the one reference line, and have the
template's init/clone path strip both. The encapsulated layout makes that strip exactly one
directory and one line.
