# UI spec

All values below are what the source actually renders. Sizes are px unless noted.

## Tokens

Defined three times in `<helmet><style>`: `:root`, a `prefers-color-scheme: dark`
override, and explicit `[data-theme="light"]` / `[data-theme="dark"]` blocks (the
header's theme button cycles auto → light → dark by setting `data-theme`).

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| `--bg` | `#f3f2f2` | `#141313` | page + canvas ground |
| `--surface` | `#ffffff` | `#1e1c1b` | card and drawer fill |
| `--ink` | `#201e1d` | `#f0eeec` | primary text |
| `--muted` | `#6b6663` | `#a09a95` | secondary text, edge labels |
| `--rule` | `#201e1d` | `#f0eeec` | 2px structural rules |
| `--hair` | `rgba(32,30,29,.20)` | `rgba(240,238,236,.22)` | 1.5px borders |
| `--grid` | `rgba(32,30,29,.045)` | `rgba(240,238,236,.04)` | 40px grid lines |
| `--grid2` | `rgba(32,30,29,.085)` | `rgba(240,238,236,.075)` | 200px grid lines |
| `--edge` | `#57524e` | `#9a938d` | arrow stroke (idle) |
| `--accent` | `#ec3013` | `#ff4a2c` | focus, hover, selection |
| `--code-bg` | `#eceae7` | `#282523` | code chips, hover fill |
| `--neg-bg` | `rgba(236,48,19,.06)` | `rgba(255,74,44,.10)` | "never does" callout |
| `--scrim` | `rgba(32,30,29,.40)` | `rgba(8,8,8,.55)` | drawer scrim |

Lane colors (light / dark): `--lane-setup` `#2f6fb5`/`#5b9de0`, `--lane-product`
`#7a4fa8`/`#ad83da`, `--lane-planning` `#a97400`/`#d4a12b`, `--lane-execution`
`#ec3013`/`#ff4a2c`, `--lane-learning` `#12775e`/`#2aa787`, `--lane-observability`
`#0d7a95`/`#2ea9c6`, `--lane-standalone` `#6f6a65`/`#a09a95`.

Type: `--sans` = system UI stack, `--mono` = system mono stack. Radius: 0 everywhere.

## Type scale in use

| Where | Size / weight / tracking |
| --- | --- |
| Brand `dev` | mono 19 / 700 / -0.02em |
| Header subtitle | sans 12.5 / 400 / .02em |
| Header count, zoom %, buttons | mono 10–10.5 / uppercase / .10em |
| Card lane number | mono 9 / 700 / .10em, lane color |
| Card lane name | sans 8.5 / 700 / .13em / uppercase, muted |
| Card kind badge (aux) | mono 8 / 700 / .10em / uppercase, 1px hair border |
| Card title | mono 14.5 / 700 / -0.01em, 2-line clamp |
| Card summary | sans 11 / 1.45, muted, 4-line clamp |
| Edge label | sans 10 / 600 / 1.3, centered, `--bg` plate |
| Region chip | mono 10 / 700 + sans 11 / 600 uppercase, on lane color |
| Drawer title | mono 21 / 700 / -0.02em |
| Drawer section head | sans 10.5 / 700 / .14em / uppercase + 2px rule |
| Drawer body | sans 12–12.5 / 1.5–1.55, `text-wrap: pretty` |
| Drawer code block | mono 12.5 / 600 in `--code-bg`, 1.5px hair border |

## Canvas geometry

- Canvas `4700 × 1400`. Card `240 × 160`. Column pitch `460` starting at `x=120`.
- Rows: `y=180` (above: `dev:auto`, `dev:review-pr fix`, `dev:status`),
  `y=560` (spine, 10 nodes), `y=1040` (below: `dev:backlog`, `dev:merge-pr`).
- Background: two-level grid, 40px `--grid` over 200px `--grid2`.
- Regions (x, y, w, h): product `520,500,820,280`; planning `1440,500,820,760`;
  execution `2360,120,1280,1080`; learning `3740,500,820,280`. Fill is
  `color-mix(in oklab, <lane> 5%, transparent)`, border 1.5px dashed lane color,
  chip pinned at `-1.5px/-1.5px`.
- Return corridors (arrow `y`): `460` verify→fix, `500` plan→architect,
  `790` verify→execute, `870` review-pr→backlog, `950` verify→backlog,
  `1290` retro→backlog.

## Card

Wrapper: 1.5px `--hair` border on three sides (dashed for aux nodes), 6px solid
lane-color left bar, no radius, no shadow. Inner button fills it, `padding:
13px 15px 14px`, `gap: 6px`, column, flush left, `background: --surface`.

States: hover → `background: --code-bg` plus `0 0 0 1.5px var(--accent)` ring;
selected → `outline: 2px solid var(--accent)` at `outline-offset: 3px`;
filtered out → `opacity: .22`; focus-visible → 2px accent outline, offset 2.
`z-index`: 6 selected, 3 hovered, 2 default.

## Edges

Hand-authored cubic beziers in one `<svg width="2400" height="1080">` with
`overflow: visible` and `pointer-events: none`. Stroke `--edge` at 1.4px, 2.1px
in accent when either endpoint is hovered/selected; `optional` edges use
`stroke-dasharray: 7 5`. Arrowheads are filled triangles computed from the final
segment tangent (`L=11`, `W=4.4`). Opacity: `.9` idle, `1` highlighted, `.26`
dimmed by hover, `.10` filtered out.

Labels are absolutely positioned HTML (not SVG text) on a `--bg` plate, rotated
to the path tangent unless `|deg| > 30` (then flat); loop labels also get a 1px
hair border and a 150px max width. `LADJ` holds per-edge `[dx, dy, deg?]` nudges.

## Header

`flex: none`, `border-bottom: 2px solid var(--rule)`, `z-index: 8`. Row one:
brand + subtitle + count on the left, zoom stepper (30×28 buttons around a 46px
readout, inside a 1.5px hair box), Reset view and Theme buttons on the right.
Row two: lane filter chips — 1.5px hair border with a 5px lane-colored left edge,
mono number + label + count; active chip inverts to `--ink` ground / `--bg` text.

## Drawer

Desktop: right sheet, `480` wide, full height, `border-left: 2px solid var(--rule)`,
enters with `translateX(103%) → none` over `.34s cubic-bezier(.22,.72,.16,1)`,
shadow `0 0 44px rgba(0,0,0,.16)`. Under `780px`: bottom sheet at `82%` height,
`translateY(103%)`, 2px top rule. Scrim `--scrim` fades `.3s`.

Header block is fixed (lane swatch 10×10, lane number, lane name, kind badge,
title, lane note, 32×32 close button) above an independently scrolling body with
`overscroll-behavior: contain` and `padding: 16px 18px 40px`. Sections in order:
What it does · When to use it (bullets, then "Do NOT use when" negatives) · How
to use it (Claude Code / Codex code blocks with copy buttons, argument hint,
argument shapes) · Why this skill exists (why separate, sources, the trade-off) ·
Human gates · Never does · Sources. Footer strip: `← →` move between cards,
`esc` to close.

## Interaction

- **Pan** drag anywhere on the canvas (cursor `grab`/`grabbing`); **zoom** wheel
  or pinch, clamped `0.18–2.4`, anchored at the pointer; `Reset view` refits
  (`min(1.05, (w-64)/4700, (h-64)/1400)`, centered).
- **Click a card** → select, open drawer, center the node (reserving 480px for the
  drawer on desktop, using the top 44% on narrow), write `#<slug>` to the hash.
- **Keyboard**: `←/↑` and `→/↓` step between nodes in reading order (top-to-bottom,
  then left-to-right); `Esc` closes and returns focus to the triggering card; Tab
  is trapped inside the open drawer.
- **Close** via the ✕, `Esc`, or a click/tap on the canvas that moved < 6px.
- **Deep link**: `#dev-execute` style hashes select on load and on `hashchange`.
- Lane chips toggle (clicking the active lane returns to All lanes).

## Props (tweaks)

`theme` enum auto|light|dark (default light) · `edgeLabels` enum auto|all|minimal
(default auto) · `laneRegion` boolean (default true, off hides the four regions).

## Accessibility

Cards are real `<button>`s with `aria-haspopup="dialog"` and an `aria-label`
naming the node and its lane; the drawer is `role="dialog" aria-modal="true"`
labelled by `#dw-title`; filter chips carry `aria-pressed` inside a labelled
`role="group"`; every interactive element has a 2px accent `:focus-visible`
outline. Decorative marks are `aria-hidden`.
