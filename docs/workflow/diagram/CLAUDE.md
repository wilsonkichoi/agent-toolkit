# Dev Workflow Map — working rules

You are editing an interactive diagram that was designed in Claude Design and is
meant to travel back there. Read `README.md`, `DESIGN-PRINCIPLES.md`,
`UI-SPEC.md` and `DATA-MODEL.md` in this folder before changing anything.

## Which file to edit

- **Content** — any wording, summary, rationale, edge label, lane note, or a card
  position: edit `data/diagram.json`, then run `node build.mjs --sync`. Never
  hand-edit the `const DATA = {…};` line in the `.dc.html` — it is generated from
  that JSON, and a hand edit will collide with the next sync. (If it already
  happened, `node build.mjs --extract` rescues it back into the JSON.)
- **Everything else** — markup, inline styles, tokens, arrow geometry (`ROUTES`,
  `REGIONS`, `LADJ`), the logic class: edit `src/dev-plugin-diagram.dc.html`.

## The design source

`src/dev-plugin-diagram.dc.html`. It has three parts:

1. `<helmet><style>` — CSS custom properties (the theme) and `@keyframes` only.
2. The template between `<x-dc>` and `</x-dc>` — markup with `{{ value }}` holes,
   `<sc-for>` / `<sc-if>` control flow, and **inline** `style="…"` attributes.
3. `<script type="text/x-dc" data-dc-script>` — `const DATA = {…}`, layout
   constants (`CW`, `CH`, `CVW`, `CVH`), `ROUTES`, `REGIONS`, `LADJ`, bezier
   helpers, and `class Component extends DCLogic` whose `renderVals()` returns
   every value the template reads.

`support.js` is the runtime. Never edit it, never inline it, never replace it.

## Hard rules

- **Keep the file a single self-contained Design Component.** No module splitting,
  no external CSS or JS, no npm, nothing fetched at runtime. (The format does
  allow runtime imports; this artifact forbids them because it must open as a
  `file://` URL, ship as one file, and stay editable in Claude Design. Data gets
  in at build time via `--sync` instead.)
- **Inline styles only.** No CSS classes, no stylesheet rules beyond the token
  block and keyframes already in `<helmet>`. Colors come from `var(--…)` tokens.
- **No JSX, no React rewrite, no TypeScript.** The template is HTML with dotted
  holes; the logic class is plain classic JS. Never put an expression inside
  `{{ }}` (`{{ a + b }}`, `{{ !x }}`, `{{ fn() }}` all fail silently) — compute in
  `renderVals()` and expose the result by name.
- **Do not build UI with `React.createElement`.** Anything created that way is
  invisible to the visual editor when the file goes back to Claude Design.
- **Never hand-edit `dev-plugin-diagram.html`** (generated) or `.png`.
- **Do not reformat, reorder or prettify** parts of the file you were not asked to
  change. Targeted diffs only — this is what keeps the round trip reviewable.
- **Do not invent colors or fonts.** Add a token to both `[data-theme="light"]`
  and `[data-theme="dark"]` (and the `prefers-color-scheme` block) or reuse one.
- **Arrow geometry is hand-authored.** Edit the `ROUTES` control points; never
  auto-route, never introduce a graph-layout library.
- Every `<sc-for>` needs `hint-placeholder-count`, every `<sc-if>` needs
  `hint-placeholder-val` — they are what paints while data is still streaming.

## Checklist before you commit

1. `node build.mjs --sync` passes (it pushes the JSON into the source, validates,
   then writes
   `dev-plugin-diagram.html`). It fails loudly on the mistake that is otherwise
   invisible: a `DATA.edges` entry with no matching `ROUTES` key, which drops the
   arrow silently.
2. Open `src/dev-plugin-diagram.dc.html` in a browser; console is clean.
3. Header count line reads the right `N skills · N lanes · N edges`.
4. Arrows land on card edges, cross no card, and labels do not collide — the
   build cannot check this, only your eyes can.
5. Lane filter chips, click-a-card drawer, `←`/`→` stepping, `Esc`, hash deep
   links (`#dev-execute`), pan, zoom and both themes all still work.
6. Commit the regenerated `dev-plugin-diagram.html` (and the PNG if the change
   is user-visible) alongside the source edit.

Never hand-write the standalone: `build.mjs` is the only way it is produced, and
`vendor/` + `src/support.js` are inputs to it, not things to edit.

## Which rules are real

Worth knowing the difference before you propose changing one:

- **`support.js` is untouchable** — hard. It is generated (`// GENERATED from
  dc-runtime/src/*.ts — do not edit`) and Claude Design overwrites it with its
  own copy on every round trip. Any local edit is silently lost, and a divergent
  copy breaks rendering there. Treat it as a vendored binary.
- **Inline styles, no CSS classes; no JSX; template holes are dotted paths** —
  hard. These are how the component format works, not preferences.
- **Nothing fetched at runtime** — a project decision, for the three reasons in
  `README.md`. Revisit it only if the diagram stops needing to open from disk.
- **One file, no build step for the source** — project decision. `build.mjs`
  produces the *artifact*; the source itself must still run with no build.

The JSON data file is consumed at **build time**, so it bends none of these: the
shipped page fetches nothing and `support.js` stays byte-identical.
