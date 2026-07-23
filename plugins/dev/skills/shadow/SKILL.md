---
name: shadow
description: >
  This skill should be used when the user asks to "shadow a completed issue", "replay a
  merged PR with dev:shadow", "benchmark an agent runtime on a real task", "evaluate a model
  against a finished task", or invokes /dev:shadow. Replays a completed GitHub issue from its
  historical base using the active session's model, runs execute → review → bounded fix →
  verify, then compares against the original and posts an evaluation report. Never merges;
  never mutates the source issue or original PR.
argument-hint: "#<source-issue> [pr <source-pr>]"
---

# dev:shadow

Unattended historical replay. Take a completed issue and its merged PR, reconstruct the exact
revision the original work branched from, re-implement it with the model the active session is
running, then measure the replay against the original on functional tests, DoD coverage,
review findings, scope, elapsed time, tokens, and estimated API-equivalent cost.

This is an evaluation surface, not a benchmark harness and not a lifecycle skill. It never
merges a pull request, never mutates the source issue or original PR, and never enters the
planned-task queue. Its terminal state is: candidate PR closed unmerged, shadow issue closed
as a completed evaluation, source artifacts untouched, an audit report posted.

Skill references like `dev:execute` mean this plugin's `execute` skill; when telling the user
to run one, render your harness's invocation for it (Claude Code: `/dev:execute`; Codex:
`$execute`).

Read first: `.agent-toolkit/dev.md` (tracker routing config; legacy fallbacks:
`.agent/dev.md`, then `.claude/dev.md` when absent), the plugin's `runtime_contracts/tracker.md`,
`runtime_contracts/project-bootstrap.md`, and `runtime_contracts/shadow.md` (the replay contract, artifact formats,
metrics adapters, and pricing-catalog semantics). On Claude Code these plugin docs are under
`${CLAUDE_PLUGIN_ROOT}/runtime_contracts/`; equivalently they are under `../../runtime_contracts/` relative to this
skill's directory. The deterministic helper is `../../scripts/shadow_replay.py`
(`${CLAUDE_PLUGIN_ROOT}/scripts/shadow_replay.py` on Claude Code); run it with
`uv run <path> <subcommand>`.

## Requirements and refusals

- **Source backend.** v0 replays a completed issue in a GitHub repository only. Linear and
  local source tickets are out of scope; refuse them and say so.
- **Fresh-context subagents.** Requires a harness that can dispatch fresh-context workers and
  wait on their results, exactly as `dev:auto` does. On Codex the `agents.max_depth = 1` limit
  blocks a worker from spawning `test-writer`; use sibling orchestration (the worker returns
  the public interface, the orchestrator dispatches `test-writer` itself), the same pattern
  `dev:auto` documents. On a harness with no subagent mechanism at all, refuse and stop.
- **Model discipline.** The active harness selects the model. Dispatch every worker and named
  agent with NO `model` parameter so each inherits the session model and reasoning effort;
  never pass a model alias to "match" the session and never downgrade to route around a
  model-availability error. A spawn that fails on the inherited model retries once with no
  override; a second failure is an environment stop. The report records harness, runtime
  version, model, and reasoning effort exactly as observed.

Before any repository call, resolve repository context once using `tracker.md` "GitHub
repository resolution". Carry the canonical repository, base remote, push remote, and
authenticated permission through every step and every delegated worker; never let a worker
re-infer them from its worktree. Shadow needs write permission for the shadow artifacts (the
`[SHADOW]` issue, the shadow branches, the draft PR). Lacking it is a preflight stop.

## Run identity

Each invocation mints a unique run id with `shadow_replay.py run-id` (a UTC timestamp plus a
collision-resistant suffix). Re-running the same source issue and model creates a separate
evaluation; it never overwrites or resumes another run. Carry the run id into every branch
name, artifact, and the report.

## Lifecycle

The unattended lifecycle is exactly, with no step skipped or reordered:

```
prepare → execute → review → (fix → fresh review)[0..max_fix_attempts] → verify → compare → report → stop
```

### 1. Prepare

1. `shadow_replay.py preflight --repo "$repo" --source-issue <n> [--source-pr <m>]`. It
   requires a completed source issue, one selected merged source PR bound to the issue by a
   closing reference, and a recoverable single-parent historical base, and prints the resolved
   `source_pr`, `merge_commit`, `historical_base`, and `cutoff`. Any failure stops before
   mutation. An explicit `pr <source-pr>` still passes the binding check; supply it only when
   the issue maps to more than one merged PR (preflight reports that ambiguity). Preserve the
   returned `source_snapshot_sha256`; it binds the source issue and PR content read by preflight.
2. Read the source issue packet (`gh issue view <n> --repo "$repo"`). Require an Objective and
   a Definition of Done; a missing section stops the run (do not draft or repair - this is an
   evaluation of finished work, not intake).
3. Follow `runtime_contracts/project-bootstrap.md` at the `historical_base` commit: resolve the execution
   repository, check out that exact revision, and load its context file, dev config, and
   applicable rules through `resolve_project_rules.py`. The replay must load project
   instructions from the historical revision, not from current `main`. Preserve the resolver's
   exact `Execution repository:`, `Execution revision:`, and `Rules loaded:` entries in every
   artifact.
4. Mint the run id and start metrics collection (record the wall-clock start; note the harness,
   runtime version, model, and reasoning effort).
5. Create isolated artifacts (`runtime_contracts/shadow.md` "Git and GitHub isolation"):
   - `shadow_replay.py create-branches --shadow-base shadow-base/<source-id>/<run-id>
     --candidate shadow/<source-id>/<run-id> --base-commit <historical_base>` creates both
     branches at the validated base and pushes them.
   - `shadow_replay.py create-shadow-issue --repo "$repo" --title "[SHADOW] <source title>"
     --body-file <file>` creates the isolated issue (labels `experiment:shadow`, created
     idempotently), rejects `Blocked by #N` dependency declarations, then re-reads and asserts
     no `status:*` label, milestone, or assignee.
   - Add the candidate worktree yourself: `git worktree add <path> shadow/<source-id>/<run-id>`
     (never harness worktree isolation - it creates an untracked branch no cleanup step knows
     about, exactly as `dev:execute` step 2 forbids).
   - Do not open the draft PR yet. GitHub rejects a PR whose candidate and base refs still point
     to the same commit. The execute stage pushes the first replay commit before PR creation.

Immediately before execute, re-read the pre-PR state with
`shadow_replay.py validate-invariants --repo "$repo" --shadow-issue <n>
--shadow-base <b> --candidate <c> --historical-base <base> --remote <push-remote>
--source-issue <src-issue> --source-pr <src-pr> --source-merge-sha <merge-sha>
--source-snapshot-sha256 <preflight-snapshot>`. It re-reads
the shadow issue, remote shadow-base ref, and source artifacts without requiring a PR that does
not exist yet. Before review and every later stage, and before terminal cleanup, add
`--shadow-pr <m> --head-repo <push-repository>` so the same command also binds the PR's draft/open
state, `do-not-merge` label, base branch, candidate branch, head repository, and `Refs` target.
The source snapshot includes issue comments plus PR comments and reviews. Any drift (a required
label disappears, a `status:*` label, milestone, assignee, or dependency declaration appears, an
artifact closes early, the PR's base/head repository or branch changes, a closing keyword appears,
the shadow-base ref moves, or a source artifact changes) stops the run.

### 2. Execute

Dispatch a fresh implementation worker exactly as `dev:auto` dispatches its implementer,
except: it works on the candidate branch in the prepared worktree (do not re-create it), it
reads the shadow packet and the historical rules, and its implementation context **excludes**
the original diff, the original reviews, the source-PR comments, source commits after the base,
and any post-cutoff issue comment. Pass it only: the source issue body plus comments created
strictly before the `cutoff`, the resolved execution repository/revision and loaded-rule paths,
the worktree path, the candidate branch, and `test_command`. For non-trivial work, brief
`test-writer` with ONLY the packet, historical spec/rules, and the public interface (never the
implementation diff), using nested delegation on Claude Code or sibling orchestration on Codex.
After the worker creates the first replay commit, push the candidate branch, then open the draft
PR with `shadow_replay.py open-shadow-pr --repo "$repo" --base
shadow-base/<source-id>/<run-id> --head shadow/<source-id>/<run-id> --head-repo
<push-repository> --remote <push-remote> --repo-path <execution-repository> --title
"[SHADOW] <source title>" --body-file <file> --shadow-issue <shadow-issue>`. The helper re-reads
both remote refs and refuses PR creation when they are still identical. For a contributor fork it
passes `<fork-owner>:<candidate-branch>` to GitHub and verifies `headRepository`; a bare branch
name is valid only when the push repository is the canonical repository. It labels the PR
`do-not-merge` and requires `Refs #<shadow-issue>`, never `Closes`.

Run applicable local tests and the candidate CI. `max_fix_attempts` bounds the execution CI loop;
an unrecoverable failure stops the run with a stage diagnostic.

### 3. Review

Dispatch a fresh `reviewer` (or a fresh generic worker carrying the review contract if the
named agent's planned-task routing would reject a shadow item - see `runtime_contracts/shadow.md`; never
label a shadow item `planned`, `external`, or `secondary` to bypass a contract). Give it the
shadow packet, the current candidate diff, current CI, the historical rules, and the current
candidate head SHA. The review verdict binds to that head SHA.

### 4. Fix loop

On request-changes, dispatch one fresh fixer for the current findings batch, run tests, push
to the candidate branch, then dispatch a fresh reviewer for the new head - the same
orchestrator-owned chaining `dev:auto` uses, bounded by `max_fix_attempts`. Before each fixer
dispatch, increment the one-based attempt number and require
`shadow_replay.py fix-attempt --attempt <n> --max-attempts <max_fix_attempts>` to succeed. The
helper rejects any attempt above the configured bound. Every fix push
invalidates the prior verdict; verification requires a fresh approval whose `Commit:` equals
the new candidate head. Still request-changes after `max_fix_attempts`: stop, record the
unresolved findings in the report, do not verify.

### 5. Verify

Before verifying, gate on `shadow_replay.py review-freshness --repo "$repo" --shadow-pr <n>
--review-commit <approval sha>`: the helper re-reads the current GitHub PR head, and an approval
whose commit is not that head is stale (a fix push advanced the head after the review) and stops
the run for a fresh review. Only
after a fresh approval, dispatch a fresh `verifier` (or a generic worker carrying the verify
contract, same rule as review) to gather evidence for every source Definition-of-Done
criterion. The verifier exposes no merge path: `dev:shadow` never calls a merge command and
never transitions the shadow issue through planned-task states.

### 6. Compare

Collect original and shadow evidence into two JSON blobs (`runtime_contracts/shadow.md` "Evidence blobs"),
then `shadow_replay.py compare --original <o> --shadow <s>` for the table rows. Deterministic
metrics come from the helper:

- `shadow_replay.py metrics --harness <claude-code|codex> --log <file> [--log <file> ...]`
  aggregates the final cumulative usage once per thread (it never sums every cumulative event)
  and reports input, cached-input, output, and reasoning tokens plus an `unattributed` bucket.
  Reasoning is `null` when the harness does not expose it.
- `shadow_replay.py pricing --provider <p> --model <m> --input N --cached-input N --output N
  --reasoning N [--cache-write N] [--max-request-input N]` estimates API-equivalent cost from
  the versioned catalog. Models with cache-write or long-context pricing require those inputs
  explicitly; missing harness metadata produces `cost unavailable` instead of silently applying
  base rates. A catalog's `included_in_output` reasoning treatment prevents charging reasoning
  twice when the harness reports it as a subset of output. Unknown pricing
  prints `cost unavailable` with a reason; never substitute a guessed value.

Timing boundaries (`runtime_contracts/shadow.md` "Timing and token boundaries"): shadow delivery time runs
from just before the implementation worker is dispatched to when verification of the approved
head completes; preparation, comparison, and reporting are recorded separately and included in
total run time. Original observable delivery time is the first source-PR commit's committed
timestamp to the source PR's merged timestamp, labeled a GitHub-derived estimate. Missing
original token or cost data is reported as `unavailable`, never zero or inferred. Never collapse
the dimensions into a single aggregate quality score.

### 7. Report and stop

1. Assemble the report data (run identity, harness/runtime/model/effort, every source/shadow/base/issue
   URL, the original PR merge SHA, reviewed candidate head SHA, comparison rows, verification
   evidence or the linked verifier report) and render it with
   `shadow_replay.py report --data <file>`. For a completed run the helper **enforces** the
   exact `final_state: evaluation-complete`, all 14 comparison rows with concrete evidence or a
   missing-data reason, and the audit bindings: a report missing the source issue/PR links, the original merge SHA, the
   historical base, the shadow issue/PR links, the reviewed candidate head, the exact project
   bootstrap `Execution repository:`, `Execution revision:`, and `Rules loaded:` values, or the
   verification evidence fails rather than rendering `unavailable` (a stopped run instead sets
   `final_state: failed:<stage>`, which is exempt). The report includes every required
   disclosure (same-repository replay is not blind; the source body is current not historical;
   original token/cost data may be missing; GitHub timestamps are observable, not continuous
   work; estimated cost is not the subscription charge; reviewer/verifier judgments depend on
   the identified models). The helper always emits these.
2. Post the report on the shadow issue.
3. Re-read invariants (`validate-invariants`) and prove the candidate stayed unmerged, then
   `shadow_replay.py cleanup --repo "$repo" --shadow-pr <m> --shadow-issue <n> --worktree
   <path>`. Cleanup refuses if the PR reads as merged, closes the draft PR unmerged, closes the
   shadow issue as a completed evaluation, re-reads both closed states, removes the worktree only
   after those proofs pass, and retains both remote shadow branches for reproducibility.
4. Report to the user: source issue, original PR, historical base, shadow issue, shadow PR,
   reviewed SHA, final state, and the report link. **Stop.** Do not merge, do not reopen or
   edit the source issue or original PR, do not claim another task.

## Stop conditions

Stop with a shadow-issue diagnostic (or, before the shadow issue exists, a report to the user)
and no source mutation when any of these occurs:

- Source issue is not completed, the source PR is not merged, or issue-to-PR binding is invalid.
- Source PR selection or historical-base reconstruction is ambiguous (root, merge, missing, or
  non-ancestor parent).
- Repository, permission, project-bootstrap, or historical-rule resolution fails.
- A required fresh worker cannot be dispatched (subagent mechanism absent, or a model spawn
  fails twice).
- Tests or CI remain failing after `max_fix_attempts`, or review stays request-changes after
  `max_fix_attempts`, or the approval SHA is stale.
- Verification evidence is incomplete.
- Shadow isolation drifts: a `status:*` label or milestone appears on the shadow issue, or the
  PR loses draft/`do-not-merge`/`Refs` isolation or changes base/head.
- Any next operation would merge, mutate source artifacts, or enter normal queue state.

On failure, post an actionable stage diagnostic and leave the existing shadow artifacts open
for inspection; never delete evidence automatically, and never touch the source issue or
original PR.

## Non-goals

Launching several providers from one invocation (the active session picks one model);
claiming the replay is blind or scientifically controlled; producing a single aggregate quality
score; reopening or mutating the source issue or original PR; merging a shadow PR; changing any
existing lifecycle skill's behavior; supporting Linear or local source tickets in v0.
