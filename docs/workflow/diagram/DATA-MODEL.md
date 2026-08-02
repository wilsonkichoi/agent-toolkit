# Data model and change recipes

`DATA` is authored in **`data/diagram.json`** and inlined into the
`<script data-dc-script>` block of `src/dev-plugin-diagram.dc.html` by
`node build.mjs --sync`. Edit the JSON; the `const DATA = {…};` line in the
source is generated. Everything else below — `CW`/`CH`/`CVW`/`CVH`, `ROUTES`,
`REGIONS`, `LADJ` and the logic class — is hand-authored in the `.dc.html`,
because it is design work rather than content.

So a change to a node's wording is a JSON edit; a change to how its arrow curves
is a source edit; adding a node is both.

## `DATA`

```
DATA.lanes[]        { id, display, order, note }
DATA.skills[]       { id, lane, summary, what_it_does,
                      when_to_use: { triggers[], do_not_use_when[] },
                      how_to_use:  { claude_code, codex, argument_hint?,
                                     argument_shapes[]: { shape, meaning } },
                      rationale:   { why_separate, why_separate_sources[],
                                     trade_off, trade_off_sources[] },
                      human_gates[], never_does[], sources[] }
DATA.aux_nodes[]    { id, kind, of?, lane, label, summary, note?, sources[] }
DATA.edges[]        { from, to, kind: "primary"|"loop"|"optional", label }
DATA.positions      { "<node id>": { x, y } }   // top-left of the card
DATA.layout_notes   prose record of the layout intent
```

`aux_nodes` are the non-skill boxes: `kind: "mode"` (`dev:review-pr fix`),
`kind: "artifact"` (`rules_dir`), `kind: "system"` (`task_tracker`). They render
with a dashed border and a kind badge, and their drawer shows only summary,
note and sources — except `dev:review-pr fix`, which is special-cased in
`detail()` to borrow `dev:review-pr`'s full content.

Backticks inside any string render as inline code: `runs()` splits on `\`` and
alternates mono/prose. This is the only markup allowed in content.

The content originates in `plugins/dev/skills/*/SKILL.md`, `plugins/dev/README.md`,
`plugins/dev/runtime_contracts/*.md` and `docs/adr/`. The map deliberately shows
12 of the 15 skills — `dev:feedback`, `dev:shadow` and `dev:release` are omitted.
When an upstream `SKILL.md` changes, port the affected fields into
`data/diagram.json` and run `node build.mjs --sync`.

## Layout constants

```js
const CW = 240, CH = 160, CVW = 4700, CVH = 1400;
```

`REGIONS` = the four dashed lane containers `{ lane, x, y, w, h }`.
`LADJ` = per-edge label nudges keyed `"from|to"` → `[dx, dy]` or `[dx, dy, deg]`.

## `ROUTES` — arrow geometry

Keyed `"<from>|<to>"`, exactly matching a `DATA.edges` pair. Value is
`[startPoint, segments]` where each segment is
`[c1x, c1y, c2x, c2y, endX, endY]` — a chain of cubic beziers:

```js
"dev:plan|task_tracker": [[1740,640],[[1820,640,1880,640,1960,640]]],
```

Anchor points are card edge midpoints: with a card at `(x, y)` the right edge
midpoint is `(x+240, y+80)`, left `(x, y+80)`, top `(x+120, y)`, bottom
`(x+120, y+160)`. Spine cards sit at `y=560`, so their horizontal anchors are at
`y=640`. A missing `ROUTES` entry drops the edge silently — the `.filter(Boolean)`
in `renderVals()` skips it. `node build.mjs --check` catches exactly this.

Straight horizontal or vertical runs: put both control points on the same axis
value as the endpoints. Corners: give each leg its own segment and let the
control points overshoot into the corner (see `dev:retro|dev:backlog`).

## Recipes

**Reword a label or summary** — edit `DATA` only. Nothing else moves.

**Add a skill node**
1. Append to `DATA.skills` with a `lane` that exists in `DATA.lanes`.
2. Add `DATA.positions["dev:x"]`. Keep the 460 pitch: spine `y=560`, above
   `y=180`, below `y=1040`. If it extends the spine past `x=4260`, raise `CVW`.
3. Add its `DATA.edges` entries and a `ROUTES` entry for each.
4. If it belongs inside a lane region, widen that `REGIONS` rect.
5. Check the header count line and re-fit.

**Add an edge**
1. Append `{ from, to, kind, label }` to `DATA.edges`.
2. Add the matching `ROUTES` route. Return edges go *below* the spine — pick a
   free corridor `y` (used: 790, 870, 950, 1290) or open a new one; never share
   a corridor with another edge over the same `x` range.
3. If the label collides, nudge it in `LADJ` rather than moving the path.

**Add a lane**
1. Append to `DATA.lanes` with the next `order`.
2. Add `--lane-<id>` to all four token blocks (`:root`, the dark media query, and
   both `[data-theme]` blocks). Filter chips and card bars pick it up automatically.
3. Optionally add a `REGIONS` rect.

**Remove a node** — delete it from `DATA.skills`/`aux_nodes`, its
`DATA.positions` entry, every `DATA.edges` entry naming it, and every `ROUTES`
key containing it. Leftover routes are harmless but rot; leftover edges without a
route disappear without warning, which hides the mistake.

## Rendering pipeline (why edits land where they do)

`renderVals()` is the single seam between data and template. It builds `cards`
(one per skill + aux node, positioned from `DATA.positions`), `edges` (path +
arrowhead + stroke tokens from `ROUTES`), `labels` (positioned from the path
midpoint plus `LADJ`), `filters`, `regions`, and `d` (the drawer detail assembled
by `detail()`). The template only reads named values — if something is not
rendering, it is missing from `renderVals()`, not from the markup.
