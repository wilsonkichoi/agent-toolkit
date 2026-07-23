# ADR 0001: Decouple the rule registry from Claude Code `@` imports

- **Status:** Accepted (spike decision; implementation deferred to #26)
- **Date:** 2026-07-23
- **Spike:** [#27](https://github.com/wilsonkichoi/agent-toolkit/issues/27)
- **Follow-up:** [#26](https://github.com/wilsonkichoi/agent-toolkit/issues/26)
- **Evidence revision:** `7a6968a64fc11baf6cf6c30172302ca35a9a0803`

## Context

`.agent-toolkit/dev.md` carries a `## Rules` section holding one bare `@<path>` line per promoted
rule file. That single line has two consumers with two different meanings:

- `plugins/dev/scripts/resolve_project_rules.py` treats it as a **registry edge**. It walks the
  edge, reads the terminal file's `tier` frontmatter, and applies gotcha triggers before deciding
  whether the rule is loaded or skipped.
- Claude Code treats it as a **native import**. The chain `CLAUDE.md` → `@AGENTS.md` →
  `@.agent-toolkit/dev.md` → `@.agent-toolkit/rules/<slug>.md` is expanded and injected into the
  session context at launch, before any skill runs and before the resolver exists.

The two meanings cannot both hold. A gotcha rule whose triggers do not match is reported as
`Rules skipped:` by the resolver while its full body is already in Claude Code's context. The
bootstrap audit trail recorded in every work summary, review body, and verify report therefore
misstates what the session actually read. On Codex the same registry yields the resolver's answer
only, so the two harnesses diverge on identical repository state.

This conflicts with two checked-in contracts. The repository has no `docs/PRD.md` or
`docs/SPEC.md`; these are the applicable intent sources.

`AGENTS.md`, "Skills":

> Skill prose must stay harness-neutral.

> Codex correctness must not depend on `@` import expansion.

`plugins/dev/runtime_contracts/project-bootstrap.md`, "Rule metadata":

> Doctrine rules always load.

> Gotcha rules load when any declared trigger matches.

## Evidence

All four reproductions below run against the plugin resolver at the evidence revision. The exact
fixture script is in [Appendix A](#appendix-a-reproduction-script); each block is verbatim output.

### E1. A non-matching gotcha is reported as skipped

Fixture: `.agent-toolkit/dev.md` registers `@.agent-toolkit/rules/shell-portability.md`, a
`tier: gotcha` rule triggering on `scripts/**/*.sh` and the objective substring `shell script`.
Resolved with an unrelated objective and changed path:

```text
Project instructions:
- AGENTS.md
- .agent-toolkit/dev.md
Rules loaded:
- none
Rules skipped:
- .agent-toolkit/rules/shell-portability.md [gotcha; no trigger matched]
exit=0
```

The same fixture with `--changed-path scripts/build.sh`:

```text
Rules loaded:
- .agent-toolkit/rules/shell-portability.md [gotcha; path:scripts/build.sh matches scripts/**/*.sh]
Rules skipped:
- none
```

This behavior is also pinned by the committed regression test
`tools/test_resolve_project_rules.py::test_unmatched_gotcha_is_reported_as_skipped`, which asserts
`rules_loaded == []` for a gotcha whose path, objective, and definition-of-done triggers all miss.

### E2. The same line is a native Claude Code import

The Claude Code documentation (["How Claude remembers your
project"](https://code.claude.com/docs/en/memory), "Import additional files") states:

> CLAUDE.md files can import additional files using `@path/to/import` syntax. Imported files are
> expanded and loaded into context at launch alongside the CLAUDE.md that references them.

> Imported files can recursively import other files, with a maximum depth of four hops.

> Import parsing skips Markdown code spans and fenced code blocks. To mention a path in your
> CLAUDE.md without importing it, wrap it in backticks.

This repository's own chain is three hops of the four available: `CLAUDE.md` (whose entire body is
`@AGENTS.md`) → `AGENTS.md` line 6 (`Dev workflow (agent-toolkit dev plugin):
@.agent-toolkit/dev.md`) → `.agent-toolkit/dev.md` → the `@` lines under its `## Rules` section.
Observed directly: a Claude Code session opened in this repository receives the full text of
`AGENTS.md` **and** `.agent-toolkit/dev.md`, including the `## Rules` heading, as launch context
without any tool call. Rule files sit at hop four, inside the documented limit.

The repository already asserts this as intended behavior, in
`plugins/dev/skills/setup/SKILL.md` (step 4, "Add the reference line"):

> On Claude Code the `@` import inlines `dev.md` (config frontmatter, conventions body, and the
> rule imports its `## Rules` section carries) at session start.

E1 and E2 together are the mismatch: on Claude Code the E1 rule body is in context while the
bootstrap record says `Rules skipped:`.

### E3. Pre-0.0.56 descriptive entries are invisible to both consumers

`IMPORT_RE` in the resolver is `^\s*@(?P<path>\S+)\s*$` — a whole-line bare import. Pre-0.0.56
registries used descriptive, backticked list entries. Fixture registry line:

```text
- `@.agent-toolkit/rules/guard-suite.md` - always run the guard suite
```

with a valid `tier: doctrine` rule present on disk:

```text
Rules loaded:
- none
Rules skipped:
- none
exit=0
```

The resolver's line regex does not match, so the rule is never reached; Claude Code's parser skips
code spans, so it is not imported either. The rule is silently absent from both harnesses and the
resolver still exits 0. This is the failure mode #26 reports from two downstream repositories (20
and 12 rule files).

### E4. A fenced registry block is resolver-visible and Claude-Code-invisible

Same fixture with the registry wrapped in a fence:

````text
## Rules

```
@.agent-toolkit/rules/guard-suite.md
```
````

```text
Rules loaded:
- .agent-toolkit/rules/guard-suite.md [doctrine; tier:doctrine]
Rules skipped:
- none
exit=0
```

`rules_section_imports` scans lines without fence awareness, so the resolver still resolves the
edge, while Claude Code's import parser skips fenced code blocks. Harness isolation is therefore
achievable today with zero resolver change — this is what makes Option C viable, and also what
makes it fragile (see below).

### E5. A `rules_dir` inside a harness auto-load path defeats every option

The same documentation page describes `.claude/rules/`:

> Rules without a `paths` field are loaded unconditionally and apply to all files.

`rules_dir` is documented as pointable at `.claude/rules/` (`plugins/dev/README.md`, `rules_dir`
row: "point it at an existing convention (e.g. `.claude/rules/`) when the project already has
one"). A rule file there carries this plugin's `tier:` / `triggers:` frontmatter, not Claude Code's
top-level `paths:` field, so Claude Code loads it unconditionally at launch. Under that
configuration no registry model can make a skipped gotcha absent from Claude Code context. This
constrains the decision rather than choosing between the options.

## Decision drivers

Acceptance dimensions required by #27, applied to each option:

1. Fail-closed behavior when the registry and the on-disk rule set disagree.
2. Doctrine and gotcha loading behavior on Codex and on Claude Code.
3. Migration cost.
4. Backward compatibility.
5. Authoring complexity.
6. Interaction with #26.

## Options considered

### Option A — dedicated machine-readable registry owned by the resolver

A structured list the resolver owns and no harness interprets: a `rules:` sequence in the
`.agent-toolkit/dev.md` frontmatter, or a separate `.agent-toolkit/rules.toml`. Entries are plain
paths, never `@`-prefixed.

| Dimension | Assessment |
|---|---|
| Fail-closed | Requires an explicit registry-vs-disk reconciliation pass, because two sources of truth persist permanently. That reconciliation is exactly #26's DoD; the drift class is bounded, never eliminated. |
| Codex | Unchanged: resolver output is the only input. Doctrine and gotcha behave per contract. |
| Claude Code | Clean. Plain paths are not `@` syntax and frontmatter is not an import surface, so nothing expands natively (with the E5 caveat). Gotcha skipping becomes real. |
| Migration cost | High. Every adopter converts `@` lines to structured entries; `dev:retro` and `dev:setup` learn a structured writer, including a YAML/TOML emitter with quoting rules they do not have today. |
| Backward compatibility | Poor without a dual-read shim. A shim reintroduces the `@` reader that this ADR exists to remove. |
| Authoring complexity | Worst of the three. Two coupled edits per rule forever: write the file, then register it in a structured list whose syntax is stricter than a markdown line. |
| Interaction with #26 | #26 survives in full, plus permanent reconciliation machinery. |

### Option B — frontmatter-only discovery under `rules_dir` (selected)

No registry. The resolver enumerates Markdown under the configured `rules_dir` and classifies each
file from its own frontmatter. The `## Rules` section stops being a registry and holds no `@`
lines.

| Dimension | Assessment |
|---|---|
| Fail-closed | Strongest. The filesystem is the only source of truth, so "a rule file exists but is unreachable from the registry" stops being a representable state. The remaining failure is an *unclassified* file, which hard-stops and names every offending path. |
| Codex | Unchanged semantics, simpler mechanics: no graph traversal, no index files, no cycles. |
| Claude Code | Clean. `.agent-toolkit/rules/` is not on any Claude Code auto-load path and no `@` line points into it, so a skipped gotcha is genuinely absent from context (E5 caveat applies to a `rules_dir` that is a harness path). |
| Migration cost | Moderate and mechanical. Delete the `@` lines from `## Rules`; stamp `tier:` on files that lack it. Both steps are scriptable and land in `dev:setup`. |
| Backward compatibility | Deliberately broken once, with an actionable diagnostic. Pre-0.0.56 descriptive registries (E3, today silently empty) start working the moment their files are classified. The current legacy rule "terminal rule without frontmatter loads as doctrine" is retired, because under discovery it would apply to every stray `.md` in the tree rather than only to files an author registered on purpose. |
| Authoring complexity | Lowest. One file is one rule; dropping it in `rules_dir` is the whole act. `dev:retro` stops editing `dev.md`, removing a class of half-applied promotions where the file lands but the registration does not. |
| Interaction with #26 | #26's central bug class disappears rather than being detected. #26 remains an implementation task with restated criteria (see below). |

### Option C — retain the `## Rules` graph plus a harness-isolation mechanism

Keep the import graph; stop Claude Code from expanding it, using the documented parser exclusions:
fence the whole block (E4, works today unchanged) or backtick each entry (needs a resolver regex
that accepts the backticked form, which also revives pre-0.0.56 registries from E3).

| Dimension | Assessment |
|---|---|
| Fail-closed | Unchanged from today. Registry-vs-disk drift remains the primary failure and stays silent until #26 lands. |
| Codex | Unchanged. |
| Claude Code | Isolation works but **fails open**. Removing a fence or a pair of backticks silently restores full expansion, produces no diagnostic, and looks like a cosmetic edit in review. The mechanism is invisible in the artifact it protects. |
| Migration cost | Lowest. Wrap the existing block in a fence; teach the resolver the backticked form for pre-0.0.56 repos. |
| Backward compatibility | Highest. No adopter breaks. |
| Authoring complexity | Deceptively low. The registry keeps its dual meaning and is merely muzzled, so every future author must know that the fence is load-bearing. |
| Interaction with #26 | #26 survives in full and unchanged. |
| Additional risk | Inverts the harness-neutrality rule. `AGENTS.md` requires that Codex correctness not depend on `@` expansion; under C, Claude Code correctness depends on Claude Code *not* expanding a line that is valid import syntax — a dependency on a third-party parser exclusion, load-bearing and untestable from this repository. |

## Decision

**Adopt Option B: frontmatter-only discovery under `rules_dir`.**

It is the only option that removes the dual meaning at its source rather than suppressing one of
the two readings. It collapses two sources of truth into one, which turns #26's reported bug class
into a non-category instead of a detected condition, and it is the cheapest model to author
against. Option A pays a permanent authoring and reconciliation tax for the same isolation. Option
C is cheapest today and fails open, which is the wrong failure direction for a correctness-gating
mechanism.

### Fail-closed semantics

The resolver's rule phase becomes:

1. Resolve `rules_dir` as today (relative to the dev configuration, inside the execution
   repository). A missing directory yields zero rules and exits 0.
2. Enumerate every `*.md` under `rules_dir` recursively, in deterministic repository-relative sort
   order. Resolve symlinks; a target outside the execution repository is a hard stop, preserving
   today's path-escape guarantee.
3. Classify each discovered file from its own frontmatter:
   - `tier: doctrine` → loaded.
   - `tier: gotcha` with at least one declared trigger → loaded when a trigger matches, otherwise
     reported under `Rules skipped:`.
   - the explicit non-rule marker (below) → excluded, reported under a new `Rules excluded:`
     section so the decision is auditable.
   - **anything else — no frontmatter, frontmatter without `tier`, an unknown `tier` value, a
     trigger-free gotcha, malformed frontmatter — is a hard stop.** The diagnostic names every
     offending repository-relative path in deterministic order and states both remedies: declare a
     `tier`, or mark the file as a non-rule.
4. An `@` import line anywhere inside a `rules_dir` file is a hard stop. Rule files are terminal by
   construction, which retires the index, import-cycle, and import-path-escape classes rather than
   weakening them; step 2's symlink check carries the escape guarantee forward.
5. A `rules_dir` whose Markdown is entirely and explicitly excluded resolves to zero rules and
   exits 0. Every file was a recorded human decision, so there is no ambiguity to fail on. This
   deliberately narrows #26's original "non-empty `rules_dir` with zero rules exits nonzero" to
   "non-empty `rules_dir` containing an unclassified file exits nonzero".
6. `rules_dir` resolving inside a harness's native auto-load path (notably `.claude/rules/`) is
   **reported, not stopped** (E5). Native auto-load over-includes context; it never removes an
   instruction, so it is not a correctness failure. The resolver emits a parity warning naming the
   directory and the affected tier, and the bootstrap record carries it.

The governing asymmetry: **under-inclusion is a hard stop, over-inclusion is a reported warning.**
A rule that should have loaded and did not is a silent correctness hole; a rule that loaded when it
need not have costs context and nothing else.

### Explicit non-rule marker

One mechanism, per file, explicit, opt-out only:

```markdown
---
tier: none
---

# Rules directory conventions

Notes for human maintainers; not an agent instruction.
```

`tier: none` is chosen over a sidecar ignore file or a filename convention because it lives in the
file it describes, is visible in review, and reuses the field the resolver already parses. No broad
implicit ignore (no `.rulesignore`, no `README.md` special case): an unmarked file is always a hard
stop, so silence is never interpreted as consent.

## Consequences

**Positive.**

- The bootstrap audit trail becomes true on both harnesses: `Rules loaded:` / `Rules skipped:`
  describes what the session actually read.
- `dev:retro` promotion becomes a single file write. The "wrote the rule, failed to register it"
  half-applied state is unrepresentable, and `dev:status`'s "unregistered rules" check retires.
- Pre-0.0.56 repositories with descriptive registries (E3) go from silently ruleless to
  hard-stopping with a named-file diagnostic, then to fully working after a mechanical fix.
- `resolve_rule_files` loses recursive traversal, cycle detection, and index handling.

**Negative.**

- A one-time breaking migration for every adopter with rules. Mitigated by making `dev:setup`
  perform it and by the diagnostic naming every file and both remedies.
- The legacy "no frontmatter means doctrine" guarantee is retired. The migration writes
  `tier: doctrine` onto exactly those files, so post-migration behavior is byte-identical to
  today's for every currently-registered rule; only unregistered strays change status, and they
  change from "silently ignored" to "must be classified".
- Any Markdown a project keeps under `rules_dir` for humans now needs `tier: none`.
- E5 remains unsolved for `rules_dir: .claude/rules/`. Documented as a parity caveat with
  `.agent-toolkit/rules/` recommended; not solvable by any registry model.

## Migration plan

Each case below is decidable from repository state alone, with no human judgement beyond the
`tier: none` decision in case 4.

**1. Pre-0.0.56 descriptive or backticked registry entries.** Detectable: the `## Rules` section
contains a line matching `@<path>` inside a code span or list item, and `rules_dir` is non-empty.
These repositories are already silently ruleless (E3), so nothing regresses. Migration: for every
`*.md` under `rules_dir` lacking `tier`, prepend `tier: doctrine` frontmatter — the tier the
pre-0.0.56 model implied for every entry; then delete the `## Rules` entries. Result: rules that
were invisible on both harnesses start loading. `dev:retro` may retier individual files to `gotcha`
later, with evidence, as it does today.

**2. 0.0.56+ bare-`@path` registries.** Detectable: `## Rules` contains whole-line bare `@` imports
that the current resolver walks. Migration: delete every `@` line from `## Rules` and leave the
section with its maintainer comment. Rule files already carry `tier` frontmatter (0.0.56+
`dev:retro` writes it), so no file-level change is needed; any that lack it get `tier: doctrine`
per case 1. Registered files were already loading, so behavior is unchanged. The observable
difference is that a skipped gotcha stops appearing in Claude Code context — the point of the
change.

**3. Repositories with no rules.** Detectable: `rules_dir` absent or containing no `*.md`. No
action. The resolver reports `Rules loaded: none` and exits 0, exactly as today. This repository is
in that state at the evidence revision, so this ADR's own branch exercises the case.

**4. Intentional non-rule Markdown under `rules_dir`.** Detectable: after cases 1-3, the resolver
hard-stops naming the file. Migration: the human decides per named file — add `tier: none` to keep
it in place, or move it out of `rules_dir`. `dev:setup` presents each unclassified file with both
options and never guesses.

`dev:setup` owns cases 1, 2, and the mechanical half of 4; it must be idempotent and must report
every file it stamps. Running it is the documented upgrade step, and the resolver's hard-stop
diagnostic names it.

## Surfaces the follow-up must change

Implementation lands in #26. Exact surfaces, at the evidence revision:

| Surface | Change |
|---|---|
| `plugins/dev/scripts/resolve_project_rules.py` | Replace `rules_section_imports`, `all_imports`, and `resolve_rule_files` with directory enumeration + classification. Retire `IMPORT_RE` for the rule path (the dev-config reference line is unaffected). Add `tier: none`, the unclassified hard stop with deterministic multi-path diagnostics, the in-rule `@`-import hard stop, symlink escape checks, the `Rules excluded:` output section, and the E5 parity warning. |
| `plugins/dev/runtime_contracts/project-bootstrap.md` | Rewrite "Rule metadata": discovery replaces the `@` graph; state the discovery-completeness invariant, `tier: none`, the under-inclusion/over-inclusion asymmetry, and the exact hard-stop list. Update the step 3/4 wording that presumes a registry. |
| `AGENTS.md`, "Skills" | Update "Promoted rule files use `tier: doctrine` … or `tier: gotcha` …" to state discovery under `rules_dir` and the unclassified-file hard stop. |
| `tools/test_resolve_project_rules.py` | Add: discovery of nested rules; unclassified file exits nonzero naming every path in deterministic order; `tier: none` excludes; all-excluded directory exits 0; `@` line inside a rule file exits nonzero; symlink escape exits nonzero. Retire or invert `test_codex_resolves_three_import_indirections_to_terminal_rule` and `test_legacy_terminal_rule_without_metadata_defaults_to_doctrine`. Keep `test_unmatched_gotcha_is_reported_as_skipped`, `test_terminal_rule_frontmatter_requires_tier`, and the revision-mismatch tests green. |
| `plugins/dev/skills/retro/SKILL.md` | Section 3 "Promote": drop the "append an `@<rules_dir><slug>.md` import line" step and the "an unregistered rule file is invisible" rationale. Promotion is the file write plus `tier`/`triggers` frontmatter. |
| `plugins/dev/skills/setup/SKILL.md` | Step 3/4 of the consumer migration; the `## Rules` block in the config template and its maintainer comment; the "On Claude Code the `@` import inlines … the rule imports its `## Rules` section carries" paragraph. Add the four-case migration action above. |
| `plugins/dev/skills/status/SKILL.md` | Replace the "Unregistered rules" consistency check with an unclassified-file check; keep "Unmatched gotchas in `Rules skipped:` are healthy". |
| `plugins/dev/skills/auto/SKILL.md` | The rule-promotion target wording that references registration in `.agent-toolkit/dev.md`. |
| `plugins/dev/README.md` | `rules_dir` field row; the `## Rules` sentence in "Configuration: `.agent-toolkit/dev.md`"; the "Rule promotion" ownership row; the memory-loop principle; the `memory_target` files-row description; add the E5 parity caveat for `rules_dir: .claude/rules/`. |
| `tools/check_repo.py` | Optional: assert the contract and skill prose no longer instruct registration via `@` lines, in the style of the existing `check_project_bootstrap_adoption` guard. |
| Version fields | Behavior-changing skill edits require the lockstep bump in `.claude-plugin/marketplace.json`, `plugins/dev/.claude-plugin/plugin.json`, `plugins/dev/.codex-plugin/plugin.json` (per `AGENTS.md` "Pre-commit checklist"). |
| User-facing migration guidance | `plugins/dev/README.md` upgrade note plus the `dev:setup` migration steps; state that the resolver hard-stops until migration and that `dev:setup` performs it. |

## Effect on #26

#26 **remains an implementation task** and **changes scope**. Its objective ("make rule discovery
fail closed") survives; its mechanism does not, because there is no registry left to reconcile
against disk. Restated criteria:

- Its DoD 1 bullet "a fully registered or fully discoverable rule set exits 0" keeps the discovery
  half only.
- Its DoD 1 bullet "a non-empty `rules_dir` with zero registered or discoverable rules exits
  nonzero" narrows to "containing an unclassified file exits nonzero"; an all-`tier: none`
  directory exits 0 (fail-closed semantics, item 5).
- Its DoD 2 explicit-exclusion mechanism resolves to `tier: none`, and its "an unmarked rule file
  still fails resolution" clause holds without exception, since the legacy no-frontmatter default
  is retired.
- Its DoD 3 "does not weaken the existing import-cycle, path-escape … failures" is satisfied by
  retirement plus replacement: cycles and index files cease to exist, in-rule `@` imports hard
  stop, and path escape is carried by the symlink check.
- Its DoD 5 ("consistent with the selected registry model from #27") is now decidable against this
  ADR.

## Appendix A: reproduction script

Run from a checkout at the evidence revision. Requires `uv` and `git`; makes no network calls and
writes only under the temporary directory.

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="$(git rev-parse --show-toplevel)"
RESOLVER="$REPO/plugins/dev/scripts/resolve_project_rules.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fixture() { # $1 = name, $2 = body of the "## Rules" section
  local F="$TMP/$1"
  mkdir -p "$F/.agent-toolkit/rules"
  git -C "$F" init -q .
  git -C "$F" config user.email t@t
  git -C "$F" config user.name t
  printf '# Fixture\n\nDev workflow: @.agent-toolkit/dev.md\n' > "$F/AGENTS.md"
  printf -- '---\ntracker: local\ntest_command: "true"\ncontext_file: AGENTS.md\nrules_dir: .agent-toolkit/rules/\n---\n\n## Rules\n\n%s\n' \
    "$2" > "$F/.agent-toolkit/dev.md"
  printf -- '---\ntier: gotcha\ntriggers:\n  paths:\n    - "scripts/**/*.sh"\n  objective:\n    - "shell script"\n---\n\n# Shell script portability\n\nRun shell scripts under every supported shell.\n' \
    > "$F/.agent-toolkit/rules/shell-portability.md"
  printf -- '---\ntier: doctrine\n---\n\n# Guard suite\n\nRun the guard suite.\n' \
    > "$F/.agent-toolkit/rules/guard-suite.md"
  git -C "$F" add -A
  git -C "$F" commit -qm fixture
  printf '%s' "$F"
}

resolve() { # $1 = fixture path, remaining args passed through
  local F="$1"; shift
  uv run "$RESOLVER" --tracker-repo "$F" --execution-repo "$F" \
    --execution-revision HEAD "$@"
}

echo "== E1a: bare registry, gotcha triggers miss =="
F1="$(fixture bare '@.agent-toolkit/rules/shell-portability.md')"
resolve "$F1" --objective "Update the release notes" \
  --definition-of-done "Release notes updated" --changed-path docs/RELEASE.md

echo "== E1b: same registry, gotcha triggers match =="
resolve "$F1" --objective "Update the release notes" \
  --definition-of-done "Release notes updated" --changed-path scripts/build.sh

echo "== E3: pre-0.0.56 descriptive entry, rule invisible, exit 0 =="
F3="$(fixture desc '- `@.agent-toolkit/rules/guard-suite.md` - always run the guard suite')"
resolve "$F3" --objective x --definition-of-done y

echo "== E4: fenced registry still resolves (Claude Code skips fenced blocks) =="
F4="$(fixture fenced '```
@.agent-toolkit/rules/guard-suite.md
```')"
resolve "$F4" --objective x --definition-of-done y
```

The E2 half is not scriptable from this repository: it depends on Claude Code's launch-time context
assembly, which has no offline harness here. It is established by the vendor documentation quoted
above, this repository's own committed assertion in `plugins/dev/skills/setup/SKILL.md`, and direct
observation of a session in this repository receiving `.agent-toolkit/dev.md` as launch context.
Claude Code's `InstructionsLoaded` hook logs which instruction files loaded and is the check an
adopter can run to confirm E2 locally.
