# Shadow Replay Contract

`dev:shadow` replays a completed GitHub issue from its historical base with the active
session's model, then measures the replay against the original. This document is the reference
for the deterministic pieces the `shadow` skill orchestrates: the isolation model, the
artifact and evidence formats, the metrics adapters, the pricing catalog, and the benchmark
limitations that every report must disclose. The skill (`skills/shadow/SKILL.md`) owns the
lifecycle; the helper (`scripts/shadow_replay.py`) owns the deterministic steps.

`dev:shadow` is an evaluation surface, not a scientific benchmark and not a lifecycle skill.
It never merges a pull request, never mutates the source issue or original PR, and never enters
the planned-task queue.

## Supported harnesses and source backends

- **Harnesses:** any harness that can dispatch fresh-context subagents and wait on them (Claude
  Code natively; Codex via `spawn_agent`/`wait_agent`). Codex's `agents.max_depth = 1` blocks a
  worker from spawning `test-writer`, so the orchestrator dispatches `test-writer` as a sibling
  (same pattern as `dev:auto`). A harness with no subagent mechanism cannot run `dev:shadow`.
- **Source backend:** GitHub only in v0. The source issue and merged PR live in
  `github_primary_repo`. Linear and local source tickets are out of scope.

## Historical reconstruction and cutoff

1. Resolve the source issue and merged PR in the canonical repository. A closing reference must
   bind the PR to the issue (`preflight` checks the PR's `closingIssuesReferences`); an explicit
   `pr <source-pr>` still passes that check.
2. Order source-PR commits by GitHub's commit sequence. For a normal single-root feature
   branch, the historical base is the sole parent of the first source-PR commit. A root commit
   (no parent), a merge commit (multiple parents), a missing parent, or a parent that is not an
   ancestor of the source head is ambiguous and stops the run.
3. The information cutoff is the first source-PR commit's committed timestamp. The
   implementation worker receives the current source issue body plus comments created strictly
   before that cutoff. GitHub does not expose a reliable historical snapshot of an edited issue
   body through this contract, so the report discloses that the current body may contain later
   edits.
4. The implementation context **excludes** the original diff, source-PR reviews, source-PR
   comments, source commits after the base, post-cutoff issue comments, and comparison results.
   Those are available only to the review, verification, and comparison stages as appropriate.
5. Project instructions and rules load at the historical base through the shared
   `docs/project-bootstrap.md` contract. Every lifecycle artifact records the exact execution
   repository, revision, and loaded-rule paths.

## Git and GitHub isolation

- `shadow-base/<source-id>/<run-id>` is an immutable branch at the validated historical base.
- `shadow/<source-id>/<run-id>` is the candidate branch, created from the shadow-base branch in
  an isolated worktree (`git worktree add`, never harness worktree isolation).
- The `[SHADOW]` issue carries `experiment:shadow`, no `status:*` label, no milestone, no
  dependency edges, and no normal task assignment. Required labels are created idempotently.
- The candidate PR is a **draft** whose base is the shadow-base branch (so its diff is only
  replay work) and whose head is the candidate branch. It carries `do-not-merge` and references
  the shadow issue with `Refs #<shadow-issue>`, never `Closes`.
- Before each lifecycle stage and before terminal cleanup, `validate-invariants` re-reads the
  issue and PR and stops on any drift. It binds identities and revisions, not just names: the
  `Refs` must target the actual shadow issue number; when given `--historical-base`, the remote
  shadow-base ref must still equal that immutable SHA (a force-push is caught); and when given
  `--source-issue`/`--source-pr`/`--source-merge-sha`, the source issue must still be
  completed and the source PR still merged at the same merge commit (source mutation is caught).
- On success, cleanup closes the draft PR unmerged, closes the shadow issue as a completed
  evaluation, removes the worktree, and **retains both remote shadow branches** for audit and
  reproducibility. On failure, artifacts stay open for inspection; nothing is deleted
  automatically, and the source issue and original PR are never touched.

## Reusing review and verification agents

The named `reviewer` and `verifier` agents enforce planned-task GitHub routing (they require a
trusted execute work-summary and a `status:in-review` label). A shadow item has neither by
design. When that routing would reject a shadow artifact, dispatch a fresh generic worker that
carries the review or verify contract verbatim (body format, SHA binding, rubric) instead of
labeling the shadow item `planned`, `external`, or `secondary` to satisfy a contract it does
not belong to. The review still binds to the candidate head SHA and the verify still gathers
evidence for every source DoD criterion; only the queue-routing preconditions are replaced by
the shadow contract.

## `shadow_replay.py` subcommands

All subcommands are dependency-free and print one JSON object on success (except `report`,
which prints Markdown to stdout or `--out`). Read subcommands are safe to repeat; write
subcommands re-read GitHub state and assert isolation before reporting success.

| Subcommand | Purpose |
|---|---|
| `run-id` | Print `<UTC-timestamp>-<suffix>`; `--now`/`--suffix` make it deterministic for tests. |
| `preflight` | Gate the source issue (completed), PR (merged + bound), and historical base (recoverable). |
| `historical-base` | Reconstruct the base commit and cutoff from the source-PR commits; detect ambiguity. |
| `create-shadow-issue` | Idempotently ensure labels, create the `[SHADOW]` issue, assert no `status:*`/milestone. |
| `create-branches` | Create and push the shadow-base and candidate branches at the validated base. |
| `open-shadow-pr` | Open the draft `do-not-merge` PR; reject a closing keyword, require `Refs #N`. |
| `validate-invariants` | Re-read issue + PR, bind identities/revisions, assert isolation; stop on drift. |
| `review-freshness` | Reject an approval whose commit is not the current candidate head (stale review). |
| `metrics` | Aggregate harness token usage per adapter without double-counting. |
| `pricing` | Estimate API-equivalent cost from the versioned catalog, or `cost unavailable`. |
| `compare` | Assemble the comparison table rows; missing data becomes `unavailable`. |
| `report` | Render the Markdown evaluation report, always including the required disclosures. |
| `cleanup` | Close the draft PR unmerged (proof re-read), close the shadow issue, remove the worktree. |

## Metrics adapters

`metrics --harness <name> --log <file> [--log <file> ...]` maps a harness's session logs into
one usage total. Adapters are deterministic and covered by fixture tests; they read only numeric
usage metadata and never emit prompts, reasoning text, tool arguments, or repository content.

The critical distinction is **cumulative vs incremental** usage. Summing every cumulative event
multiplies usage by the event count; the adapter must know which shape its harness emits.

- **`claude-code`** — transcript JSONL. Each `{"type":"assistant","message":{"usage":{...}}}`
  record carries *incremental* per-message usage, so the adapter sums within a thread. A thread
  is `sessionId` plus whether the record is a sidechain (subagent) turn. Field mapping:
  `input_tokens` and `cache_creation_input_tokens` → input; `cache_read_input_tokens` → cached
  input; `output_tokens` → output. Claude Code does not expose reasoning tokens, so
  `reasoning_tokens` is `null`.
- **`codex`** — rollout JSONL. Token events use the real Codex envelope
  `{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{...}}}}`
  (a flattened `{"type":"token_count","info":{...}}` is also accepted). These totals are
  *cumulative*, so the adapter keeps the **last** event in the rollout (never sums them). One
  rollout file is one thread; its session id (from the `session_meta` record) labels the thread
  when present. Field mapping: `input_tokens` → input; `cached_input_tokens` → cached input;
  `output_tokens` → output; `reasoning_output_tokens` → reasoning.

Across multiple logs (parent plus child rollouts), the adapter sums the per-file finals. A
`claude-code` assistant record with no `sessionId` is unattributable; its tokens go to an
`unattributed` bucket and are still included in the totals, labeled `unattributed`, never
guessed into a stage. When a harness or model exposes no reasoning category, `reasoning_tokens`
is `null` and the comparison row reads `unavailable` - the adapter never fabricates a zero.

Adding a harness is one adapter function keyed in `ADAPTERS` plus a fixture; nothing else in the
script changes.

## Evidence blobs

`compare --original <file> --shadow <file>` reads two JSON objects. Each key is the comparison
dimension lowercased with spaces and hyphens replaced by underscores; a missing key or a `null`
value renders as `unavailable`. The recognized keys are:

```
functional_tests, dod_criteria_met, review_blockers, fix_and_review_cycles,
files_changed, lines_added_and_removed, observable_delivery_time, total_run_time,
ci_wait_time, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens,
estimated_api_equivalent_cost
```

The comparison never collapses these into a single aggregate quality score, and it never invents
an original quality score. Original token and cost data that GitHub does not expose stays
`unavailable`.

## Timing and token boundaries

- **Shadow delivery time** starts just before the implementation worker is dispatched and ends
  when verification of the approved candidate head completes. Preparation, comparison, and report
  publication are recorded separately and included in total run time.
- **Original observable delivery time** starts at the first source-PR commit's committed
  timestamp and ends at the source PR's merged timestamp. The report labels this a GitHub-derived
  estimate, not continuous agent work.
- **CI wait time** uses workflow job or check-suite start and completion timestamps when
  available.
- Token adapters aggregate the final cumulative usage record once per distinct thread and must
  not double-count. Unattributable usage is included in total tokens and labeled `unattributed`.

## Pricing catalog

`pricing` reads `scripts/shadow_pricing.json`, a versioned catalog. Each entry carries
`provider`, `model`, `effective_date`, `source_url`, `currency`, and per-MTok `input`,
`cached_input`, and `output` rates plus a `reasoning` treatment:

- a number — a per-MTok rate for reasoning tokens;
- `"output"` / `"input"` — bill reasoning at that category's rate;
- `"unpriced"` — the provider does not bill reasoning separately (rate 0).

Cost = Σ (tokens × rate) / 1,000,000 over the categories with non-zero tokens. A model absent
from the catalog, or a missing rate for a category that has non-zero tokens, yields
`cost unavailable` with a reason - never a guessed value. Estimated API-equivalent cost is a
list-price estimate, not the user's actual subscription charge; the report discloses this.

Keep the catalog current: add dated, sourced entries when published prices change, and bump
`catalog_version`. Do not edit an entry's rates in place without updating `effective_date` and
`source_url`.

## Required report disclosures

Every report includes these, emitted by `report` automatically:

- Same-repository replay is not blind; the original solution may be discoverable in Git history
  or through GitHub.
- The source issue body is current, not guaranteed to be its exact historical text at cutoff.
- Original token and cost data may be unavailable.
- GitHub timestamps are observable workflow timestamps, not continuous agent work.
- Estimated API-equivalent cost is not the user's actual subscription charge.
- Reviewer and verifier judgments depend on the identified models.

## Report schema enforcement

A completed report (`final_state` not starting with `failed`) must carry every audit binding:
the run id, harness, model, source issue and PR links, the original PR merge SHA, the historical
base, the information cutoff, the shadow issue and PR links, the reviewed candidate head SHA, and
the verification evidence or verifier-report link. `report` fails instead of rendering
`unavailable` for a missing binding, so a malformed run cannot produce a green report and then
close the artifacts as evaluation-complete. A stopped run sets `final_state: failed:<stage>`,
which is exempt from binding enforcement. Legitimately missing measurement data (original tokens,
cost) still renders as `unavailable`; only the identity/audit bindings are mandatory.

## Stop conditions

`dev:shadow` stops with a diagnostic and no source mutation when: the source issue is not
completed, the source PR is not merged, or their binding is invalid; source-PR selection or
historical-base reconstruction is ambiguous; repository, permission, project-bootstrap, or
historical-rule resolution fails; a required fresh worker cannot be dispatched; tests or CI stay
red or review stays request-changes after `max_fix_attempts`, or the approval SHA is stale;
verification evidence is incomplete; shadow isolation drifts; or any next operation would merge,
mutate source artifacts, or enter normal queue state.
