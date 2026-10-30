// tests/cases/snapshot.js and rebuild.js against the stub Plugin API: a seed rebuilt on another
// page snapshots back to the same seed.
//
//   node --test tests/snapshot_test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { createFigma } = require('./figma_stub');

const AsyncFunction = (async () => {}).constructor;
const src = (name) => fs.readFileSync(path.join(__dirname, 'cases', name), 'utf8');
const snapshot = (id, max) => new AsyncFunction('figma', 'SNAP_ID', 'SNAP_MAX', src('snapshot.js'))(figma, id, max);
const rebuild = (seed, parent) => new AsyncFunction('figma', 'SEED', 'PARENT_ID', src('rebuild.js'))(figma, seed, parent);

async function screen() {
  await figma.loadFontAsync({ family: 'Inter', style: 'Bold' });
  const home = figma.createFrame();
  home.name = 'Home'; home.resize(1440, 900); home.x = 40;
  home.layoutMode = 'VERTICAL'; home.itemSpacing = 16; home.paddingTop = 24;
  home.fills = [{ type: 'SOLID', visible: true, opacity: 1, blendMode: 'NORMAL', color: { r: 0.1, g: 0.2, b: 0.3 } }];
  const title = figma.createText();
  home.appendChild(title);
  title.fontName = { family: 'Inter', style: 'Bold' }; title.fontSize = 32; title.characters = 'Revenue';
  title.layoutSizingHorizontal = 'FILL';
  const def = figma.createComponent(); def.name = 'State=Default'; def.resize(120, 40);
  const hov = figma.createComponent(); hov.name = 'State=Hover'; hov.resize(120, 40);
  const set = figma.combineAsVariants([def, hov], home);
  set.name = 'Toggle';
  await def.setReactionsAsync([{ trigger: { type: 'ON_HOVER' }, actions: [{ type: 'NODE', destinationId: hov.id, navigation: 'CHANGE_TO', transition: null }] }]);
  const kept = def.createInstance(); home.appendChild(kept);
  const quiet = def.createInstance(); home.appendChild(quiet);
  await quiet.setReactionsAsync([]);
  const next = figma.createFrame(); next.name = 'Next'; figma.currentPage.appendChild(next);
  const go = figma.createRectangle(); go.name = 'Go'; home.appendChild(go);
  await go.setReactionsAsync([{ trigger: { type: 'ON_CLICK' }, actions: [{ type: 'NODE', destinationId: next.id, navigation: 'NAVIGATE', transition: null }] }]);
  return { home, next, kept, quiet, go };
}

test('a rebuilt seed snapshots back to the same seed', async () => {
  global.figma = createFigma();
  const { home } = await screen();
  const seed = await snapshot(home.id);
  assert.equal(seed.truncated, false);
  assert.equal(seed.nodes, 8);
  const away = figma.createPage();
  const out = await rebuild(seed, away);
  const again = await snapshot(out.root);
  const go = seed.root.children.find((c) => c.props.name === 'Go');
  delete go.reactions;
  assert.deepEqual(again.root, seed.root);
  assert.notEqual(out.root, home.id);
  assert.deepEqual(out.dropped, ['reaction on Go to a node outside the seed']);
});

test('ids are remapped: nothing in a seed names a node id', async () => {
  global.figma = createFigma();
  const { home, next } = await screen();
  const seed = await snapshot(home.id);
  const text = JSON.stringify(seed);
  assert.doesNotMatch(text, /\b\d+:\d+\b/);
  assert.match(text, /"destinationId":"ext:Next"/);
  assert.ok(next.id);
  const variant = seed.root.children.find((c) => c.type === 'COMPONENT_SET').children[0];
  assert.match(variant.reactions[0].actions[0].destinationId, /^s\d+$/);
});

test('an instance keeps its own empty reactions and inherits otherwise', async () => {
  global.figma = createFigma();
  const { home } = await screen();
  const seed = await snapshot(home.id);
  const [kept, quiet] = seed.root.children.filter((c) => c.type === 'INSTANCE');
  assert.equal(kept.reactions, undefined);
  assert.deepEqual(quiet.reactions, []);
  const out = await rebuild(seed, figma.createPage());
  const rebuilt = await figma.getNodeByIdAsync(out.ids[quiet.sid]);
  assert.deepEqual(rebuilt.reactions, []);
  assert.equal((await figma.getNodeByIdAsync(out.ids[kept.sid])).reactions[0].trigger.type, 'ON_HOVER');
});

test('SNAP_MAX stops the walk and says so', async () => {
  global.figma = createFigma();
  const { home } = await screen();
  const seed = await snapshot(home.id, 3);
  assert.equal(seed.nodes, 3);
  assert.equal(seed.truncated, true);
});

test('an instance of a component outside the seed comes back as a frame', async () => {
  global.figma = createFigma();
  const { kept } = await screen();
  const seed = await snapshot(kept.id);
  assert.equal(seed.root.main, 'ext:State=Default');
  const out = await rebuild(seed, figma.createPage());
  assert.equal((await figma.getNodeByIdAsync(out.root)).type, 'FRAME');
  assert.deepEqual(out.dropped, ['instance ' + seed.root.props.name + ' of ext:State=Default became a frame']);
});
