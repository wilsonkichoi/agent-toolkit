#!/usr/bin/env node
// Build the standalone, fully offline diagram from the Design Component source.
//
//   node build.mjs                 -> validate + build dev-plugin-diagram.html
//   node build.mjs --sync          -> data/diagram.json -> the source's DATA, then build
//                                     (--import is an alias)
//   node build.mjs --extract       -> the source's DATA -> data/diagram.json, then build
//                                     (--export is an alias)
//   node build.mjs --check         -> validate only, write nothing
//   node build.mjs --out other.html --src src/other.dc.html
//
// Content (wording, summaries, edge labels, positions) lives in
// data/diagram.json. The .dc.html carries an inlined copy of it as
// `const DATA = {...};` because the design must stay self-contained — it opens
// straight from disk and round-trips to Claude Design with no fetch. --sync and
// --extract keep the two in step; a plain build refuses to run if they disagree.
//
// Zero dependencies, no network. Node 18+.
//
// What it does: the .dc.html source loads React and the dc-runtime at runtime
// (support.js pulls React from unpkg unless window.React already exists, and
// re-fetches its own URL to hot-reload the template unless window.__resources
// is set). This script inlines vendored React + ReactDOM + support.js ahead of
// the document and sets window.__resources = {}, which turns both of those
// network paths off. The result is one file that opens from disk with no server
// and no internet.

import { readFile, writeFile, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = args.indexOf('--' + name);
  return i === -1 ? fallback : args[i + 1];
};
const SRC = resolve(HERE, flag('src', 'src/dev-plugin-diagram.dc.html'));
const OUT = resolve(HERE, flag('out', 'dev-plugin-diagram.html'));
const DATA_FILE = resolve(HERE, flag('data', 'data/diagram.json'));
const TITLE = flag('title', 'dev — workflow map');
const CHECK_ONLY = args.includes('--check');
const SYNC = args.includes('--sync') || args.includes('--import');
const EXTRACT = args.includes('--extract') || args.includes('--export');
if (SYNC && EXTRACT) {
  console.error('✕ --sync/--import and --extract/--export are opposite directions; pick one');
  process.exit(1);
}

const DATA_RE = /const DATA = (\{[\s\S]*?\});\n/;
const canonical = (obj) => JSON.stringify(obj);
const readDataBlock = (src) => {
  const m = src.match(DATA_RE);
  if (!m) throw new Error('could not find "const DATA = {...};" in ' + SRC);
  return JSON.parse(m[1]);
};

const read = (p) => readFile(resolve(HERE, p), 'utf8');
const escapeScript = (code) => code.split('</script').join('<\\/script');
const inlineTag = (label, code) =>
  `<script data-inlined="${label}">\n${escapeScript(code)}\n</script>`;

async function newer(a, bPath) {
  try { return (await stat(a)).mtimeMs > (await stat(bPath)).mtimeMs; } catch { return false; }
}

// ---------------------------------------------------------------- validation
function validate(dc) {
  const problems = [];
  const dataMatch = dc.match(/const DATA = (\{[\s\S]*?\});\n/);
  if (!dataMatch) return ['could not find "const DATA = {...};" in the source'];

  let DATA;
  try { DATA = JSON.parse(dataMatch[1]); }
  catch (err) { return ['DATA is not valid JSON: ' + err.message]; }

  const routeKeys = new Set(
    [...dc.matchAll(/^\s*"([^"]+\|[^"]+)":\s*\[\[/gm)].map((m) => m[1])
  );
  const nodes = [...DATA.skills, ...DATA.aux_nodes];
  const ids = new Set(nodes.map((n) => n.id));
  const laneIds = new Set(DATA.lanes.map((l) => l.id));

  for (const n of nodes) {
    if (!DATA.positions[n.id]) problems.push(`node "${n.id}" has no DATA.positions entry`);
    if (!laneIds.has(n.lane)) problems.push(`node "${n.id}" is in unknown lane "${n.lane}"`);
  }
  for (const id of Object.keys(DATA.positions)) {
    if (!ids.has(id)) problems.push(`DATA.positions has "${id}" but no such node exists`);
  }
  for (const e of DATA.edges) {
    const key = e.from + '|' + e.to;
    if (!ids.has(e.from)) problems.push(`edge "${key}" starts at unknown node "${e.from}"`);
    if (!ids.has(e.to)) problems.push(`edge "${key}" ends at unknown node "${e.to}"`);
    // A missing route makes the arrow vanish silently at runtime.
    if (!routeKeys.has(key)) problems.push(`edge "${key}" has no ROUTES entry — it will not render`);
    if (!['primary', 'loop', 'optional'].includes(e.kind)) {
      problems.push(`edge "${key}" has unknown kind "${e.kind}"`);
    }
  }
  const edgeKeys = new Set(DATA.edges.map((e) => e.from + '|' + e.to));
  for (const key of routeKeys) {
    if (!edgeKeys.has(key)) problems.push(`ROUTES has "${key}" but no matching DATA.edges entry (dead route)`);
  }
  for (const lane of laneIds) {
    if (!dc.includes('--lane-' + lane + ':')) problems.push(`lane "${lane}" has no --lane-${lane} color token`);
  }

  console.log(
    `  ${DATA.skills.length} skills · ${DATA.aux_nodes.length} aux nodes · ` +
    `${DATA.lanes.length} lanes · ${DATA.edges.length} edges · ${routeKeys.size} routes`
  );
  return problems;
}

// ------------------------------------------------------------- data <-> source
let dc = await read(SRC);
const rel = (p) => p.replace(HERE + '/', '');

let json = null;
try { json = JSON.parse(await readFile(DATA_FILE, 'utf8')); }
catch (err) {
  if (err.code !== 'ENOENT') { console.error('✕ ' + rel(DATA_FILE) + ' is not valid JSON: ' + err.message); process.exit(1); }
}

if (json) {
  const inSource = readDataBlock(dc);
  const same = canonical(json) === canonical(inSource);

  if (EXTRACT) {
    if (same) console.log('  = the source already matches ' + rel(DATA_FILE));
    else {
      await writeFile(DATA_FILE, JSON.stringify(inSource, null, 2) + '\n', 'utf8');
      console.log('  ↑ extracted DATA -> ' + rel(DATA_FILE));
    }
  } else if (SYNC) {
    if (same) console.log('  = ' + rel(DATA_FILE) + ' already matches the source');
    else {
      dc = dc.replace(DATA_RE, () => 'const DATA = ' + canonical(json) + ';\n');
      await writeFile(SRC, dc, 'utf8');
      console.log('  ↓ synced ' + rel(DATA_FILE) + ' -> the source\'s DATA');
    }
  } else if (!same) {
    // Refuse to guess: both sides are legitimate edit surfaces (JSON here,
    // the visual editor in Claude Design) and picking wrong loses work.
    const hint = (await newer(DATA_FILE, SRC)) ? 'the JSON is the newer file' : 'the source is the newer file';
    console.error('✕ ' + rel(DATA_FILE) + ' and the DATA inlined in ' + rel(SRC) + ' disagree (' + hint + ').');
    console.error('  Run --sync    to push the JSON into the source (you edited the JSON).');
    console.error('  Run --extract to pull the source into the JSON (you edited the design).');
    process.exit(1);
  }
} else if (EXTRACT || SYNC) {
  const inSource = readDataBlock(dc);
  await writeFile(DATA_FILE, JSON.stringify(inSource, null, 2) + '\n', 'utf8');
  console.log('  + created ' + rel(DATA_FILE) + ' from the source');
}

// --------------------------------------------------------------------- build
console.log('Checking ' + rel(SRC));
const problems = validate(dc);
if (problems.length) {
  console.error('\n  ' + problems.length + ' problem(s):');
  for (const p of problems) console.error('  ✕ ' + p);
  process.exit(1);
}
console.log('  ✓ data model consistent');
if (CHECK_ONLY) process.exit(0);

const [support, react, reactDom] = await Promise.all([
  read('src/support.js'),
  read('vendor/react.production.min.js'),
  read('vendor/react-dom.production.min.js'),
]);

const inlined = [
  inlineTag('react', react),
  inlineTag('react-dom', reactDom),
  // Truthy __resources stops support.js re-fetching its own URL to hot-reload
  // the template — that fetch fails under file:// and is useless in a build.
  '<script>window.__resources = {};</script>',
  inlineTag('dc-runtime', support),
].join('\n');

const scriptTag = /<script[^>]*src=["'][^"']*support\.js["'][^>]*>\s*<\/script>/i;
if (!scriptTag.test(dc)) {
  console.error('✕ could not find the <script src="./support.js"> tag in the source');
  process.exit(1);
}

// Function replacer: React's minified source contains $&, $` and $' sequences
// that a string replacement would expand and silently corrupt.
let out = dc.replace(scriptTag, () => inlined);
if (!out.includes('<title>')) {
  out = out.replace('<meta charset="utf-8">', () => `<meta charset="utf-8">\n<title>${TITLE}</title>`);
}

// Anything still pointing at a sibling file would break the "opens from disk
// anywhere" promise. Absolute URLs are fine (fonts, links the user may add).
const leftovers = [...out.matchAll(/(?:src|href)=["'](?!data:|#|https?:|mailto:)([^"']+)["']/g)]
  .map((m) => m[1]);
if (leftovers.length) {
  console.warn('  ! relative references left in the output (will 404): ' + [...new Set(leftovers)].join(', '));
}

await writeFile(OUT, out, 'utf8');
console.log(`  ✓ wrote ${OUT.replace(HERE + '/', '')} (${(out.length / 1024).toFixed(0)} KB)`);
console.log('    open it directly from disk — no server, no network.');
