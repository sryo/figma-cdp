// Offline tests for figma_svg.js: SVG markup Figma's createNodeFromSvg would drop or misdraw,
// rewritten into markup it draws (prepare), and the mask layers rebuilt as Figma masks (finish).
//
//   node --test tests/svg_test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { createFigma } = require('./figma_stub');

global.window = {};
(0, eval)(fs.readFileSync(path.join(__dirname, '..', 'figma_svg.js'), 'utf8'));
const S = window.__fxSvg;
// figma_svg.js's V and the file's hash at that version: any edit changes the hash, so bump V (tabs
// keep an equal or newer copy) and pin the new pair here.
const PIN = { v: 3, sha: 'f05e7351f9d44378' };

test('figma_svg.js is pinned to its version', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'figma_svg.js'), 'utf8');
  const sha = require('crypto').createHash('sha256').update(src).digest('hex').slice(0, 16);
  assert.ok(S.v === PIN.v && sha === PIN.sha, 'figma_svg.js changed: bump V and pin { v: ' + S.v + ", sha: '" + sha + "' }");
});

test('a <style> rule becomes attributes on the elements it matches, and the <style> goes', () => {
  const r = S.prepare('<svg width="10" height="10"><style>.sky{fill:#1f8fd0} #ink{stroke:#18181b} @media (prefers-color-scheme:dark){.sky{fill:#fff}}</style><rect class="sky" width="5" height="5"/><path id="ink" d="M0 0L5 5"/></svg>');
  assert.doesNotMatch(r.svg, /<style/);
  assert.match(r.svg, /<rect[^>]*fill="#1f8fd0"/);
  assert.match(r.svg, /<path[^>]*stroke="#18181b"/);
});

test('var() resolves from o.vars, else its fallback; currentColor takes o.color', () => {
  const r = S.prepare('<svg width="10" height="10"><path style="stroke:var(--papel)" d="M0 0"/><path fill="var(--x, #00ff00)" d="M0 0"/><path stroke="currentColor" d="M0 0"/></svg>', { vars: { '--papel': '#ffffff' }, color: '#1B1B19' });
  assert.match(r.svg, /stroke="#ffffff"/);
  assert.match(r.svg, /fill="#00ff00"/);
  assert.match(r.svg, /stroke="#1B1B19"/);
  assert.doesNotMatch(r.svg, /var\(|currentColor/);
});

test('an unresolvable var() is reported, not left for Figma to paint black', () => {
  const r = S.prepare('<svg width="10" height="10"><path style="fill:var(--nope)" d="M0 0"/></svg>');
  assert.doesNotMatch(r.svg, /var\(/);
  assert.ok(r.notes.some((n) => /--nope/.test(n)), r.notes.join('; '));
});

test('a userSpaceOnUse pattern fill becomes its tiles clipped to the shape', () => {
  const r = S.prepare('<svg width="100" height="60"><defs><pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="6" cy="6" r="3.2" fill="#000"/></pattern></defs><path d="M 0 0 C 50 10 80 10 90 50 Z" fill="url(#dots)"/></svg>');
  assert.doesNotMatch(r.svg, /url\(#dots\)|<pattern/);
  assert.match(r.svg, /<clipPath id="[^"]+"><path d="M 0 0 C 50 10 80 10 90 50 Z"/);
  assert.ok((r.svg.match(/<circle/g) || []).length >= 8, 'tiles cover the shape: 4 x 2 at least');
});

test('mask layers keep their painting order, white and black, for finish to apply in turn', () => {
  const r = S.prepare('<svg width="100" height="100"><defs><mask id="luz" maskUnits="userSpaceOnUse"><rect width="100%" height="100%" fill="white"/><path fill="black" d="M10 10H90V90H10Z"/><path fill="white" d="M20 20H40V40H20Z"/></mask></defs><g mask="url(#luz)"><rect width="100" height="100" fill="#000"/></g></svg>');
  assert.doesNotMatch(r.svg, /<mask|mask="url/);
  const order = [...r.svg.matchAll(/id="MSK([WB])_1_(\d)"/g)].map((m) => m[1] + m[2]);
  assert.deepEqual(order, ['W0', 'B1', 'W2']);
  assert.match(r.svg, /<rect[^>]*width="100"[^>]*height="100"/, '100% resolves against the viewport');
});

test('a SourceAlpha blur-and-offset filter becomes a blurred, offset, faded copy under the shape', () => {
  const r = S.prepare('<svg width="100" height="100"><defs><filter id="ss"><feGaussianBlur in="SourceAlpha" stdDeviation="8"/><feOffset dy="6"/><feComponentTransfer><feFuncA type="linear" slope="0.45"/></feComponentTransfer><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs><g filter="url(#ss)"><rect id="stamp" width="40" height="50" fill="#ffffff"/></g></svg>');
  assert.match(r.svg, /<g transform="translate\(0 6\)" opacity="0.45"[^>]*filter="url\(#[^"]+-blur\)">/);
  assert.match(r.svg, /<feGaussianBlur stdDeviation="8"\/>/);
  assert.match(r.svg, /<rect id="stamp" width="40" height="50" fill="#ffffff"\/>/, 'the shape itself stays sharp, with no filter');
  assert.ok(r.svg.indexOf('translate(0 6)') < r.svg.indexOf('id="stamp"'), 'the shadow paints first');
});

test('a filter that is only a shadow (no SourceGraphic) keeps just the shadow', () => {
  const r = S.prepare('<svg width="100" height="100"><defs><filter id="sh"><feGaussianBlur in="SourceAlpha" stdDeviation="14"/><feOffset dy="12"/><feComponentTransfer><feFuncA type="linear" slope="0.30"/></feComponentTransfer></filter></defs><rect width="80" height="80" fill="#000" filter="url(#sh)"/></svg>');
  assert.equal((r.svg.match(/<rect/g) || []).length, 1);
  assert.match(r.svg, /translate\(0 12\)" opacity="0.3"/);
});

test('markup with nothing to fix passes through untouched', () => {
  const svg = '<svg width="24" height="24" viewBox="0 0 24 24"><path d="M2 2L22 22" stroke="#000" fill="none"/></svg>';
  const r = S.prepare(svg);
  assert.equal(r.svg, svg);
  assert.deepEqual(r.notes, []);
});

test('finish turns each MSK group into a Figma mask: white layers unioned, black subtracted, in order', () => {
  global.figma = createFigma();
  const calls = [];
  for (const k of ['union', 'subtract']) { const f = figma[k].bind(figma); figma[k] = (n, p, i) => { calls.push(k); return f(n, p, i); }; }
  const r = S.prepare('<svg width="100" height="100"><defs><mask id="m"><rect width="100" height="100" fill="white"/><path fill="black" d="M10 10H90V90H10Z"/><path fill="white" d="M20 20H40V40H20Z"/></mask></defs><g mask="url(#m)"><rect width="100" height="100" fill="#000"/></g></svg>');
  const node = figma.createNodeFromSvg(r.svg);
  const out = S.finish(node);
  assert.deepEqual(calls, ['subtract', 'union']);
  assert.equal(out.masks, 1);
  const g = node.findOne((n) => /^MSK_1$/.test(n.name));
  assert.equal(g.children[0].isMask, true);
  assert.equal(g.children[0].name, 'mask');
  assert.ok(!node.findOne((n) => /^MSKL_/.test(n.name)), 'the layer groups are consumed');
});

test('a mask whose layers leave nothing white hides its content', () => {
  global.figma = createFigma();
  const r = S.prepare('<svg width="10" height="10"><defs><mask id="m"><path fill="black" d="M0 0H10V10H0Z"/></mask></defs><g mask="url(#m)"><rect width="10" height="10"/></g></svg>');
  const node = figma.createNodeFromSvg(r.svg);
  S.finish(node);
  const g = node.findOne((n) => n.name === 'MSK_1');
  assert.equal(g.children[0].isMask, true);
  assert.ok(g.children[0].width < 1);
});

test('a masked shape with a pattern fill keeps the mask around its tiles', () => {
  const r = S.prepare('<svg width="100" height="100"><defs><pattern id="p" width="10" height="10" patternUnits="userSpaceOnUse"><rect width="10" height="4" fill="#00f"/></pattern><mask id="m"><rect width="100" height="100" fill="#fff"/><circle cx="50" cy="50" r="10" fill="#000"/></mask></defs><rect width="100" height="100" fill="url(#p)" mask="url(#m)"/></svg>');
  const msk = r.svg.indexOf('id="MSK_1"'), clip = r.svg.indexOf('<clipPath');
  assert.ok(msk >= 0 && clip > msk, 'the MSK group holds the clipped tiles');
  assert.ok(!/<clipPath[^>]*>(?:(?!<\/clipPath>).)*MSK/.test(r.svg), 'no mask inside a clip path');
});

test('a rotated pattern tiles the shape in the pattern space', () => {
  const r = S.prepare('<svg width="100" height="100"><defs><pattern id="p" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(90)"><rect width="6" height="2" fill="#00f"/></pattern></defs><rect x="40" y="40" width="20" height="20" fill="url(#p)"/></svg>');
  const xs = [...r.svg.matchAll(/translate\((-?[\d.]+) (-?[\d.]+)\)/g)].map((m) => [+m[1], +m[2]]);
  // rotate(90) maps pattern (u, v) to user (-v, u): the shape's 40..60 box is u in 40..60, v in -60..-40.
  assert.ok(xs.some(([u, v]) => u <= 40 && v <= -60) && xs.some(([u, v]) => u >= 54 && v >= -46), JSON.stringify(xs.slice(0, 6)));
});

test("a shape's own transform also places its tiles", () => {
  const r = S.prepare('<svg width="200" height="100"><defs><pattern id="p" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="3" fill="#000"/></pattern></defs><path transform="translate(118 64)" d="M0 0H20V20H0Z" fill="url(#p)"/></svg>');
  assert.match(r.svg, /<g transform="translate\(118 64\)">(<g transform="translate\(0 0\)">|<g>)/);
});

test("a pattern-filled shape's mask, opacity and filter move to its tiles", () => {
  const r = S.prepare('<svg width="100" height="100"><defs><pattern id="p" width="10" height="10" patternUnits="userSpaceOnUse"><rect width="10" height="4"/></pattern><mask id="m"><rect width="100" height="100" fill="#fff"/></mask></defs><rect width="100" height="100" fill="url(#p)" mask="url(#m)" opacity="0.5"/></svg>', { masks: false });
  assert.match(r.svg, /<g clip-path="url\(#fxclip1\)" mask="url\(#m\)" opacity="0.5">/);
});
