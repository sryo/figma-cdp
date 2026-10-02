// Shared helpers for eval seeds, scorers and harness ops. run.py composes every script as
//   (async function (EVAL) { <lib.js> <script body> })(<json>)
// so a body sees these helpers and `EVAL` = {task, rep, prefix, pageId, pageName, expect,
// seed (the seed's return value, scorers only), answer (the session's final text, scorers only)}.
// Plain Plugin API, no optional chaining: it runs in Figma's sandbox and in tests/figma_stub.js.

var DEFAULT_NAME = /^(Frame|Rectangle|Group|Ellipse|Text|Vector|Line|Polygon|Star|Component|Instance|Section)( \d+)?$/;

function belongs(name) { return name === EVAL.prefix || name.indexOf(EVAL.prefix + ' · ') === 0; }
function evalPages() { return figma.root.children.filter(function (p) { return belongs(p.name); }); }
async function loadPage(p) { if (p && typeof p.loadAsync === 'function') await p.loadAsync(); return p; }
async function targetPage() { return loadPage(await figma.getNodeByIdAsync(EVAL.pageId)); }
function round(v) { return Math.round(v * 1000) / 1000; }
function share(num, den) { return den ? round(num / den) : 0; }

function toHex(c) {
  function h(v) { var s = Math.round(v * 255).toString(16); return s.length < 2 ? '0' + s : s; }
  return '#' + h(c.r) + h(c.g) + h(c.b);
}
function fromHex(hex) {
  var n = parseInt(hex.slice(1), 16);
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 };
}
function near(a, b) {
  var x = fromHex(a), y = fromHex(b);
  return Math.abs(x.r - y.r) * 255 <= 3 && Math.abs(x.g - y.g) * 255 <= 3 && Math.abs(x.b - y.b) * 255 <= 3;
}
function norm(s) { return String(s).replace(/\s+/g, ' ').trim().toLowerCase(); }
function baseName(name) { var parts = String(name).split('/'); return parts[parts.length - 1].toLowerCase().replace(/[^a-z0-9]/g, ''); }

function inInstance(n) { for (var p = n.parent; p; p = p.parent) if (p.type === 'INSTANCE') return true; return false; }
function inComponent(n) { for (var p = n.parent; p; p = p.parent) if (p.type === 'COMPONENT' || p.type === 'COMPONENT_SET') return true; return false; }
// What the screen shows: every node on the page except component definitions.
function screenNodes(page) { return page.findAll(function (n) { return n.type !== 'COMPONENT_SET' && n.type !== 'COMPONENT' && !inComponent(n); }); }
function nodesOf(pages) {
  var out = [];
  pages.forEach(function (p) { out = out.concat(p.findAll()); });
  return out;
}
function solidPaints(n) {
  var out = [];
  ['fills', 'strokes'].forEach(function (k) {
    var v = n[k];
    if (!v || v === figma.mixed || !v.length) return;
    v.forEach(function (p) { if (p.type === 'SOLID' && p.visible !== false) out.push(p); });
  });
  return out;
}

// Share of the expected strings some text layer shows (case and whitespace folded).
function copyMatch(expected, nodes) {
  var texts = nodes.filter(function (n) { return n.type === 'TEXT'; }).map(function (n) { return norm(n.characters); });
  var hit = expected.filter(function (s) {
    var want = norm(s);
    return texts.some(function (t) { return t === want || t.indexOf(want) !== -1; });
  });
  return share(hit.length, expected.length);
}
// onPalette: share of distinct solid colors in use that are a source token;
// tokensUsed: share of the screen's expected tokens that appear.
function colorMatch(keys, nodes) {
  var palette = Object.keys(EVAL.expect.colors).map(function (k) { return EVAL.expect.colors[k]; });
  var used = {};
  nodes.forEach(function (n) { solidPaints(n).forEach(function (p) { used[toHex(p.color)] = 1; }); });
  var hexes = Object.keys(used);
  var on = hexes.filter(function (h) { return palette.some(function (t) { return near(h, t); }); });
  var present = keys.filter(function (k) { return hexes.some(function (h) { return near(h, EVAL.expect.colors[k]); }); });
  return { onPalette: share(on.length, hexes.length), tokensUsed: share(present.length, keys.length) };
}

// Design-quality metrics over every node on the run's pages. QUALITY_LOWER names the metrics
// where less is better; the rest are better higher.
async function quality(pages) {
  var all = nodesOf(pages);
  var own = all.filter(function (n) { return !inInstance(n); });
  var containers = own.filter(function (n) {
    return (n.type === 'FRAME' || n.type === 'COMPONENT') && n.children && n.children.length >= 1;
  });
  var auto = containers.filter(function (n) { return n.layoutMode && n.layoutMode !== 'NONE'; });
  var stacks = containers.filter(function (n) { return n.children.length >= 2 && auto.indexOf(n) === -1; });
  var flowKids = [], sized = 0, absKids = [], constrained = 0;
  auto.forEach(function (f) {
    f.children.forEach(function (c) {
      if (c.layoutPositioning === 'ABSOLUTE') {
        absKids.push(c);
        if (c.constraints && (c.constraints.horizontal !== 'MIN' || c.constraints.vertical !== 'MIN')) constrained++;
        return;
      }
      if (c.type === 'RECTANGLE' || c.type === 'ELLIPSE' || c.type === 'VECTOR' || c.type === 'LINE') return;
      flowKids.push(c);
      if (c.layoutSizingHorizontal !== 'FIXED' || c.layoutSizingVertical !== 'FIXED') sized++;
    });
  });
  var instances = own.filter(function (n) { return n.type === 'INSTANCE'; });
  var rawFrames = own.filter(function (n) { return n.type === 'FRAME' && !inComponent(n); });
  var comps = all.filter(function (n) {
    return n.type === 'COMPONENT_SET' || (n.type === 'COMPONENT' && !(n.parent && n.parent.type === 'COMPONENT_SET'));
  });
  var byBase = {};
  comps.forEach(function (c) { var b = baseName(c.name); byBase[b] = (byBase[b] || 0) + 1; });
  var dup = 0;
  Object.keys(byBase).forEach(function (b) { dup += byBase[b] - 1; });
  var detached = rawFrames.filter(function (f) { return byBase[baseName(f.name)]; }).length;
  var named = own.filter(function (n) { return DEFAULT_NAME.test(n.name); }).length;
  var m = {
    autoLayoutShare: share(auto.length, containers.length),
    absoluteStacks: stacks.length,
    sizingShare: share(sized, flowKids.length),
    constrainedAbsShare: absKids.length ? share(constrained, absKids.length) : 1,
    instanceRatio: share(instances.length, instances.length + rawFrames.length),
    duplicateComponents: dup,
    detachedLike: detached,
    defaultNames: named,
  };
  var vars = await figma.variables.getLocalVariablesAsync('COLOR');
  if (vars.length) {
    var bound = 0, hard = 0;
    own.forEach(function (n) {
      if (n.fillStyleId && typeof n.fillStyleId === 'string') { bound++; return; }
      solidPaints(n).forEach(function (p) { if (p.boundVariables && p.boundVariables.color) bound++; else hard++; });
    });
    m.boundPaintShare = share(bound, bound + hard);
    m.hardcodedPaints = hard;
  }
  return m;
}
var QUALITY_LOWER = ['absoluteStacks', 'duplicateComponents', 'detachedLike', 'defaultNames', 'hardcodedPaints'];

// Instances on the run's pages whose main component (or its set) is one of ids.
async function instancesOf(pages, ids) {
  var out = [];
  var insts = nodesOf(pages).filter(function (n) { return n.type === 'INSTANCE'; });
  for (var i = 0; i < insts.length; i++) {
    var main = await insts[i].getMainComponentAsync();
    if (!main) continue;
    var set = main.parent && main.parent.type === 'COMPONENT_SET' ? main.parent : null;
    if (ids.indexOf(main.id) !== -1 || (set && ids.indexOf(set.id) !== -1)) out.push({ node: insts[i], main: main, set: set });
  }
  return out;
}

// Order-sensitive fingerprint of a subtree: ids, types, names, text and geometry.
function signature(n) {
  var s = [n.id, n.type, n.name, n.type === 'TEXT' ? n.characters : '', Math.round(n.x), Math.round(n.y),
    Math.round(n.width), Math.round(n.height)].join('|');
  return s + '[' + (n.children || []).map(signature).join(',') + ']';
}
function hash(s) { var h = 5381; for (var i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0; return h.toString(16); }

// ---- building helpers for seeds ---------------------------------------------

var FONTS = { Regular: 1, Medium: 1, Bold: 1 };
async function loadFonts() { for (var s in FONTS) await figma.loadFontAsync({ family: 'Inter', style: s }); }
function paintOf(key, vars) {
  var p = { type: 'SOLID', color: fromHex(EVAL.expect.colors[key] || key) };
  return vars && vars[key] ? figma.variables.setBoundVariableForPaint(p, 'color', vars[key]) : p;
}
function mkText(parent, chars, opts) {
  opts = opts || {};
  var t = figma.createText();
  t.fontName = { family: 'Inter', style: opts.style || 'Regular' };
  t.characters = chars;
  t.fontSize = opts.size || 14;
  t.fills = [paintOf(opts.color || 'text', opts.vars)];
  t.name = opts.name || chars;
  parent.appendChild(t);
  return t;
}
function mkFrame(parent, name, dir, opts) {
  opts = opts || {};
  var f = opts.component ? figma.createComponent() : figma.createFrame();
  f.name = name;
  if (parent) parent.appendChild(f);
  f.layoutMode = dir;
  if (dir !== 'NONE') {
    f.itemSpacing = opts.gap || 0;
    var p = opts.pad || [0, 0, 0, 0];
    f.paddingTop = p[0]; f.paddingRight = p[1]; f.paddingBottom = p[2]; f.paddingLeft = p[3];
    if (opts.align) f.counterAxisAlignItems = opts.align;
    if (opts.justify) f.primaryAxisAlignItems = opts.justify;
  }
  f.fills = opts.fill ? [paintOf(opts.fill, opts.vars)] : [];
  if (opts.stroke) { f.strokes = [paintOf(opts.stroke, opts.vars)]; f.strokeWeight = 1; }
  if (opts.radius) f.cornerRadius = opts.radius;
  if (opts.width) { f.resize(opts.width, f.height); f.layoutSizingHorizontal = 'FIXED'; }
  return f;
}
// A variable collection named "<prefix> tokens" holding one COLOR variable per source token.
function seedTokens() {
  var col = figma.variables.createVariableCollection(EVAL.prefix + ' tokens');
  var mode = col.modes[0].modeId, out = {}, ids = {};
  Object.keys(EVAL.expect.colors).forEach(function (k) {
    var v = figma.variables.createVariable('color/' + k, col, 'COLOR');
    var c = fromHex(EVAL.expect.colors[k]);
    v.setValueForMode(mode, { r: c.r, g: c.g, b: c.b, a: 1 });
    out[k] = v; ids[k] = v.id;
  });
  return { vars: out, ids: ids, collectionId: col.id };
}
// A second page beside the run's page, for seeded libraries.
async function libraryPage() {
  var p = figma.createPage();
  p.name = EVAL.prefix + ' · library';
  return p;
}

// The fixture's Button as a component set on parent: Variant=Primary|Secondary ×
// State=Default|Disabled, a "Label" TEXT property on every variant's label.
function buildButtonSet(parent, vars) {
  var looks = {
    Primary: { fill: 'primary', text: 'on-primary' },
    Secondary: { fill: 'surface', text: 'primary', stroke: 'border' },
  };
  var comps = [], labels = [];
  ['Primary', 'Secondary'].forEach(function (variant) {
    ['Default', 'Disabled'].forEach(function (state) {
      var look = state === 'Disabled' ? { fill: 'disabled-bg', text: 'disabled-text' } : looks[variant];
      var c = mkFrame(parent, 'Variant=' + variant + ', State=' + state, 'HORIZONTAL',
        { component: true, pad: [12, 16, 12, 16], gap: 8, align: 'CENTER', justify: 'CENTER', radius: 6,
          fill: look.fill, stroke: look.stroke, vars: vars });
      labels.push(mkText(c, 'Button', { style: 'Medium', size: 14, color: look.text, name: 'Label', vars: vars }));
      comps.push(c);
    });
  });
  var set = figma.combineAsVariants(comps, parent);
  set.name = 'Button';
  set.layoutMode = 'HORIZONTAL';
  set.itemSpacing = 16;
  var key = set.addComponentProperty('Label', 'TEXT', 'Button');
  labels.forEach(function (t) { t.componentPropertyReferences = { characters: key }; });
  return set;
}
// The fixture's Input as a component on parent, with Label and Placeholder TEXT properties.
function buildInput(parent, vars) {
  var c = mkFrame(parent, 'Input', 'VERTICAL', { component: true, gap: 4, width: 320, vars: vars });
  var label = mkText(c, 'Label', { style: 'Medium', size: 12, color: 'text-muted', name: 'Label', vars: vars });
  var field = mkFrame(c, 'Field', 'HORIZONTAL', { pad: [12, 12, 12, 12], radius: 6, fill: 'surface', stroke: 'border', vars: vars });
  field.layoutSizingHorizontal = 'FILL';
  var ph = mkText(field, 'Placeholder', { size: 14, color: 'text-muted', name: 'Placeholder', vars: vars });
  label.componentPropertyReferences = { characters: c.addComponentProperty('Label', 'TEXT', 'Label') };
  ph.componentPropertyReferences = { characters: c.addComponentProperty('Placeholder', 'TEXT', 'Placeholder') };
  return c;
}
