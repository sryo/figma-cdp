// Offline tests for figma_lib.js (window.__fx) against the stub Plugin API in tests/figma_stub.js.
//
//   node --test tests/figma_lib_test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { createFigma } = require('./figma_stub');

const LIB = fs.readFileSync(path.join(__dirname, '..', 'figma_lib.js'), 'utf8');
// The version figma_lib.js stamps (`var V = n;`) and the file's hash at that version. Any edit
// changes the hash: bump V in figma_lib.js so tabs holding the old copy replace it, then pin the
// new pair here.
const PIN = { v: 6, sha: '95031cfcafe209cb' };

function load(src) { (0, eval)(src || LIB); return window.__fx; }
function fresh() {
  global.figma = createFigma();
  global.window = {};
  return load();
}
function solid(hex) {
  const n = parseInt(hex.slice(1), 16);
  return { type: 'SOLID', visible: true, opacity: 1, color: { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 } };
}
async function fonts() { for (const s of ['Regular', 'Medium', 'Bold']) await figma.loadFontAsync({ family: 'Inter', style: s }); }
function mkText(parent, chars, name) {
  const t = figma.createText();
  t.characters = chars;
  t.name = name || chars;
  parent.appendChild(t);
  return t;
}
function mkFrame(parent, name, dir, w, h) {
  const f = figma.createFrame();
  if (name) f.name = name;
  if (parent) parent.appendChild(f);
  if (dir) f.layoutMode = dir;
  if (w) f.resize(w, h || f.height);
  return f;
}
// Button set: Variant=Primary|Secondary x State=Default|Disabled, a Label TEXT property linked
// on every variant.
function buttonSet(parent) {
  const comps = [], labels = [];
  for (const variant of ['Primary', 'Secondary']) {
    for (const state of ['Default', 'Disabled']) {
      const c = figma.createComponent();
      c.name = 'Variant=' + variant + ', State=' + state;
      c.layoutMode = 'HORIZONTAL';
      labels.push(mkText(c, 'Button', 'Label'));
      comps.push(c);
    }
  }
  const set = figma.combineAsVariants(comps, parent);
  set.name = 'Button';
  const key = set.addComponentProperty('Label', 'TEXT', 'Button');
  labels.forEach((t) => { t.componentPropertyReferences = { characters: key }; });
  return set;
}
// A row: FRAME:H[TEXT, FRAME:V[TEXT, TEXT]] at 320x64.
function row(parent, label) {
  const r = mkFrame(parent, 'Row', 'HORIZONTAL', 320, 64);
  mkText(r, label, 'Title');
  const col = mkFrame(r, 'Meta', 'VERTICAL');
  mkText(col, 'a', 'A');
  mkText(col, 'b', 'B');
  return r;
}
function tokens() {
  const col = figma.variables.createVariableCollection('Tokens');
  col.modes[0].name = 'Light';
  col.modes.push({ modeId: 'm2', name: 'Dark' });
  const blue = figma.variables.createVariable('blue/600', col, 'COLOR');
  blue.setValueForMode('m1', { r: 0x25 / 255, g: 0x63 / 255, b: 0xeb / 255, a: 1 });
  const primary = figma.variables.createVariable('color/primary', col, 'COLOR');
  primary.setValueForMode('m1', { type: 'VARIABLE_ALIAS', id: blue.id });
  const space = figma.variables.createVariable('space/4', col, 'FLOAT');
  space.setValueForMode('m1', 16);
  return { col, blue, primary, space };
}

// ---- install guard

test('installs once per tab; a newer copy replaces it, an equal or older one does not', () => {
  const fx = fresh();
  assert.equal(fx.v, PIN.v);
  fx.mark = 1;
  assert.equal(load(), fx, 'same version: the guard returns before building anything');
  assert.equal(load(LIB.replace(/var V = \d+;/, 'var V = 0;')).mark, 1);
  const next = load(LIB.replace(/var V = \d+;/, 'var V = ' + (PIN.v + 1) + ';'));
  assert.notEqual(next, fx);
  assert.equal(next.v, PIN.v + 1);
});

test('the version is bumped whenever the file changes', () => {
  const v = Number(/var V = (\d+);/.exec(LIB)[1]);
  const sha = crypto.createHash('sha256').update(LIB).digest('hex').slice(0, 16);
  assert.ok(v === PIN.v && sha === PIN.sha,
    `figma_lib.js changed (sha ${sha}): bump its V past ${PIN.v} and set PIN in tests/figma_lib_test.js to { v: ${v === PIN.v ? PIN.v + 1 : v}, sha: '<new sha>' }`);
});

test('the source is ASCII, so both backends carry it byte for byte', () => {
  assert.ok(/^[\x00-\x7f]*$/.test(LIB));
});

// ---- recon

test('recon: page list and a depth-capped flat tree of the current page', async () => {
  const fx = fresh();
  await fonts();
  const p2 = figma.createPage();
  p2.name = 'Library';
  const screen = mkFrame(figma.currentPage, 'Screen', 'VERTICAL', 375, 812);
  const r = row(screen, 'Hello world');
  const set = buttonSet(figma.currentPage);
  const inst = set.children[0].createInstance();
  screen.appendChild(inst);
  const out = await fx.recon();
  assert.deepEqual(out.pages, ['Page 1 [' + figma.currentPage.id + '] *', 'Library [' + p2.id + ']']);
  const lines = out.tree.split('\n');
  assert.equal(lines[0], 'PAGE "Page 1" [' + figma.currentPage.id + ']');
  assert.equal(lines[1], '  FRAME "Screen" [' + screen.id + '] 375x812 auto:V');
  assert.ok(lines.includes('    FRAME "Row" [' + r.id + '] 320x64 auto:H'), out.tree);
  assert.ok(lines.includes('      TEXT "Title" [' + r.children[0].id + '] "Hello world" 12px'), out.tree);
  assert.ok(lines.includes('      FRAME "Meta" [' + r.children[1].id + '] 100x100 auto:V +2'), 'depth 3 stops here and counts what it hid');
  assert.ok(out.tree.includes('INSTANCE "Button" [' + inst.id + '] -> Button {Variant=Primary, State=Default}'), out.tree);
  assert.equal(out.truncated, false);
  assert.equal(out.lines, lines.length);
});

test('recon: a node scope goes full depth; maxChars cuts whole lines and says so', async () => {
  const fx = fresh();
  await fonts();
  const screen = mkFrame(figma.currentPage, 'Screen', 'VERTICAL', 375, 812);
  const r = row(screen, 'One');
  const scoped = await fx.recon({ nodeId: r.id });
  assert.equal(scoped.tree.split('\n').length, 5);
  assert.ok(scoped.tree.includes('TEXT "A"'));
  for (let i = 0; i < 40; i++) row(screen, 'Row ' + i);
  const capped = await fx.recon({ nodeId: screen.id, maxChars: 500 });
  assert.equal(capped.truncated, true);
  assert.ok(capped.tree.length <= 500);
  assert.ok(capped.tree.endsWith(']') || /\S$/.test(capped.tree));
  await assert.rejects(fx.recon({ nodeId: '9:999' }), /node 9:999 not found/);
});

// ---- inventory

async function designSystem() {
  await fonts();
  const page = figma.currentPage;
  const set = buttonSet(page);
  const input = figma.createComponent();
  input.name = 'Input';
  input.layoutMode = 'VERTICAL';
  mkText(input, 'Label').componentPropertyReferences = { characters: input.addComponentProperty('Label', 'TEXT', 'Label') };
  mkText(input, 'Placeholder').componentPropertyReferences = { characters: input.addComponentProperty('Placeholder', 'TEXT', 'x') };
  // Library components: remote mains on another page, used by instances here.
  const lib = figma.createPage();
  lib.name = 'Remote';
  await figma.setCurrentPageAsync(lib);
  const avatar = figma.createComponent();
  avatar.name = 'Avatar';
  avatar.addComponentProperty('Initials', 'TEXT', 'AB');
  avatar.remote = true;
  const sm = figma.createComponent(), md = figma.createComponent();
  sm.name = 'Size=sm'; md.name = 'Size=md';
  const tag = figma.combineAsVariants([sm, md], lib);
  tag.name = 'Tag';
  [tag, sm, md].forEach((n) => { n.remote = true; });
  await figma.setCurrentPageAsync(page);
  const screen = mkFrame(page, 'Screen', 'VERTICAL', 375, 812);
  screen.appendChild(avatar.createInstance());
  screen.appendChild(avatar.createInstance());
  screen.appendChild(md.createInstance());
  const rows = [row(screen, 'One'), row(screen, 'Two'), row(screen, 'Three')];
  const odd = mkFrame(screen, 'Wide', 'HORIZONTAL', 640, 64);
  mkText(odd, 'x');
  const col = mkFrame(odd, 'Meta', 'VERTICAL');
  mkText(col, 'a'); mkText(col, 'b');
  // Styles and variables.
  const red = figma.createPaintStyle();
  red.name = 'Brand/Primary';
  red.paints = [solid('#2563eb')];
  const body = figma.createTextStyle();
  body.name = 'Body';
  Object.assign(body, { fontName: { family: 'Inter', style: 'Medium' }, fontSize: 16, lineHeight: { unit: 'PIXELS', value: 24 } });
  const shadow = figma.createEffectStyle();
  shadow.name = 'Shadow/md';
  shadow.effects = [{ type: 'DROP_SHADOW', color: { r: 0, g: 0, b: 0, a: 0.1 }, offset: { x: 0, y: 4 }, radius: 12, spread: 0, visible: true }];
  const tk = tokens();
  return { set, input, avatar, tag, rows, red, body, shadow, tk, screen };
}

test('inventory: sets with collapsed axes, components, library, styles, variables and patterns as text lines', async () => {
  const fx = fresh();
  const d = await designSystem();
  const out = await fx.inventory();
  const lines = out.text.split('\n');
  const want = [
    'SET Button [' + d.set.id + '] Variant=Primary|Secondary; State=Default|Disabled props: Label:TEXT',
    'COMP Input [' + d.input.id + '] props: Label:TEXT, Placeholder:TEXT',
    'LIB Avatar [' + d.avatar.id + '] key=k' + d.avatar.id + ' uses=2 props: Initials:TEXT',
    'LIB Tag [' + d.tag.id + '] key=k' + d.tag.id + ' uses=1 Size=sm|md',
    'PAINT Brand/Primary [' + d.red.id + '] #2563eb',
    'TEXTSTYLE Body [' + d.body.id + '] Inter Medium 16/24',
    'EFFECT Shadow/md [' + d.shadow.id + '] DROP_SHADOW 0,4 blur 12 #0000001a',
    'VARS Tokens [' + d.tk.col.id + '] modes: Light|Dark',
    '  blue/600 [' + d.tk.blue.id + '] #2563eb',
    '  color/primary [' + d.tk.primary.id + '] #2563eb =blue/600',
    '  space/4 [' + d.tk.space.id + '] 16',
    'PATTERN x3 FRAME:H[TEXT,FRAME:V[TEXT,TEXT]] ~320x64 ids: ' + d.rows.map((r) => r.id).join(', '),
  ];
  assert.deepEqual(lines, want);
  assert.equal(out.truncated, false);
  assert.equal(figma._stats.variantDefReads, 0, 'componentPropertyDefinitions read on a variant: Figma throws there');
  for (const v of d.set.children) assert.ok(!out.text.includes('[' + v.id + ']'), 'no per-variant ids');
});

test('inventory: survives a set whose variants throw on componentPropertyDefinitions', async () => {
  const fx = fresh();
  await fonts();
  const set = buttonSet(figma.currentPage);
  assert.throws(() => set.children[0].componentPropertyDefinitions, /Can only get definitions/);
  const out = await fx.inventory();
  assert.match(out.text, /^SET Button \[/);
});

test('inventory: cached in __batchState; fresh rescans; match filters; maxChars caps', async () => {
  const fx = fresh();
  const d = await designSystem();
  await fx.inventory();
  assert.ok(Array.isArray(window.__batchState.fxInventory.lines));
  const late = figma.createComponent();
  late.name = 'Late';
  assert.ok(!(await fx.inventory()).text.includes('COMP Late'), 'served from the cache');
  assert.ok((await fx.inventory({ fresh: true })).text.includes('COMP Late [' + late.id + ']'));

  const m = await fx.inventory({ match: 'button|primary' });
  assert.deepEqual(m.text.split('\n'), [
    'SET Button [' + d.set.id + '] Variant=Primary|Secondary; State=Default|Disabled props: Label:TEXT',
    'PAINT Brand/Primary [' + d.red.id + '] #2563eb',
    'VARS Tokens [' + d.tk.col.id + '] modes: Light|Dark',
    '  color/primary [' + d.tk.primary.id + '] #2563eb =blue/600',
  ]);
  const capped = await fx.inventory({ maxChars: 120 });
  assert.equal(capped.truncated, true);
  assert.ok(capped.text.length <= 120);
  assert.ok(capped.total > capped.lines);
});

// ---- build helpers

test('frame: auto layout with padding shorthand, fill sizing in a parent, hug by default, fill bound to a matching variable', async () => {
  const fx = fresh();
  const tk = tokens();
  const screen = await fx.frame({ name: 'Screen', dir: 'V', w: 375, h: 812 });
  assert.equal(screen.layoutMode, 'VERTICAL');
  assert.equal(screen.width, 375);
  assert.deepEqual([screen.layoutSizingHorizontal, screen.layoutSizingVertical], ['FIXED', 'FIXED']);
  assert.deepEqual(screen.fills, [], 'no fill unless asked');
  const r = await fx.frame({ parent: screen.id, name: 'Row', dir: 'H', gap: 8, pad: [12, 16], align: 'center', justify: 'between', w: 'fill', fill: '#2563eb', radius: 6 });
  assert.equal(r.parent, screen);
  assert.deepEqual([r.itemSpacing, r.paddingTop, r.paddingRight, r.paddingBottom, r.paddingLeft], [8, 12, 16, 12, 16]);
  assert.deepEqual([r.counterAxisAlignItems, r.primaryAxisAlignItems, r.cornerRadius], ['CENTER', 'SPACE_BETWEEN', 6]);
  assert.deepEqual([r.layoutSizingHorizontal, r.layoutSizingVertical], ['FILL', 'HUG']);
  assert.equal(r.fills[0].boundVariables.color.id, tk.primary.id, 'the semantic alias wins over the primitive');
  const box = await fx.frame({ parent: r, name: 'Box', w: 24, h: 24 });
  assert.equal(box.layoutMode, 'NONE');
  const abs = await fx.frame({ parent: screen, name: 'Badge', abs: true, constraints: { horizontal: 'MAX', vertical: 'MIN' }, x: 300, y: 8 });
  assert.equal(abs.layoutPositioning, 'ABSOLUTE');
  assert.deepEqual([abs.x, abs.y, abs.constraints.horizontal], [300, 8, 'MAX']);
  await assert.rejects(fx.frame({ name: 'Bad', dir: 'V', w: 'stretchy' }), /sizing/);
  const al = await fx.autoLayout(box.id, { dir: 'H', pad: 4 });
  assert.deepEqual([al.layoutMode, al.paddingLeft, al.paddingTop], ['HORIZONTAL', 4, 4]);
});

test('text: loads its font, binds color by variable name, fills width, applies a text style', async () => {
  const fx = fresh();
  const tk = tokens();
  const body = figma.createTextStyle();
  body.name = 'Body';
  Object.assign(body, { fontName: { family: 'Inter', style: 'Medium' }, fontSize: 16, lineHeight: { unit: 'PIXELS', value: 24 } });
  const row = await fx.frame({ name: 'Row', dir: 'H', w: 320 });
  const t = await fx.text('Hello', { parent: row, weight: 'Bold', size: 18, color: 'color/primary', w: 'fill' });
  assert.deepEqual(t.fontName, { family: 'Inter', style: 'Bold' });
  assert.deepEqual([t.characters, t.name, t.fontSize], ['Hello', 'Hello', 18]);
  assert.equal(t.fills[0].boundVariables.color.id, tk.primary.id);
  assert.deepEqual([t.layoutSizingHorizontal, t.textAutoResize], ['FILL', 'HEIGHT']);
  const s = await fx.text('Styled', { parent: row, textStyle: 'Body', name: 'Caption' });
  assert.deepEqual([s.textStyleId, s.fontName.style, s.fontSize, s.name], [body.id, 'Medium', 16, 'Caption']);
  const fixed = await fx.text('Wrap me', { parent: row, w: 120 });
  assert.deepEqual([fixed.width, fixed.textAutoResize], [120, 'HEIGHT']);
  await assert.rejects(fx.text('x', { family: 'Missing' }), /font Missing Regular is not available/);
  await assert.rejects(fx.text('x', { textStyle: 'Nope' }), /no text style Nope/);
});

test('instance: by set id, name or key; variant props pick the variant, short property names map to keys', async () => {
  const fx = fresh();
  await fonts();
  const set = buttonSet(figma.currentPage);
  const screen = await fx.frame({ name: 'Screen', dir: 'V', w: 375 });
  const a = await fx.instance(set.id, { Variant: 'Secondary', Label: 'Go' }, { parent: screen, name: 'Submit', w: 'fill' });
  const main = await a.getMainComponentAsync();
  assert.equal(main.name, 'Variant=Secondary, State=Default');
  assert.equal(a.parent, screen);
  assert.equal(a.name, 'Submit');
  assert.equal(a.layoutSizingHorizontal, 'FILL');
  assert.equal(a.findOne((n) => n.type === 'TEXT').characters, 'Go');
  const b = await fx.instance('Button', { state: 'disabled' });
  assert.equal((await b.getMainComponentAsync()).name, 'Variant=Primary, State=Disabled');
  const key = 'a'.repeat(40);
  figma.importComponentSetByKeyAsync = async (k) => { if (k === key) return set; throw new Error('not published'); };
  figma.importComponentByKeyAsync = async () => { throw new Error('a set key'); };
  const c = await fx.instance(key, {});
  assert.equal((await c.getMainComponentAsync()).parent, set);
  await assert.rejects(fx.instance(set.id, { Colour: 'x' }), /unknown property Colour on Button; has Variant, State, Label/);
  await assert.rejects(fx.instance(set.id, { Variant: 'Ghost' }), /no variant of Button/);
  await assert.rejects(fx.instance('Nope', {}), /no component named Nope/);
  await assert.rejects(fx.instance(screen.id, {}), /not a component/);
});

test('instance: a variant id keeps that variant; props change only the axes they name', async () => {
  const fx = fresh();
  await fonts();
  const set = buttonSet(figma.currentPage);
  const secondaryDisabled = set.children.find((c) => c.name === 'Variant=Secondary, State=Disabled');
  const a = await fx.instance(secondaryDisabled.id, {});
  assert.equal((await a.getMainComponentAsync()).name, 'Variant=Secondary, State=Disabled');
  const b = await fx.instance(secondaryDisabled.id, { State: 'Default' });
  assert.equal((await b.getMainComponentAsync()).name, 'Variant=Secondary, State=Default');
});

test('instance: a TEXT property loads the font of the layers it drives first', async () => {
  const fx = fresh();
  await fonts();
  const set = buttonSet(figma.currentPage);
  figma._unloadFonts();
  const a = await fx.instance(set.id, { Label: 'Go' });
  assert.equal(a.findOne((n) => n.type === 'TEXT').characters, 'Go');
});

test('text: a style id that is not a text style is refused by name', async () => {
  const fx = fresh();
  const paint = figma.createPaintStyle();
  await assert.rejects(fx.text('x', { textStyle: paint.id }), new RegExp('no text style ' + paint.id));
});

test('inventory: an effect with no blur radius prints its type alone', async () => {
  const fx = fresh();
  const grain = figma.createEffectStyle();
  grain.name = 'Grain';
  grain.effects = [{ type: 'NOISE', noiseType: 'MONOTONE', noiseSize: 1, density: 0.5, visible: true, blendMode: 'NORMAL',
    color: { r: 0, g: 0, b: 0, a: 0.25 } }];
  const out = await fx.inventory({ match: 'Grain' });
  assert.equal(out.text, 'EFFECT Grain [' + grain.id + '] NOISE #00000040');
});

test('bindFill: variable when a value matches, else a matching paint style, else raw; ids and names too', async () => {
  const fx = fresh();
  const tk = tokens();
  const red = figma.createPaintStyle();
  red.name = 'Brand/Red';
  red.paints = [solid('#ff0000')];
  const f = figma.createFrame();
  assert.deepEqual(await fx.bindFill(f, '#2563EB'), { bound: 'variable', id: tk.primary.id });
  assert.equal(f.fills[0].boundVariables.color.id, tk.primary.id);
  assert.equal(fx.hex(f.fills[0].color), '#2563eb');
  assert.deepEqual(await fx.bindFill(f, '#f00'), { bound: 'style', id: red.id });
  assert.equal(f.fillStyleId, red.id);
  assert.deepEqual(await fx.bindFill(f, '#123456'), { bound: 'raw', id: null });
  assert.equal(fx.hex(f.fills[0].color), '#123456');
  assert.deepEqual(await fx.bindFill(f, tk.blue), { bound: 'variable', id: tk.blue.id });
  assert.deepEqual(await fx.bindFill(f.id, tk.blue.id, 'strokes'), { bound: 'variable', id: tk.blue.id });
  assert.equal(f.strokes[0].boundVariables.color.id, tk.blue.id);
  assert.deepEqual(await fx.bindFill(f, red.id, 'strokes'), { bound: 'style', id: red.id });
  assert.equal(f.strokeStyleId, red.id);
  assert.deepEqual(await fx.bindFill(f, 'Brand/Red'), { bound: 'style', id: red.id });
  const late = figma.variables.createVariable('color/late', tk.col, 'COLOR');
  late.setValueForMode('m1', { r: 1, g: 1, b: 0, a: 1 });
  assert.deepEqual(await fx.bindFill(f, '#ffff00'), { bound: 'variable', id: late.id }, 'a miss rescans before falling back to raw');
  await assert.rejects(fx.bindFill(f, 'color/nope'), /no color variable or paint style named color\/nope/);
});

// ---- audit

test('audit: counts every structural problem with capped offending ids', async () => {
  const fx = fresh();
  await fonts();
  const tk = tokens();
  const page = figma.currentPage;
  const screen = mkFrame(page, 'Screen', 'VERTICAL', 400, 800);
  screen.layoutSizingHorizontal = 'FIXED';
  screen.fills = [solid('#2563eb')];
  const rows = [row(screen, 'One'), row(screen, 'Two'), row(screen, 'Three')];
  const box = mkFrame(screen, null, null, 50, 50);
  const rect = figma.createRectangle(); rect.name = 'Swatch'; box.appendChild(rect);
  const r2 = figma.createRectangle(); r2.name = 'Dot'; box.appendChild(r2);
  const group = figma.group([r2], box);
  const badge = mkFrame(screen, 'Badge');
  badge.layoutPositioning = 'ABSOLUTE';
  const none = mkText(screen, 'Clipped');
  none.textAutoResize = 'NONE';
  const wide = mkText(screen, 'Too wide');
  wide.resize(500, 20);
  const card = figma.createComponent();
  card.name = 'Card';
  const cardText = mkText(card, 'Card title');
  const chip = figma.createComponent();
  chip.name = 'Chip';
  chip.layoutMode = 'HORIZONTAL';
  mkText(chip, 'Chip label');
  chip.addComponentProperty('Label', 'TEXT', 'Chip');
  screen.appendChild(chip.createInstance());

  const a = await fx.audit(page.id, { limit: 2 });
  assert.equal(a.root, page.id);
  assert.deepEqual(a.counts, {
    rawRepeats: 3, fixedInFlow: 1, absDefaultConstraints: 3, groups: 1,
    defaultNames: 2, unboundPaints: 1, textFixedInAutoLayout: 1, textOverflow: 1, componentsWithoutAutoLayout: 1, unlinkedProps: 1,
    danglingReactions: 0, lostHover: 0, overlayNotFullSize: 0,
  });
  assert.deepEqual(a.shares, { instanceRatio: 0.1, autoLayoutShare: 0.8 });
  assert.deepEqual(a.ids.rawRepeats, [rows[0].id, rows[1].id]);
  assert.deepEqual(a.ids.fixedInFlow, [box.id]);
  assert.deepEqual(a.ids.absDefaultConstraints, [badge.id, group.id]);
  assert.deepEqual(a.ids.groups, [group.id]);
  assert.deepEqual(a.ids.defaultNames, [box.id, group.id]);
  assert.deepEqual(a.ids.unboundPaints, [screen.id]);
  assert.deepEqual(a.ids.textFixedInAutoLayout, [none.id]);
  assert.deepEqual(a.ids.textOverflow, [wide.id]);
  assert.deepEqual(a.ids.componentsWithoutAutoLayout, [card.id]);
  assert.deepEqual(a.ids.unlinkedProps, [chip.id + ':Label']);
  assert.ok(cardText);
  assert.ok(!('instanceRatio' in a.ids));
  const lines = a.text.split('\n');
  assert.equal(lines.length, 10, 'one line per nonzero count');
  assert.equal(lines[0], 'rawRepeats 3 [' + rows[0].id + ',' + rows[1].id + ',...] -> make one component, replace the copies with instances');
  assert.ok(lines.includes('groups 1 [' + group.id + '] -> replace the group with an auto-layout frame'), a.text);
});

test('audit: a clean component-built screen has no problems', async () => {
  const fx = fresh();
  await fonts();
  const tk = tokens();
  const chip = await fx.frame({ component: true, name: 'Chip', dir: 'H', pad: 4 });
  const label = await fx.text('Chip', { parent: chip, name: 'Label' });
  label.componentPropertyReferences = { characters: chip.addComponentProperty('Label', 'TEXT', 'Chip') };
  const screen = await fx.frame({ name: 'Screen', dir: 'V', w: 375, fill: '#2563eb' });
  for (const s of ['One', 'Two', 'Three']) await fx.instance(chip.id, { Label: s }, { parent: screen });
  const a = await fx.audit(screen.id);
  for (const k of Object.keys(a.counts)) assert.equal(a.counts[k], 0, k + ': ' + JSON.stringify(a.ids[k]));
  assert.deepEqual(a.shares, { instanceRatio: 0.75, autoLayoutShare: 1 });
  assert.deepEqual(a.ids, {});
  assert.equal(a.text, '');
  assert.ok(tk);
});

test('recon and audit load a page other than the current one before reading it', async () => {
  const fx = fresh();
  const other = figma.createPage();
  other.name = 'Other';
  await figma.setCurrentPageAsync(other);
  mkFrame(other, 'Screen', 'VERTICAL', 375, 812);
  await figma.setCurrentPageAsync(figma.root.children[0]);
  assert.ok(!other._raw._loaded);
  assert.match((await fx.recon({ nodeId: other.id })).tree, /FRAME "Screen"/);
  assert.ok(other._raw._loaded);
  other._raw._loaded = false;
  assert.equal((await fx.audit(other.id)).nodes, 1);
  assert.ok(other._raw._loaded);
});

test('measure: the counts tests/eval/lib.js quality() is built on', async () => {
  const fx = fresh();
  await fonts();
  const screen = mkFrame(figma.currentPage, 'Screen', 'VERTICAL', 400, 800);
  row(screen, 'One');
  const stack = mkFrame(screen, 'Stack', null, 50, 50);
  mkText(stack, 'a'); mkText(stack, 'b');
  const m = fx.measure(figma.currentPage.findAll());
  assert.deepEqual([m.containers.length, m.auto.length, m.stacks.length, m.flow.length, m.fixedFlow.length,
    m.instances.length, m.rawFrames.length, m.defaultNamed.length], [4, 3, 1, 6, 1, 0, 4, 0]);
});

// ---- prototyping

// A Toggle set, State=Default|Hover, with hover on Default as an interactive component.
async function hoverSet(fx, parent) {
  const def = figma.createComponent(); def.name = 'State=Default';
  const hov = figma.createComponent(); hov.name = 'State=Hover';
  const set = figma.combineAsVariants([def, hov], parent);
  set.name = 'Toggle';
  await fx.react(def, [{ on: 'hover', do: { to: hov, nav: 'change' } }]);
  return { set, def, hov };
}

test('react: triggers and actions map to Plugin API reactions with default transitions', async () => {
  const fx = fresh();
  const page = figma.currentPage;
  const a = mkFrame(page, 'A', null, 400, 300), b = mkFrame(page, 'B', null, 400, 300);
  const btn = mkFrame(a, 'Button', null, 80, 32);
  assert.equal(await fx.react(btn.id, [
    { on: 'click', do: { to: b } },
    { on: 'hover', do: { to: b.id, nav: 'overlay', anim: 'dissolve', ms: 150 } },
    { on: { key: 27 }, do: 'back' },
    { on: { after: 800 }, do: 'close' },
    { on: 'press', do: { to: b, nav: 'swap', anim: 'push-right' } },
  ]), btn);
  const rs = btn.reactions;
  assert.deepEqual(rs.map((r) => r.trigger), [
    { type: 'ON_CLICK' }, { type: 'ON_HOVER' }, { type: 'ON_KEY_DOWN', device: 'KEYBOARD', keyCodes: [27] },
    { type: 'AFTER_TIMEOUT', timeout: 800 }, { type: 'ON_PRESS' },
  ]);
  const act = rs.map((r) => r.actions[0]);
  assert.deepEqual(act[0], { type: 'NODE', destinationId: b.id, navigation: 'NAVIGATE', preserveScrollPosition: false,
    transition: { type: 'SMART_ANIMATE', easing: { type: 'EASE_IN_AND_OUT' }, duration: 0.3 } });
  assert.equal(act[1].navigation, 'OVERLAY');
  assert.deepEqual(act[1].transition, { type: 'DISSOLVE', easing: { type: 'EASE_OUT' }, duration: 0.15 });
  assert.equal(act[1].resetScrollPosition, true);
  assert.deepEqual(act[2], { type: 'BACK' });
  assert.deepEqual(act[3], { type: 'CLOSE' });
  assert.equal(act[4].navigation, 'SWAP');
  assert.equal(act[4].transition.type, 'PUSH');
  assert.equal(act[4].transition.direction, 'RIGHT');
});

test('react: replaces reactions unless append, which swaps only the triggers it names', async () => {
  const fx = fresh();
  const page = figma.currentPage;
  const a = mkFrame(page, 'A'), b = mkFrame(page, 'B'), c = mkFrame(page, 'C');
  await fx.react(a, [{ on: 'click', do: { to: b } }, { on: 'hover', do: { to: b, nav: 'overlay' } }]);
  await fx.react(a, [{ on: 'click', do: { to: c } }], { append: true });
  assert.deepEqual(a.reactions.map((r) => r.trigger.type + '>' + r.actions[0].destinationId), ['ON_HOVER>' + b.id, 'ON_CLICK>' + c.id]);
  await fx.react(a, [{ on: { key: 27 }, do: 'close' }]);
  assert.deepEqual(a.reactions.map((r) => r.trigger.type), ['ON_KEY_DOWN']);
});

test('react: refuses an unknown trigger, a missing destination and CHANGE_TO to a non-variant', async () => {
  const fx = fresh();
  const page = figma.currentPage;
  const a = mkFrame(page, 'A'), b = mkFrame(page, 'B');
  await assert.rejects(fx.react(a, [{ on: 'drag', do: 'back' }]), /unknown trigger/);
  await assert.rejects(fx.react(a, [{ on: 'click', do: { to: '9:999' } }]), /not found/);
  const other = figma.createPage(), far = mkFrame(other, 'Far');
  await assert.rejects(fx.react(a, [{ on: 'click', do: { to: far } }]), /rejected/, 'a destination on another page');
  await assert.rejects(fx.react(a, [{ on: 'click', do: { to: b, nav: 'change' } }]), /CHANGE_TO needs a variant/);
  await assert.rejects(fx.react(a, [{ on: 'click', do: { to: b, nav: 'teleport' } }]), /unknown nav/);
  const { def, hov } = await hoverSet(fx, page);
  assert.deepEqual(def.reactions[0].actions[0], { type: 'NODE', destinationId: hov.id, navigation: 'CHANGE_TO', transition: null,
    preserveScrollPosition: false });
});

test('overlayFrame: base-sized, see-through, items in place over a scrim that closes, Esc closes', async () => {
  const fx = fresh();
  const page = figma.currentPage;
  const base = mkFrame(page, 'Home', null, 1440, 900);
  base.x = 100; base.y = 50;
  const panel = mkFrame(page, 'Menu', null, 240, 320);
  const old = mkFrame(page, 'Menu overlay');
  const f = await fx.overlayFrame({ base: base.id, name: 'Menu overlay', items: [{ node: panel, x: 1180, y: 64 }] });
  assert.ok(old.removed);
  assert.deepEqual([f.name, f.parent, f.width, f.height, f.x, f.y, f.fills.length, f.clipsContent],
    ['Menu overlay', page, 1440, 900, 100, 50 + 900 + 200, 0, false]);
  assert.deepEqual(f.children.map((c) => c.name), ['Scrim', 'Menu']);
  const scrim = f.children[0];
  assert.deepEqual([scrim.width, scrim.height, scrim.fills.length, scrim.constraints.horizontal], [1440, 900, 0, 'STRETCH']);
  assert.deepEqual(scrim.reactions.map((r) => [r.trigger.type, r.actions[0].type]), [['ON_CLICK', 'CLOSE']]);
  assert.deepEqual([panel.x, panel.y], [1180, 64]);
  assert.deepEqual(f.reactions.map((r) => [r.trigger, r.actions[0].type]),
    [[{ type: 'ON_KEY_DOWN', device: 'KEYBOARD', keyCodes: [27] }, 'CLOSE']]);
  const bare = await fx.overlayFrame({ base, name: 'Toast', items: [mkFrame(page, 'T')], scrim: false });
  assert.deepEqual(bare.children.map((c) => c.name), ['T']);
});

test('flow: adds or renames a page flow starting point, one per frame and name', async () => {
  const fx = fresh();
  const page = figma.currentPage;
  const a = mkFrame(page, 'A'), b = mkFrame(page, 'B');
  await fx.flow(page, a, 'Main');
  await fx.flow(page.id, b.id, 'Settings');
  assert.deepEqual(await fx.flow(page, a, 'Onboarding'), [{ nodeId: b.id, name: 'Settings' }, { nodeId: a.id, name: 'Onboarding' }]);
  assert.deepEqual(page.flowStartingPoints, [{ nodeId: b.id, name: 'Settings' }, { nodeId: a.id, name: 'Onboarding' }]);
});

test('audit: dangling destinations, instances whose own reactions dropped the hover, small overlays', async () => {
  const fx = fresh();
  const page = figma.currentPage;
  const { def } = await hoverSet(fx, page);
  const home = mkFrame(page, 'Home', null, 1440, 900), next = mkFrame(page, 'Next', null, 1440, 900);
  const gone = mkFrame(page, 'Gone');
  const link = mkFrame(home, 'Link'), dropped = mkFrame(home, 'Dropped');
  await fx.react(link, [{ on: 'click', do: { to: gone } }]);
  await fx.react(dropped, [{ on: 'click', do: { to: gone } }]);
  page.flowStartingPoints = [{ nodeId: gone.id, name: 'Gone' }];
  gone.remove();
  assert.deepEqual([dropped.reactions, page.flowStartingPoints], [[], []], 'Figma drops links to a removed node');
  // A stale reaction written some other way, which the Plugin API itself never leaves.
  link._raw._reactions = [{ trigger: { type: 'ON_CLICK' }, actions: [{ type: 'NODE', destinationId: gone.id, navigation: 'NAVIGATE' }] }];
  const kept = def.createInstance(); home.appendChild(kept);
  const lost = def.createInstance(); home.appendChild(lost);
  await fx.react(lost, [{ on: 'click', do: { to: next } }]);
  const emptied = def.createInstance(); home.appendChild(emptied);
  await emptied.setReactionsAsync([]);
  const fixed = def.createInstance(); home.appendChild(fixed);
  await fx.react(fixed, [{ on: 'click', do: { to: next } }, { on: 'hover', do: { to: def.parent.children[1], nav: 'change' } }]);
  const small = mkFrame(page, 'Small menu', null, 240, 320);
  const full = await fx.overlayFrame({ base: home, name: 'Full menu', items: [] });
  const opener = mkFrame(home, 'Opener');
  await fx.react(opener, [{ on: 'click', do: { to: small, nav: 'overlay' } }, { on: 'hover', do: { to: full, nav: 'overlay' } }]);
  const a = await fx.audit(page.id);
  assert.deepEqual([a.counts.danglingReactions, a.counts.lostHover, a.counts.overlayNotFullSize], [1, 2, 1]);
  assert.deepEqual(a.ids.danglingReactions, [link.id]);
  assert.deepEqual(a.ids.lostHover, [lost.id, emptied.id]);
  assert.deepEqual(a.ids.overlayNotFullSize, [opener.id]);
});

// ---- presence and stale (figma_run.py --ns)

async function run(fx, ns, v) { const refused = fx.stale(ns); return refused || fx.presence(ns, await v); }

test('presence: notes a write under another worker\'s frame and a component it already made', async () => {
  const fx = fresh();
  const a = mkFrame(figma.currentPage, 'A'), b = mkFrame(figma.currentPage, 'B');
  assert.deepEqual(await run(fx, 'a_', { rootId: a.id, createdNodeIds: [] }), { rootId: a.id, createdNodeIds: [] });
  const mine = mkFrame(b, 'Row');
  const ok = await run(fx, 'b_', { rootId: b.id, createdNodeIds: [mine.id] });
  assert.ok(!('fxNote' in ok), 'disjoint writes get no note');
  const stray = mkFrame(a, 'Stray');
  const crossed = await run(fx, 'b_', { rootId: b.id, createdNodeIds: [stray.id] });
  assert.match(crossed.fxNote, new RegExp("another worker's frame: " + stray.id + ' \\(in ' + a.id + ', a_\\)'));
  assert.deepEqual(crossed.createdNodeIds, [stray.id], 'the value is kept');

  const c1 = figma.createComponent(); c1.name = 'Chip'; a.appendChild(c1);
  await run(fx, 'a_', { rootId: a.id, createdNodeIds: [c1.id] });
  const c2 = figma.createComponent(); c2.name = 'Chip'; b.appendChild(c2);
  const dup = await run(fx, 'b_', { rootId: b.id, createdNodeIds: [c2.id] });
  assert.match(dup.fxNote, new RegExp('already made Chip \\(a_ made ' + c1.id + '\\)'));
  assert.equal(await run(fx, 'b_', 'plain'), 'plain', 'a value without ids passes through');
});

test('presence: a lapsed claim no longer counts', async () => {
  const fx = fresh();
  const a = mkFrame(figma.currentPage, 'A');
  await run(fx, 'a_', { rootId: a.id });
  window.__fxPresence.claims[a.id].ts -= 600001;
  const stray = mkFrame(a, 'Stray');
  assert.ok(!('fxNote' in await run(fx, 'b_', { createdNodeIds: [stray.id] })));
});

test('stale: a collaborator\'s edit in a claimed frame refuses the next eval once', async () => {
  const fx = fresh();
  const a = mkFrame(figma.currentPage, 'A'), other = mkFrame(figma.currentPage, 'Other');
  const row = mkFrame(a, 'Row');
  await run(fx, 'a_', { rootId: a.id });
  figma._nodeChange([{ node: other }, { node: row, origin: 'LOCAL' }]);
  assert.equal(fx.stale('a_'), null, 'edits outside the frame, and this client\'s own, pass');
  figma._nodeChange([{ node: row }]);
  const r = fx.stale('a_');
  assert.deepEqual([r.applied, r.reason, r.changed], [false, 'stale', [row.id]]);
  assert.equal(fx.stale('a_'), null, 'the re-read goes through');
  assert.equal(fx.stale('b_'), null, 'a worker without a claim is never refused');
});

test('stale: keeps watching after the current page changes', async () => {
  const fx = fresh();
  const p2 = figma.createPage();
  await figma.setCurrentPageAsync(p2);
  const a = mkFrame(p2, 'A');
  await run(fx, 'a_', { rootId: a.id });
  figma._nodeChange([{ node: a }]);
  assert.equal(fx.stale('a_').reason, 'stale');
});
