# Dev Workflow Map — design handoff

Interactive workflow diagram for the `dev` AI development-lifecycle plugin.
Read this file first; it explains what each file is for and how to move the design
between Claude Code and Claude Design without losing work.

## What is authoritative

| Thing | Source of truth |
| --- | --- |
| The design itself (markup, styles, logic, arrow geometry) | `src/dev-plugin-diagram.dc.html` |
| Node/edge/lane **content** — summaries, rationale, labels, positions | `data/diagram.json` |
| Upstream skill facts (all 15 skills, provenance) | `plugins/dev/skills/*/SKILL.md` → `data/skills.upstream.json` |
| Shipped artifact | `dev-plugin-diagram.html` (standalone, offline, ~1.1 MB — generated, never hand-edit) |
| Static image | `dev-plugin-diagram.png` (generated) |

Two edit surfaces, one build:

- **Wording, a new bullet, an edge label, moving a card** → edit `data/diagram.json`,
  run `node build.mjs --sync`. No HTML involved.
- **Anything visual or behavioural** — layout, type, color, arrow geometry,
  interactions → edit `src/dev-plugin-diagram.dc.html`.

The `.dc.html` carries an inlined copy of the JSON as `const DATA = {…};`. That
copy is generated: `--sync` writes JSON → source, `--extract` writes source →
JSON (use it after editing content in Claude Design), and a plain `node build.mjs`
refuses to run if the two disagree rather than guessing which one you meant.

When a `SKILL.md` changes upstream, port the affected wording into
`data/diagram.json` and re-sync. The map deliberately shows 12 of the 15 skills
with its own lanes and layout, so there is no automatic path from the upstream
extraction into this file — the curation is the point.

## The round trip

**Recommended repo layout** — keep the bundle as one self-contained directory
rather than flattening it into `docs/workflow/`, so its `CLAUDE.md` scopes to
the diagram and not to every doc in the folder.

```
docs/workflow/
  skills.json                       <- upstream data DATA is derived from
  diagram/
    CLAUDE.md                       <- rules for Claude Code (scoped to this dir)
    README.md                       <- this file
    DESIGN-PRINCIPLES.md
    UI-SPEC.md
    DATA-MODEL.md
    build.mjs                       <- sync + validate + standalone build
    data/diagram.json               <- content: edit this for wording
    src/dev-plugin-diagram.dc.html  <- the design source (edit this for visuals)
    src/support.js                  <- runtime that renders the source (do not edit)
    vendor/react*.min.js            <- pinned React 18.3.1 UMD, for offline builds
    dev-plugin-diagram.html         <- generated standalone build
    dev-plugin-diagram.png          <- generated image
```

**Editing in Claude Code.** Open `src/dev-plugin-diagram.dc.html` in a browser
(it runs directly from the filesystem next to `support.js`) and edit with the
file open — reload to see changes. Content changes (a new skill summary, a
reworded edge label) are pure `DATA` edits. Structural changes (a new node, a
rerouted arrow) touch `DATA.positions`, `DATA.edges` and `ROUTES` — see
`DATA-MODEL.md` for the exact recipes.

**Bringing it back to Claude Design.** Upload / attach `src/dev-plugin-diagram.dc.html`
(plus this folder for context). It is a Design Component and opens natively in the
design tool with the visual editor, tweaks panel and live preview intact — no
conversion, no re-import. Because the file keeps the same structure that left the
design tool, edits made in Claude Code survive the trip back.

**What breaks the round trip** (see `CLAUDE.md` for the full list): moving styles
out to a CSS file or class names, rewriting the template as JSX/React, splitting
the file into modules, or reformatting the whole file so diffs become unreadable.

## Regenerating the outputs

```sh
node build.mjs --sync     # JSON -> source, validate, write dev-plugin-diagram.html
                          #   (--import is an alias for this)
node build.mjs            # validate + build (fails if JSON and source disagree)
node build.mjs --extract  # source -> JSON, validate, build (after a Claude Design edit)
                          #   (--export is an alias for this)
node build.mjs --check    # validate only, write nothing (good as a CI/pre-commit step)
```

So the minor-wording loop is: edit `data/diagram.json` → `node build.mjs --sync`
→ commit the JSON, the source and the rebuilt HTML.

Node 18+, zero dependencies, no network. Run it from this directory after any
edit to `src/dev-plugin-diagram.dc.html`.

**Why the JSON is inlined rather than fetched.** Not a platform limitation — the
component format supports runtime imports fine. Three practical reasons:
a `fetch('../data/diagram.json')` is blocked by CORS when the page is opened as a
`file://` URL (the main way this diagram gets viewed); the standalone artifact
has to be one file with no siblings; and Claude Design's visual editor can only
edit content that is present in the source it opens. A build-time inline keeps
all three. `--sync` costs one command and buys a JSON edit surface with none of
the downsides.

**How the build works.** `src/dev-plugin-diagram.dc.html` is already the whole
design; it just resolves three things at runtime — React and ReactDOM from
unpkg, `./support.js` from disk, and a re-fetch of its own URL to hot-reload the
template. `build.mjs` inlines vendored React + ReactDOM + `support.js` ahead of
the document and sets `window.__resources = {}`, which switches both network
paths off (`support.js` skips the CDN when `window.React` already exists). The
output is a single ~330 KB file that opens from disk with no server and no
internet. Nothing is minified, compressed or transformed, so the DATA and the
template stay greppable in the build output.

**What the check catches** (it runs before every build and exits non-zero):
nodes missing a `DATA.positions` entry, positions with no node, edges whose
endpoints don't exist, unknown edge `kind`, lanes with no `--lane-*` color token,
and — the important one — **edges with no matching `ROUTES` entry**, which
otherwise vanish from the diagram silently, and dead `ROUTES` with no edge.

**PNG** — screenshot the built standalone at the default fitted view, light
theme. Optional one-liner if you have Playwright available:
`npx playwright screenshot --viewport-size=2400,1350 dev-plugin-diagram.html dev-plugin-diagram.png`.

The older `.zip` bundle and the previous `.html`/`.png` are superseded — delete
them and regenerate from source; git history keeps the old copies.

## Fidelity

High fidelity. Colors, type, spacing, geometry and interactions in the source are
final and intentional. `UI-SPEC.md` documents them so a change can be judged
against intent rather than guessed at.
