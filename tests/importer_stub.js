// No-Figma run of a capture import: `figma_capture.py import --dry-run` writes the evals the
// live import would send (reset, assets, node chunks + figma_importer.js), and this replays
// them in order against the stub Plugin API in tests/figma_stub.js (fonts loaded before
// fontName/characters, layout rules enforced). Prints the final report plus node type
// counts; exits non-zero on any throw or unresolved captureIds entry. --dump writes
// {tree, ids, report}: the page's node tree, captureIds, and the last chunk's report.
//
//   node tests/importer_stub.js /tmp/figma_capture_<slug>.json [--componentize] [--chunk-bytes N] [--dump tree.json]
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const args = process.argv.slice(2);
const specPath = args[0];
const opt = (name) => { const k = args.indexOf(name); return k === -1 ? null : args[k + 1]; };
const dumpPath = opt('--dump');
const helperArgs = [];
if (args.includes('--componentize')) helperArgs.push('--componentize');
if (opt('--chunk-bytes')) helperArgs.push('--chunk-bytes', opt('--chunk-bytes'));

const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'importer-stub-'));
execFileSync('python3', [path.join(__dirname, '..', 'figma_capture.py'), 'import', specPath, '--dry-run', dir, ...helperArgs],
  { stdio: ['ignore', 'ignore', 'inherit'] });
const scripts = fs.readdirSync(dir).sort().map((f) => ({ f, src: fs.readFileSync(path.join(dir, f), 'utf8') }));
fs.rmSync(dir, { recursive: true, force: true });

const { createFigma } = require('./figma_stub');
global.figma = createFigma();
let imageCount = 0;
const createImage = figma.createImage;
figma.createImage = (bytes) => { const img = createImage(bytes); imageCount++; return img; };

function dumpNode(n) {
  const out = { id: n.id, type: n.type, name: n.name, width: n.width, height: n.height };
  if (n.layoutSizingHorizontal) out.sizing = [n.layoutSizingHorizontal, n.layoutSizingVertical];
  if (n.constraints) out.constraints = [n.constraints.horizontal, n.constraints.vertical];
  out.positioning = n.layoutPositioning;
  if (n.layoutGrow) out.layoutGrow = n.layoutGrow;
  if (n.layoutAlign && n.layoutAlign !== 'INHERIT') out.layoutAlign = n.layoutAlign;
  if (n.layoutMode) out.layoutMode = n.layoutMode;
  if (n.type === 'TEXT') out.characters = n.characters;
  if (n.type === 'INSTANCE' && n.mainComponent) out.main = n.mainComponent.name;
  if (n.type === 'COMPONENT') out.props = Object.keys(n.componentPropertyDefinitions || {}).map((k) => k.split('#')[0]);
  if (n.children) out.children = n.children.map(dumpNode);
  return out;
}

(async function () {
  global.window = {};
  let last = null;
  const t0 = Date.now();
  for (const { f, src } of scripts) {
    const result = await eval(src);
    if (result && result.error) throw new Error(f + ': ' + result.error);
    if (/_nodes-/.test(f)) last = result;
  }
  const byReason = {};
  last.flagged.forEach(f => { byReason[f.reason] = (byReason[f.reason] || 0) + 1; });
  const types = {};
  figma.currentPage.findAll().forEach(n => { types[n.type] = (types[n.type] || 0) + 1; });
  const ids = window.__batchState.captureIds;
  let unresolved = 0;
  for (const k of Object.keys(ids)) if (!(await figma.getNodeByIdAsync(ids[k]))) unresolved++;
  const ok = last.created === spec.nodes.length && unresolved === 0;
  if (dumpPath) {
    fs.writeFileSync(dumpPath, JSON.stringify({ tree: figma.currentPage.children.map(dumpNode), ids, report: last }));
  }
  console.log(JSON.stringify({ ok, created: last.created, nodes: spec.nodes.length, flagged: byReason, types,
    images: imageCount, components: (last.components || []).length, instantiated: last.instantiated.length,
    fontsFallenBack: last.fontsFallenBack, warnings: last.warnings, ms: Date.now() - t0 }, null, 1));
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
