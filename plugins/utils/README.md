# utils

General-purpose utility skills for research, investigation, knowledge synthesis, session retrospectives, and security auditing.

**Invocation across harnesses:** the `/research` / `/utils:research` forms below are Claude
Code. On Codex invoke explicitly as `$research`; on Kiro as `/research`. `research` and `retro`
never fire implicitly (guarded per harness). The `回顧` skill keeps its CJK name on Claude Code
and Codex; the Kiro export renames it `retro-zh`. Install per harness: repo-root
[README](../../README.md).

## Skills

### /research

Structured research and report generation. Accepts any combination of:

- Topic description or research question
- URLs (blog posts, GitHub repos, documentation)
- Local files/folders (PDF, markdown, images, code)
- Output path (default: `./<topic-slug>-report.md`)

Produces a comprehensive markdown report with YAML frontmatter, inline citations, and full operational detail. Reports prioritize completeness of information over structural ceremony.

**Invoke with:** `/research` or `/utils:research`

#### Process

1. **Clarify Scope** - enters plan mode, asks only what's needed to begin
2. **Gather Material** - fetches URLs, reads local files, runs 3-5 web searches (fans out subagents for broad topics)
3. **Write Report** - linear-flow markdown with executive summary, content sections, sources table
4. **Present & Iterate** - reports coverage/gaps, revises in place until satisfied

### /llm-wiki

Build and maintain a persistent, compounding knowledge base as interlinked markdown files. Based on Karpathy's LLM Wiki pattern.

- Ingest sources (URLs, PDFs, pasted text) into a structured wiki
- Query the wiki with synthesis and citations
- Lint for orphan pages, broken links, stale content, contradictions

The wiki uses `[[wikilinks]]` (Obsidian-compatible), YAML frontmatter, and a three-layer architecture: raw sources, wiki pages, and a schema file.

**Invoke with:** `/llm-wiki` or `/utils:llm-wiki`

### /retro

Brutally honest retrospective on your working session. Analyzes conversation history, git activity, and file changes to identify habits, blind spots, and the single highest-impact improvement.

- Gathers evidence from conversation + `git log` + `git diff`
- Supports `/retro {commit-hash}` to review a specific commit's work session
- Refuses if insufficient material (short conversation, no commit hash)
- Every claim backed by specific evidence; inferences explicitly marked

**Invoke with:** `/retro` or `/review-my-work` (English) or `/回顧` (繁體中文)

### /security-scan

On-demand security audit of the current repository. Scans five categories:

- **Secrets/credentials** - API keys, tokens, passwords, .env files, private keys
- **Code vulnerabilities** - injection, XSS, deserialization, path traversal, weak crypto
- **Infrastructure misconfigs** - open CORS, permissive IAM, debug mode, exposed ports
- **Git history** - leaked secrets in past commits
- **Dependencies** - unpinned versions, known CVEs, typosquat risk

Supports depth modifiers: `quick`, `deep`, `secrets`, `vulns`.

**Invoke with:** `/security-scan` or `/sec-scan`

## Install

```bash
claude plugin install utils@agent-toolkit
```

### Disable Globally
```bash 
claude plugin disable utils@agent-toolkit
```

### Then enable per-project (from project root)
```bash
claude plugin enable -s local utils@agent-toolkit
```

### Typical update workflow
```bash
claude plugin marketplace update agent-toolkit 
claude plugin update -s local utils@agent-toolkit
```
