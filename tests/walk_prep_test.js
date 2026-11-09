// Offline tests for figma_walk_prep.js's notes: what a background tab leaves out, and the one hint
// figma_capture.py hands it (cfg.hint) for the way to get it. Runs the prep in node:vm on a DOM fake.
//
//   node --test tests/walk_prep_test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'figma_walk_prep.js'), 'utf8');

// A hidden tab whose page has one WebGL canvas and nothing else.
function hiddenPage() {
  const canvas = { getContext: (k) => (k === '2d' ? null : {}), toDataURL: () => '' };
  const doc = {
    visibilityState: 'hidden',
    documentElement: { scrollHeight: 0, style: {} },
    styleSheets: [],
    body: { querySelectorAll: () => [] },
    querySelectorAll: (q) => (q === 'canvas' ? [canvas] : []),
  };
  const win = { innerWidth: 1440, innerHeight: 900, scrollTo() {}, getComputedStyle: () => ({}), requestAnimationFrame() {} };
  win.window = win;
  win.document = doc;
  // Kept so notes() can close them: an open port holds node's event loop after the test.
  win.channels = [];
  win.MessageChannel = function () { const c = new MessageChannel(); win.channels.push(c); return c; };
  win.Map = Map;
  return win;
}

async function notes(cfg) {
  const win = hiddenPage();
  try {
    return (await vm.runInContext(SRC.replace(/[\s;]+$/, ''), vm.createContext(win))(cfg)).notes;
  } finally {
    for (const c of win.channels) { c.port1.close(); c.port2.close(); }
  }
}

test('a background tab says what it left out and ends each such note with the hint it was given', async () => {
  const got = await notes({ width: 0, scheme: 'page', scroll: true, hint: 'HINT-TEXT' });
  const bg = got.find((n) => /in the background/.test(n));
  const gl = got.find((n) => /WebGL/.test(n));
  assert.ok(bg && gl, JSON.stringify(got));
  assert.match(bg, /; HINT-TEXT$/);
  assert.match(gl, /; HINT-TEXT$/);
});

test('without a hint the notes say only what is missing', async () => {
  const got = await notes({ width: 0, scheme: 'page', scroll: true });
  for (const n of got) assert.doesNotMatch(n, /room|shown|show the tab|window|undefined/, n);
});

test('the prep never tells the agent to show, raise, widen or resize a window, and names no tiler', () => {
  assert.doesNotMatch(SRC, /stackd|widen|resize|raise|show the tab|tab shown|rooms up/i);
});
