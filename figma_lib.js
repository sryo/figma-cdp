// figma_lib.js: resident helpers, installed once per Figma tab as window.__fx.
// figma_run.py / figma_batch_run.py --lib put this file in front of the script. A copy with a
// higher V replaces the installed one; an equal or older copy returns at its first line, so a
// tab that has it pays one property read. Bump V with every change (tests/figma_lib_test.js
// pins the file's hash to V). Plain Plugin API, ASCII, no optional chaining: tests/eval/run.py
// also loads it into the eval scorers.
(function () {
  var V = 6;
  if (window.__fx && window.__fx.v >= V) return;

  var DEFAULT_NAME = /^(Frame|Rectangle|Group|Ellipse|Text|Vector|Line|Polygon|Star|Component|Instance|Section)( \d+)?$/;
  var SHAPES = { RECTANGLE: 1, ELLIPSE: 1, VECTOR: 1, LINE: 1, POLYGON: 1, STAR: 1, BOOLEAN_OPERATION: 1 };
  var AXIS = { V: 'VERTICAL', H: 'HORIZONTAL', VERTICAL: 'VERTICAL', HORIZONTAL: 'HORIZONTAL', NONE: 'NONE' };
  var ALIGN = { start: 'MIN', center: 'CENTER', end: 'MAX', between: 'SPACE_BETWEEN', baseline: 'BASELINE' };
  var SIZING = { fill: 'FILL', hug: 'HUG', fixed: 'FIXED' };
  var NODE_ID = /^I?\d+:\d+(;\d+:\d+)*$/, KEY = /^[0-9a-f]{40}$/i;

  // ---- shared primitives

  function isAL(n) { return !!(n && n.layoutMode && n.layoutMode !== 'NONE'); }
  function inInstance(n) { for (var p = n.parent; p; p = p.parent) if (p.type === 'INSTANCE') return true; return false; }
  function inComponent(n) {
    for (var p = n.parent; p; p = p.parent) if (p.type === 'COMPONENT' || p.type === 'COMPONENT_SET') return true;
    return false;
  }
  function isVariant(n) { return n.type === 'COMPONENT' && !!n.parent && n.parent.type === 'COMPONENT_SET'; }
  function isDefaultConstraint(n) { var c = n.constraints; return !c || (c.horizontal === 'MIN' && c.vertical === 'MIN'); }
  function round(v) { return Math.round(v * 1000) / 1000; }
  function share(a, b) { return b ? round(a / b) : 0; }
  function clip(s, max) { s = String(s).replace(/\s+/g, ' '); return s.length > max ? s.slice(0, max - 3) + '...' : s; }
  function byte(v) { var s = Math.round(v * 255).toString(16); return s.length < 2 ? '0' + s : s; }
  function hex(c) { return '#' + byte(c.r) + byte(c.g) + byte(c.b); }
  // #rrggbb, plus aa when the alpha (a paint's opacity, else the color's own a) is under 1.
  function hex8(c, alpha) {
    var a = alpha != null ? alpha : c.a != null ? c.a : 1;
    return hex(c) + (a < 1 ? byte(a) : '');
  }
  function parseHex(s) {
    var m = /^#?([0-9a-f]{3}|[0-9a-f]{6})([0-9a-f]{2})?$/i.exec(String(s).trim());
    if (!m) throw new Error('not a hex color: ' + s);
    var h = m[1].length === 3 ? m[1].replace(/./g, '$&$&') : m[1], n = parseInt(h, 16);
    return { color: { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 },
      opacity: m[2] ? parseInt(m[2], 16) / 255 : 1 };
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
  function state() { window.__batchState = window.__batchState || {}; return window.__batchState; }

  async function node(ref) {
    if (ref && typeof ref === 'object') return ref;
    var n = await figma.getNodeByIdAsync(ref);
    if (!n) { await figma.loadAllPagesAsync(); n = await figma.getNodeByIdAsync(ref); }
    if (!n) throw new Error('node ' + ref + ' not found');
    // A page other than the current one has no children to read until it is loaded.
    if (n.type === 'PAGE' && n.loadAsync) await n.loadAsync();
    return n;
  }

  // componentPropertyDefinitions throws on a variant: read it on sets and standalone components only.
  function defs(n) {
    if (n.type !== 'COMPONENT_SET' && (n.type !== 'COMPONENT' || isVariant(n))) return {};
    try { return n.componentPropertyDefinitions || {}; } catch (e) { return {}; }
  }
  function propName(k) { var i = k.lastIndexOf('#'); return i > 0 ? k.slice(0, i) : k; }
  // " Size=sm|md; State=a|b props: Label:TEXT, Icon:INSTANCE_SWAP"
  function describe(owner) {
    var d = defs(owner), axes = [], props = [];
    Object.keys(d).forEach(function (k) {
      if (d[k].type === 'VARIANT') axes.push(k + '=' + (d[k].variantOptions || []).join('|'));
      else props.push(propName(k) + ':' + d[k].type);
    });
    if (owner.type === 'COMPONENT_SET' && !axes.length) {
      var seen = {}, order = [];
      owner.children.forEach(function (c) {
        var vp = c.variantProperties || {};
        Object.keys(vp).forEach(function (k) {
          if (!seen[k]) { seen[k] = []; order.push(k); }
          if (seen[k].indexOf(vp[k]) === -1) seen[k].push(vp[k]);
        });
      });
      axes = order.map(function (k) { return k + '=' + seen[k].join('|'); });
    }
    return (axes.length ? ' ' + axes.join('; ') : '') + (props.length ? ' props: ' + props.join(', ') : '');
  }

  // ---- variables and colors

  async function varContext() {
    var ctx = { vars: {}, cols: {} };
    (await figma.variables.getLocalVariableCollectionsAsync()).forEach(function (c) { ctx.cols[c.id] = c; });
    (await figma.variables.getLocalVariablesAsync()).forEach(function (v) { ctx.vars[v.id] = v; });
    return ctx;
  }
  async function defaultMode(v, ctx) {
    var col = ctx.cols[v.variableCollectionId];
    if (!col && figma.variables.getVariableCollectionByIdAsync) {
      col = await figma.variables.getVariableCollectionByIdAsync(v.variableCollectionId);
    }
    return col ? col.defaultModeId : Object.keys(v.valuesByMode)[0];
  }
  // The default-mode value of v with aliases followed: {value, text, via (first alias target name)}.
  async function resolve(v, ctx) {
    var val = v.valuesByMode[await defaultMode(v, ctx)], via = null, cur = v;
    for (var hops = 0; val && val.type === 'VARIABLE_ALIAS' && hops < 10; hops++) {
      cur = ctx.vars[val.id] || await figma.variables.getVariableByIdAsync(val.id);
      if (!cur) return { value: null, text: 'alias?', via: via };
      if (via === null) via = cur.name;
      val = cur.valuesByMode[await defaultMode(cur, ctx)];
    }
    var text = val && typeof val === 'object' && 'r' in val ? hex8(val)
      : typeof val === 'number' ? String(round(val)) : typeof val === 'string' ? JSON.stringify(val) : String(val);
    return { value: val, text: text + (via ? ' =' + via : ''), via: via };
  }

  // hex8 -> variable (aliases first: the semantic token wins) and -> single-solid paint style.
  var colors = null;
  async function colorIndex(fresh) {
    if (colors && !fresh && Date.now() - colors.at < 3000) return colors;
    var ctx = await varContext(), idx = { at: Date.now(), vars: {}, styles: {}, varByName: {}, styleByName: {} };
    var list = Object.keys(ctx.vars).map(function (id) { return ctx.vars[id]; })
      .filter(function (v) { return v.resolvedType === 'COLOR'; });
    var alias = function (v) {
      var x = v.valuesByMode[Object.keys(v.valuesByMode)[0]];
      return x && x.type === 'VARIABLE_ALIAS' ? 0 : 1;
    };
    list.sort(function (a, b) { return alias(a) - alias(b) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0); });
    for (var i = 0; i < list.length; i++) {
      var r = await resolve(list[i], ctx);
      idx.varByName[list[i].name] = list[i];
      if (r.value && 'r' in r.value) { var k = hex8(r.value); if (!idx.vars[k]) idx.vars[k] = list[i]; }
    }
    (await figma.getLocalPaintStylesAsync()).forEach(function (s) {
      idx.styleByName[s.name] = s;
      var p = s.paints || [];
      if (p.length === 1 && p[0].type === 'SOLID') { var k = hex8(p[0].color, p[0].opacity); if (!idx.styles[k]) idx.styles[k] = s; }
    });
    colors = idx;
    return idx;
  }
  // value: a Variable, 'VariableID:..', 'S:..' (paint style), '#hex', or a variable / paint style name.
  async function paintSource(value) {
    if (value && typeof value === 'object' && value.resolvedType) return { variable: value };
    var s = String(value);
    if (/^VariableID:/.test(s)) {
      var v = await figma.variables.getVariableByIdAsync(s);
      if (!v) throw new Error('no variable ' + s);
      return { variable: v };
    }
    if (/^S:/.test(s)) {
      var st = await figma.getStyleByIdAsync(s);
      if (!st) throw new Error('no style ' + s);
      return { style: st };
    }
    for (var pass = 0; pass < 2; pass++) {
      var idx = await colorIndex(pass > 0);
      if (s.charAt(0) === '#') {
        var c = parseHex(s), k = hex8(c.color, c.opacity);
        if (idx.vars[k]) return { variable: idx.vars[k], color: c.color };
        if (idx.styles[k]) return { style: idx.styles[k] };
        if (pass) return { color: c.color, opacity: c.opacity };
      } else {
        if (idx.varByName[s]) return { variable: idx.varByName[s] };
        if (idx.styleByName[s]) return { style: idx.styleByName[s] };
        if (pass) throw new Error('no color variable or paint style named ' + s);
      }
    }
  }
  // Paints node's fills (or strokes) from value, binding to a variable or style whose value matches.
  async function bindFill(n, value, field) {
    n = await node(n);
    field = field || 'fills';
    var src = await paintSource(value);
    if (src.style) {
      await (field === 'strokes' ? n.setStrokeStyleIdAsync(src.style.id) : n.setFillStyleIdAsync(src.style.id));
      return { bound: 'style', id: src.style.id };
    }
    var color = src.color;
    if (src.variable && !color) {
      var r = await resolve(src.variable, await varContext());
      color = r.value && 'r' in r.value ? { r: r.value.r, g: r.value.g, b: r.value.b } : { r: 0, g: 0, b: 0 };
    }
    var p = { type: 'SOLID', color: color, opacity: src.variable ? 1 : src.opacity };
    if (src.variable) p = figma.variables.setBoundVariableForPaint(p, 'color', src.variable);
    n[field] = [p];
    return { bound: src.variable ? 'variable' : 'raw', id: src.variable ? src.variable.id : null };
  }

  // ---- structure

  // Shape of a subtree two levels deep: "FRAME:H[TEXT,FRAME:V[TEXT,TEXT]]"; c.n counts the levels below n.
  function shape(n, d, c) {
    var s = n.type + (isAL(n) ? ':' + n.layoutMode.charAt(0) : '');
    if (d > 0) c.n++;
    if (d < 2 && n.children && n.children.length) {
      s += '[' + n.children.map(function (k) { return shape(k, d + 1, c); }).join(',') + ']';
    }
    return s;
  }
  function bucket(v) { return Math.round(v / 16) * 16; }
  // Repeated raw subtrees among nodes: frames and groups (outside instances and components) with
  // the same shape and size to 16px, 2+ of them. A group whose members sit inside another group's
  // members is dropped unless 2+ of them stand outside it.
  function patterns(nodes) {
    var groups = {}, keys = [];
    nodes.forEach(function (n) {
      if ((n.type !== 'FRAME' && n.type !== 'GROUP') || !n.children || !n.children.length) return;
      if (inInstance(n) || inComponent(n)) return;
      var c = { n: 0 }, s = shape(n, 0, c);
      if (c.n < 2) return;
      s += ' ~' + bucket(n.width) + 'x' + bucket(n.height);
      if (!groups[s]) { groups[s] = []; keys.push(s); }
      groups[s].push(n);
    });
    keys = keys.filter(function (k) { return groups[k].length >= 2; });
    var member = {};
    keys.forEach(function (k) { groups[k].forEach(function (n) { member[n.id] = k; }); });
    return keys.filter(function (k) {
      var free = groups[k].filter(function (n) {
        for (var p = n.parent; p; p = p.parent) if (member[p.id] && member[p.id] !== k) return false;
        return true;
      });
      return free.length >= 2;
    }).map(function (k) { return { shape: k, nodes: groups[k] }; })
      .sort(function (a, b) { return b.nodes.length - a.nodes.length; });
  }

  // Layout counts over nodes (those inside instances skipped), shared with the eval scorers.
  function measure(nodes) {
    var r = { own: [], containers: [], auto: [], stacks: [], flow: [], fixedFlow: [], abs: [], absDefault: [],
      instances: [], rawFrames: [], defaultNamed: [] };
    nodes.forEach(function (n) {
      if (inInstance(n)) return;
      r.own.push(n);
      if ((n.type === 'FRAME' || n.type === 'COMPONENT') && n.children && n.children.length) {
        r.containers.push(n);
        if (isAL(n)) {
          r.auto.push(n);
          n.children.forEach(function (c) {
            if (c.layoutPositioning === 'ABSOLUTE') {
              r.abs.push(c);
              if (isDefaultConstraint(c)) r.absDefault.push(c);
              return;
            }
            if (SHAPES[c.type]) return;
            r.flow.push(c);
            if (c.layoutSizingHorizontal === 'FIXED' && c.layoutSizingVertical === 'FIXED') r.fixedFlow.push(c);
          });
        } else if (n.children.length >= 2) {
          r.stacks.push(n);
        }
      }
      if (n.type === 'INSTANCE') r.instances.push(n);
      if (n.type === 'FRAME' && !inComponent(n)) r.rawFrames.push(n);
      if (DEFAULT_NAME.test(n.name)) r.defaultNamed.push(n);
    });
    return r;
  }

  // ---- recon

  async function summary(n) {
    var p = [];
    if (n.type === 'TEXT') {
      var c = n.characters;
      if (c && c !== n.name) p.push('"' + clip(c, 50) + '"');
      if (typeof n.fontSize === 'number') p.push(n.fontSize + 'px');
    }
    if (n.type === 'INSTANCE') {
      var m = await n.getMainComponentAsync();
      if (m) p.push('-> ' + (isVariant(m) ? m.parent.name + ' {' + m.name + '}' : m.name));
    }
    if (n.type !== 'TEXT' && n.type !== 'PAGE' && typeof n.width === 'number') p.push(Math.round(n.width) + 'x' + Math.round(n.height));
    if (isAL(n)) p.push('auto:' + n.layoutMode.charAt(0));
    if (n.visible === false) p.push('hidden');
    return p.length ? ' ' + p.join(' ') : '';
  }
  // Pages plus a flat text tree of nodeId (default: the current page, 3 levels; a node: full depth).
  async function recon(o) {
    o = o || {};
    var max = o.maxChars || 8000;
    var root = o.nodeId ? await node(o.nodeId) : figma.currentPage;
    var depth = o.depth != null ? o.depth : o.nodeId ? 100 : 3;
    var lines = [], len = 0, truncated = false;
    async function walk(n, d) {
      var kids = n.children || [];
      var line = new Array(d + 1).join('  ') + n.type + (n.name ? ' "' + clip(n.name, 80) + '"' : '') + ' [' + n.id + ']' +
        await summary(n) + (kids.length && d >= depth ? ' +' + kids.length : '');
      if (len + line.length + 1 > max + 1) { truncated = true; return; }
      lines.push(line);
      len += line.length + 1;
      if (d < depth) for (var i = 0; i < kids.length && !truncated; i++) await walk(kids[i], d + 1);
    }
    await walk(root, 0);
    return {
      pages: figma.root.children.map(function (p) { return p.name + ' [' + p.id + ']' + (p === figma.currentPage ? ' *' : ''); }),
      tree: lines.join('\n'), lines: lines.length, truncated: truncated,
    };
  }

  // ---- inventory

  function paintsText(paints) {
    return (paints || []).map(function (p) { return p.type === 'SOLID' ? hex8(p.color, p.opacity) : p.type.toLowerCase(); }).join(' + ');
  }
  function effectText(e) {
    return e.type + (e.offset ? ' ' + round(e.offset.x) + ',' + round(e.offset.y) : '') +
      (typeof e.radius === 'number' ? ' blur ' + round(e.radius) : '') +
      (e.spread ? ' spread ' + round(e.spread) : '') + (e.color ? ' ' + hex8(e.color) : '');
  }
  function lineHeight(l) {
    if (!l || l.unit === 'AUTO') return '';
    return '/' + round(l.value) + (l.unit === 'PERCENT' ? '%' : '');
  }
  async function scan(scope) {
    await figma.loadAllPagesAsync();
    var lines = [];
    var comps = figma.root.findAllWithCriteria({ types: ['COMPONENT_SET', 'COMPONENT'] })
      .filter(function (n) { return !n.remote && !isVariant(n); });
    ['COMPONENT_SET', 'COMPONENT'].forEach(function (t) {
      comps.forEach(function (n) {
        if (n.type === t) lines.push((t === 'COMPONENT_SET' ? 'SET ' : 'COMP ') + n.name + ' [' + n.id + ']' + describe(n));
      });
    });
    var insts = figma.root.findAllWithCriteria({ types: ['INSTANCE'] }), lib = {}, order = [], scanned = 0;
    for (var i = 0; i < insts.length; i++) {
      if (inInstance(insts[i])) continue;
      if (scanned++ >= 2000) { lines.push('# library scan stopped after 2000 instances'); break; }
      var m = await insts[i].getMainComponentAsync();
      if (!m || !m.remote) continue;
      var owner = isVariant(m) ? m.parent : m;
      if (!lib[owner.key]) { lib[owner.key] = { owner: owner, uses: 0 }; order.push(owner.key); }
      lib[owner.key].uses++;
    }
    order.forEach(function (k) {
      var e = lib[k];
      lines.push('LIB ' + e.owner.name + ' [' + e.owner.id + '] key=' + k + ' uses=' + e.uses + describe(e.owner));
    });
    (await figma.getLocalPaintStylesAsync()).forEach(function (s) {
      lines.push('PAINT ' + s.name + ' [' + s.id + '] ' + paintsText(s.paints));
    });
    (await figma.getLocalTextStylesAsync()).forEach(function (s) {
      lines.push('TEXTSTYLE ' + s.name + ' [' + s.id + '] ' + s.fontName.family + ' ' + s.fontName.style + ' ' +
        round(s.fontSize) + lineHeight(s.lineHeight));
    });
    (await figma.getLocalEffectStylesAsync()).forEach(function (s) {
      lines.push('EFFECT ' + s.name + ' [' + s.id + '] ' + (s.effects || []).map(effectText).join(' + '));
    });
    var ctx = await varContext();
    var cols = Object.keys(ctx.cols).map(function (id) { return ctx.cols[id]; });
    for (var c = 0; c < cols.length; c++) {
      lines.push('VARS ' + cols[c].name + ' [' + cols[c].id + '] modes: ' + cols[c].modes.map(function (m) { return m.name; }).join('|'));
      for (var j = 0; j < cols[c].variableIds.length; j++) {
        var v = ctx.vars[cols[c].variableIds[j]];
        if (v) lines.push('  ' + v.name + ' [' + v.id + '] ' + (await resolve(v, ctx)).text);
      }
    }
    patterns(scope.findAll()).forEach(function (g) {
      var ids = g.nodes.slice(0, 5).map(function (n) { return n.id; });
      lines.push('PATTERN x' + g.nodes.length + ' ' + g.shape + ' ids: ' + ids.join(', ') + (g.nodes.length > 5 ? ', ...' : ''));
    });
    return lines;
  }
  // Kept lines: a match keeps a header with all its indented lines, or a matching indented line
  // under its header. Whole lines only, up to max chars.
  function pick(lines, re, max) {
    var out = [], len = 0, truncated = false, head = null, headShown = false, headHit = false;
    function emit(l) {
      if (truncated || len + l.length + (out.length ? 1 : 0) > max) { truncated = true; return; }
      len += l.length + (out.length ? 1 : 0);
      out.push(l);
    }
    lines.forEach(function (l) {
      if (l.charAt(0) !== ' ') {
        head = l; headHit = !re || re.test(l); headShown = false;
        if (headHit) { emit(l); headShown = true; }
      } else if (headHit || re.test(l)) {
        if (!headShown) { emit(head); headShown = true; }
        emit(l);
      }
    });
    return { text: out.join('\n'), lines: out.length, total: lines.length, truncated: truncated };
  }
  // What the file already has to reuse, one text line each. Scanned once into
  // window.__batchState.fxInventory (patterns over o.scope, default the current page); fresh rescans.
  async function inventory(o) {
    o = o || {};
    var st = state(), scope = o.scope ? await node(o.scope) : figma.currentPage, inv = st.fxInventory;
    if (!inv || o.fresh || inv.scope !== scope.id) {
      inv = st.fxInventory = { scope: scope.id, at: Date.now(), lines: await scan(scope) };
    }
    return pick(inv.lines, o.match ? new RegExp(o.match, 'i') : null, o.maxChars || 8000);
  }

  // ---- build

  async function parentOf(o) { return o.parent ? node(o.parent) : null; }
  function padding(p) {
    if (typeof p === 'number') return [p, p, p, p];
    if (p.length === 2) return [p[0], p[1], p[0], p[1]];
    return p;
  }
  function sizingMode(v, keep) {
    if (v == null) return keep;
    if (typeof v === 'number') return 'FIXED';
    var m = SIZING[String(v).toLowerCase()];
    if (!m) throw new Error("unknown sizing " + v + " (use a number, 'fill' or 'hug')");
    return m;
  }
  // w / h: a number (FIXED at that size), 'fill' or 'hug'. An axis left out keeps its sizing.
  function size(n, w, h) {
    var mh = sizingMode(w, n.layoutSizingHorizontal), mv = sizingMode(h, n.layoutSizingVertical);
    if (typeof w === 'number' || typeof h === 'number') n.resize(typeof w === 'number' ? w : n.width, typeof h === 'number' ? h : n.height);
    if (mh && n.layoutSizingHorizontal !== mh) n.layoutSizingHorizontal = mh;
    if (mv && n.layoutSizingVertical !== mv) n.layoutSizingVertical = mv;
  }
  function place(n, o) {
    if (o.abs) n.layoutPositioning = 'ABSOLUTE';
    if (o.x != null) n.x = o.x;
    if (o.y != null) n.y = o.y;
    if (o.constraints) n.constraints = o.constraints;
  }
  // Auto layout on an existing frame: dir V|H|NONE, gap, pad (n | [v,h] | [t,r,b,l]), align / justify
  // (start|center|end|between|baseline), wrap, w / h as in size().
  async function autoLayout(n, o) {
    n = await node(n);
    o = o || {};
    if (o.dir) {
      if (!AXIS[o.dir]) throw new Error('unknown dir ' + o.dir + ' (V, H or NONE)');
      n.layoutMode = AXIS[o.dir];
    }
    if (o.wrap) n.layoutWrap = 'WRAP';
    if (o.gap != null) n.itemSpacing = o.gap;
    if (o.pad != null) {
      var p = padding(o.pad);
      n.paddingTop = p[0]; n.paddingRight = p[1]; n.paddingBottom = p[2]; n.paddingLeft = p[3];
    }
    if (o.align) n.counterAxisAlignItems = ALIGN[o.align] || o.align;
    if (o.justify) n.primaryAxisAlignItems = ALIGN[o.justify] || o.justify;
    size(n, o.w, o.h);
    return n;
  }
  // A new frame (component: true for a component) in parent; with dir it hugs unless w / h say otherwise.
  // fill / stroke take anything bindFill does; no fill unless given.
  async function frame(o) {
    o = o || {};
    var auto = o.dir && AXIS[o.dir] !== 'NONE';
    sizingMode(o.w); sizingMode(o.h);
    var parent = await parentOf(o);
    var f = o.component ? figma.createComponent() : figma.createFrame();
    if (o.name) f.name = o.name;
    if (parent) parent.appendChild(f);
    f.fills = [];
    if (o.fill) await bindFill(f, o.fill);
    if (o.stroke) { await bindFill(f, o.stroke, 'strokes'); f.strokeWeight = o.strokeWeight || 1; }
    if (o.radius != null) f.cornerRadius = o.radius;
    if (o.clip != null) f.clipsContent = o.clip;
    await autoLayout(f, Object.assign({}, o, { w: o.w != null ? o.w : auto ? 'hug' : null, h: o.h != null ? o.h : auto ? 'hug' : null }));
    place(f, o);
    return f;
  }
  async function loadFont(f) {
    try { await figma.loadFontAsync(f); } catch (e) {
      throw new Error('font ' + f.family + ' ' + f.style + ' is not available; pick one from figma.listAvailableFontsAsync()');
    }
    return f;
  }
  // A text node: font loaded first (family / weight, or a text style's), color via bindFill,
  // w: 'fill' or a width wraps the text (textAutoResize HEIGHT).
  async function text(chars, o) {
    o = o || {};
    var style = null;
    if (o.textStyle) {
      style = /^S:/.test(o.textStyle) ? await figma.getStyleByIdAsync(o.textStyle)
        : (await figma.getLocalTextStylesAsync()).filter(function (s) { return s.name === o.textStyle; })[0];
      if (!style || style.type !== 'TEXT') throw new Error('no text style ' + o.textStyle);
    }
    var font = await loadFont(style ? style.fontName : { family: o.family || 'Inter', style: o.weight || 'Regular' });
    var parent = await parentOf(o);
    var t = figma.createText();
    t.fontName = font;
    t.characters = String(chars);
    t.name = o.name || clip(chars, 40);
    if (style) await t.setTextStyleIdAsync(style.id);
    else {
      if (o.size) t.fontSize = o.size;
      if (o.lineHeight) t.lineHeight = typeof o.lineHeight === 'number' ? { unit: 'PIXELS', value: o.lineHeight } : o.lineHeight;
    }
    if (o.align) t.textAlignHorizontal = ({ start: 'LEFT', center: 'CENTER', end: 'RIGHT' })[o.align] || o.align;
    if (parent) parent.appendChild(t);
    if (o.color) await bindFill(t, o.color);
    if (o.w === 'fill') { t.layoutSizingHorizontal = 'FILL'; t.textAutoResize = 'HEIGHT'; }
    else if (typeof o.w === 'number') { t.resize(o.w, t.height); t.textAutoResize = 'HEIGHT'; }
    place(t, o);
    return t;
  }
  async function findComponent(ref) {
    if (ref && typeof ref === 'object') return ref;
    var hits;
    if (NODE_ID.test(ref)) {
      var n = await node(ref);
      if (n.type !== 'COMPONENT' && n.type !== 'COMPONENT_SET') throw new Error(ref + ' is a ' + n.type + ', not a component');
      return n;
    }
    if (KEY.test(ref)) {
      try { return await figma.importComponentByKeyAsync(ref); } catch (e) { /* a set's key, or unpublished */ }
      try { return await figma.importComponentSetByKeyAsync(ref); } catch (e) { /* unpublished: look locally */ }
      await figma.loadAllPagesAsync();
      hits = figma.root.findAllWithCriteria({ types: ['COMPONENT_SET', 'COMPONENT'] }).filter(function (c) { return c.key === ref; });
      if (hits.length) return hits[0];
      throw new Error('no component or component set with key ' + ref);
    }
    await figma.loadAllPagesAsync();
    hits = figma.root.findAllWithCriteria({ types: ['COMPONENT_SET', 'COMPONENT'] })
      .filter(function (c) { return !isVariant(c) && c.name === ref; });
    if (hits.length === 1) return hits[0];
    if (hits.length) throw new Error('several components named ' + ref + ': ' + hits.map(function (c) { return c.id; }).join(', '));
    throw new Error('no component named ' + ref + '; see __fx.inventory()');
  }
  function same(a, b) { return String(a).toLowerCase() === String(b).toLowerCase(); }
  // An instance of a component or set (node id, 40-hex key or name). props mixes variant axes,
  // which pick the variant, with other properties by short name ("Label", not "Label#1:2").
  async function instance(ref, props, o) {
    props = props || {};
    o = o || {};
    var comp = await findComponent(ref), picked = null;
    if (isVariant(comp)) { picked = comp; comp = comp.parent; }
    var main = comp, axes = [];
    if (comp.type === 'COMPONENT_SET') {
      // Axes props leave out keep the given variant's values, else the set's default variant's.
      var base = picked || comp.defaultVariant || comp.children[0], want = {}, cur = base.variantProperties || {};
      axes = Object.keys(cur);
      axes.forEach(function (a) { want[a] = cur[a]; });
      Object.keys(props).forEach(function (k) {
        var a = axes.filter(function (x) { return same(x, k); })[0];
        if (a) want[a] = props[k];
      });
      main = comp.children.filter(function (c) {
        var vp = c.variantProperties || {};
        return axes.every(function (a) { return same(vp[a], want[a]); });
      })[0];
      if (!main) throw new Error('no variant of ' + comp.name + ' with ' + JSON.stringify(want));
    }
    var d = defs(comp), keyed = {};
    Object.keys(props).forEach(function (k) {
      if (axes.some(function (a) { return same(a, k); })) return;
      var key = d[k] ? k : Object.keys(d).filter(function (x) { return d[x].type !== 'VARIANT' && same(propName(x), k); })[0];
      if (!key) {
        var has = axes.concat(Object.keys(d).filter(function (x) { return d[x].type !== 'VARIANT'; }).map(propName));
        throw new Error('unknown property ' + k + ' on ' + comp.name + '; has ' + has.join(', '));
      }
      keyed[key] = props[k];
    });
    var parent = await parentOf(o);
    var inst = main.createInstance();
    if (parent) parent.appendChild(inst);
    // Figma writes a TEXT property into the layers it drives, so their fonts load first.
    var texts = inst.findAll(function (n) {
      var r = n.type === 'TEXT' && n.componentPropertyReferences;
      return !!(r && r.characters && keyed[r.characters] !== undefined);
    });
    for (var i = 0; i < texts.length; i++) {
      var t = texts[i], fonts = t.fontName === figma.mixed ? t.getRangeAllFontNames(0, t.characters.length) : [t.fontName];
      for (var j = 0; j < fonts.length; j++) await loadFont(fonts[j]);
    }
    if (Object.keys(keyed).length) inst.setProperties(keyed);
    if (o.name) inst.name = o.name;
    size(inst, o.w, o.h);
    place(inst, o);
    return inst;
  }

  // ---- prototyping

  // What a script can set is narrower than the UI (references/prototyping.md): overlay position,
  // background and click-outside are read-only, and SET_VARIABLE / CONDITIONAL need a paid plan.
  function trigger(on) {
    if (on === 'click') return { type: 'ON_CLICK' };
    if (on === 'hover') return { type: 'ON_HOVER' };
    if (on === 'press') return { type: 'ON_PRESS' };
    if (on && on.key != null) return { type: 'ON_KEY_DOWN', device: 'KEYBOARD', keyCodes: [].concat(on.key) };
    if (on && on.after != null) return { type: 'AFTER_TIMEOUT', timeout: on.after };
    throw new Error('react: unknown trigger ' + JSON.stringify(on) + " (click, hover, press, {key}, {after: ms})");
  }
  function triggerKey(t) { return t.type + (t.keyCodes ? ':' + t.keyCodes.join(',') : '') + (t.timeout != null ? ':' + t.timeout : ''); }
  var NAV = { navigate: 'NAVIGATE', overlay: 'OVERLAY', swap: 'SWAP', change: 'CHANGE_TO', scroll: 'SCROLL_TO' };
  // anim: smart (default for navigate), dissolve (default for overlay / swap / scroll), instant
  // (default for change), push-left|right|up|down; ms the duration.
  function transition(anim, ms) {
    var smooth = { type: 'EASE_IN_AND_OUT' };
    if (anim === 'instant') return null;
    if (anim === 'smart') return { type: 'SMART_ANIMATE', easing: smooth, duration: (ms || 300) / 1000 };
    if (/^push/.test(anim)) {
      return { type: 'PUSH', direction: (anim.split('-')[1] || 'left').toUpperCase(), matchLayers: false, easing: smooth, duration: (ms || 300) / 1000 };
    }
    if (anim !== 'dissolve') throw new Error('react: unknown anim ' + anim + ' (smart, dissolve, instant, push-<dir>)');
    return { type: 'DISSOLVE', easing: { type: 'EASE_OUT' }, duration: (ms || 200) / 1000 };
  }
  async function action(d) {
    if (d === 'back') return { type: 'BACK' };
    if (d === 'close') return { type: 'CLOSE' };
    var nav = NAV[d.nav || 'navigate'];
    if (!nav) throw new Error('react: unknown nav ' + d.nav + ' (navigate, overlay, swap, change, scroll)');
    var dest = await node(d.to);
    if (nav === 'CHANGE_TO' && !isVariant(dest)) throw new Error('react: CHANGE_TO needs a variant, got ' + dest.type + ' ' + dest.name);
    var a = { type: 'NODE', destinationId: dest.id, navigation: nav, preserveScrollPosition: false,
      transition: transition(d.anim || (nav === 'NAVIGATE' ? 'smart' : nav === 'CHANGE_TO' ? 'instant' : 'dissolve'), d.ms) };
    if (nav === 'OVERLAY' || nav === 'SWAP') a.resetScrollPosition = true;
    return a;
  }
  // Sets n's reactions from [{on, do}]; append keeps the reactions whose trigger the list doesn't name.
  async function react(n, list, o) {
    n = await node(n);
    var rs = [];
    for (var i = 0; i < list.length; i++) rs.push({ trigger: trigger(list[i].on), actions: [await action(list[i].do)] });
    var named = {};
    rs.forEach(function (r) { named[triggerKey(r.trigger)] = 1; });
    var keep = o && o.append ? (n.reactions || []).filter(function (r) { return !named[triggerKey(r.trigger)]; })
      .map(function (r) { return { trigger: r.trigger, actions: r.actions || [r.action] }; }) : [];
    await n.setReactionsAsync(keep.concat(rs));
    return n;
  }
  // An overlay that opens in place: the size of base, see-through, items at their x / y in base's
  // coordinates over a Scrim that closes on click, Esc closing it. Replaces a same-named frame on the page.
  async function overlayFrame(o) {
    var base = await node(o.base), pg = o.page ? await node(o.page) : base.parent;
    pg.children.filter(function (c) { return c.name === o.name; }).forEach(function (c) { c.remove(); });
    var f = figma.createFrame();
    f.name = o.name;
    pg.appendChild(f);
    f.resize(base.width, base.height);
    f.fills = [];
    f.clipsContent = false;
    f.x = base.x;
    f.y = base.y + base.height + 200;
    if (o.scrim !== false) {
      var s = figma.createFrame();
      s.name = 'Scrim';
      f.appendChild(s);
      s.resize(base.width, base.height);
      s.fills = [];
      s.constraints = { horizontal: 'STRETCH', vertical: 'STRETCH' };
      await react(s, [{ on: 'click', do: 'close' }]);
    }
    var items = o.items || [];
    for (var i = 0; i < items.length; i++) {
      var it = items[i], n = await node(it.node || it), x = it.node && it.x != null ? it.x : n.x, y = it.node && it.y != null ? it.y : n.y;
      f.appendChild(n);
      n.x = x;
      n.y = y;
    }
    await react(f, [{ on: { key: 27 }, do: 'close' }]);
    return f;
  }
  // Names a flow starting at start on page; one entry per frame and per name.
  async function flow(pg, start, name) {
    pg = await node(pg);
    start = await node(start);
    pg.flowStartingPoints = pg.flowStartingPoints.filter(function (p) { return p.nodeId !== start.id && p.name !== name; })
      .concat([{ nodeId: start.id, name: name }]);
    return pg.flowStartingPoints;
  }
  // The top-level frame holding n (null inside a component, whose screens are its instances').
  function screenOf(n) {
    for (; n && n.parent; n = n.parent) {
      if (n.type === 'COMPONENT' || n.type === 'COMPONENT_SET') return null;
      if (n.parent.type === 'PAGE' || n.parent.type === 'SECTION') return n;
    }
    return null;
  }
  // Figma refuses unknown destinations and drops reactions to removed nodes, so danglingReactions
  // catches only state written some other way. An instance's reactions read its main's until it
  // has its own, an empty list included.
  async function reactionProblems(own, lists) {
    for (var i = 0; i < own.length; i++) {
      var n = own[i], rs = n.reactions || [], dangling = false;
      for (var j = 0; j < rs.length; j++) {
        var acts = rs[j].actions || [rs[j].action];
        for (var k = 0; k < acts.length; k++) {
          var a = acts[k];
          if (!a || a.type !== 'NODE' || !a.destinationId) continue;
          var dest = await figma.getNodeByIdAsync(a.destinationId);
          if (!dest) { dangling = true; continue; }
          var screen = a.navigation === 'OVERLAY' && screenOf(n);
          if (screen && (dest.overlayPositionType || 'CENTER') === 'CENTER' && (dest.width < screen.width || dest.height < screen.height)) {
            lists.overlayNotFullSize.push(n);
          }
        }
      }
      if (dangling) lists.danglingReactions.push(n);
      if (n.type === 'INSTANCE' && !rs.some(function (r) { return r.trigger && r.trigger.type === 'ON_HOVER'; })) {
        var m = await n.getMainComponentAsync();
        if (m && (m.reactions || []).some(function (r) { return r.trigger && r.trigger.type === 'ON_HOVER'; })) lists.lostHover.push(n);
      }
    }
  }

  // ---- audit

  // The fix for each audit count, printed after its ids in audit().text.
  var AUDIT_FIX = {
    rawRepeats: 'make one component, replace the copies with instances',
    fixedInFlow: "set layoutSizingHorizontal/Vertical to 'FILL' or 'HUG' after appendChild",
    absDefaultConstraints: 'put the parent in auto layout, or set constraints to how the child should pin',
    groups: 'replace the group with an auto-layout frame',
    defaultNames: 'name the layer for its role',
    unboundPaints: 'bind the paint to its variable: __fx.bindFill(node, hex)',
    textFixedInAutoLayout: "set textAutoResize to 'HEIGHT' (or 'WIDTH_AND_HEIGHT')",
    textOverflow: "set the text to layoutSizingHorizontal 'FILL' with textAutoResize 'HEIGHT'",
    componentsWithoutAutoLayout: 'give the component auto layout',
    unlinkedProps: 'reference the property from a layer (componentPropertyReferences) or delete it',
    danglingReactions: 'point the reaction at an existing node or remove it',
    lostHover: "re-add the main component's ON_HOVER reaction to the instance (gotchas #17)",
    overlayNotFullSize: 'size the overlay frame to the screen, or open it as a positioned overlay',
  };

  // Structural problems under rootId (default: the current page): counts (all best at 0) plus up to
  // o.limit ids each, and shares (higher is better) kept apart so callers can require every count at 0.
  // text is what to fix, one line per nonzero count with its ids, and empty when there's nothing.
  async function audit(rootId, o) {
    o = o || {};
    var lim = o.limit || 5;
    var root = rootId ? await node(rootId) : figma.currentPage;
    var nodes = (root.type === 'PAGE' ? [] : [root]).concat(root.findAll ? root.findAll() : []);
    var m = measure(nodes), own = m.own, idx = await colorIndex();
    var lists = {
      rawRepeats: [], fixedInFlow: [], absDefaultConstraints: m.absDefault.slice(), groups: [], defaultNames: m.defaultNamed,
      unboundPaints: [], textFixedInAutoLayout: [], textOverflow: [], componentsWithoutAutoLayout: [], unlinkedProps: [],
      danglingReactions: [], lostHover: [], overlayNotFullSize: [],
    };
    patterns(nodes).forEach(function (g) { lists.rawRepeats = lists.rawRepeats.concat(g.nodes); });
    lists.fixedInFlow = m.fixedFlow.filter(function (c) { return c.type !== 'INSTANCE' && c.type !== 'TEXT'; });
    m.containers.forEach(function (f) {
      if (isAL(f)) return;
      f.children.forEach(function (c) { if (!SHAPES[c.type] && isDefaultConstraint(c)) lists.absDefaultConstraints.push(c); });
    });
    own.forEach(function (n) {
      var p = n.parent;
      if (n.type === 'GROUP') lists.groups.push(n);
      if (n.type === 'COMPONENT' && n.children && n.children.length && !isAL(n)) lists.componentsWithoutAutoLayout.push(n);
      if (n.type === 'TEXT' && isAL(p) && n.layoutPositioning !== 'ABSOLUTE') {
        if (n.textAutoResize === 'NONE') lists.textFixedInAutoLayout.push(n);
        if (p.layoutSizingHorizontal !== 'HUG' && n.width > p.width - (p.paddingLeft || 0) - (p.paddingRight || 0) + 1) lists.textOverflow.push(n);
      }
      ['fills', 'strokes'].forEach(function (f) {
        var v = n[f], styleId = f === 'fills' ? n.fillStyleId : n.strokeStyleId;
        if (!v || v === figma.mixed || !v.length || (typeof styleId === 'string' && styleId)) return;
        v.forEach(function (paint) {
          if (paint.type !== 'SOLID' || paint.visible === false || (paint.boundVariables && paint.boundVariables.color)) return;
          if (idx.vars[hex8(paint.color, paint.opacity)]) lists.unboundPaints.push(n);
        });
      });
      if (n.type === 'COMPONENT_SET' || (n.type === 'COMPONENT' && !isVariant(n))) {
        var d = defs(n), used = {};
        [n].concat(n.findAll()).forEach(function (x) {
          var r = x.componentPropertyReferences;
          if (r) Object.keys(r).forEach(function (k) { used[r[k]] = 1; });
        });
        Object.keys(d).forEach(function (k) { if (d[k].type !== 'VARIANT' && !used[k]) lists.unlinkedProps.push(n.id + ':' + propName(k)); });
      }
    });
    await reactionProblems(own, lists);
    var counts = {}, ids = {}, more = {};
    Object.keys(lists).forEach(function (k) {
      counts[k] = lists[k].length;
      if (!lists[k].length) return;
      var seen = {};
      ids[k] = [];
      lists[k].forEach(function (x) {
        var id = typeof x === 'string' ? x : x.id;
        if (seen[id]) return;
        seen[id] = 1;
        if (ids[k].length < lim) ids[k].push(id); else more[k] = 1;
      });
    });
    var shares = { instanceRatio: share(m.instances.length, m.instances.length + m.rawFrames.length),
      autoLayoutShare: share(m.auto.length, m.containers.length) };
    var text = Object.keys(ids).map(function (k) {
      return k + ' ' + counts[k] + ' [' + ids[k].join(',') + (more[k] ? ',...' : '') + '] -> ' + AUDIT_FIX[k];
    }).join('\n');
    return { root: root.id, nodes: nodes.length, counts: counts, shares: shares, ids: ids, text: text };
  }

  // ---- presence: parallel workers share one tab; figma_run.py --ns <NS> names the worker

  // A worker claims the rootId its scripts return. __fx.presence (after a --ns script) notes writes
  // under a frame another worker claimed and components another worker already made with the same
  // name; it warns, the write stays. __fx.stale (before a --ns script) refuses to run when a
  // collaborator (REMOTE) edited this worker's frames since its last eval. Claims lapse after
  // 10 idle minutes, so a finished task needs no release.
  var CLAIM_MS = 600000;

  function board() { return window.__fxPresence || (window.__fxPresence = { claims: {}, comps: {}, seen: {} }); }
  function live(c, now) { return !!c && now - c.ts < CLAIM_MS; }

  // REMOTE changes on the current page, as {seq, chain: [node id, its ancestors' ids...]}. Installed
  // once per tab whatever the library version; a tab without page events just never refuses.
  function watch() {
    var w = window.__fxWatch || (window.__fxWatch = { seq: 0, ring: [] });
    if (w.on) return w;
    try {
      if (typeof figma.on !== 'function' || typeof figma.currentPage.on !== 'function') return w;
      var page = figma.currentPage;
      var onChange = function (ev) {
        (ev.nodeChanges || []).forEach(function (c) {
          if (c.origin !== 'REMOTE') return;
          var chain = [];
          try { for (var n = c.node; n && n.type !== 'PAGE' && chain.length < 40; n = n.parent) chain.push(n.id); } catch (e) {}
          if (!chain.length) chain.push(c.id);
          w.ring.push({ seq: ++w.seq, chain: chain });
          if (w.ring.length > 500) w.ring.shift();
        });
      };
      page.on('nodechange', onChange);
      figma.on('currentpagechange', function () {
        try { page.off('nodechange', onChange); page = figma.currentPage; page.on('nodechange', onChange); } catch (e) {}
      });
      w.on = true;
    } catch (e) {}
    return w;
  }

  async function presence(ns, v) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return v;
    try {
      var created = v.createdNodeIds || [], ids = created.concat(v.mutatedNodeIds || []);
      if (v.rootId) ids.push(v.rootId);
      if (!ids.length) return v;
      var b = board(), now = Date.now(), crossed = [], dupes = [], noted = {}, i, n, c;
      if (v.rootId && !(live(b.claims[v.rootId], now) && b.claims[v.rootId].ns !== ns)) {
        b.claims[v.rootId] = { ns: ns, ts: now };
        if (!(ns in b.seen)) b.seen[ns] = watch().seq;
      }
      for (i = 0; i < ids.length; i++) {
        for (n = await figma.getNodeByIdAsync(ids[i]); n && n.type !== 'PAGE'; n = n.parent) {
          c = b.claims[n.id];
          if (!live(c, now)) continue;
          if (c.ns === ns) c.ts = now;
          else if (!noted[ids[i]]) { noted[ids[i]] = 1; crossed.push(ids[i] + ' (in ' + n.id + ', ' + c.ns + ')'); }
          break;
        }
      }
      for (i = 0; i < created.length; i++) {
        n = await figma.getNodeByIdAsync(created[i]);
        if (!n || (n.type !== 'COMPONENT' && n.type !== 'COMPONENT_SET') || (n.parent && n.parent.type === 'COMPONENT_SET')) continue;
        c = b.comps[n.name];
        if (live(c, now) && c.ns !== ns && c.id !== n.id && await figma.getNodeByIdAsync(c.id)) dupes.push(n.name + ' (' + c.ns + ' made ' + c.id + ')');
        else b.comps[n.name] = { ns: ns, id: n.id, ts: now };
      }
      var notes = [];
      if (crossed.length) notes.push("Wrote inside another worker's frame: " + crossed.join(', ') + ". Don't touch those nodes again; re-read them and report DONE_WITH_CONCERNS.");
      if (dupes.length) notes.push('Another worker already made ' + dupes.join(', ') + '. Use that component instead of yours and report DONE_WITH_CONCERNS.');
      if (!notes.length) return v;
      var out = {};
      Object.keys(v).forEach(function (k) { out[k] = v[k]; });
      out.fxNote = notes.join(' ');
      return out;
    } catch (e) {
      return v;
    }
  }

  function stale(ns) {
    var w = window.__fxWatch, b = window.__fxPresence;
    if (!w || !b || !(ns in b.seen)) return null;
    var since = b.seen[ns], now = Date.now(), mine = {}, changed = [];
    b.seen[ns] = w.seq;
    Object.keys(b.claims).forEach(function (k) { if (b.claims[k].ns === ns && live(b.claims[k], now)) mine[k] = 1; });
    w.ring.forEach(function (r) {
      if (r.seq <= since) return;
      for (var i = 0; i < r.chain.length; i++) {
        if (mine[r.chain[i]]) { if (changed.indexOf(r.chain[0]) < 0) changed.push(r.chain[0]); return; }
      }
    });
    if (!changed.length) return null;
    return { applied: false, reason: 'stale', changed: changed.slice(0, 20),
      note: 'Someone else edited your frame since your last eval, so nothing ran. Re-read those nodes, adjust, and send the script again.' };
  }

  window.__fx = {
    v: V, recon: recon, inventory: inventory, frame: frame, autoLayout: autoLayout, text: text, instance: instance,
    bindFill: bindFill, audit: audit, react: react, overlayFrame: overlayFrame, flow: flow, node: node, hex: hex, hex8: hex8, measure: measure, patterns: patterns,
    solidPaints: solidPaints, inInstance: inInstance, inComponent: inComponent, DEFAULT_NAME: DEFAULT_NAME,
    presence: presence, stale: stale,
  };
  watch();
})();
