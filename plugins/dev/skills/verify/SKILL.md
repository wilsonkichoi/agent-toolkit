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
every criterion is mechanically evidenced (test or CI). A manual criterion always requires a
live human, regardless of config.

Read first: `.claude/dev.md` (config) and `${CLAUDE_PLUGIN_ROOT}/docs/tracker.md`.

## 1. Preconditions

Resolve the task and PR (from the argument, the task's `pr` link, or the PR's linked task).
Check: task status is `In Review`, CI is green, and an approving review exists
(`gh pr view <n> --json reviews`). An approving review is either `state: APPROVED` or a
`dev:review-pr`-formatted review body whose verdict line reads `Verdict: approve` - the
latter is the only form possible when reviewer and PR author are the same account (GitHub
forbids self-approval, so solo repos never get `APPROVED` state). A missing review is a
warning, not a hard stop; report it and let the human decide whether to proceed without one.

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
  the endpoint, inspect the artifact); when only a human can observe it, present the step and
  ask the user for the observation.

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
   then delete the branch - `git branch -d task/<id>-<slug>` plus, with a remote,
   `git push origin --delete task/<id>-<slug>` - then update local `main`. Confirm the
   remote branch is actually gone (`git ls-remote --heads origin task/<id>-<slug>` prints
   nothing): this leak is silent and easy to miss.

Declined or deferred: leave everything as-is and report what the human decided.

## Spikes

A spike verifies differently: evidence is the ADR in `docs/adr/` plus the recommendation
comment on the task. No merge - the spike branch is throwaway. Confirm both artifacts exist,
transition to `Done`, delete the branch and worktree.
