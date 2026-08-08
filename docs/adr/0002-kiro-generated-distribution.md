# 2. Kiro ships as a generated per-skill distribution, not a plugin

Date: 2026-08-08

## Status

Accepted.

## Context

The `dev` and `utils` plugins install into Claude Code and Codex as plugins. A plugin has a shared
root, so all 15 dev skills reference one copy of each shared file:

```
${CLAUDE_PLUGIN_ROOT}/runtime_contracts/tracker.md
${CLAUDE_PLUGIN_ROOT}/scripts/work_summary.py
```

Kiro implements the [Agent Skills](https://agentskills.io/specification) standard. There, a skill
directory is the unit of distribution, and the spec requires file references to resolve relative to
`SKILL.md`. Kiro reads skills from `.kiro/skills/` (workspace) or `~/.kiro/skills/` (global), with
workspace winning on a name collision. There is no plugin root, no shared sibling directory, and no
supported way for one skill to reference another skill's files.

Three consequences follow, and each needed a decision.

**Sharing requires copying.** A shared contract or helper has to be physically present inside every
skill that needs it. This is not a packaging preference; the spec leaves no alternative that keeps
skills portable.

**Kiro is not a marketplace target.** There is no Kiro plugin marketplace manifest, Power, or
installer for this shape of artifact. Kiro's own import paths are a single local folder or a
GitHub subdirectory URL, one skill at a time.

**Skill names collide across plugins.** Both plugins define `retro`, and `utils` defines the CJK
skill `回顧`, while the Agent Skills `name` field permits only lowercase alphanumerics and hyphens
and must equal the directory name.

Two alternatives were considered and rejected. Putting shared contracts in `.kiro/steering/`
instead of duplicating them would require a second install target, produce a non-portable layout,
and push roughly 60 KB of contracts into every unrelated conversation, since steering is not
skill-scoped. Declaring shared files through a custom agent's `resources` field does not help
either: agents do not load skills by default and the field addresses agent context, not
skill-relative resolution.

Runtime probing also established a hard scope limit. In a multi-root workspace, both roots'
steering reached the parent and child context before a generated skill could select an execution
root. That happens in Kiro's own context assembly, upstream of anything a generator emits, so no
generated artifact can repair it. Full probe results are in `docs/kiro-preview-validation.md`.

## Decision

**Ship a generated clone/copy distribution under `dist/kiro/`.** It is committed, produced by
`tools/generate_kiro.py` from the same authoritative skill and agent sources the plugins use, and
installed by copying `skills/` and `agents/` into a `.kiro` directory. It is not plugin-installable
and no installer is provided. `manifest.json` records every source mapping, per-skill closure, and
file hash so the artifact is auditable and removable by exact path.

**Give each dev skill the smallest correct dependency closure, not the full set.** `shared_closure`
seeds from the shared file names a skill's source text mentions, then closes in both directions to a
fixpoint: a contract brings every helper it names, a helper brings the contract that governs it, and
a contract brings any contract it names. The reverse direction is load-bearing - `dev:status` names
`resolve_project_rules.py` and never names `project-bootstrap.md`, so a forward-only closure would
ship the resolver with no contract describing how to run it.

**Ship a subset of the dev plugin.** `feedback` and `release` act on the agent-toolkit repository
itself rather than an adopter's project, and `shadow` is unsupported in Kiro. All three are excluded
through `EXCLUDED_SKILL_SOURCES`. No shipped skill hands off to any of them, so the exclusion leaves
no dead pointer.

**Resolve name collisions through a committed explicit map.** `tools/kiro_names.json` maps every
emitted source directory to its Kiro name (`utils-retro`, `dev-retro`, `utils-retro-zh`). Names are
never derived implicitly, and the map must cover exactly the emitted set.

**Scope the preview to single-root Kiro IDE workspaces.** Kiro CLI, multi-root workspaces, and
explicit agent `resources:` are unsupported and must not be advertised. Generated skills carry that
limit in their `compatibility` field and preamble, and instruct the agent to stop if inactive-root
instructions, steering, or resources appear.

## Consequences

The generated tree is 1.1 MB across 70 files, down from 4.3 MB across 206. A change to a shared
helper now produces a diff proportional to the skills that actually use it: `github_pr.py` reaches 3
skills, `plugin_release.py` and `shadow_replay.py` reach none.

Duplication does not disappear, so copies can drift. Two generator checks fail closed on that:
every copy emitted at the same relative path under the shared closure roots must be byte-identical,
and every backticked `references/`, `scripts/`, or `assets/` path a generated skill cites must
resolve inside it. Both were added after a real drift defect - one skill's `tracker.md` copy had
been corrupted by an unanchored name rewrite - passed silently through generation and CI.

The closure is computed from file names that appear in the source. A dependency expressed only as
untraceable prose ("run the shared validator", with no file name anywhere) is invisible to it and
would surface as a missing file at Kiro runtime rather than at generation. The bidirectional step
covers the realistic cases, because such prose refers to helpers a governing contract already pulls
in, and `validate_skill_closure` asserts the governing-contract rule independently of the code that
computes the closure.

Skills excluded from the preview stay available on Claude Code and Codex. Excluding a skill that
another shipped skill hands off to would create a dead pointer, so the test suite asserts the
shipped set references none of the excluded names.

Multi-root support can be reconsidered only if a future Kiro release demonstrates parent and child
active-root isolation. Until then the constraint is documented, not worked around.

Sources: [Kiro skills](https://kiro.dev/docs/skills/),
[Agent Skills specification](https://agentskills.io/specification),
[Kiro custom agents](https://kiro.dev/docs/custom-agents/),
[Kiro steering](https://kiro.dev/docs/steering). Content was rephrased for compliance with
licensing restrictions.
