// SVG markup → markup figma.createNodeFromSvg draws as a browser would, then masks rebuilt
// after the import. Installs window.__fxSvg = { prepare, finish } once per tab.
//
// createNodeFromSvg drops <mask>, <pattern> fills, <style> rules and var(), paints
// currentColor black, and turns a drop-shadow filter into a blur of the whole shape. prepare
// rewrites each into what it draws: attributes for CSS, tiles clipped to the shape for a
// pattern, a blurred, offset, faded copy for a shadow, and each mask as an MSK_n group of its
// layers (MSKW_n_k white, MSKB_n_k black, in painting order) beside the content. finish(node)
// turns each MSK group into a Figma mask: the layers flattened, white unioned and black
// subtracted in turn. Both return what they could not convert, as notes. o.masks === false leaves
// masks as they are (a browser draws them, so a render can check the rest). A copy with a higher V
// replaces the installed one: bump V with every change (tests/svg_test.js pins the file's hash).
(function () {
  var V = 3;
  if (window.__fxSvg && window.__fxSvg.v >= V) return;
  var SHAPES = /^(path|rect|circle|ellipse|line|polyline|polygon|use|text)$/;
  var PAINT_PROPS = ['fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray',
    'fill-opacity', 'stroke-opacity', 'opacity', 'fill-rule', 'clip-rule', 'display', 'visibility', 'stop-color', 'stop-opacity'];

  // ---- a small XML tree: {tag, attrs: [[k, v]], kids: [...]} or a string for text/comments ----
  function parse(src) {
    var root = { tag: '#root', attrs: [], kids: [] }, stack = [root], re = /<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|<!DOCTYPE[^>]*>|<\/([\w:.-]+)\s*>|<([\w:.-]+)((?:\s+[^\s=\/>]+(?:\s*=\s*(?:"[^"]*"|'[^']*'))?)*)\s*(\/?)>|[^<]+/g, m;
    while ((m = re.exec(src))) {
      var top = stack[stack.length - 1];
      if (m[1]) { if (stack.length > 1) stack.pop(); }
      else if (m[2]) {
        var el = { tag: m[2], attrs: [], kids: [], raw: m[0] }, am, are = /([^\s=\/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'))?/g;
        while ((am = are.exec(m[3]))) el.attrs.push([am[1], am[2] !== undefined ? am[2] : am[3] !== undefined ? am[3] : '']);
        top.kids.push(el);
        if (!m[4]) stack.push(el);
      } else top.kids.push(m[0]);
    }
    return root;
  }
  function esc(v) { return String(v).replace(/&(?!\w+;|#\d+;|#x[\da-f]+;)/gi, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }
  function out(n) {
    if (typeof n === 'string') return n;
    if (n.tag === '#root') return n.kids.map(out).join('');
    if (!changed(n) && n.raw) return /\/>$/.test(n.raw) ? n.raw : n.raw + n.kids.map(out).join('') + '</' + n.tag + '>';
    var open = '<' + n.tag + n.attrs.map(function (a) { return ' ' + a[0] + '="' + esc(a[1]) + '"'; }).join('');
    return n.kids.length ? open + '>' + n.kids.map(out).join('') + '</' + n.tag + '>' : open + '/>';
  }
  function changed(n) { return typeof n !== 'string' && (n.dirty || n.kids.some(changed)); }
  function get(n, k) { for (var i = 0; i < n.attrs.length; i++) if (n.attrs[i][0] === k) return n.attrs[i][1]; return null; }
  function set(n, k, v) {
    n.dirty = true;
    for (var i = 0; i < n.attrs.length; i++) if (n.attrs[i][0] === k) { if (v === null) n.attrs.splice(i, 1); else n.attrs[i][1] = v; return; }
    if (v !== null) n.attrs.push([k, v]);
  }
  function el(tag, attrs, kids) { return { tag: tag, attrs: attrs || [], kids: kids || [], dirty: true }; }
  function walk(n, fn, parent) { if (typeof n === 'string') return; fn(n, parent); n.kids.slice().forEach(function (k) { walk(k, fn, n); }); }
  function copy(n) { return typeof n === 'string' ? n : { tag: n.tag, attrs: n.attrs.map(function (a) { return a.slice(); }), kids: n.kids.map(copy), dirty: true }; }
  function text(n) { return typeof n === 'string' ? n.replace(/^<!\[CDATA\[|\]\]>$/g, '') : n.kids.map(text).join(''); }
  function num(v, base) { if (v == null) return 0; v = String(v).trim(); return /%$/.test(v) ? parseFloat(v) * base / 100 : parseFloat(v) || 0; }

  // ---- CSS: <style> rules and style="" into attributes ----
  function rules(css) {
    var outR = [];
    css = css.replace(/\/\*[\s\S]*?\*\//g, '');
    var depth = 0, i = 0, start = 0;
    // Only top-level rules: @media and other at-blocks hold variants for other contexts.
    while (i < css.length) {
      var c = css[i];
      if (c === '{') {
        var head = css.slice(start, i).trim();
        if (depth === 0 && head && head[0] !== '@') {
          var end = css.indexOf('}', i);
          outR.push({ sel: head.split(',').map(function (s) { return s.trim(); }), decls: decls(css.slice(i + 1, end)) });
          i = end + 1; start = i; continue;
        }
        depth++;
      } else if (c === '}') { depth = Math.max(0, depth - 1); if (depth === 0) start = i + 1; }
      i++;
    }
    return outR;
  }
  function decls(s) { var o = []; s.split(';').forEach(function (d) { var k = d.indexOf(':'); if (k > 0) o.push([d.slice(0, k).trim(), d.slice(k + 1).trim().replace(/\s*!important$/, '')]); }); return o; }
  function matches(n, sel) {
    var m = /^([\w-]*)((?:[.#][\w-]+)*)$/.exec(sel);
    if (!m) return false;
    if (m[1] && m[1] !== '*' && m[1] !== n.tag) return false;
    var cls = (get(n, 'class') || '').split(/\s+/), parts = m[2].match(/[.#][\w-]+/g) || [];
    if (!m[1] && !parts.length) return false;
    return parts.every(function (p) { return p[0] === '.' ? cls.indexOf(p.slice(1)) >= 0 : get(n, 'id') === p.slice(1); });
  }

  function prepare(svg, o) {
    o = o || {};
    var notes = [], tree = parse(String(svg)), root = null, ids = {}, n = 0;
    walk(tree, function (x) { if (!root && x.tag === 'svg') root = x; var id = get(x, 'id'); if (id) ids[id] = x; });
    if (!root) return { svg: svg, notes: ['no <svg> root'] };
    var vb = (get(root, 'viewBox') || '').split(/[\s,]+/).map(Number), W = vb.length === 4 ? vb[2] : num(get(root, 'width')) || 100, H = vb.length === 4 ? vb[3] : num(get(root, 'height')) || 100;

    // <style> rules, in source order, then each element's own style="" (which wins).
    var css = [];
    walk(tree, function (x, p) { if (x.tag === 'style') { css = css.concat(rules(text(x))); p.kids.splice(p.kids.indexOf(x), 1); p.dirty = true; } });
    walk(tree, function (x) {
      if (x.tag === '#root') return;
      css.forEach(function (r) { if (r.sel.some(function (s) { return matches(x, s); })) r.decls.forEach(function (d) { if (PAINT_PROPS.indexOf(d[0]) >= 0) set(x, d[0], d[1]); }); });
      var st = get(x, 'style');
      if (st !== null) {
        var keep = [];
        decls(st).forEach(function (d) { if (PAINT_PROPS.indexOf(d[0]) >= 0) set(x, d[0], d[1]); else keep.push(d[0] + ':' + d[1]); });
        set(x, 'style', keep.length ? keep.join(';') : null);
      }
    });

    // var() and currentColor in every attribute.
    walk(tree, function (x) {
      x.attrs.slice().forEach(function (a) {
        var v = a[1];
        if (v.indexOf('var(') >= 0) {
          v = v.replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)/g, function (_, name, fb) {
            if (o.vars && o.vars[name] != null) return o.vars[name];
            if (fb != null && fb.trim()) return fb.trim();
            notes.push(a[0] + '="' + a[1] + '": no value for ' + name + ' (pass it in vars)');
            return '';
          });
          set(x, a[0], v.trim() ? v : null);
        }
        if (/currentColor/i.test(a[1])) set(x, a[0], a[1].replace(/currentColor/gi, o.color || '#000000'));
      });
    });

    // Masks: each use becomes MSK_n holding its layers in order, then the content.
    var masks = {};
    if (o.masks !== false) walk(tree, function (x, p) { if (x.tag === 'mask') { masks[get(x, 'id')] = x; p.kids.splice(p.kids.indexOf(x), 1); p.dirty = true; } });
    var mi = 0;
    walk(tree, function (x, p) {
      var mv = get(x, 'mask'), m = mv && /^url\(#([^)]+)\)$/.exec(mv.trim()), mk = m && masks[m[1]];
      if (!mv || o.masks === false) return;
      set(x, 'mask', null);
      if (!mk) { notes.push('mask #' + (m ? m[1] : mv) + ' not found; content shown unmasked'); return; }
      mi++;
      var layers = mk.kids.filter(function (k) { return typeof k !== 'string'; }).map(function (k, i) {
        var c = copy(k);
        walk(c, function (z) { ['x', 'y', 'width', 'height', 'cx', 'cy', 'r', 'rx', 'ry'].forEach(function (a) { var v = get(z, a); if (v && /%$/.test(v)) set(z, a, r6(num(v, /^(x|width|cx|rx)$/.test(a) ? W : /^(y|height|cy|ry)$/.test(a) ? H : Math.hypot(W, H) / Math.SQRT2))); }); });
        var white = /^(#fff|#ffffff|white)$/i.test(get(c, 'fill') || '');
        return el('g', [['id', 'MSK' + (white ? 'W' : 'B') + '_' + mi + '_' + i], ['fill', white ? '#ffffff' : '#000000']], [c]);
      });
      var g = el('g', [['id', 'MSK_' + mi]], [el('g', [['id', 'MSKL_' + mi]], layers), x]);
      p.kids.splice(p.kids.indexOf(x), 1, g); p.dirty = true;
    });

    // Pattern fills: the tiles over the shape's bounds, clipped to the shape.
    var used = {};
    walk(tree, function (x, p) {
      var f = get(x, 'fill'), m = f && /^url\(#([^)]+)\)$/.exec(f.trim()), pat = m && ids[m[1]];
      if (!pat || pat.tag !== 'pattern') return;
      if ((get(pat, 'patternUnits') || 'objectBoundingBox') !== 'userSpaceOnUse' || !SHAPES.test(x.tag)) { notes.push('pattern #' + m[1] + ': only userSpaceOnUse patterns on a shape convert'); return; }
      var b = bbox(x, ids);
      if (!b) { notes.push('pattern #' + m[1] + ': no bounds for <' + x.tag + '>'); return; }
      var pw = num(get(pat, 'width')), ph = num(get(pat, 'height')), px = num(get(pat, 'x')), py = num(get(pat, 'y')), pt = get(pat, 'patternTransform');
      // Tiles sit in pattern space: the shape's box mapped back through patternTransform.
      if (pt) {
        var inv = invert(matrix(pt));
        if (!inv) { notes.push('pattern #' + m[1] + ': patternTransform "' + pt + '" not understood'); return; }
        var cs = [[b[0], b[1]], [b[2], b[1]], [b[0], b[3]], [b[2], b[3]]].map(function (q) { return [inv[0] * q[0] + inv[2] * q[1] + inv[4], inv[1] * q[0] + inv[3] * q[1] + inv[5]]; });
        b = [Math.min.apply(null, cs.map(function (q) { return q[0]; })), Math.min.apply(null, cs.map(function (q) { return q[1]; })),
          Math.max.apply(null, cs.map(function (q) { return q[0]; })), Math.max.apply(null, cs.map(function (q) { return q[1]; }))];
      }
      var cols = Math.ceil((b[2] - px) / pw) - Math.floor((b[0] - px) / pw) + 1, rows = Math.ceil((b[3] - py) / ph) - Math.floor((b[1] - py) / ph) + 1;
      if (!(pw > 0 && ph > 0) || cols * rows > 4000) { notes.push('pattern #' + m[1] + ': ' + cols * rows + ' tiles, too many to draw'); return; }
      var cid = 'fxclip' + (++n), shape = copy(x);
      set(shape, 'fill', null); set(shape, 'id', null);
      var tiles = [];
      for (var tx = Math.floor((b[0] - px) / pw) * pw + px; tx <= b[2]; tx += pw)
        for (var ty = Math.floor((b[1] - py) / ph) * ph + py; ty <= b[3]; ty += ph)
          tiles.push(el('g', [['transform', 'translate(' + r6(tx) + ' ' + r6(ty) + ')']], pat.kids.filter(function (k) { return typeof k !== 'string'; }).map(copy)));
      var inner = el('g', pt ? [['transform', pt]] : [], tiles), own = get(x, 'transform');
      if (own) inner = el('g', [['transform', own]], [inner]);
      var g = el('g', [['clip-path', 'url(#' + cid + ')']], [inner]);
      ['mask', 'opacity', 'filter'].forEach(function (k) { var v = get(x, k); if (v !== null) { set(g, k, v); set(shape, k, null); } });
      var stroke = get(x, 'stroke');
      var out2 = [el('clipPath', [['id', cid]], [shape]), g];
      if (stroke && stroke !== 'none') { var edge = copy(x); set(edge, 'fill', 'none'); out2.push(edge); }
      p.kids.splice.apply(p.kids, [p.kids.indexOf(x), 1].concat(out2)); p.dirty = true;
      used[m[1]] = pat;
    });
    walk(tree, function (x, p) { if (x.tag === 'pattern' && used[get(x, 'id')]) { p.kids.splice(p.kids.indexOf(x), 1); p.dirty = true; } });

    // Drop-shadow filters: a blurred, offset, faded copy painted under the shape.
    walk(tree, function (x, p) {
      var f = get(x, 'filter'), m = f && /^url\(#([^)]+)\)$/.exec(f.trim()), fl = m && ids[m[1]];
      if (!fl || fl.tag !== 'filter') return;
      var sh = shadowOf(fl);
      if (!sh) { notes.push('filter #' + m[1] + ': kept as is (Figma draws only a plain blur)'); return; }
      var bid = m[1] + '-blur';
      if (!ids[bid]) { ids[bid] = el('filter', [['id', bid], ['x', '-50%'], ['y', '-50%'], ['width', '200%'], ['height', '200%']], [el('feGaussianBlur', [['stdDeviation', String(sh.std)]])]); fl.parent2 = true; insertAfter(tree, fl, ids[bid]); }
      var ghost = copy(x); set(ghost, 'filter', null); set(ghost, 'id', null);
      walk(ghost, function (k) { if (get(k, 'fill') && get(k, 'fill') !== 'none') set(k, 'fill', '#000000'); if (get(k, 'stroke') && get(k, 'stroke') !== 'none') set(k, 'stroke', '#000000'); set(k, 'id', null); });
      var gs = el('g', [['transform', 'translate(' + r6(sh.dx) + ' ' + r6(sh.dy) + ')'], ['opacity', String(sh.alpha)], ['filter', 'url(#' + bid + ')']], [ghost]);
      set(x, 'filter', null);
      var at = p.kids.indexOf(x);
      if (sh.keep) p.kids.splice(at, 0, gs); else p.kids.splice(at, 1, gs);
      p.dirty = true;
    });

    return { svg: changed(tree) ? out(tree) : String(svg), notes: notes };
  }

  // An SVG transform list as [a, b, c, d, e, f], or null for one it can't read.
  function matrix(t) {
    var M = [1, 0, 0, 1, 0, 0], ok = true, re = /(\w+)\s*\(([^)]*)\)/g, m;
    var mul = function (A, B) { return [A[0] * B[0] + A[2] * B[1], A[1] * B[0] + A[3] * B[1], A[0] * B[2] + A[2] * B[3], A[1] * B[2] + A[3] * B[3], A[0] * B[4] + A[2] * B[5] + A[4], A[1] * B[4] + A[3] * B[5] + A[5]]; };
    while ((m = re.exec(t))) {
      var v = m[2].trim().split(/[\s,]+/).map(Number), k = m[1], T;
      if (k === 'translate') T = [1, 0, 0, 1, v[0] || 0, v[1] || 0];
      else if (k === 'scale') T = [v[0], 0, 0, v[1] == null ? v[0] : v[1], 0, 0];
      else if (k === 'rotate') {
        var a = v[0] * Math.PI / 180, co = Math.cos(a), si = Math.sin(a), cx = v[1] || 0, cy = v[2] || 0;
        T = mul(mul([1, 0, 0, 1, cx, cy], [co, si, -si, co, 0, 0]), [1, 0, 0, 1, -cx, -cy]);
      } else if (k === 'matrix' && v.length === 6) T = v;
      else if (k === 'skewX') T = [1, 0, Math.tan(v[0] * Math.PI / 180), 1, 0, 0];
      else if (k === 'skewY') T = [1, Math.tan(v[0] * Math.PI / 180), 0, 1, 0, 0];
      else ok = false;
      if (T) M = mul(M, T);
    }
    return ok ? M : null;
  }
  function invert(M) {
    if (!M) return null;
    var det = M[0] * M[3] - M[1] * M[2];
    if (Math.abs(det) < 1e-9) return null;
    return [M[3] / det, -M[1] / det, -M[2] / det, M[0] / det, (M[2] * M[5] - M[3] * M[4]) / det, (M[1] * M[4] - M[0] * M[5]) / det];
  }
  function insertAfter(tree, after, node) {
    walk(tree, function (x) { var i = x.kids.indexOf(after); if (i >= 0) { x.kids.splice(i + 1, 0, node); x.dirty = true; } });
  }
  function r6(v) { return String(Math.round(v * 1e4) / 1e4); }

  // {std, dx, dy, alpha, keep} for blur(SourceAlpha) → offset → alpha slope → [merge with SourceGraphic].
  function shadowOf(fl) {
    var k = fl.kids.filter(function (z) { return typeof z !== 'string'; }), i = 0, sh = { std: 0, dx: 0, dy: 0, alpha: 1, keep: false };
    if (!k[i] || k[i].tag !== 'feGaussianBlur' || get(k[i], 'in') !== 'SourceAlpha') return null;
    sh.std = parseFloat((get(k[i], 'stdDeviation') || '0').split(/[\s,]+/)[0]); i++;
    if (k[i] && k[i].tag === 'feOffset') { sh.dx = num(get(k[i], 'dx')); sh.dy = num(get(k[i], 'dy')); i++; }
    if (k[i] && k[i].tag === 'feComponentTransfer') {
      var a = k[i].kids.filter(function (z) { return typeof z !== 'string' && z.tag === 'feFuncA'; })[0];
      if (a && get(a, 'type') === 'linear') sh.alpha = parseFloat(get(a, 'slope') || '1'); i++;
    }
    if (k[i] && k[i].tag === 'feMerge') {
      var ins = k[i].kids.filter(function (z) { return typeof z !== 'string'; }).map(function (z) { return get(z, 'in'); });
      if (ins.length !== 2 || ins[0] || ins[1] !== 'SourceGraphic') return null;
      sh.keep = true; i++;
    }
    return i === k.length ? sh : null;
  }

  // [x0, y0, x1, y1] of a shape from its attributes (path control points included).
  function bbox(x, ids) {
    var a = function (k) { return num(get(x, k)); };
    if (x.tag === 'rect') return [a('x'), a('y'), a('x') + a('width'), a('y') + a('height')];
    if (x.tag === 'circle') return [a('cx') - a('r'), a('cy') - a('r'), a('cx') + a('r'), a('cy') + a('r')];
    if (x.tag === 'ellipse') return [a('cx') - a('rx'), a('cy') - a('ry'), a('cx') + a('rx'), a('cy') + a('ry')];
    if (x.tag === 'use') { var t = ids[(get(x, 'href') || get(x, 'xlink:href') || '').slice(1)]; return t ? bbox(t, ids) : null; }
    var pts = [];
    if (x.tag === 'polygon' || x.tag === 'polyline') { var v = (get(x, 'points') || '').trim().split(/[\s,]+/).map(Number); for (var i = 0; i + 1 < v.length; i += 2) pts.push([v[i], v[i + 1]]); }
    else if (x.tag === 'line') pts = [[a('x1'), a('y1')], [a('x2'), a('y2')]];
    else if (x.tag === 'path') pts = pathPoints(get(x, 'd') || '');
    if (!pts.length) return null;
    var xs = pts.map(function (p) { return p[0]; }), ys = pts.map(function (p) { return p[1]; });
    return [Math.min.apply(null, xs), Math.min.apply(null, ys), Math.max.apply(null, xs), Math.max.apply(null, ys)];
  }
  function pathPoints(d) {
    var toks = d.match(/[a-zA-Z]|-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/g) || [], i = 0, cmd = '', x = 0, y = 0, sx = 0, sy = 0, pts = [];
    var N = { M: 2, L: 2, H: 1, V: 1, C: 6, S: 4, Q: 4, T: 2, A: 7, Z: 0 };
    while (i < toks.length) {
      if (/[a-zA-Z]/.test(toks[i])) cmd = toks[i++];
      var U = cmd.toUpperCase(), rel = cmd !== U, n = N[U];
      if (U === 'Z') { x = sx; y = sy; continue; }
      if (n === undefined) break;
      var v = toks.slice(i, i + n).map(Number); i += n;
      if (v.length < n) break;
      var ox = rel ? x : 0, oy = rel ? y : 0;
      if (U === 'H') { x = v[0] + (rel ? x : 0); pts.push([x, y]); }
      else if (U === 'V') { y = v[0] + (rel ? y : 0); pts.push([x, y]); }
      else if (U === 'A') { x = v[5] + ox; y = v[6] + oy; pts.push([x - v[0], y - v[1]], [x + v[0], y + v[1]]); }
      else { for (var j = 0; j < n; j += 2) pts.push([v[j] + ox, v[j + 1] + oy]); x = v[n - 2] + ox; y = v[n - 1] + oy; }
      if (U === 'M') { sx = x; sy = y; cmd = rel ? 'l' : 'L'; }
    }
    return pts;
  }

  // ---- after createNodeFromSvg: each MSK_n group's layers into one Figma mask ----
  function finish(node) {
    var notes = [], masks = 0;
    var isShape = function (z) { return 'vectorNetwork' in z || /^(RECTANGLE|ELLIPSE|POLYGON|STAR|LINE|VECTOR|BOOLEAN_OPERATION)$/.test(z.type); };
    var groups = node.findAll(function (z) { return /(^|-)MSK_\d+$/.test(z.name); }).reverse();
    groups.forEach(function (g) {
      try {
        var L = g.children.filter(function (c) { return /(^|-)MSKL_\d+$/.test(c.name); })[0], acc = null;
        if (!L) return;
        L.children.slice().forEach(function (layer) {
          // Figma deletes a group its last child leaves, so read the layer before flattening it.
          var white = /(^|-)MSKW_\d+_\d+$/.test(layer.name);
          var shapes = layer.type === 'GROUP' || layer.type === 'FRAME' ? layer.findAll(isShape) : isShape(layer) ? [layer] : [];
          if (!shapes.length) return;
          var v = figma.flatten(shapes, g, acc ? 1 : 0);
          if (white) acc = acc ? figma.union([acc, v], g, 0) : v;
          else if (acc) acc = figma.subtract([acc, v], g, 0);
          else v.remove();
          if (!layer.removed) layer.remove();
        });
        if (!L.removed) L.remove();
        if (!acc) { acc = figma.createRectangle(); acc.resize(0.01, 0.01); g.insertChild(0, acc); }
        acc.name = 'mask';
        acc.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }];
        acc.strokes = [];
        acc.isMask = true;
        masks++;
      } catch (e) { notes.push(g.name + ': ' + (e && e.message || e)); }
    });
    return { masks: masks, notes: notes };
  }

  window.__fxSvg = { v: V, prepare: prepare, finish: finish };
})();
