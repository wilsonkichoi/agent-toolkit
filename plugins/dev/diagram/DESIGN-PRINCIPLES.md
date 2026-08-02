# Design principles

## Inherited system: Modernist

Flat, architectural, near-mono red on white. No corner radius anywhere. Structure
is carried by alignment and strong 2px rules, not by shadows or decoration.

- **Zero radius.** Every box, button, chip and card is square-cornered.
- **Flush left.** Headings, copy, and button labels all start at the left padding
  edge — never centered. (The only exception is edge labels on the canvas, which
  are centered on their arrow because they are map annotation, not UI copy.)
- **2px rules divide, whitespace does not.** Header, drawer header and drawer
  section rules are 2px solid ink. Hairlines are for card borders only.
- **Accent used sparingly.** Red `#ec3013` marks focus rings, the active/hovered
  edge, selection outline, negative ("never does") callouts and subheads. It is
  not a background field anywhere in this diagram.
- **Monospace is semantic.** Skill ids, code snippets, numeric readouts and lane
  numbers are mono; prose is sans.

## Diagram principles

1. **One left-to-right spine.** The forward path reads as a single line at
   `y=560`: setup → discover → architect → plan → task tracker → execute →
   review-pr → verify → retro → rules_dir. Nothing interrupts it.
2. **Forward above, return below.** Loop and correction edges leave the spine and
   run in dedicated horizontal corridors *underneath* it, each at its own `y`, so
   no two return paths overlap. Only `dev:auto`, `review-pr fix` and `dev:status`
   sit above the spine — they are drivers/observers, not workflow steps.
3. **Lanes are containers, not swimlanes.** Four dashed regions (product,
   planning, execution, learning) group the spine into phases with a solid color
   header chip. Filtering by lane dims everything else instead of hiding it, so
   the reader never loses the shape of the whole map.
4. **Color encodes lane, nothing else.** Each lane owns one color, applied as a
   6px left bar on its cards, its region border and its region chip. Card
   surfaces stay white.
5. **Solid vs dashed is meaning, not style.** Solid = primary path or loop;
   dashed = optional. Dashed *card borders* mean "not a skill" (an aux node: a
   mode, an artifact, an external system).
6. **The card is a teaser, the drawer is the document.** Cards clamp to two title
   lines and four summary lines; the full what/when/how/why, human gates, never-does
   and sources live in the drawer, which scrolls independently.
7. **Every claim is traceable.** Rationale and never-does entries carry `sources`
   pointing at real repo paths. Do not add content without one.
8. **Progressive disclosure of labels.** With nothing hovered, primary and optional
   edge labels show and loop labels hide; hovering a node reveals its own labels in
   accent and dims the rest. The `edgeLabels` prop can force `all` or `minimal`.

## Decisions worth not re-litigating

- The task tracker is the handoff point: `dev:plan` and `dev:backlog` write into
  it; `dev:execute` pulls from it. No direct plan → execute edge.
- `rules_dir` is terminal — it has no outbound edge; the bootstrap that reads it
  is described in its drawer copy instead of drawn.
- `dev:status` has no outbound edges (read-only observer).
- `dev:backlog` → task tracker is drawn as a clean vertical riser, not a diagonal.
- `dev:feedback`, `dev:shadow` and `dev:release` are deliberately not on the map.
- `dev:review-pr <pr> fix` is drawn as its own box because it is a distinct
  invocation with distinct stop semantics, but clicking it opens `dev:review-pr`.
