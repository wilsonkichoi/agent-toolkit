---
name: research
description: >
  This skill should ONLY be used when the user explicitly invokes /research or
  /utils:research. Do NOT trigger on general research-related phrases like
  "research a topic", "investigate", "deep dive into", etc. Only activate on
  explicit slash command invocation.
---

# Research

Produce a comprehensive, well-organized research report. Prioritize completeness of information over structural ceremony. The output should read linearly top-to-bottom without requiring the reader to jump between sections.

## Inputs

All optional. If none provided, ask the user what they want researched.

- **Topic/question** - what to research
- **URLs** - sources to ingest
- **Local files/folders** - PDF, txt, md, images, code
- **Output path** - where to save (default: `./<topic-slug>-report.md`)

## Process

### 1. Clarify Scope

Enter plan mode. Ask only what's needed to begin:
- What specifically should the report cover?
- Anything explicitly out of scope?
- Output path confirmation

Skip questions answerable from provided context. If inputs are clear, proceed with 0-1 questions.

If `<topic-slug>-report.md` already exists at the output path, ask: update or replace?

Confirm scope, exit plan mode.

### 2. Gather Material

**URLs**: WebFetch first. If blocked/empty, fall back to Playwright (navigate, snapshot, extract). Record failures.

**Local files**: Read directly. PDFs use pages parameter for large files. Folders: scan and read relevant files.

**GitHub repos**: README + directory structure + key files (docs/, src/ entry points, configs).

**Web search**: 3-5 searches to fill gaps from provided sources. For broad topics, fan out subagents via workflow, one per research angle, 2-3 searches each in parallel.

Extract everything. Miss nothing. Operational details, gotchas, exact commands, edge cases, known bugs matter more than high-level summaries.

### 3. Write Report

**Output format:**

```yaml
---
topic: "<topic>"
date: YYYY-MM-DD
sources_count: N
---
```

**Structure:**

```markdown
# {Topic Title}

## Executive Summary
3-5 sentences. Core answer to the research question.

## {Content Sections}
Organize by logical topic flow. Reader should never need to scroll
back to understand what they're reading now.

## Sources
| # | Source | URL | Key Contribution |
|---|--------|-----|-----------------|
```

**Writing rules:**

- **Linear flow**: each section builds on previous. No forward references.
- **Organize for the reader**: group related information together. If a concept has setup steps, gotchas, and examples, keep them together rather than splitting across sections.
- **Extract fully**: include exact commands, code examples, configuration snippets, tables, specific values. Don't summarize away the details.
- **Operational detail over abstraction**: known bugs, version requirements, workarounds, scope limitations, error messages. These are what users actually need.
- **Scannable**: bullets, tables, short paragraphs. Bold key terms on first introduction.
- **Cite inline**: `[Source Name](url)` or `[N]` linking to Sources table.
- **No fabrication**: "Unknown" when information unavailable. Never invent details.
- **Mark inaccessible sources**: if a URL failed to fetch, note what it was and why in a brief section at the end.

### 4. Present & Iterate

After saving the report, tell the user:
- What was covered
- Notable gaps or inaccessible sources
- Suggested follow-up if relevant

Wait for feedback. Revise in place until user is satisfied.

## Constraints

- Cite sources for every factual claim
- "Unknown" always beats fabrication
- Never silently skip inaccessible resources
- Valid markdown (proper heading hierarchy, link syntax, valid YAML frontmatter)
