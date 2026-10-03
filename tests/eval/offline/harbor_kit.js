// Draws source screens (EVAL.expect.screens, from source.py) into the stub, for offline end
// states. Knobs say how good the result is:
//   comps     component kinds built as components and placed as instances (others drawn raw)
//   values    per kind, the variant values its set gets (default: every value in expect.axes)
//   split     kinds that get a second, duplicate component, used on the last screen
//   autoLayout, sizing, bind (colors as variables), names (meaningful layer names)
//   drop      source strings left out; invent: strings added that the source does not have
// Usage: var kit = await harborKit(cfg).init(screens); screens.forEach(function (s, i) { kit.screen(s, i * 1400); });

function harborKit(cfg) {
  var E = EVAL.expect, vars = null, defs = {}, kindOf = {}, page = null, screenNo = 0, screenCount = 0;
  var comps = setOf(cfg.comps || []);
  function isComp(c) { return !!comps[norm(c)]; }
  function cap(s) { s = String(s); return s.charAt(0).toUpperCase() + s.slice(1); }
  function nm(name, type) { return cfg.names ? name : (type || 'Frame'); }
  function color(key) { return cfg.bind ? key : (cfg.offPalette || {})[key] || E.colors[key]; }
  function box(parent, name, dir, opts) {
    opts = opts || {};
    var o = { gap: opts.gap, pad: opts.pad, align: opts.align, justify: opts.justify, radius: opts.radius,
      fill: opts.fill ? color(opts.fill) : null, stroke: opts.stroke ? color(opts.stroke) : null,
      vars: cfg.bind ? vars : null, component: opts.component, width: opts.width };
    var f = mkFrame(parent, nm(name), cfg.autoLayout ? dir : 'NONE', o);
    if (opts.height) f.resize(f.width, opts.height);
    return f;
  }
  function text(parent, s, opts) {
    opts = opts || {};
    var t = mkText(parent, s, { style: opts.style, size: opts.size, color: color(opts.color || 'text'), vars: cfg.bind ? vars : null,
      name: cfg.names ? (opts.name || s) : 'Text' });
    return t;
  }
  function size(n, want) {
    if (!cfg.sizing || !want || !cfg.autoLayout) return;
    var al = n.parent && n.parent.layoutMode && n.parent.layoutMode !== 'NONE';
    ['h', 'v'].forEach(function (ax) {
      var v = want[ax];
      if (!v || (v === 'FILL' && !al) || (v === 'HUG' && n.type !== 'TEXT' && !(n.layoutMode && n.layoutMode !== 'NONE'))) return;
      n[ax === 'h' ? 'layoutSizingHorizontal' : 'layoutSizingVertical'] = v;
    });
  }
  function strings(u) { return u.items.filter(function (i) { return i.s !== undefined && (cfg.drop || []).indexOf(i.s) === -1; }); }

  // The look of one usage, raw or as a component variant: a frame holding its strings and kids.
  function draw(parent, u, asComponent) {
    var c = u.c, p = u.props || {}, f;
    var opt = { component: asComponent };
    if (c === 'Icon') {
      f = box(parent, 'Icon/' + cap(p.name), 'HORIZONTAL', opt);
      f.resize(20, 20);
      var g = figma.createRectangle();
      g.name = nm('Glyph', 'Rectangle');
      f.appendChild(g);
      g.resize(16, 16);
      g.fills = [paintOf(color('text-muted'), cfg.bind ? vars : null)];
      return f;
    }
    var look = {
      AppHeader: ['HORIZONTAL', { justify: 'SPACE_BETWEEN', align: 'CENTER', pad: [12, 24, 12, 24], fill: 'surface', stroke: 'border' }],
      Avatar: ['HORIZONTAL', { justify: 'CENTER', align: 'CENTER', radius: 999, fill: 'avatar-bg' }],
      Badge: ['HORIZONTAL', { pad: [2, 8, 2, 8], radius: 999, fill: (p.tone || 'neutral') + '-bg' }],
      Button: ['HORIZONTAL', { gap: 8, align: 'CENTER', pad: [8, 16, 8, 16], radius: 6,
        fill: p.variant === 'secondary' ? 'surface' : 'primary', stroke: p.variant === 'secondary' ? 'border' : null }],
      Card: ['VERTICAL', { gap: 16, pad: [16, 16, 16, 16], radius: 10, fill: 'surface', stroke: 'border' }],
      StatCard: ['VERTICAL', { gap: 8, pad: [16, 16, 16, 16], radius: 10, fill: 'surface', stroke: 'border' }],
      Input: ['VERTICAL', { gap: 4 }],
      ListItem: ['HORIZONTAL', { gap: 12, align: 'CENTER', pad: [12, 16, 12, 16], fill: p.selected === 'true' ? 'selected-bg' : null }],
      Tabs: ['HORIZONTAL', { gap: 24, stroke: 'border' }],
      Tab: ['HORIZONTAL', { pad: [8, 0, 8, 0] }],
    }[c];
    f = box(parent, c, look[0], Object.assign(opt, look[1]));
    if (c === 'Avatar') { var d = p.size === 'lg' ? 56 : 32; f.resize(d, d); if (cfg.autoLayout) { f.layoutSizingHorizontal = 'FIXED'; f.layoutSizingVertical = 'FIXED'; } }
    var ss = strings(u), kids = u.kids;
    var tcolor = { Avatar: 'avatar-text', Badge: (p.tone || 'neutral') + '-text', Button: p.variant === 'secondary' ? 'text' : 'on-primary',
      Tab: p.selected === 'true' ? 'primary' : 'text-muted' }[c] || 'text';
    function place(into, k) { return k === undefined ? null : child(into, kids[k]); }
    if (c === 'ListItem' || c === 'StatCard') {
      var kidIdx = u.items.filter(function (i) { return i.k !== undefined; }).map(function (i) { return i.k; });
      if (c === 'ListItem') place(f, kidIdx[0]);
      var col = c === 'ListItem' ? box(f, 'Copy', 'VERTICAL', { gap: 2 }) : f;
      ss.forEach(function (i, n) { text(col, i.s, { name: n ? 'Subtitle' : 'Title', style: n ? 'Regular' : 'Medium', color: n ? 'text-muted' : 'text' }); });
      if (col !== f) size(col, { h: 'FILL' });
      kidIdx.slice(c === 'ListItem' ? 1 : 0).forEach(function (k) { place(f, k); });
      return f;
    }
    if (c === 'Input') {
      var st = p.state || 'default';
      var lab = ss.length > 1 ? ss[0] : null, val = ss.length > 1 ? ss[1] : ss[0], msg = ss[2];
      if (lab) text(f, lab.s, { name: 'Label', size: 12, color: 'text-muted' });
      var field = box(f, 'Field', 'HORIZONTAL', { gap: 8, pad: [8, 12, 8, 12], radius: 6, align: 'CENTER',
        fill: st === 'disabled' ? 'disabled-bg' : 'surface', stroke: st === 'focus' ? 'primary' : st === 'error' ? 'error' : 'border' });
      size(field, { h: 'FILL' });
      u.items.forEach(function (i) { if (i.k !== undefined) place(field, i.k); });
      if (val) size(text(field, val.s, { name: 'Value', color: st === 'disabled' ? 'disabled-text' : 'text' }), { h: 'FILL' });
      if (msg) text(f, msg.s, { name: 'Message', size: 12, color: st === 'error' ? 'error' : 'text-muted' });
      return f;
    }
    var actions = null;
    u.items.forEach(function (i, n) {
      if (i.s !== undefined) {
        if ((cfg.drop || []).indexOf(i.s) !== -1) return;
        text(f, i.s, { name: c === 'AppHeader' ? 'Brand' : n === 0 ? 'Title' : 'Label', color: c === 'AppHeader' ? 'primary' : tcolor,
          style: c === 'AppHeader' || (c === 'Card' && n === 0) ? 'Bold' : 'Regular' });
      } else if (c === 'AppHeader') {
        if (!actions) actions = box(f, 'Actions', 'HORIZONTAL', { gap: 16, align: 'CENTER' });
        place(actions, i.k);
      } else {
        place(f, i.k);
      }
    });
    return f;
  }
  // One usage inside parent: an instance with overrides when its kind is a component, else drawn.
  function child(parent, u) {
    var n;
    if (isComp(u.c) && defs[u.c]) {
      n = instance(u);
      parent.appendChild(n);
      if (E.slots.indexOf(u.c) !== -1) {
        // slot content: everything but the key, after the instance's own title
        u.items.forEach(function (i) {
          if (i.s !== undefined) { if (i.s !== u.key && (cfg.drop || []).indexOf(i.s) === -1) text(n, i.s); }
          else child(n, u.kids[i.k]);
        });
      }
    } else {
      n = draw(parent, u, false);
    }
    size(n, E.sizing[u.c]);
    return n;
  }
  function variantOf(u, which) {
    var d = which || defs[u.c];
    if (d.type !== 'COMPONENT_SET') return d;
    var axes = E.axes[u.c] || {};
    var want = d.children.filter(function (v) {
      return Object.keys(axes).every(function (a) { return token(v.variantProperties[cap(a)]) === token(u.props[a]); });
    })[0];
    return want || d.children[0];
  }
  function instance(u) {
    var useSplit = (cfg.split || []).indexOf(u.c) !== -1 && screenNo === screenCount - 1 && defs[u.c + ':2'];
    var i = variantOf(u, useSplit ? defs[u.c + ':2'] : null).createInstance();
    i.name = nm(u.c, 'Instance');
    override(i, u);
    return i;
  }
  function ownTexts(n) {
    var out = [];
    (n.children || []).forEach(function (c) {
      if (c.type === 'TEXT') out.push(c);
      else if (c.type !== 'INSTANCE') out = out.concat(ownTexts(c));
    });
    return out;
  }
  function nestedInstances(n) {
    var out = [];
    (n.children || []).forEach(function (c) { if (c.type === 'INSTANCE') out.push(c); else out = out.concat(nestedInstances(c)); });
    return out;
  }
  function override(inst, u) {
    // the instance's own text layers, in drawing order: its strings and those of kids drawn
    // as plain layers inside the component
    function flat(x) {
      var out = [];
      x.items.forEach(function (i) {
        if (i.s !== undefined) { if ((cfg.drop || []).indexOf(i.s) === -1) out.push(i); }
        else if (!isComp(x.kids[i.k].c)) out = out.concat(flat(x.kids[i.k]));
      });
      return out;
    }
    var ts = ownTexts(inst), ss = flat(u);
    if (E.slots.indexOf(u.c) !== -1) ss = ss.filter(function (i) { return i.s === u.key; });
    if (u.c === 'Input' && ss.length === 1) ss = [null, ss[0]];
    ts.forEach(function (t, n) { if (ss[n]) t.characters = ss[n].s; else t.visible = false; });
    var nested = nestedInstances(inst), used = {};
    u.kids.forEach(function (k) {
      for (var j = 0; j < nested.length; j++) {
        var m = nested[j].mainComponent;
        var owner = m && m.parent && m.parent.type === 'COMPONENT_SET' ? m.parent : m;
        if (used[j] || !owner || kindOf[owner.id] !== k.c) continue;
        used[j] = 1;
        var v = variantOf(k);
        if (v.parent && v.parent.type === 'COMPONENT_SET') {
          var props = {};
          Object.keys(v.variantProperties).forEach(function (a) { props[a] = v.variantProperties[a]; });
          nested[j].setProperties(props);
        }
        nested[j].visible = true;
        override(nested[j], k);
        return;
      }
    });
    nested.forEach(function (n, j) { if (!used[j]) n.visible = false; });
  }

  // Components show sample copy, not one usage's.
  function placeholders(u) {
    var n = 0;
    u.items.forEach(function (i) { if (i.s !== undefined) i.s = 'Sample ' + u.c.toLowerCase() + ' ' + (++n); });
    u.key = u.items.filter(function (i) { return i.s !== undefined; }).map(function (i) { return i.s; })[0] || null;
    u.kids.forEach(placeholders);
  }
  // Component definitions, leaves first, each from the usage of its kind with the most content.
  async function build(screens) {
    var lib = box(page, 'Components', 'HORIZONTAL', { gap: 40 });
    lib.y = -2000;
    var byKind = {};
    function collect(u) {
      var have = byKind[u.c];
      var score = u.anchors.length * 10 + u.kids.length;
      if (!have || score > have.score) byKind[u.c] = { u: u, score: score };
      if (u.c === 'Input' || u.c === 'Button') {  // the template also needs the icon some usages lead with
        var withIcon = u.kids.some(function (k) { return k.c === 'Icon'; });
        if (withIcon) byKind[u.c + ':icon'] = { u: u };
      }
      u.kids.forEach(collect);
    }
    screens.forEach(function (s) { s.usages.forEach(collect); });
    ['Icon', 'Avatar', 'Badge', 'Button', 'Tab', 'Input', 'Tabs', 'ListItem', 'StatCard', 'AppHeader', 'Card'].forEach(function (c) {
      if (!isComp(c) || !byKind[c]) return;
      var t = JSON.parse(JSON.stringify(byKind[c].u));
      if (byKind[c + ':icon'] && !t.kids.some(function (k) { return k.c === 'Icon'; })) {
        var icon = byKind[c + ':icon'].u.kids.filter(function (k) { return k.c === 'Icon'; })[0];
        t.kids.unshift(icon);
        t.items = [{ k: 0 }].concat(t.items.map(function (i) { return i.k !== undefined ? { k: i.k + 1 } : i; }));
      }
      if (E.slots.indexOf(c) !== -1) { t.items = [{ s: t.key }]; t.kids = []; }
      placeholders(t);
      if (c === 'Tabs') { var tab = t.kids[0]; while (t.kids.length < 4) { t.items.push({ k: t.kids.length }); t.kids.push(tab); } }
      var copies = (cfg.split || []).indexOf(c) !== -1 ? 2 : 1;
      for (var n = 0; n < copies; n++) {
        var axes = E.axes[c] || {}, axisNames = Object.keys(axes), made;
        if (!axisNames.length) {
          made = draw(lib, t, true);
          made.name = nm(c, 'Component');
        } else {
          var a = axisNames[0], values = (cfg.values || {})[c] || Object.keys(axes[a].values);
          var vs = values.map(function (v) {
            var copy = JSON.parse(JSON.stringify(t));
            copy.props[a] = v;
            var comp = draw(lib, copy, true);
            comp.name = cap(a) + '=' + cap(v);
            return comp;
          });
          made = figma.combineAsVariants(vs, lib);
          made.name = nm(c, 'Component');
          if (cfg.autoLayout) made.layoutMode = 'HORIZONTAL';
        }
        defs[n ? c + ':2' : c] = made;
        kindOf[made.id] = c;
      }
    });
  }
  return {
    init: async function (screens) {
      await loadFonts();
      page = await targetPage();
      if (cfg.bind) {
        vars = {};
        for (var k in EVAL.seed.variables) vars[k] = await figma.variables.getVariableByIdAsync(EVAL.seed.variables[k]);
      }
      screenCount = screens.length;
      await build(screens);
      return this;
    },
    screen: function (s, x) {
      var f = box(page, s.title, 'VERTICAL', { fill: 'background', width: 1280 });
      f.x = x || 0;
      var body = box(f, 'Content', 'VERTICAL', { gap: 24, pad: [32, 32, 32, 32] });
      size(body, { h: 'FILL' });
      s.items.forEach(function (i) {
        if (i.s !== undefined) { if ((cfg.drop || []).indexOf(i.s) === -1) text(body, i.s, { style: 'Bold', size: 28, name: 'Title' }); }
        else child(s.usages[i.k].c === 'AppHeader' ? f : body, s.usages[i.k]);
      });
      // the header sits above the content
      var header = f.children.filter(function (c) { return c !== body; })[0];
      if (header) f.insertChild(0, header);
      (cfg.invent || []).forEach(function (s) { text(body, s); });
      screenNo++;
      return f;
    },
  };
}
