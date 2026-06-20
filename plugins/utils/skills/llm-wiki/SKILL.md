---
name: llm-wiki
description: >
  Build and maintain a persistent, compounding LLM-powered knowledge base as interlinked
  markdown files. Use this skill whenever the user mentions "wiki", "knowledge base",
  "ingest into wiki", "add to wiki", "what do I know about", "lint my wiki", "wiki health check",
  wants to build up structured knowledge over time, or references "LLM wiki" or "Karpathy wiki".
  Also trigger when the user has an existing wiki directory (raw/ + wiki/ structure) and asks
  questions that could be answered from it. Do NOT trigger for one-off research reports or
  general note-taking without the wiki pattern.
---

# LLM Wiki

Build and maintain a persistent, compounding knowledge base as interlinked markdown files.
Based on [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Unlike RAG (which rediscovers knowledge from scratch per query), the wiki compiles knowledge
once and keeps it current. Cross-references already exist. Contradictions are flagged.
Synthesis reflects everything ingested. The wiki gets richer with every source added and
every question asked.

**Division of labor:** You curate sources, direct analysis, ask questions. The LLM
summarizes, cross-references, files, and maintains consistency.

---

## Architecture

Three layers, all under a single root directory:

```
<wiki-root>/
├── SCHEMA.md              # Layer 3: conventions, domain config, tag taxonomy
├── index.md               # Content catalog with one-line summaries
├── log.md                 # Chronological action log (append-only)
├── raw/                   # Layer 1: immutable source material
│   ├── articles/
│   ├── papers/
│   ├── transcripts/
│   └── assets/            # Images, diagrams referenced by sources
├── entities/              # Layer 2: entity pages (people, orgs, products)
├── concepts/              # Layer 2: concept/topic pages
├── comparisons/           # Layer 2: side-by-side analyses
└── queries/               # Layer 2: filed query results worth keeping
```

**Layer 1 - Raw Sources:** Immutable. Read but never modify. Your source of truth.
**Layer 2 - The Wiki:** LLM-owned markdown files. Created, updated, cross-referenced.
**Layer 3 - The Schema:** `SCHEMA.md` defines structure, conventions, tag taxonomy.

---

## Wiki Location

Check for `WIKI_PATH` environment variable. If unset, ask the user where the wiki should live.
Default suggestion: `~/wiki`.

---

## Resuming an Existing Wiki

When the user has an existing wiki, orient yourself before doing anything:

1. Read `SCHEMA.md` to understand domain, conventions, tag taxonomy
2. Read `index.md` to learn what pages exist
3. Read last 20-30 entries of `log.md` to understand recent activity

Only after orientation should you ingest, query, or lint. Skipping this causes duplicates
and missed cross-references.

---

## Initializing a New Wiki

When the user asks to create or start a wiki:

1. Determine the wiki path (from `$WIKI_PATH`, or ask the user)
2. Ask what domain the wiki covers, be specific
3. Create the directory structure
4. Write `SCHEMA.md` customized to the domain (see template below)
5. Write initial `index.md` with sectioned header
6. Write initial `log.md` with creation entry
7. Confirm ready and suggest first sources to ingest

### SCHEMA.md Template

Adapt to user's domain:

```markdown
# Wiki Schema

## Domain
[What this wiki covers]

## Conventions
- File names: lowercase, hyphens, no spaces (e.g., `transformer-architecture.md`)
- Every wiki page starts with YAML frontmatter
- Use `[[wikilinks]]` for internal links (minimum 2 outbound links per page)
- When updating a page, bump the `updated` date
- Every new page must be added to `index.md`
- Every action must be appended to `log.md`

## Frontmatter

---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query | summary
tags: [from taxonomy below]
sources: [raw/articles/source-name.md]
---

## Tag Taxonomy
[Define 10-20 top-level tags for the domain. Add new tags here BEFORE using them.]

## Page Thresholds
- Create a page when an entity/concept appears in 2+ sources OR is central to one source
- Add to existing page when a source mentions something already covered
- Don't create a page for passing mentions or minor details outside the domain
- Split a page when it exceeds ~200 lines

## Update Policy
When new information conflicts with existing content:
1. Check dates, newer sources generally supersede older ones
2. If genuinely contradictory, note both positions with dates and sources
3. Flag for user review in lint report
```

### index.md Template

```markdown
# Wiki Index

> Content catalog. Every wiki page listed under its type with a one-line summary.
> Last updated: YYYY-MM-DD | Total pages: N

## Entities

## Concepts

## Comparisons

## Queries
```

### log.md Template

```markdown
# Wiki Log

> Chronological record of all wiki actions. Append-only.
> Format: `## [YYYY-MM-DD] action | subject`
> Actions: ingest, update, query, lint, create, archive

## [YYYY-MM-DD] create | Wiki initialized
- Domain: [domain]
- Structure created
```

---

## Core Operations

### 1. Ingest

When the user provides a source (URL, file, paste), integrate it into the wiki:

**Step 1: Capture the raw source**
- URL: fetch content, save to `raw/articles/` as markdown
- PDF: extract text, save to `raw/papers/`
- Pasted text: save to appropriate `raw/` subdirectory
- Name descriptively: `raw/articles/karpathy-llm-wiki-2026.md`
- Add metadata header: source URL, date collected, date published

**Step 2: Discuss takeaways with the user**
What's interesting? What matters for the domain? Skip in batch/automated contexts.

**Step 3: Check what already exists**
Search `index.md` and wiki pages for mentioned entities/concepts.
This prevents duplicates.

**Step 4: Write or update wiki pages**
- New entities/concepts: create pages per Page Thresholds in SCHEMA.md
- Existing pages: add new information, update facts, bump `updated` date
- Cross-reference: every page links to at least 2 others via `[[wikilinks]]`
- Tags: only use tags from taxonomy in SCHEMA.md
- Handle contradictions explicitly: note both claims, flag for review

**Step 5: Update navigation**
- Add new pages to `index.md` under correct section
- Update page count and date in index header
- Append to `log.md`: `## [YYYY-MM-DD] ingest | Source Title`
- List every file created or updated in the log entry

**Step 6: Report what changed**
List every file created or updated.

A single source typically touches 5-15 wiki pages. This is the compounding effect.

### 2. Query

When the user asks a question about the wiki's domain:

1. Read `index.md` to identify relevant pages
2. For large wikis (100+ pages), also search across `.md` files for key terms
3. Read relevant pages
4. Synthesize an answer citing wiki pages: "Based on [[page-a]] and [[page-b]]..."
5. File valuable answers back: if the answer is a substantial synthesis, comparison, or
   novel connection, create a page in `queries/` or `comparisons/`. Don't file trivial lookups.
6. Update `log.md` with the query and whether it was filed

### 3. Lint

When the user asks to lint, health-check, or audit the wiki:

**Checks to run:**

1. **Orphan pages** - pages with no inbound `[[wikilinks]]` from other pages
2. **Broken wikilinks** - `[[links]]` pointing to pages that don't exist
3. **Index completeness** - every wiki page should appear in `index.md`
4. **Frontmatter validation** - required fields present, tags in taxonomy
5. **Stale content** - pages not updated despite newer sources on the same topic
6. **Contradictions** - pages on the same topic with conflicting claims
7. **Page size** - flag pages over 200 lines as candidates for splitting
8. **Tag audit** - flag tags not in SCHEMA.md taxonomy
9. **Missing pages** - concepts frequently mentioned but lacking dedicated pages
10. **Log rotation** - if `log.md` exceeds 500 entries, rotate to `log-YYYY.md`

**Report findings** grouped by severity:
broken links > orphans > stale content > contradictions > style issues

Append to `log.md`: `## [YYYY-MM-DD] lint | N issues found`

---

## Conventions

- All internal links use `[[wikilinks]]` syntax (Obsidian-compatible)
- Standard markdown otherwise
- YAML frontmatter on every wiki page
- `raw/` is immutable, never modify source files
- Always orient before operating (read SCHEMA + index + recent log)
- Don't create pages for passing mentions
- Keep pages scannable, split at ~200 lines
- Ask before mass-updating if an ingest would touch 10+ existing pages
- Rotate log at 500 entries

---

## Tips

- The wiki directory works as an Obsidian vault out of the box: `[[wikilinks]]` render
  as clickable links, graph view visualizes the knowledge network, YAML frontmatter
  powers Dataview queries
- The wiki is just a git repo of markdown files. Version history, branching, and
  collaboration for free.
- Good query answers should be filed back into the wiki. Explorations compound in
  the knowledge base just like ingested sources.
- Periodically lint to keep the wiki healthy as it grows.
