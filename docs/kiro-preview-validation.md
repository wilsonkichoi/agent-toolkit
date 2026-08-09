# Kiro preview validation evidence

The in-repo record behind every "validated" or "passed" claim about the generated Kiro
distribution in `README.md`, `plugins/dev/README.md`, `plugins/utils/README.md`, `CHANGELOG.md`,
and `dist/kiro/README.md`. Claims elsewhere must not exceed what this file records.

## Surface under test

| Item | Value |
|---|---|
| Kiro IDE build | 0.12.333 (`c7e35289ee989c7c61a1e9440d48b51361d95a10`, arm64) |
| Probe date | 2026-08-07 |
| Source branch | `feat/kiro-support` |
| Plugin versions | dev `0.0.74`, utils `0.0.5` |
| Installation path | clone plus `ditto` copy into `<project>/.kiro/` and `~/.kiro/` |
| Fixtures | disposable single-purpose Git repositories, no remotes, clean baselines |

Kiro CLI was never installed and was deliberately excluded from scope.

## Outcomes

Every row below was exercised manually in a fresh Kiro IDE window against a disposable
repository, with an independent `git status --short` check after each run.

| Area | Result |
|---|---|
| Skill discovery, slash invocation, trailing-argument preservation | passed |
| Natural-language activation without a slash command | passed, then **superseded** (see below) |
| Global and workspace installation; workspace-over-global precedence | passed |
| Non-ASCII safe alias (`/utils-retro-zh`, source skill `回顧`) | passed |
| Bundled dependency resolution beneath the installed skill directory | passed |
| Named agent dispatch by exact generated name, isolated child context | passed |
| Child failure propagation without inline substitution | passed |
| Human-gated `setup → plan → execute → review-pr → verify` lifecycle | passed |
| Safe stop: required named agent absent | passed |
| Safe stop: denied tool, no retry or substitution | passed |
| Safe stop: interrupted in-progress task, no reclaim or repair | passed |
| Safe stop: stale approving review against a newer task head | passed |
| Bounded `dev:auto` single-task run honoring WIP and `max_tasks_per_run` | passed |
| Clean-checkout install, byte-parity recopy, exact manifest-owned removal | passed |
| Multi-root active-folder isolation | **failed** - both roots' steering reached parent and child |
| Explicit agent `resources:` | **not demonstrated** - generated profiles omit the field |
| `max_fix_attempts` exhaustion | **not demonstrated** - no legitimate review requested changes |
| Kiro CLI (any version) | **not tested** |
| `dev:shadow`, `dev:feedback`, `dev:release` | **not tested** - not generated for Kiro |

The natural-language activation probe was run against a `security-scan` description that invited
automatic activation. That description was subsequently made explicit-invocation only on every
harness, so the probe records what Kiro *can* do with an inviting description, not intended
behavior for the shipped skill. No shipped utility skill claims automatic activation.

## Consequences for the shipped artifact

- Support is limited to single-root Kiro IDE workspaces. The multi-root failure happens in Kiro's
  parent workspace context before a generated profile can select an execution root, so a static
  generator cannot repair it.
- Generated agents intentionally omit `resources:`; current evidence does not show that declaring
  it suppresses inherited inactive-root steering.
- CLI compatibility must not be advertised or inferred from the IDE result.
- `dev:shadow`, `dev:feedback`, and `dev:release` are not generated for Kiro at all, so no probe
  covers them there. See `docs/adr/0002-kiro-generated-distribution.md`.

Stop condition: if later IDE testing loses named-agent isolation, synchronous result return, or
failure propagation, stop and do not weaken the independent review, test-authoring, or
verification contracts.

Detailed per-probe transcripts, fixture commit SHAs, and runbooks were kept in the maintainer's
local research notes and are not part of this repository. This file is the summary of record.
