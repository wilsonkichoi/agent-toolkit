#!/usr/bin/env python3
"""Mechanical, idempotent export of the Claude-source plugin skills into a Kiro-native tree.

Run: `uv run tools/export_kiro.py` (stdlib only; plain `python3 tools/export_kiro.py` also works).

It regenerates `dist/kiro/skills/` from `plugins/*/skills/` applying exactly the transforms
documented in `.local/codex-research/07-implementation-plan.md` section 5.1:

  1. Copy every `plugins/*/skills/<skill>/` directory.
  2. Rename map (folder AND frontmatter `name:`, which the Kiro skills spec requires to match):
       - every `dev` skill  -> `dev-<name>`   (resolves the flat-namespace collision)
       - `回顧`             -> `retro-zh`      (spec-conformant ASCII name; its documented alias)
       - `utils` skills otherwise keep their names
  3. Bundle the tracker doc: copy `plugins/dev/docs/tracker.md` into every exported *dev* skill
     as `references/tracker.md`, and rewrite the skill's tracker references to point at it.
  4. Strip `agents/openai.yaml` (Codex-only metadata) from exported skills.
  5. Emit no generation header inside skill files (YAML frontmatter must be the first content);
     `dist/kiro/README.md` records that the tree is generated and how to regenerate it.

Plus one spec-conformance fix the reference validator forces (agentskills `validate` rejects
the Claude-only `argument-hint` frontmatter field): relocate `argument-hint` into the allowed
`metadata` field. Claude source is never touched.

The `dist/kiro/agents/*.md` files are hand-maintained (see plan 5.2); this script never touches
them. Only `dist/kiro/skills/` is wiped and regenerated.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"
OUT_SKILLS = REPO / "dist" / "kiro" / "skills"
TRACKER_SRC = PLUGINS / "dev" / "docs" / "tracker.md"


def target_name(plugin: str, skill: str) -> str:
    """Apply the transform-2 rename map."""
    if plugin == "dev":
        return f"dev-{skill}"
    if skill == "回顧":
        return "retro-zh"
    return skill


def rewrite_frontmatter_name(text: str, new_name: str) -> str:
    """Replace the first `name:` field inside the leading YAML frontmatter block."""
    if not text.startswith("---"):
        raise ValueError("SKILL.md does not start with YAML frontmatter")
    end = text.index("\n---", 3)
    head, body = text[:end], text[end:]
    head, n = re.subn(r"(?m)^name:[ \t]*.*$", f"name: {new_name}", head, count=1)
    if n != 1:
        raise ValueError("could not find a single `name:` field in frontmatter")
    return head + body


def relocate_argument_hint(text: str) -> str:
    """Spec-conformance: the agentskills/Kiro skill spec rejects the Claude-only
    `argument-hint` frontmatter field (only name/description/metadata/allowed-tools/
    license/compatibility are allowed). Move it under the allowed `metadata` field so the
    hint survives and the skill validates. Claude source is untouched; this runs on the
    export copy only."""
    end = text.index("\n---", 3)
    head, body = text[:end], text[end:]
    m = re.search(r"(?m)^argument-hint:[ \t]*(.*)$", head)
    if not m:
        return text
    value = m.group(1).strip()
    head = re.sub(r"(?m)^argument-hint:[ \t]*.*\n?", "", head, count=1).rstrip("\n")
    if re.search(r"(?m)^metadata:[ \t]*$", head):
        head = head + f"\n  argument-hint: {value}"
    else:
        head = head + f"\nmetadata:\n  argument-hint: {value}"
    return head + body


def bundle_tracker_refs(text: str) -> str:
    """Transform 3: point every tracker-doc reference at the bundled `references/tracker.md`
    and collapse the now-redundant Claude-specific locator clause in the Read-first line."""
    # Longest paths first so shorter substrings do not corrupt them.
    text = text.replace("${CLAUDE_PLUGIN_ROOT}/docs/tracker.md", "references/tracker.md")
    text = text.replace("../../docs/tracker.md", "references/tracker.md")
    text = text.replace("docs/tracker.md", "references/tracker.md")
    # Collapse the "— on Claude Code `references/tracker.md`, equivalently `references/tracker.md`
    # relative to this skill's directory" scaffolding (all wrapping variants) to a clean note.
    text = re.sub(
        r"\s*(?:—|\()\s*on Claude Code\b.*?this skill's directory\)?",
        " (bundled with this skill)",
        text,
        flags=re.DOTALL,
    )
    return text


def export_skill(plugin: str, src: Path, dest: Path, is_dev: bool) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)

    # Transform 4: strip Codex-only metadata.
    openai_yaml = dest / "agents" / "openai.yaml"
    if openai_yaml.exists():
        openai_yaml.unlink()
        agents_dir = dest / "agents"
        if agents_dir.is_dir() and not any(agents_dir.iterdir()):
            agents_dir.rmdir()

    skill_md = dest / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    # Transform 2: frontmatter name matches the (renamed) folder.
    text = rewrite_frontmatter_name(text, dest.name)

    # Spec-conformance: relocate the Claude-only `argument-hint` field into `metadata`.
    text = relocate_argument_hint(text)

    # Transform 3: only dev skills read the tracker doc.
    if is_dev:
        text = bundle_tracker_refs(text)
        refs = dest / "references"
        refs.mkdir(exist_ok=True)
        shutil.copy2(TRACKER_SRC, refs / "tracker.md")

    skill_md.write_text(text, encoding="utf-8")


def main() -> int:
    if not TRACKER_SRC.exists():
        print(f"error: tracker doc not found at {TRACKER_SRC}", file=sys.stderr)
        return 1

    if OUT_SKILLS.exists():
        shutil.rmtree(OUT_SKILLS)
    OUT_SKILLS.mkdir(parents=True)

    exported: list[tuple[str, str]] = []
    for plugin_dir in sorted(PLUGINS.iterdir()):
        skills_dir = plugin_dir / "skills"
        if not skills_dir.is_dir():
            continue
        plugin = plugin_dir.name
        for src in sorted(skills_dir.iterdir()):
            if not (src / "SKILL.md").exists():
                continue
            new_name = target_name(plugin, src.name)
            dest = OUT_SKILLS / new_name
            export_skill(plugin, src, dest, is_dev=(plugin == "dev"))
            exported.append((f"{plugin}/{src.name}", new_name))

    write_readme(exported)
    print(f"Exported {len(exported)} skills to {OUT_SKILLS.relative_to(REPO)}:")
    for source, name in exported:
        print(f"  {source:28s} -> {name}")
    return 0


def write_readme(exported: list[tuple[str, str]]) -> None:
    rows = "\n".join(f"| `{src}` | `{name}` |" for src, name in exported)
    readme = f"""# dist/kiro — generated Kiro export

**Do not edit files under `skills/` here by hand.** This tree is generated from the
Claude-source plugins by `tools/export_kiro.py`. Regenerate after any change to
`plugins/*/skills/` or `plugins/dev/docs/tracker.md`:

```
uv run tools/export_kiro.py
```

Transforms applied (see `.local/codex-research/07-implementation-plan.md` §5.1): skills are
copied and renamed (`dev` skills gain a `dev-` prefix, `回顧` becomes `retro-zh`), the tracker
doc is bundled into each `dev` skill as `references/tracker.md`, and Codex-only
`agents/openai.yaml` metadata is stripped.

The `agents/*.md` files in this tree are hand-maintained (not generated) and mirror
`plugins/dev/agents/*.md` for Kiro.

## Skill name map

| Source skill | Kiro skill |
|---|---|
{rows}

## Install (Kiro)

- Skills: import into project scope `.kiro/skills/` or global `~/.kiro/skills/`. See the repo
  root `README.md` Kiro section for the exact `npx skills add` / URL-import instructions.
- Agents: copy `agents/*.md` into `.kiro/agents/` (project) or `~/.kiro/agents/`.
"""
    (OUT_SKILLS.parent / "README.md").write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
