// No-Figma smoke run of figma_importer.js over a walker spec, against the stub Plugin API in
// tests/figma_stub.js (fonts loaded before fontName/characters, layout rules enforced). Prints
// the final report plus node type counts; exits non-zero on any throw or unresolved captureIds entry.
//
//   node tests/importer_stub.js /tmp/figma_capture_<slug>.json [chunk=400]
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'figma_importer.js'), 'utf8');
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const chunkSize = parseInt(process.argv[3], 10) || 400;

const { createFigma } = require('./figma_stub');
global.figma = createFigma();
let imageCount = 0;
const createImage = figma.createImage;
figma.createImage = (bytes) => { const img = createImage(bytes); imageCount++; return img; };

(async function () {
  global.window = { __batchState: { captureAssets: spec.assets || {} } };
  let last = null;
  const t0 = Date.now();
  for (let i = 0; i < spec.nodes.length; i += chunkSize) {
    window.__captureSpec = { nodes: spec.nodes.slice(i, i + chunkSize), flagged: spec.flagged || [],
      components: {}, meta: spec.meta || {} };
    last = await eval(src);
    if (last.error) throw new Error(last.error);
  }
  const byReason = {};
  last.flagged.forEach(f => { byReason[f.reason] = (byReason[f.reason] || 0) + 1; });
  const types = {};
  figma.currentPage.findAll().forEach(n => { types[n.type] = (types[n.type] || 0) + 1; });
  const ids = window.__batchState.captureIds;
  let unresolved = 0;
  for (const k of Object.keys(ids)) if (!(await figma.getNodeByIdAsync(ids[k]))) unresolved++;
  const ok = last.created === spec.nodes.length && unresolved === 0;
  console.log(JSON.stringify({ ok, created: last.created, nodes: spec.nodes.length, flagged: byReason, types,
    images: imageCount, fontsFallenBack: last.fontsFallenBack, warnings: last.warnings, ms: Date.now() - t0 }, null, 1));
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
