# Kiro preview installation

This generated artifact supports **single-root Kiro IDE workspaces only**. Kiro CLI, multi-root
active-folder isolation, and explicit agent resources are not supported. All utility skills, the
named dev agents, the human-gated manual lifecycle, and bounded `dev:auto` have passed fresh
single-root IDE runtime probes; what was run, on which Kiro build, and with what outcome is
recorded in this repository's `docs/kiro-preview-validation.md`.

This is a subset of the dev plugin, not a mirror of it. `dev:feedback` and `dev:release` act on the
agent-toolkit repository itself rather than your project, and `dev:shadow` is unsupported in Kiro,
so none of the three is generated here. Use Claude Code or Codex for those. Each generated skill
bundles only the shared contracts and helpers it actually needs; `manifest.json` records that set
per skill.

Kiro owns permission and trust decisions; this distribution does not install or modify those
settings. Start in a disposable or trusted project and approve only expected operations. Lifecycle
skills can create files, commits, branches, worktrees, tracker updates, and merges after their
documented gates. A denied operation or unavailable required named agent is a safe stop: do not
retry with another tool, substitute inline work, or bypass the denial.

Kiro is not installed through either plugin marketplace. There is no Kiro marketplace manifest,
Power, or installer; the supported distribution is this generated clone/copy artifact.

## Clone and copy

Clone this repository, then set `SOURCE` to this generated directory and `TARGET` to either the
current project's `.kiro` directory or the user-level Kiro directory:

```bash
git clone https://github.com/wilsonkichoi/agent-toolkit.git /tmp/agent-toolkit
SOURCE=/tmp/agent-toolkit/dist/kiro
TARGET="$PWD/.kiro" # workspace install; use "$HOME/.kiro" for a global install
mkdir -p "$TARGET/skills" "$TARGET/agents"
ditto "$SOURCE/skills" "$TARGET/skills"
ditto "$SOURCE/agents" "$TARGET/agents"
```

Open a fresh Kiro window after copying. Workspace skills and agents take precedence over global
artifacts with the same generated name. Kiro's local-folder importer may also import one
`$SOURCE/skills/<name>` directory at a time. Repository-root bulk import and `npx skills add` are
unsupported because they are not proven for this generated layout.

## Update

Pull the clone and repeat the two `ditto` commands. They replace only same-named generated files
and preserve unrelated Kiro artifacts.

## Remove exactly this generated set

Set `TARGET` to the workspace or user-level `.kiro` directory used during installation, then remove
only these manifest-owned paths:

```bash
rm -rf \
  "$TARGET/skills/dev-architect" \
  "$TARGET/skills/dev-auto" \
  "$TARGET/skills/dev-backlog" \
  "$TARGET/skills/dev-discover" \
  "$TARGET/skills/dev-execute" \
  "$TARGET/skills/dev-merge-pr" \
  "$TARGET/skills/dev-plan" \
  "$TARGET/skills/dev-retro" \
  "$TARGET/skills/dev-review-pr" \
  "$TARGET/skills/dev-setup" \
  "$TARGET/skills/dev-status" \
  "$TARGET/skills/dev-verify" \
  "$TARGET/skills/utils-llm-wiki" \
  "$TARGET/skills/utils-research" \
  "$TARGET/skills/utils-retro" \
  "$TARGET/skills/utils-security-scan" \
  "$TARGET/skills/utils-retro-zh"
rm -f \
  "$TARGET/agents/dev-reviewer.md" \
  "$TARGET/agents/dev-test-writer.md" \
  "$TARGET/agents/dev-verifier.md"
```

Do not delete the whole `.kiro` directory when it contains unrelated settings, hooks, steering,
skills, or agents. `manifest.json` records every generated source mapping and file hash.
