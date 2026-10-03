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
      // Only raw frames: an instance's or component's size is its design (a 32x32 avatar is
      // FIXED on purpose), and a text layer hugs by default, so neither says anything here.
      if (c.type !== 'FRAME') return;
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

// ---- reading screens built from a fixture's source (tasks with "fixture") -----------------
// EVAL.expect.screens (source.py) says which component usages and layout roles each source
// screen holds, by the strings inside them. Nothing here relies on layer names: a usage is
// found by its key string, and its extent is the outermost ancestor of that string holding no
// string that belongs elsewhere on the screen (its "region"). It counts as an instance when an
// instance (or the main component itself, drawn in place) on that chain carries its key and
// its nested usages' keys.

function isShown(n) { for (var p = n; p && p.type !== 'PAGE'; p = p.parent) if (p.visible === false) return false; return true; }
function isInside(n, root) { for (var p = n; p; p = p.parent) if (p === root) return true; return false; }
function setOf(list) { var o = {}; list.forEach(function (s) { o[norm(s)] = 1; }); return o; }
function minus(a, b) { var o = {}; Object.keys(a).forEach(function (k) { if (!b[k]) o[k] = 1; }); return o; }
function anyIn(held, set) { for (var k in held) if (set[k]) return true; return false; }
function countIn(held, list) { return list.filter(function (s) { return held[norm(s)]; }).length; }
function keyName(k) { return String(k).split('#')[0]; }
function token(s) { return String(s).toLowerCase().replace(/[^a-z0-9]/g, ''); }

// Which shown strings each node on the page holds, computed once.
function textScene(page) {
  var held = {}, texts = [];
  function walk(n, hidden) {
    hidden = hidden || n.visible === false;
    var own = {};
    if (n.type === 'TEXT' && !hidden) {
      var s = norm(n.characters);
      if (s) { own[s] = 1; texts.push({ node: n, s: s }); }
    }
    (n.children || []).forEach(function (c) {
      var h = walk(c, hidden);
      for (var k in h) own[k] = 1;
    });
    held[n.id] = own;
    return own;
  }
  walk(page, false);
  return { page: page, texts: texts, held: function (n) { return held[n.id] || {}; } };
}
// Outermost ancestor of start (up to bound) that holds none of the foreign strings.
function regionFrom(sc, start, foreign, bound) {
  var top = start;
  for (var p = start.parent; p && p.type !== 'PAGE'; p = p.parent) {
    if (anyIn(sc.held(p), foreign)) break;
    top = p;
    if (p === bound) break;
  }
  return top;
}
// Outermost node on the chain start..top that is an instance or a component and holds every key.
function instanceOnChain(sc, start, top, keys) {
  var hit = null;
  for (var p = start; p; p = p.parent) {
    if ((p.type === 'INSTANCE' || p.type === 'COMPONENT') && countIn(sc.held(p), keys) === keys.length) hit = p;
    if (p === top) break;
  }
  return hit;
}
function textless(sc, n) { return Object.keys(sc.held(n)).length === 0; }

// Finds each screen (by its title) and each usage in it. Returns {sc, screens, recs}; a rec is
// {u, screen, parent, text, region, inst, main, owner}: region null when the usage's key is not
// on the page, inst null when it is drawn as plain layers.
async function readScreens(page, screens, expect) {
  var sc = textScene(page);
  var slots = setOf(expect.slots || []);
  var recs = [], claims = {}, out = [];
  function claimed(kind, n) { return claims[kind + '|' + n.id]; }
  function claim(kind, n) { claims[kind + '|' + n.id] = 1; }

  function match(usages, bound, screenSet, parent, screen) {
    var keyed = [], icons = [];
    usages.forEach(function (u) {
      var rec = { u: u, screen: screen, parent: parent, text: null, region: null, inst: null, main: null, owner: null };
      recs.push(rec);
      if (u.key === null) { icons.push(rec); return; }
      keyed.push(rec);
      var foreign = minus(screenSet, setOf(u.texts));
      var want = norm(u.key), best = null, bestScore = -1;
      sc.texts.forEach(function (t) {
        if (t.s !== want || claimed(u.c, t.node) || (bound && !isInside(t.node, bound))) return;
        var r = regionFrom(sc, t.node, foreign, bound);
        var score = countIn(sc.held(r), u.texts);
        if (score > bestScore) { best = { t: t.node, r: r }; bestScore = score; }
      });
      if (best) {
        claim(u.c, best.t);
        rec.text = best.t;
        rec.region = best.r;
        var keys = [u.key];
        if (!slots[norm(u.c)]) u.kids.forEach(function (k) { if (k.key !== null) keys.push(k.key); });
        rec.inst = instanceOnChain(sc, best.t, best.r, keys);
      }
      match(u.kids, rec.region || bound, screenSet, rec, screen);
    });
    if (!icons.length) return;
    // Icons carry no string: the outermost text-free instances in the parent's region, outside
    // the instances of its other nested usages, in order.
    var root = bound || page;
    var taken = keyed.map(function (r) { return r.inst; }).filter(Boolean);
    var cands = (root.findAll ? root.findAll(function (n) {
      return (n.type === 'INSTANCE' || n.type === 'COMPONENT') && isShown(n) && textless(sc, n);
    }) : []).filter(function (n) {
      if (claimed('Icon', n)) return false;
      if (taken.some(function (r) { return isInside(n, r); })) return false;
      for (var p = n.parent; p && p !== root; p = p.parent) if ((p.type === 'INSTANCE' || p.type === 'COMPONENT') && textless(sc, p)) return false;
      return true;
    });
    icons.forEach(function (rec, i) {
      var n = cands[i];
      if (!n) return;
      claim('Icon', n);
      rec.region = n;
      rec.inst = n;
    });
  }

  var titles = {};
  screens.forEach(function (s) { titles[s.title] = s; });
  var found = [];
  screens.forEach(function (s) {
    var mine = setOf(s.strings), others = {};
    screens.forEach(function (o) { if (o !== s) Object.keys(setOf(o.strings)).forEach(function (k) { if (!mine[k]) others[k] = 1; }); });
    var want = norm(s.title), best = null, bestScore = -1;
    sc.texts.forEach(function (t) {
      if (t.s !== want) return;
      var top = t.node;
      for (var p = t.node.parent; p && p.type !== 'PAGE'; p = p.parent) { if (anyIn(sc.held(p), others)) break; top = p; }
      var score = countIn(sc.held(top), s.strings);
      if (score > bestScore) { best = top; bestScore = score; }
    });
    found.push({ screen: s, region: best });
    if (best) { match(s.usages, best, mine, null, s); return; }
    (function missing(us, parent) {
      us.forEach(function (u) {
        var rec = { u: u, screen: s, parent: parent, text: null, region: null, inst: null, main: null, owner: null };
        recs.push(rec);
        missing(u.kids, rec);
      });
    })(s.usages, null);
  });
  for (var i = 0; i < recs.length; i++) {
    var r = recs[i];
    if (!r.inst) continue;
    r.main = r.inst.type === 'COMPONENT' ? r.inst : await r.inst.getMainComponentAsync();
    r.owner = r.main && r.main.parent && r.main.parent.type === 'COMPONENT_SET' ? r.main.parent : r.main;
  }
  return { sc: sc, screens: found, recs: recs };
}

function isComponentKind(c, expect) { return c !== 'Screen' && !(expect.roles && expect.roles[c]); }
// Every node a found screen shows (component definitions placed inside it included).
function screenRegionNodes(read) {
  var out = [];
  read.screens.forEach(function (f) { if (f.region) out = out.concat([f.region], f.region.findAll ? f.region.findAll() : []); });
  return out;
}
// Shown text layers on the screens whose string is not in the source (folded; a fragment of a
// source string, or a source string with extra words, counts as sourced).
function inventedCopy(read, strings) {
  var src = Object.keys(setOf(strings));
  return screenRegionNodes(read).filter(function (n) {
    if (n.type !== 'TEXT' || !isShown(n)) return false;
    var s = norm(n.characters);
    if (!s) return false;
    return !src.some(function (x) { return x === s || (s.length >= 4 && x.indexOf(s) !== -1) || (x.length >= 4 && s.indexOf(x) !== -1); });
  }).length;
}

// The value group (source.py AXES) a variant option or property name stands for.
function groupOf(value, spec) {
  var t = token(value);
  if (t.indexOf('is') === 0 && t.length > 2 && !groupOfToken(t, spec)) t = t.slice(2);
  return groupOfToken(t, spec);
}
function groupOfToken(t, spec) {
  for (var g in spec.values) if (spec.values[g].indexOf(t) !== -1) return g;
  return null;
}
function definitions(owner) {
  try { return (owner && owner.componentPropertyDefinitions) || {}; } catch (e) { return {}; }
}
// How a component carries one source axis: a variant property whose options name 2+ of its
// values, a boolean for a two-valued axis, or one boolean per non-default value.
function axisCarrier(defs, axis, spec) {
  var best = null, bestN = 1;
  Object.keys(defs).forEach(function (k) {
    if (defs[k].type !== 'VARIANT') return;
    var gs = {};
    (defs[k].variantOptions || []).forEach(function (o) { var g = groupOf(o, spec); if (g) gs[g] = 1; });
    var n = Object.keys(gs).length;
    if (n > bestN) { best = { kind: 'variant', key: k, groups: gs }; bestN = n; }
  });
  if (best) return best;
  var bools = Object.keys(defs).filter(function (k) { return defs[k].type === 'BOOLEAN'; });
  if (spec.boolean) {
    var b = bools.filter(function (k) { return groupOf(keyName(k), spec) === 'true' || token(keyName(k)) === token(axis); })[0];
    if (b) return { kind: 'bool', key: b, groups: { 'true': 1, 'false': 1 } };
    return null;
  }
  var flags = {}, groups = {};
  bools.forEach(function (k) { var g = groupOf(keyName(k), spec); if (g && g !== spec['default']) { flags[g] = k; groups[g] = 1; } });
  if (!Object.keys(flags).length) return null;
  groups[spec['default']] = 1;
  return { kind: 'flags', flags: flags, groups: groups };
}
function propValues(rec) {
  if (rec.inst.type === 'INSTANCE') return rec.inst.componentProperties || {};
  var out = {}, defs = definitions(rec.owner), vp = rec.main.variantProperties || {};
  Object.keys(defs).forEach(function (k) { out[k] = { type: defs[k].type, value: defs[k].defaultValue }; });
  Object.keys(vp).forEach(function (k) { out[k] = { type: 'VARIANT', value: vp[k] }; });
  return out;
}
function axisValue(rec, carrier, spec) {
  var p = propValues(rec);
  if (carrier.kind === 'variant') return p[carrier.key] ? groupOf(p[carrier.key].value, spec) : null;
  if (carrier.kind === 'bool') return p[carrier.key] ? String(p[carrier.key].value === true || p[carrier.key].value === 'true') : null;
  var on = Object.keys(carrier.flags).filter(function (g) { var v = p[carrier.flags[g]]; return v && (v.value === true || v.value === 'true'); });
  return on.length === 1 ? on[0] : on.length === 0 ? spec['default'] : null;
}

// Component metrics over matched usages. Icons are grouped per icon name (an icon set is many
// components); everything else per source component.
async function componentMetrics(read, expect, pages) {
  var recs = read.recs.filter(function (r) { return isComponentKind(r.u.c, expect); });
  function group(r) { return r.u.c === 'Icon' ? 'Icon:' + r.u.props.name : r.u.c; }
  function ownerId(r) { return r.u.c === 'Icon' ? r.main && r.main.id : r.owner && r.owner.id; }
  var groups = {};
  recs.forEach(function (r) { (groups[group(r)] = groups[group(r)] || []).push(r); });
  var reused = 0, componentized = 0, split = 0;
  Object.keys(groups).forEach(function (g) {
    var rs = groups[g], owners = {};
    rs.forEach(function (r) { if (r.inst && ownerId(r)) owners[ownerId(r)] = 1; });
    var n = Object.keys(owners).length;
    split += Math.max(0, n - 1);
    if (rs.length < 2) return;
    reused++;
    if (n === 1 && rs.every(function (r) { return r.inst; })) componentized++;
  });
  // variant axes
  var cov = [], matched = 0, checked = 0;
  Object.keys(expect.axes).forEach(function (c) {
    if (c === 'Icon') return;
    var rs = recs.filter(function (r) { return r.u.c === c; });
    if (!rs.length) return;
    Object.keys(expect.axes[c]).forEach(function (axis) {
      var spec = expect.axes[c][axis], used = {};
      rs.forEach(function (r) { used[r.u.props[axis]] = 1; });
      var covered = {}, carriers = {};
      rs.forEach(function (r) {
        if (!r.owner || carriers[r.owner.id] !== undefined) return;
        var car = axisCarrier(definitions(r.owner), axis, spec);
        carriers[r.owner.id] = car;
        if (car) Object.keys(car.groups).forEach(function (g) { covered[g] = 1; });
      });
      cov.push(share(Object.keys(used).filter(function (v) { return covered[v]; }).length, Object.keys(used).length));
      rs.forEach(function (r) {
        if (!r.inst) return;
        checked++;
        var car = r.owner ? carriers[r.owner.id] : null;
        if (car && axisValue(r, car, spec) === r.u.props[axis]) matched++;
      });
    });
  });
  // nesting: a usage inside another component's usage is an instance inside that instance
  var nested = recs.filter(function (r) { return r.parent && isComponentKind(r.parent.u.c, expect) && (expect.slots || []).indexOf(r.parent.u.c) === -1; });
  function nestedOk(r) { return !!(r.inst && r.parent.inst && r.inst !== r.parent.inst && isInside(r.inst, r.parent.inst)); }
  var avatars = nested.filter(function (r) { return r.u.c === 'Avatar' && r.parent.u.c === 'ListItem'; });
  // sizing on the boxes the CSS sizes
  var sizeOk = 0, sizeChecks = 0;
  recs.forEach(function (r) {
    var want = expect.sizing[r.u.c];
    if (!want) return;
    var n = r.inst || r.region;
    if (want.h) { sizeChecks++; if (n && n.layoutSizingHorizontal === want.h) sizeOk++; }
    if (want.v) { sizeChecks++; if (n && n.layoutSizingVertical === want.v) sizeOk++; }
  });
  // components nothing on the run's pages instances
  var all = nodesOf(pages), usedIds = {};
  var insts = all.filter(function (n) { return n.type === 'INSTANCE'; });
  for (var i = 0; i < insts.length; i++) {
    var m = await insts[i].getMainComponentAsync();
    if (m) { usedIds[m.id] = 1; if (m.parent && m.parent.type === 'COMPONENT_SET') usedIds[m.parent.id] = 1; }
  }
  recs.forEach(function (r) { if (r.inst && r.inst.type === 'COMPONENT') { usedIds[r.inst.id] = 1; if (r.owner) usedIds[r.owner.id] = 1; } });
  var unused = all.filter(function (n) {
    return (n.type === 'COMPONENT_SET' || (n.type === 'COMPONENT' && !(n.parent && n.parent.type === 'COMPONENT_SET'))) && !usedIds[n.id];
  }).length;
  return {
    usages: recs.length,
    instanceShare: share(recs.filter(function (r) { return r.inst; }).length, recs.length),
    rawUsages: recs.filter(function (r) { return r.region && !r.inst; }).length,
    missingUsages: recs.filter(function (r) { return !r.region && r.u.key !== null; }).length,
    reusedComponentized: share(componentized, reused),
    splitComponents: split,
    unusedComponents: unused,
    variantCoverage: cov.length ? round(cov.reduce(function (a, b) { return a + b; }, 0) / cov.length) : 0,
    variantMatch: share(matched, checked),
    nestedShare: share(nested.filter(nestedOk).length, nested.length),
    listItemAvatarNested: share(avatars.filter(nestedOk).length, avatars.length),
    sizingMatch: share(sizeOk, sizeChecks),
  };
}
var COMPONENT_LOWER = ['rawUsages', 'missingUsages', 'splitComponents', 'unusedComponents', 'inventedCopy'];
