---
name: verify
description: >
  This skill should be used when the user asks to "verify the task", "check the definition of
  done", "merge the PR", "close out task <id>", or invokes /dev:verify. Gathers evidence for
  every Definition of Done criterion, posts a verification report, and only then, on explicit
  human approval, merges the PR and transitions the task to Done.
argument-hint: "[task-id | pr-number]"
---

# dev:verify

The merge gate. `Done` means every DoD criterion has evidence and the human approved the
merge. This skill is the only thing in the lifecycle allowed to merge or to set `Done`.
Without explicit human approval in this session, do not merge - with one carve-out: when
invoked by `/dev:auto` with `auto_merge: true` in `.claude/dev.md`, that flag is the human's
standing approval, valid only when the review is approved AND every criterion is met AND
every criterion is either mechanically evidenced (test or CI) or carries a recorded human
sign-off (section 2). A manual criterion always requires a human - a recorded sign-off or a
live confirmation in this session - regardless of config; `auto_merge` never substitutes
for it.

Read first: `.claude/dev.md` (config) and `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md`.

## Independence rule

The verifier must not share context with the implementer - the session that wrote the code
reads its own work summary as evidence and its motivated reasoning marks criteria met. If
this session implemented the PR (or contains its implementation context), do not gather
evidence inline: delegate sections 1-3 (preconditions, evidence, report) to the
`dev:verifier` agent, passing the PR number, the task id, and the packet + task-comment
text *fetched verbatim from the tracker* - the agent's toolset (Read/Grep/Glob/Bash) covers
`gh` but not tracker MCP servers, so on Linear/custom backends it cannot self-fetch them
(task comments included, since recorded sign-offs live there). Pass nothing else: no
implementation rationale, no opinions on whether criteria are met. A fresh session (one
that did not implement the PR and contains no implementation context) runs sections 1-3
inline; delegate only when the independence rule forces it.

Section 4 never delegates. The human gate, live confirmation of manual/visual criteria and
its durable recording (section 2), human-gate checkbox writes, the merge, the `Done`
transition, and cleanup all stay in the calling session - the agent cannot ask the human
and holds no merge approval. It reports which criteria are unmet or awaiting human
confirmation; the calling session takes it from there. On backends the agent cannot write
to, the calling session also posts the task-comment copy of the report the agent returns.

## 1. Preconditions

Resolve the task and PR (from the argument, the task's `pr` link, or the PR's linked task).
Check: task status is `In Review`, CI is green, and an approving review exists
(`gh pr view <n> --json reviews`). An approving review is either `state: APPROVED` or a
`dev:review-pr`-formatted review body whose verdict line reads `Verdict: approve` - the
latter is the only form possible when reviewer and PR author are the same account (GitHub
forbids self-approval, so solo repos never get `APPROVED` state). A missing review is a
warning, not a hard stop; report it and let the human decide whether to proceed without one.

The approving review must target the current PR HEAD. Compare the review's `commit_id`
(`gh api repos/{owner}/{repo}/pulls/<n>/reviews --jq '.[].commit_id'`; for a comment-form
verdict, the `Commit:` line in its body) against `gh pr view <n> --json headRefOid`. A
mismatch means commits landed after the review - typically a `/dev:review-pr <n> fix` push -
so the approve is stale and the newer commits are unreviewed. Treat a stale approve as no
approving review: warning in manual mode, hard stop under `auto_merge`. Run a fresh
`/dev:review-pr <n>` first. A content-identical rebase also trips this check; accept the
re-review, it is cheap and never wrong. (A rebase performed by verify itself is governed by
section 4 step 0.) No GitHub remote: compare the review comment's `Commit:` line against the
task branch head.

**No GitHub remote:** the task records a branch instead of a PR, the approving review is the
`/dev:review-pr` comment on the task, and the local `test_command` run stands in for CI.

**No primary task** (a secondary-channel in-place `#N` PR, or a drive-by PR with no issue -
`${CLAUDE_PLUGIN_ROOT}/docs/tracker.md` "Secondary intake channel"): there is no primary-tracker task and no `In Review`
status to check. Gate on CI green + an approving review only. The DoD criteria to verify come
from the linked issue's acceptance criteria (`gh issue view <n>`) when one exists, else the PR
description. Section 4 skips the `Done` transition and status-label strip (there is no primary
task and in-place items carry no `status:*` label); `Closes #N` auto-closes the issue on
merge. Post no primary-tracker comment; the verification report on the PR (and the issue, if
any) is the record.

## 2. Evidence per DoD criterion

For each Definition of Done criterion in the packet, gather evidence by type:

- **Test-backed:** run the named test (or the project `test_command` filtered to it) on the
  PR branch; record the command and result. Run it inside the task's worktree - never check
  the branch out in the main working copy, where a parallel verify or review session would
  fight over HEAD. (Manual-criterion commands that need the branch's files run there too.)
- **CI-backed:** cite the check name and the run URL from `gh pr checks`.
- **Manual:** perform the stated verification step where tools allow (run the binary, curl
  the endpoint, inspect the artifact); when only a human can observe it, check for a recorded
  sign-off (below) first, and only if none exists present the step and ask the user for the
  observation.
- **Visual / UI:** criteria requiring human judgment of appearance or interaction. Check for
  a recorded sign-off (below) first. If none: point the human to the "Local preview" section
  in the PR body (added by `dev:execute`) and ask them to run the dev server, interact with
  the UI, and confirm pass/fail. Never mark these as met without explicit human confirmation,
  recorded or live.

**Recorded sign-off.** The canonical record of a human-gate confirmation is a comment - on
the task or the PR - authored by the human, naming the criterion and approving it. Before
asking live, scan the task and PR comments (a prior `dev:verify` report counts, since its
evidence cell records who confirmed and when); cite the comment (author, date, link) as the
evidence. PR-body DoD checkbox state is NOT sign-off evidence: a checkbox carries no author
or timestamp, so a checked human-gate box proves nothing by itself - treat it as display
only. When the human instead confirms live in this session, make it durable: record who
confirmed and when in the report's evidence cell (the report is posted as a PR and task
comment, so it becomes the recorded sign-off for any later run), and check that criterion's
DoD box in the PR body. `dev:verify` after live or recorded confirmation is the only writer
allowed to check a human-gate box (`dev:execute` is barred from it).

A criterion with no evidence path is **unmet** - never "assumed met". Evidence must come from
the artifact (tests, CI, observed behavior), not from the implementer's claims in the work
summary.

## 3. Report

Post the verification report as a PR comment and a task comment:

```
## dev:verify - <task-id>
Result: <n>/<total> criteria met

| # | Criterion | Evidence | Met |
|---|-----------|----------|-----|
| 1 | <criterion> | <command + result / CI check + URL / observation> | yes/NO |
```

**Any criterion unmet:** stop. Do not merge; the task stays `In Review`. Route the gap:
implementation gap → `/dev:review-pr <n> fix` or a fresh `/dev:execute <id>` pass; wrong or
untestable criterion → the packet is the problem, send it through `/dev:backlog` triage.

## 4. Human gate and merge

All criteria met: present the report and ask the human to approve the merge. On approval:

0. Check mergeability first, not just CI: `gh pr view <n> --json mergeable,mergeStateStatus`.
   Sibling PRs that branched before an earlier one merged conflict exactly here (green CI,
   unmergeable). If conflicting or behind: rebase the task branch onto `origin/main` in its
   worktree, push, let CI re-run to green - and if resolving conflicts changed hunks the
   review already read, get a re-review before merging.
1. Merge per `merge_policy`: `gh pr merge <n> --squash` (or `--merge`). Do NOT pass
   `--delete-branch`: the task branch is always still checked out in its worktree at this
   point (`dev:execute` created it; cleanup is step 4), so the local delete fails and the
   remote delete is skipped with it - the merge succeeds but the remote branch silently
   leaks. All branch deletion happens in step 4, after the worktree is gone. No GitHub
   remote: merge locally instead - `git checkout main` then `git merge --squash` + commit
   (or `git merge --no-ff` per policy); branch deletion likewise waits for step 4.
2. Transition the task to `Done` (GitHub backend: confirm the linked issue auto-closed as
   completed, close it explicitly if not, and remove the now-stale `status:*` label -
   `gh issue edit <n> --remove-label status:in-review` - since `Closes #N` auto-close does
   not touch labels and a closed issue must carry none).
3. Comment the merge commit / PR URL on the task.
4. Clean up, in order: `git worktree remove` the task worktree (this frees the branch),
   then `rmdir ../<repo>-worktrees 2>/dev/null || true` (removes the container dir when
   this was the last worktree in it; `rmdir` refuses non-empty dirs, so it is safe while
   sibling task worktrees exist), then delete the branch - `git branch -d task/<id>-<slug>`
   plus, with a remote, `git push origin --delete task/<id>-<slug>` - then update local
   `main`. Confirm the remote branch is actually gone
   (`git ls-remote --heads origin task/<id>-<slug>` prints nothing): this leak is silent
   and easy to miss.

Declined or deferred: leave everything as-is and report what the human decided.

## Spikes

A spike verifies differently: evidence is the ADR in `docs/adr/` plus the recommendation
comment on the task. No merge - the spike branch is throwaway. Confirm both artifacts exist,
transition to `Done`, delete the branch and worktree (same cleanup as step 4 above,
including the empty-container `rmdir`).
