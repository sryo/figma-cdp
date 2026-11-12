// Offline tests for figma_walker.js's 3D decomposition: a CSS own transform as a 2D affine
// followed by Figma's fixed order, translateZ · rotateX · rotateY · rotateZ (references/motion.md).
// Outside a page the walker has nothing to walk and returns its pure geometry instead.
//
//   node --test tests/walker_3d_test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'figma_walker.js'), 'utf8');
let fixedOrder;
test.before(async () => { ({ fixedOrder } = await vm.runInNewContext(SRC, {})); });

// Row-major 4x4 matrices acting on column vectors, as CSS composes its transform list.
const rad = (d) => d * Math.PI / 180;
const I = () => [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]];
const mul = (a, b) => a.map((row) => b[0].map((_, c) => row.reduce((s, v, k) => s + v * b[k][c], 0)));
const chain = (...ms) => ms.reduce(mul, I());
const translate = (x, y, z = 0) => { const m = I(); m[0][3] = x; m[1][3] = y; m[2][3] = z; return m; };
const scale = (x, y, z = 1) => { const m = I(); m[0][0] = x; m[1][1] = y; m[2][2] = z; return m; };
const rotateX = (d) => { const c = Math.cos(rad(d)), s = Math.sin(rad(d)), m = I(); m[1][1] = c; m[1][2] = -s; m[2][1] = s; m[2][2] = c; return m; };
const rotateY = (d) => { const c = Math.cos(rad(d)), s = Math.sin(rad(d)), m = I(); m[0][0] = c; m[0][2] = s; m[2][0] = -s; m[2][2] = c; return m; };
const rotateZ = (d) => { const c = Math.cos(rad(d)), s = Math.sin(rad(d)), m = I(); m[0][0] = c; m[0][1] = -s; m[1][0] = s; m[1][1] = c; return m; };
const skewX = (d) => { const m = I(); m[0][1] = Math.tan(rad(d)); return m; };
const perspective = (d) => { const m = I(); m[3][2] = -1 / d; return m; };
// DOMMatrix names its entries column by column: m21 is row 1, column 2.
const dom = (m) => { const o = {}; for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) o['m' + (c + 1) + (r + 1)] = m[r][c]; return o; };
const affine2d = (d) => [[d.a, d.c, 0, d.e], [d.b, d.d, 0, d.f], [0, 0, 1, 0], [0, 0, 0, 1]];
const recompose = (d) => chain(affine2d(d), translate(0, 0, d.translateZ), rotateX(d.rotateX), rotateY(d.rotateY), rotateZ(d.rotateZ));
const close = (a, b, eps = 1e-6) => a.flat().every((v, k) => Math.abs(v - b.flat()[k]) < eps);
const near = (a, b) => Math.abs(a - b) < 1e-6;

test('a rotateY alone is that angle, with no 2D part', () => {
  const d = fixedOrder(dom(rotateY(35)));
  assert.ok(near(d.rotateY, 35) && near(d.rotateX, 0) && near(d.rotateZ, 0) && near(d.translateZ, 0), JSON.stringify(d));
  assert.ok(close([[d.a, d.c, d.e], [d.b, d.d, d.f]], [[1, 0, 0], [0, 1, 0]]));
});

test("a list already in Figma's order keeps its values", () => {
  const d = fixedOrder(dom(chain(translate(0, 0, 40), rotateX(20), rotateY(30), rotateZ(10))));
  assert.ok(near(d.translateZ, 40) && near(d.rotateX, 20) && near(d.rotateY, 30) && near(d.rotateZ, 10), JSON.stringify(d));
});

test('a 2D scale and translation ahead of the tilt stay in the 2D part', () => {
  const d = fixedOrder(dom(chain(scale(1.5, 1.5), translate(10, 20), rotateX(45))));
  assert.ok(close([[d.a, d.c, d.e], [d.b, d.d, d.f]], [[1.5, 0, 15], [0, 1.5, 30]]), JSON.stringify(d));
  assert.ok(near(d.rotateX, 45) && near(d.rotateY, 0) && near(d.rotateZ, 0));
});

test('any other rotation order recomposes to the same matrix', () => {
  for (const m of [chain(rotateY(30), rotateX(20)), chain(rotateZ(10), rotateX(45), translate(5, 6, 7)),
    chain(rotateX(120), rotateY(-200)), chain(scale(-1, 1), rotateY(30)), chain(skewX(15), rotateX(30)), rotateY(90), rotateY(-90),
    chain(rotateX(30), rotateY(90), rotateZ(20))]) {
    const d = fixedOrder(dom(m));
    assert.ok(d, 'decomposes');
    assert.ok(close(recompose(d), m), JSON.stringify(d));
  }
});

test('what the order cannot express comes back null', () => {
  for (const [name, m] of [['perspective()', chain(perspective(500), rotateY(30))], ['3D scale', scale(1, 1, 2)],
    ['a scale under the tilt', chain(rotateY(30), scale(1.5, 1.5))], ['a skew under the tilt', chain(rotateY(30), skewX(20))],
    ['singular', chain(scale(0, 1), rotateY(30))]]) {
    assert.equal(fixedOrder(dom(m)), null, name);
  }
});
