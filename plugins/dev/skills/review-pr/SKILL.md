---
name: review-pr
description: >
  This skill should be used when the user asks to "review the PR", "review task <id>'s PR",
  "run the dev review", "apply review fixes", "address review comments", or invokes
  /dev:review-pr. Reviews a task's pull request against its packet (DoD, spec excerpts) and
  posts one structured verdict; in fix mode, applies one current findings batch and pushes,
  then stops. Never merges.
argument-hint: "[pr-number | task-id] [fix]"
---

# dev:review-pr

Independent review of one task's PR, or (fix mode) application of an existing review's
findings. Never merge; merging is `dev:verify`'s job.

Each manual invocation performs exactly one action and stops. Review mode posts one review;
fix mode applies one snapshot of currently recorded findings. Neither mode dispatches the next
review or fix action. `dev:auto` alone owns automatic chaining between separate review and fix
invocations, subject to its `max_fix_attempts` limit.

Skill references like `dev:verify` mean this plugin's `verify` skill; when telling the user to
run one, render your harness's invocation for it (Claude Code: `/dev:verify`; Codex: `$verify`).

Read first: `.agent-toolkit/dev.md` (tracker routing config; legacy fallbacks:
`.agent/dev.md`, then `.claude/dev.md` when absent), the plugin's `runtime_contracts/tracker.md`, and the
plugin's `runtime_contracts/project-bootstrap.md`. On Claude Code these plugin docs are under
`${CLAUDE_PLUGIN_ROOT}/runtime_contracts/`; equivalently they are under `../../runtime_contracts/` relative to this
skill's directory.

Before any repository or tracker call, resolve repository context once using `tracker.md`
"GitHub repository resolution". In active fork routing, the PR, linked issue, CI checks,
review, and REST API target are all `github_primary_repo`; every `gh pr`, `gh issue`, and
`gh run` command uses `--repo "$github_primary_repo"`, and every `gh api` path starts with
`repos/$github_primary_repo/`. Fixes push to the contributor branch on `origin`, never to
`upstream`. Existing non-opt-in routing remains unchanged.

Resolve queue classification through `tracker.md` "Trusted GitHub work-summary routing" before
choosing the planned-task or no-planned-queue path. Never treat the latest comment containing the
field as authoritative without validating its author and PR/revision binding. A validated
`Queue classification: planned` remains authoritative when the issue's current `status:*` label
is missing or malformed; report that as an execute lifecycle failure and stop instead of silently
treating the task as an external contribution. Likewise, validated `external` and `secondary`
records do not acquire queue state from incidental labels. Use legacy routing only when the task
has no classification field in any comment; never use a missing lifecycle label alone to infer
external work.

Before gathering or posting a review for a validated planned primary-GitHub task, re-read the
canonical issue and require that it is open with exactly `status:in-review`. `status:in-progress`,
`status:blocked`, a missing label, or multiple lifecycle labels mean `dev:execute` did not complete
its handoff; report the exact state and stop without reviewing. No-planned-queue work has no such
precondition.

Routine lifecycle transitions are not review operations. `dev:review-pr` preserves the task's
existing queue state and never sets `status:in-progress`, `status:in-review`, or `status:blocked`
to compensate for a failed or omitted execute transition. Return the failure to `dev:execute` or
the orchestrating `dev:auto` flow.

After the minimal task/PR fetch needed to identify the execution repository, follow
`runtime_contracts/project-bootstrap.md` before gathering the diff, spec, CI, or review evidence. Pass every
changed path from the PR or branch diff to the resolver, then read every reported project
instruction and loaded rule. Fix mode reruns the bootstrap after edits before tests and push.
Resolver failure, including an execution-revision mismatch, is a hard stop: check out the expected
revision - detach a temporary worktree at the PR head when no checkout matches it - rerun, and
never substitute another revision. A merged PR's squash commit is not a substitute for its head.

## Independence rule

The reviewer must not share context with the implementer. If this session implemented the PR
(or contains its implementation context), do not review inline: delegate the entire review to
the `dev:reviewer` agent (spawned with no `model` override - it pins `model: inherit` - and
with fresh context, never a fork/copy of this session's history), passing the PR number, the
task id, and the packet + work-summary
*text fetched verbatim from the tracker* - the agent works from the local repo + `gh` only
and has no tracker access, so on Linear/custom backends it cannot self-fetch them - pass the
packet text verbatim. Pass the validated work summary verbatim together with its author login,
comment URL, and confirmed PR URL/branch/revision binding. Never pass a bare
`Queue classification:` value as authoritative. On the GitHub backend the agent re-fetches and
validates the record itself. The agent must not re-infer routing from current labels. The dispatch
message must also embed the review contract itself,
because the agent cannot reliably read this skill's file on every harness: the step 3 body
format verbatim, the solo-repo `gh pr review --comment` fallback, and the requirement to
fill `Commit:` with the current PR HEAD. In active fork routing, also pass the resolved
`github_primary_repo`, linked issue number if any, origin branch push destination, and the
requirement that every GitHub call explicitly target the canonical repository. Pass nothing
else except the resolved execution repository and revision, changed paths, and exact
project-instruction / loaded-rule paths from the bootstrap; the reviewer reads those files
itself. Pass no
implementation rationale and no opinions about the diff. A fresh session
(one that did not implement the PR and contains no implementation context) reviews inline;
delegate only when the independence rule forces it.

## Review mode (default)

Manual review mode performs exactly one review pass and stops, regardless of whether its verdict
is approve or request-changes. It never starts fix mode within the same invocation.

1. **Gather** (the reviewer's whole world):
   - For validated planned primary-GitHub work, the canonical issue precondition above has passed
     with exactly `status:in-review`.
   - Task packet via `get-task`: objective, DoD, inlined spec excerpts, dependencies.
   - The work-summary comment on the task.
   - PR diff (`gh pr diff <n>`), changed-file list, and CI results (`gh pr checks <n>`).
   - The `docs/SPEC.md` sections the packet references.

   Checkout discipline: never check out the PR branch in the main working copy
   (`gh pr checkout` / `git checkout task/...`) - parallel reviews would fight over its
   HEAD. Anything needing the branch's files (running `test_command`, reading code beyond
   the diff) happens in that task's worktree, which exists until `dev:verify` cleans it up;
   if it is gone, use a temporary detached worktree (`git worktree add --detach`) and
   remove it afterwards.
2. **Review against the rubric**, in this order:
   - **DoD compliance:** does the diff satisfy each criterion *at the criterion's stated
     bar*? A criterion is met when the diff covers the cases the criterion names - for a
     qualitative criterion, the common and enumerated cases. Residual completeness gaps
     beyond that bar are SUGGESTIONs, not a BLOCKER, unless the gap defeats the criterion's
     core purpose. Name any criterion with no supporting change.
   - **Spec compliance:** diff vs the packet's inlined excerpts and referenced sections.
     Deviations are findings even when the code "works".
   - **Correctness:** a BLOCKER must (a) name the DoD or spec clause the diff violates, or a
     regression the diff introduces versus the prior revision, *and* (b) give a concrete
     failure scenario (inputs/state → wrong behavior). A failure scenario that maps to no
     clause and no regression is at most a SUGGESTION. Style objections are NITs.
   - **Tests:** do they test the contract (DoD criteria, spec promises) rather than mirror
     the implementation? Were any assertions weakened to pass?
   - **Scope:** every changed line traces to the task. Unrelated refactors are findings.
   - **Security:** when the diff touches auth, input parsing, secrets, or permissions, check
     the obvious failure classes for that surface.

   **Severity and downstream gates.** Before promoting a finding to BLOCKER, account for the
   controls the task already ships. A defect fully caught by a mandatory downstream gate the
   task defines - an explicit human-approval step, `dev:verify` - is at most a SUGGESTION
   unless it defeats that gate. BLOCKER is for what reaches merge or a user uncaught, not for
   every constructible imperfection.

   **Re-review convergence.** When a prior `dev:review-pr` verdict already exists on this PR,
   read it first (`gh pr view <n> --comments` and prior review bodies). This pass may raise
   only: (a) regressions the fix introduced, (b) genuinely new findings, or (c) prior findings
   still unaddressed. Do not re-raise a category you already pushed on by substituting a fresh
   edge case of the same finding, and do not contradict a resolution a prior pass directed. If
   the only remaining findings are same-category refinements of already-addressed ones, the
   verdict is `approve` with those refinements recorded as SUGGESTIONs.
3. **Post the review** via `gh pr review <n>` with `--request-changes` if any BLOCKER exists,
   else `--approve`. GitHub rejects both flags on the author's own PR (`Can not approve your
   own pull request`) - unavoidable when one account is both implementer and reviewer, e.g.
   any solo repo. In that case post the identical body with `gh pr review <n> --comment`
   instead: the
   `Verdict:` line in the body is the verdict of record either way; the formal GitHub review
   state is best-effort. Never fall back to `gh pr comment` - that creates an issue comment,
   which does not appear in `gh pr view --json reviews`, so `dev:verify` cannot find it.
   Body format:

   ```
   ## dev:review-pr - <task-id>
   Verdict: request-changes | approve
   Commit: <sha of the PR HEAD this review read>
   Execution repository: <resolved repository>
   Execution revision: <resolved commit>
   Rules loaded: <exact resolver paths, or "none">
   DoD: <n>/<total> criteria have supporting changes

   ### Findings
   [B1] BLOCKER <file:line> - <defect>. Failure: <concrete scenario>.
   [S1] SUGGESTION <file:line> - <improvement and why>.
   [N1] NIT <file:line> - <minor>.
   ```

   Zero findings: say so explicitly rather than inventing NITs.

   The `Commit:` line is what lets `dev:verify` detect a stale verdict when the review is a
   comment (solo-repo fallback, task-comment reviews) and carries no native `commit_id`.
   Always fill it with the head SHA of the diff actually reviewed.
4. **Record on the tracker:** comment the verdict + finding count on the task. In delegated
   mode on backends the agent cannot write to (Linear, custom), the calling session posts
   this comment from the tracker comment body the agent returns. Approved →
   next step is `dev:verify`. Request-changes → next step is `dev:review-pr <n> fix`.
   Stop after recording either verdict. A request-changes verdict never starts fix mode or
   another review without a new user command.

**No GitHub remote** (local-only projects): review `git diff main...task/<id>-<slug>` with the
same rubric and post the full review as a task comment instead of a PR review.

**No planned queue task** (a primary-GitHub external contribution, a secondary-channel
in-place `#N` PR, or a drive-by PR with no issue at all - `runtime_contracts/tracker.md` repository
resolution and "Secondary intake channel"): there is no queue packet. Gather instead the PR diff +
CI, the linked GitHub issue's body and acceptance criteria when one exists (`gh issue view
<n>`), and `docs/SPEC.md` / `docs/PRD.md`. Run the same rubric with "DoD compliance" reading
against the issue's stated acceptance criteria (or, absent an issue, the PR description);
`Verdict:` line unchanged; add a line `Reviewed against: issue #<n> + spec` (or
`PR description + spec`) so the reader knows no packet existed. Record the verdict as a
comment on the resolved GitHub issue when there is one, else the PR review is the record. Do
**not** claim, assign, label, milestone, count WIP, or transition any primary-tracker status.
The review remains a full independent review, not a reduced pre-review.

## Fix mode (`fix` argument)

Runs in the task's worktree, on the same branch. This mode may share context with the
implementation; independence applies to reviewing, not fixing.

A manual fix invocation applies exactly one batch of findings recorded at its start, completes
the steps below, and stops.

For an external cross-repository PR, compare the PR head repository and branch with the
validated local `origin`. Apply fixes only when `origin` is that contributor fork and the
authenticated user can push the head branch. A maintainer reviewing from a canonical clone does
not rewrite or push a contributor-owned branch; return the findings to the contributor instead.

1. At invocation start, snapshot the PR's currently recorded findings from its review threads
   (`gh pr view <n> --comments` and review bodies). This snapshot is the only batch this
   invocation addresses; findings posted after it require a new user command.
2. Address every BLOCKER, and each SUGGESTION unless the user (or the finding thread) says
   otherwise. To dispute a finding, reply on the thread with reasoning and leave it for the
   human; never silently skip or resolve a finding without either a fix or a reply.
3. Run the `test_command`, push to the same branch when it has a remote, and let CI run. In
   fork routing, that push remote is `origin`; never push a fix to `upstream`, and keep all
   PR/check operations scoped to `github_primary_repo`. Preserve local-only behavior when no
   GitHub remote exists.
4. Reply per finding: what changed, or why not. Request re-review only as a notification, using
   `gh pr edit --add-reviewer <eligible-reviewer>` when GitHub permits it. Never dispatch or
   execute review mode from fix mode. If no eligible reviewer exists, including a solo
   repository where the PR author cannot request themselves, record that re-review is still
   needed and report that a fresh manual `dev:review-pr <n>` invocation is required. Do not run
   that invocation. Stop after the notification or fallback report; do not read a new findings
   batch, start another fix pass, or review the pushed commit. The fix author never declares the
   findings resolved; a later review pass does.
