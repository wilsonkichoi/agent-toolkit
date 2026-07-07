---
name: review-pr
description: >
  This skill should be used when the user asks to "review the PR", "review task <id>'s PR",
  "run the dev review", "apply review fixes", "address review comments", or invokes
  /dev:review-pr. Reviews a task's pull request against its packet (DoD, spec excerpts) and
  posts a structured verdict; in fix mode, applies the review findings and pushes. Never
  merges.
argument-hint: "[pr-number | task-id] [fix]"
---

# dev:review-pr

Independent review of one task's PR, or (fix mode) application of an existing review's
findings. Never merge; merging is `/dev:verify`'s job.

Read first: `.claude/dev.md` (config) and `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md`.

## Independence rule

The reviewer must not share context with the implementer. If this session implemented the PR
(or contains its implementation context), do not review inline: delegate the entire review to
the `dev:reviewer` agent, passing the PR number, the task id, and the packet + work-summary
*text fetched verbatim from the tracker* - the agent's toolset (Read/Grep/Glob/Bash) covers
`gh` but not tracker MCP servers, so on Linear/custom backends it cannot self-fetch them.
Pass nothing else: no implementation rationale, no opinions about the diff. A fresh session
may review inline or delegate; delegation is the safe default.

## Review mode (default)

1. **Gather** (the reviewer's whole world):
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
   - **DoD compliance:** for each criterion, does the diff plausibly satisfy it? Name any
     criterion with no supporting change.
   - **Spec compliance:** diff vs the packet's inlined excerpts and referenced sections.
     Deviations are findings even when the code "works".
   - **Correctness:** a BLOCKER requires a concrete failure scenario (inputs/state → wrong
     behavior), not a style objection.
   - **Tests:** do they test the contract (DoD criteria, spec promises) rather than mirror
     the implementation? Were any assertions weakened to pass?
   - **Scope:** every changed line traces to the task. Unrelated refactors are findings.
   - **Security:** when the diff touches auth, input parsing, secrets, or permissions, check
     the obvious failure classes for that surface.
3. **Post the review** via `gh pr review <n>` with `--request-changes` if any BLOCKER exists,
   else `--approve`. GitHub rejects both flags on the author's own PR (`Can not approve your
   own pull request`) - unavoidable when one account is both implementer and reviewer, e.g.
   any solo repo. In that case post the identical body with `--comment` instead: the
   `Verdict:` line in the body is the verdict of record either way; the formal GitHub review
   state is best-effort. Body format:

   ```
   ## dev:review-pr - <task-id>
   Verdict: request-changes | approve
   DoD: <n>/<total> criteria have supporting changes

   ### Findings
   [B1] BLOCKER <file:line> - <defect>. Failure: <concrete scenario>.
   [S1] SUGGESTION <file:line> - <improvement and why>.
   [N1] NIT <file:line> - <minor>.
   ```

   Zero findings: say so explicitly rather than inventing NITs.
4. **Record on the tracker:** comment the verdict + finding count on the task. Approved →
   next step is `/dev:verify`. Request-changes → next step is `/dev:review-pr <n> fix`.

**No GitHub remote** (local-only projects): review `git diff main...task/<id>-<slug>` with the
same rubric and post the full review as a task comment instead of a PR review.

**No primary task** (a secondary-channel in-place `#N` PR, or a drive-by PR with no issue at
all - tracker.md "Secondary intake channel"): there is no packet. Gather instead the PR diff +
CI, the linked GitHub issue's body and acceptance criteria when one exists (`gh issue view
<n>`), and `docs/SPEC.md` / `docs/PRD.md`. Run the same rubric with "DoD compliance" reading
against the issue's stated acceptance criteria (or, absent an issue, the PR description);
`Verdict:` line unchanged; add a line `Reviewed against: issue #<n> + spec` (or
`PR description + spec`) so the reader knows no packet existed. Record the verdict as a comment
on the issue when there is one, else the PR review is the record. Do **not** transition any
primary-tracker status.

## Fix mode (`fix` argument)

Runs in the task's worktree, on the same branch. This mode may share context with the
implementation; independence applies to reviewing, not fixing.

1. Read the PR's review threads (`gh pr view <n> --comments` and review bodies).
2. Address every BLOCKER, and each SUGGESTION unless the user (or the finding thread) says
   otherwise. To dispute a finding, reply on the thread with reasoning and leave it for the
   human; never silently skip or resolve a finding without either a fix or a reply.
3. Run the `test_command`, push to the same branch, let CI run.
4. Reply per finding: what changed, or why not. Then re-request review (`gh pr edit
   --add-reviewer` or re-run `/dev:review-pr` fresh) and stop. The fix author never declares
   the findings resolved; the next review pass does.
