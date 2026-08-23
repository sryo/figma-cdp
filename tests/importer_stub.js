// No-Figma smoke run of figma_importer.js over a walker spec. A stub Plugin API
// records node creation and enforces the ordering the real sandbox enforces
// (fonts loaded before fontName/characters). Prints the final report plus node
// type counts; exits non-zero on any throw or unresolved captureIds entry.
//
//   node tests/importer_stub.js /tmp/figma_capture_<slug>.json [chunk=400]
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'figma_importer.js'), 'utf8');
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const chunkSize = parseInt(process.argv[3], 10) || 400;

let nextId = 1;
const byId = {};
const loadedFonts = {};
let imageCount = 0;

function makeNode(type) {
  const t = { id: 'n' + (nextId++), type, name: '', children: [], parent: null,
    width: 100, height: 100, x: 0, y: 0, layoutMode: type === 'FRAME' ? 'NONE' : undefined };
  if (type === 'TEXT') { t.characters = ''; t.fontName = { family: 'Inter', style: 'Regular' }; }
  t.appendChild = function (c) { c.parent = proxy; t.children.push(c); };
  t.resize = function (w, h) { t.width = w; t.height = h; };
  t.rescale = function (s) { t.width *= s; t.height *= s; };
  t.findOne = function (fn) { return t.children.find(fn) || null; };
  t.getRangeAllFontNames = function () { return [t.fontName]; };
  ['setRangeFontName', 'setRangeFontSize', 'setRangeFills', 'setRangeTextDecoration'].forEach(function (m) {
    t[m] = function () {};
  });
  const proxy = new Proxy(t, {
    set(target, k, v) {
      if (target.type === 'TEXT') {
        if (k === 'fontName' && !loadedFonts[v.family + '/' + v.style]) throw new Error('fontName set before loadFontAsync: ' + JSON.stringify(v));
        if (k === 'characters' && !loadedFonts[target.fontName.family + '/' + target.fontName.style]) throw new Error('characters set before a loaded fontName');
      }
      target[k] = v; return true;
    },
  });
  byId[t.id] = proxy;
  return proxy;
}

global.figma = {
  mixed: Symbol('mixed'),
  createFrame: () => makeNode('FRAME'),
  createText: () => makeNode('TEXT'),
  createImage: (bytes) => { if (!(bytes instanceof Uint8Array)) throw new Error('createImage takes Uint8Array'); imageCount++; return { hash: 'h' + bytes.length }; },
  base64Decode: (s) => Uint8Array.from(Buffer.from(s, 'base64')),
  createNodeFromSvg: (svg) => { if (!/^\s*<svg/.test(svg)) throw new Error('bad svg'); const f = makeNode('FRAME'); f.width = 24; f.height = 24; return f; },
  getNodeByIdAsync: async (id) => byId[id] || null,
  // Every family loads except "Missing", so the ladder's substitution path is exercised.
  loadFontAsync: async (f) => { if (f.family === 'Missing') throw new Error('font not found'); loadedFonts[f.family + '/' + f.style] = true; },
};

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
  Object.values(byId).forEach(n => { types[n.type] = (types[n.type] || 0) + 1; });
  const ids = window.__batchState.captureIds;
  const unresolved = Object.keys(ids).filter(k => !byId[ids[k]]).length;
  const ok = last.created === spec.nodes.length && unresolved === 0;
  console.log(JSON.stringify({ ok, created: last.created, nodes: spec.nodes.length, flagged: byReason, types,
    images: imageCount, fontsFallenBack: last.fontsFallenBack, warnings: last.warnings, ms: Date.now() - t0 }, null, 1));
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
