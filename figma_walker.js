// DOM → capture envelope {meta, flagged, assets, nodes}. Runs in the SOURCE page
// under agent-browser, which awaits the returned promise; figma_capture.py
// persists the result. No Figma API here. Schema: references/capture.md.
(async function () {
  var XHTML = 'http://www.w3.org/1999/xhtml';
  var SVGNS = 'http://www.w3.org/2000/svg';
  var MAX_DEPTH = 60;
  var ASSET_TIMEOUT_MS = 8000, ASSET_BUDGET_MS = 20000;
  var ASSET_MAX_BYTES = 4 * 1024 * 1024, ASSET_TOTAL_BYTES = 24 * 1024 * 1024, ASSET_MAX_SIDE = 4096;
  var RASTER_MIMES = { 'image/png': 1, 'image/jpeg': 1, 'image/webp': 1, 'image/gif': 1 };
  var REPLACED = { img: 1, video: 1, audio: 1, canvas: 1, iframe: 1, svg: 1, input: 1, select: 1,
    textarea: 1, button: 1, object: 1, embed: 1 };
  var LEAF = { img: 1, video: 1, audio: 1, canvas: 1, iframe: 1, svg: 1, input: 1, select: 1,
    textarea: 1, object: 1, embed: 1 };

  var nodes = [], flagged = [], assets = {}, assetByUrl = {}, assetJobs = [], assetPending = {};
  var assetCount = 0, assetBytes = 0;
  var pseudoPending = { '::before': [], '::after': [] };

  function px(v) { var n = parseFloat(v); return isFinite(n) ? n : 0; }
  function r2(n) { return Math.round(n * 100) / 100; }

  // rgb()/rgba() → {r,g,b,a} in 0..1, null for transparent/none.
  function parseColor(s) {
    if (!s) return null;
    var m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    var p = m[1].split(/[\s,\/]+/).map(function (x) { return parseFloat(x); });
    var a = p.length > 3 ? p[3] : 1;
    if (!(a > 0)) return null;
    return { r: p[0] / 255, g: p[1] / 255, b: p[2] / 255, a: a };
  }

  // "a, b(c, d), e" → ["a", "b(c, d)", "e"]
  function splitTopLevel(s) {
    var out = [], depth = 0, start = 0;
    for (var i = 0; i < s.length; i++) {
      var ch = s[i];
      if (ch === '(') depth++;
      else if (ch === ')') depth--;
      else if (ch === ',' && depth === 0) { out.push(s.slice(start, i).trim()); start = i + 1; }
    }
    out.push(s.slice(start).trim());
    return out;
  }

  // CSS string escapes: \hex{1,6} (+ one optional whitespace) → code point,
  // escaped newline → nothing, \x → x.
  function unescapeCss(s) {
    return s.replace(/\\(?:([0-9a-fA-F]{1,6})[ \t\n\r\f]?|(\r\n|[\n\r\f])|([\s\S]))/g, function (_, hex, nl, ch) {
      if (hex) {
        var cp = parseInt(hex, 16);
        if (!cp || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return '�';
        return String.fromCodePoint(cp);
      }
      return nl ? '' : ch;
    });
  }

  // Reads one quoted CSS string starting at s[i]; returns {text, end}.
  function readCssString(s, i) {
    var q = s[i], j = i + 1, raw = '';
    while (j < s.length) {
      var d = s[j];
      if (d === '\\') { raw += d + (s[j + 1] || ''); j += 2; continue; }
      if (d === q) break;
      raw += d; j++;
    }
    return { text: unescapeCss(raw), end: j + 1 };
  }

  function cssStrings(v) {
    var out = [];
    for (var i = 0; i < v.length; i++) {
      if (v[i] === '"' || v[i] === "'") { var r = readCssString(v, i); out.push(r.text); i = r.end - 1; }
    }
    return out;
  }

  // Computed `content` → {text, url}. Strings unescaped, attr() resolved, quotes
  // from the element's `quotes`, counters/gradients → "", first url() kept.
  function resolveContent(el, cs) {
    var c = cs.content;
    var res = { text: '', url: null };
    if (!c || c === 'none' || c === 'normal') return res;
    var i = 0, n = c.length, quotes = null;
    while (i < n) {
      var ch = c[i];
      if (ch === '"' || ch === "'") { var s = readCssString(c, i); res.text += s.text; i = s.end; continue; }
      if (ch === '/') break;
      var fn = /^([-a-zA-Z]+)\(/.exec(c.slice(i));
      if (fn) {
        var depth = 0, j = i + fn[0].length - 1;
        for (; j < n; j++) { if (c[j] === '(') depth++; else if (c[j] === ')' && --depth === 0) break; }
        var inner = c.slice(i + fn[0].length, j), name = fn[1].toLowerCase();
        if (name === 'attr') {
          var attr = inner.trim().split(/[\s,]+/)[0];
          res.text += (el.getAttribute && el.getAttribute(attr)) || '';
        } else if (name === 'url' && !res.url) {
          res.url = inner.trim().replace(/^["']|["']$/g, '');
        }
        i = j + 1; continue;
      }
      var w = /^[-\w]+/.exec(c.slice(i));
      if (w) {
        if (w[0] === 'open-quote' || w[0] === 'close-quote') {
          if (!quotes) quotes = cssStrings(cs.quotes || '');
          res.text += w[0] === 'open-quote' ? (quotes[0] || '"') : (quotes[1] || '"');
        }
        i += w[0].length; continue;
      }
      i++;
    }
    return res;
  }

  function kidsOf(el) {
    if (el.shadowRoot) return el.shadowRoot.childNodes;
    if (el.localName === 'slot' && el.assignedNodes) {
      var root = el.getRootNode();
      if (root && root.nodeType === 11 && root.host) return el.assignedNodes({ flatten: true });
    }
    return el.childNodes;
  }

  function hasElementKids(el) {
    var kids = kidsOf(el);
    for (var i = 0; i < kids.length; i++) if (kids[i].nodeType === 1) return true;
    return false;
  }

  // ----- geometry

  function lengthPx(tok, ref) {
    return /%$/.test(tok) ? parseFloat(tok) / 100 * ref : px(tok);
  }

  // Own transform as T(origin)·(translate·rotate·scale·transform)·T(−origin).
  // {m} for a usable 2D affine, {flag:true} for 3D / singular, null for none.
  function ownTransform(el, cs) {
    var t = cs.transform, tr = cs.translate, ro = cs.rotate, sc = cs.scale;
    function none(v) { return !v || v === 'none'; }
    if (none(t) && none(tr) && none(ro) && none(sc)) return null;
    var parts = [], toks;
    if (!none(tr)) {
      toks = tr.split(/\s+/);
      if (toks.length > 2) return { flag: true };
      parts.push('translate(' + lengthPx(toks[0], el.offsetWidth) + 'px, ' +
        lengthPx(toks[1] || '0px', el.offsetHeight) + 'px)');
    }
    if (!none(ro)) {
      toks = ro.split(/\s+/);
      if (toks.length > 1 && !(toks.length === 2 && toks[0] === 'z')) return { flag: true };
      parts.push('rotate(' + toks[toks.length - 1] + ')');
    }
    if (!none(sc)) {
      toks = sc.split(/\s+/);
      if (toks.length > 2) return { flag: true };
      parts.push('scale(' + toks[0] + ', ' + (toks[1] || toks[0]) + ')');
    }
    if (!none(t)) parts.push(t);
    var m;
    try { m = new DOMMatrix(parts.join(' ')); } catch (e) { return { flag: true }; }
    if (!m.is2D) {
      // matrix3d() with identity depth components (translateZ(0)-style hacks) is still planar.
      var depthPart = Math.abs(m.m13) + Math.abs(m.m14) + Math.abs(m.m23) + Math.abs(m.m24) +
        Math.abs(m.m31) + Math.abs(m.m32) + Math.abs(m.m33 - 1) + Math.abs(m.m34) +
        Math.abs(m.m43) + Math.abs(m.m44 - 1);
      if (depthPart > 1e-6) return { flag: true };
      m = new DOMMatrix([m.a, m.b, m.c, m.d, m.e, m.f]);
    }
    var o = (cs.transformOrigin || '0px 0px').split(/\s+/);
    var ox = px(o[0]), oy = px(o[1]);
    var own = new DOMMatrix().translate(ox, oy).multiply(m).translate(-ox, -oy);
    if (Math.abs(own.a * own.d - own.b * own.c) < 1e-6) return { flag: true };
    var eps = 1e-9;
    if (Math.abs(own.a - 1) < eps && Math.abs(own.b) < eps && Math.abs(own.c) < eps &&
        Math.abs(own.d - 1) < eps && Math.abs(own.e) < eps && Math.abs(own.f) < eps) return null;
    return { m: own };
  }

  // Untransformed layout box of `el` with every ancestor transform undone by `inv`
  // (viewport → parent layout space). cP = inv·(bcr center) is the image of the
  // layout center under the own transform, so tl = cP − own·(w/2,h/2). Children
  // get invChild = T(tl)·own⁻¹·T(−tl)·inv, which maps into this box's local space.
  function geometry(el, cs, inv, isHtml, tag) {
    var bcr = el.getBoundingClientRect();
    var own = null, flag = false;
    if (isHtml && (cs.display !== 'inline' || REPLACED[tag])) {
      var o = ownTransform(el, cs);
      if (o) { if (o.flag) flag = true; else own = o.m; }
    }
    // Bounding boxes of rotated/skewed/3D boxes are axis-aligned hulls, so the
    // layout size comes from offsetWidth/Height whenever any transform is involved.
    var axisAligned = Math.abs(inv.b) < 1e-9 && Math.abs(inv.c) < 1e-9;
    var w, h;
    if (own || flag || (isHtml && !axisAligned)) { w = el.offsetWidth; h = el.offsetHeight; }
    else if (axisAligned) { w = bcr.width * Math.abs(inv.a); h = bcr.height * Math.abs(inv.d); }
    else { w = bcr.width; h = bcr.height; }
    var cP = inv.transformPoint({ x: bcr.left + bcr.width / 2, y: bcr.top + bcr.height / 2 });
    var cL = own ? own.transformPoint({ x: w / 2, y: h / 2 }) : { x: w / 2, y: h / 2 };
    var tx = cP.x - cL.x, ty = cP.y - cL.y;
    var invChild = own
      ? new DOMMatrix().translate(tx, ty).multiply(own.inverse()).translate(-tx, -ty).multiply(inv)
      : inv;
    var g = { rect: { x: r2(tx), y: r2(ty), w: r2(w), h: r2(h) }, x: tx, y: ty, w: w, h: h,
      invChild: invChild, flag: flag };
    if (own) g.xf = [own.a, own.b, own.c, own.d, own.e, own.f].map(function (v) { return Math.round(v * 1e6) / 1e6; });
    return g;
  }

  // Line boxes: fragment rects mapped into layout space, clustered when midlines
  // are within 1px or the fragments overlap by more than half the smaller height
  // (mixed font sizes on one line).
  function lineCount(el, inv, vertical) {
    var rects;
    try {
      var range = el.ownerDocument.createRange();
      range.selectNodeContents(el);
      rects = range.getClientRects();
    } catch (e) { return 1; }
    var frags = [];
    for (var i = 0; i < rects.length; i++) {
      var r = rects[i];
      if (!r.width || !r.height) continue;
      var a = inv.transformPoint({ x: r.left, y: r.top });
      var b = inv.transformPoint({ x: r.right, y: r.bottom });
      var lo = vertical ? Math.min(a.x, b.x) : Math.min(a.y, b.y);
      var hi = vertical ? Math.max(a.x, b.x) : Math.max(a.y, b.y);
      frags.push({ lo: lo, hi: hi, mid: (lo + hi) / 2 });
    }
    if (!frags.length) return 1;
    frags.sort(function (p, q) { return p.mid - q.mid; });
    var n = 1, cur = frags[0];
    for (var j = 1; j < frags.length; j++) {
      var f = frags[j];
      var overlap = Math.min(f.hi, cur.hi) - Math.max(f.lo, cur.lo);
      var minH = Math.min(f.hi - f.lo, cur.hi - cur.lo);
      if (Math.abs(f.mid - cur.mid) <= 1 || overlap > minH / 2) continue;
      n++; cur = f;
    }
    return n;
  }

  // ----- styles

  function firstFamily(ff) {
    return (splitTopLevel(ff || '')[0] || '').replace(/^["']|["']$/g, '');
  }

  function decorationOf(cs) {
    return ((cs.textDecorationLine || cs.textDecoration || 'none').split(/\s+/)[0]) || 'none';
  }

  function blurPx(v) {
    var m = /blur\(\s*([\d.]+)px\s*\)/.exec(v || '');
    return m ? parseFloat(m[1]) : 0;
  }

  function radiusPx(v, ref) {
    var tok = (v || '0px').split(/\s+/)[0];
    return /%$/.test(tok) ? parseFloat(tok) / 100 * ref : px(tok);
  }

  function parseShadow(v) {
    if (!v || v === 'none') return null;
    var out = [];
    splitTopLevel(v).forEach(function (item) {
      var cm = item.match(/rgba?\([^)]*\)/);
      var color = parseColor(cm ? cm[0] : '');
      if (!color) return;
      var rest = item.replace(cm[0], '');
      var inset = /\binset\b/.test(rest);
      var nums = rest.replace(/\binset\b/, '').trim().split(/\s+/).map(px);
      out.push({ x: nums[0] || 0, y: nums[1] || 0, blur: nums[2] || 0, spread: nums[3] || 0,
        color: color, inset: inset });
    });
    return out.length ? out : null;
  }

  // CSS Typed OM value → specified-size category. Duck-typed: iframe realms have
  // their own CSSUnitValue/CSSKeywordValue constructors.
  function sizeCategory(v) {
    if (!v) return 'other';
    if (typeof v.unit === 'string') return v.unit === 'px' ? 'px' : v.unit === 'percent' ? 'pct' : 'other';
    if (typeof v.value === 'string') {
      var k = v.value;
      if (k === 'auto' || k === 'fit-content' || k === 'min-content' || k === 'max-content') return 'auto';
      if (k === 'stretch' || k === '-webkit-fill-available') return 'pct';
    }
    return 'other';
  }

  function sizing(st, el) {
    var map = null;
    try { map = el.computedStyleMap ? el.computedStyleMap() : null; } catch (e) { map = null; }
    if (!map) { st.sz = ['px', 'px']; return; }
    var w = sizeCategory(map.get('width')), h = sizeCategory(map.get('height'));
    if (w !== 'auto' || h !== 'auto') st.sz = [w, h];
    [['min-width', 'minW', 0], ['max-width', 'maxW', 1], ['min-height', 'minH', 0], ['max-height', 'maxH', 1]]
      .forEach(function (p) {
        var v = map.get(p[0]);
        if (v && v.unit === 'px' && (p[2] || v.value > 0)) st[p[1]] = r2(v.value);
      });
  }

  function styleOf(cs, el, hasText, w, h) {
    var st = {};
    if (cs.display !== 'block') st.display = cs.display;
    if (cs.position !== 'static') st.position = cs.position;
    if (cs.flexDirection !== 'row') st.flexDirection = cs.flexDirection;
    if (cs.flexWrap !== 'nowrap') st.flexWrap = cs.flexWrap;
    if (cs.justifyContent !== 'normal') st.justifyContent = cs.justifyContent;
    if (cs.alignItems !== 'normal') st.alignItems = cs.alignItems;
    if (cs.alignSelf !== 'auto') st.alignSelf = cs.alignSelf;
    var grow = px(cs.flexGrow); if (grow) st.flexGrow = grow;
    var gap = px(cs.rowGap); if (gap) st.gap = gap;
    var cgap = px(cs.columnGap); if (cgap) st.columnGap = cgap;
    var pad = [px(cs.paddingTop), px(cs.paddingRight), px(cs.paddingBottom), px(cs.paddingLeft)];
    if (pad[0] || pad[1] || pad[2] || pad[3]) st.padding = pad;
    if (cs.overflow !== 'visible') st.overflow = cs.overflow;
    sizing(st, el);

    var bg = parseColor(cs.backgroundColor); if (bg) st.bg = bg;
    var rad = [cs.borderTopLeftRadius, cs.borderTopRightRadius, cs.borderBottomRightRadius, cs.borderBottomLeftRadius]
      .map(function (v) { return r2(radiusPx(v, w)); });
    if (rad[0] === rad[1] && rad[1] === rad[2] && rad[2] === rad[3]) { if (rad[0]) st.radius = rad[0]; }
    else st.radii = rad;
    var widths = [], borderColor = null;
    ['Top', 'Right', 'Bottom', 'Left'].forEach(function (s) {
      var style = cs['border' + s + 'Style'], bw = px(cs['border' + s + 'Width']);
      var col = parseColor(cs['border' + s + 'Color']);
      if (!bw || style === 'none' || style === 'hidden' || !col) { widths.push(0); return; }
      widths.push(bw);
      if (!borderColor) borderColor = col;
    });
    if (borderColor) {
      var uniform = widths[0] === widths[1] && widths[1] === widths[2] && widths[2] === widths[3];
      st.border = { w: uniform ? widths[0] : widths, color: borderColor };
    }
    var shadow = parseShadow(cs.boxShadow); if (shadow) st.shadow = shadow;
    var op = parseFloat(cs.opacity); if (isFinite(op) && op !== 1) st.opacity = op;
    var bl = blurPx(cs.filter); if (bl) st.blur = bl;
    var bb = blurPx(cs.backdropFilter || cs.webkitBackdropFilter); if (bb) st.bgBlur = bb;

    if (hasText) {
      var color = parseColor(cs.color); if (color) st.color = color;
      var fam = firstFamily(cs.fontFamily); if (fam) st.fontFamily = fam;
      var fs = px(cs.fontSize); if (fs !== 16) st.fontSize = fs;
      var fw = parseInt(cs.fontWeight, 10) || 400; if (fw !== 400) st.fontWeight = fw;
      if (cs.fontStyle && cs.fontStyle !== 'normal') st.fontStyle = 'italic';
      if (cs.lineHeight && cs.lineHeight !== 'normal') st.lineHeight = px(cs.lineHeight);
      var ls = cs.letterSpacing === 'normal' ? 0 : px(cs.letterSpacing); if (ls) st.letterSpacing = ls;
      if (cs.textAlign !== 'start') st.textAlign = cs.textAlign;
      var dec = decorationOf(cs); if (dec !== 'none') st.textDecoration = dec;
      if (cs.textTransform !== 'none') st.textTransform = cs.textTransform;
    }
    return st;
  }

  // ----- text

  function isInlineTextOnly(el) {
    var kids = kidsOf(el);
    if (!kids.length) return false;
    var sawText = false;
    for (var i = 0; i < kids.length; i++) {
      var c = kids[i];
      if (c.nodeType === 3) { if (c.nodeValue.trim()) sawText = true; continue; }
      if (c.nodeType !== 1) continue;
      var d;
      try { d = getComputedStyle(c).display; } catch (e) { return false; }
      if (d.indexOf('inline') !== 0) return false;
      if (!isInlineTextOnly(c) && c.textContent.trim() && hasElementKids(c)) return false;
      if (c.textContent.trim()) sawText = true;
    }
    return sawText;
  }

  function runStyle(cs, dec) {
    return { color: parseColor(cs.color), fontSize: px(cs.fontSize), fontWeight: parseInt(cs.fontWeight, 10) || 400,
      fontStyle: cs.fontStyle && cs.fontStyle !== 'normal' ? 'italic' : 'normal',
      textDecoration: dec, fontFamily: firstFamily(cs.fontFamily) };
  }

  function runKey(r) {
    return JSON.stringify([r.color, r.fontSize, r.fontWeight, r.fontStyle, r.textDecoration, r.fontFamily]);
  }

  // Runs of an inline-text-only subtree, split where span styles differ.
  // text-decoration does not inherit in computed style but paints through
  // descendants, so the nearest decorated ancestor's line is carried down.
  function collectRuns(el, baseCs) {
    var runs = [];
    function walk(node, cs, dec) {
      var kids = kidsOf(node);
      for (var i = 0; i < kids.length; i++) {
        var c = kids[i];
        if (c.nodeType === 3) {
          if (c.nodeValue === '') continue;
          runs.push(Object.assign({ text: c.nodeValue }, runStyle(cs, dec)));
        } else if (c.nodeType === 1) {
          var ccs;
          try { ccs = getComputedStyle(c); } catch (e) { ccs = cs; }
          if (ccs.display === 'none') continue;
          var cdec = decorationOf(ccs);
          walk(c, ccs, cdec !== 'none' ? cdec : dec);
        }
      }
    }
    walk(el, baseCs, decorationOf(baseCs));
    return runs;
  }

  // Collapses whitespace across run boundaries and merges same-style neighbours
  // so that runs.map(text).join('') === text exactly.
  function normalizeRuns(raw) {
    var out = [];
    raw.forEach(function (r) {
      var t = r.text.replace(/\s+/g, ' ');
      var last = out[out.length - 1];
      if (!last || last.text.slice(-1) === ' ') t = t.replace(/^ /, '');
      if (t === '') return;
      if (last && runKey(last) === runKey(r)) last.text += t;
      else out.push(Object.assign({}, r, { text: t }));
    });
    while (out.length) {
      var end = out[out.length - 1];
      end.text = end.text.replace(/ $/, '');
      if (end.text !== '') break;
      out.pop();
    }
    var text = out.map(function (m) { return m.text; }).join('');
    return { text: text, runs: out.length > 1 ? out : null };
  }

  // ----- semantic layer: cheap in-page ARIA approximation for layer naming and
  // component matching, not a spec-compliant accname/role computation.

  var IMPLICIT_ROLE = {
    button: 'button', nav: 'navigation', header: 'banner', footer: 'contentinfo',
    main: 'main', aside: 'complementary', ul: 'list', ol: 'list', li: 'listitem',
    select: 'combobox', textarea: 'textbox', img: 'img', table: 'table',
    form: 'form', section: 'region', article: 'article', label: 'label'
  };
  var INTERACTIVE_ROLES = { button: 1, link: 1, textbox: 1, combobox: 1,
    checkbox: 1, radio: 1, menuitem: 1, tab: 1 };

  function isHeadingTag(tag) {
    return tag.length === 2 && tag.charAt(0) === 'h' && tag >= 'h1' && tag <= 'h6';
  }

  // Explicit aria role wins, else implicit-by-tag. a[href]→link (bare <a> stays
  // null), input→textbox unless its type is a known control.
  function roleOf(el, tag) {
    var explicit = el.getAttribute && el.getAttribute('role');
    if (explicit) { explicit = explicit.trim().split(/\s+/)[0]; if (explicit) return explicit; }
    if (tag === 'a') return el.getAttribute && el.getAttribute('href') != null ? 'link' : null;
    if (tag === 'input') {
      var t = (el.getAttribute && (el.getAttribute('type') || '')).toLowerCase();
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      if (t === 'button' || t === 'submit' || t === 'reset' || t === 'image') return 'button';
      if (t === 'range') return 'slider';
      if (t === 'hidden') return null;
      return 'textbox';
    }
    if (isHeadingTag(tag)) return 'heading';
    return IMPLICIT_ROLE[tag] || null;
  }

  function headingLevel(tag) {
    return isHeadingTag(tag) ? +tag.charAt(1) : null;
  }

  function cap80(s) {
    s = (s || '').replace(/\s+/g, ' ').trim();
    return s.length > 80 ? s.slice(0, 80) : s;
  }

  // aria-label, else aria-labelledby joined text, else form-control labels, else
  // alt, else title, else trimmed text for heading/button/link, else null.
  function axNameOf(el, role, ownText) {
    if (!el.getAttribute) return null;
    var lbl = el.getAttribute('aria-label');
    if (lbl && lbl.trim()) return cap80(lbl);
    var ref = el.getAttribute('aria-labelledby');
    if (ref) {
      var parts = [];
      ref.trim().split(/\s+/).forEach(function (id) {
        var t = el.ownerDocument && el.ownerDocument.getElementById(id);
        if (t && t.textContent) parts.push(t.textContent);
      });
      var joined = cap80(parts.join(' '));
      if (joined) return joined;
    }
    var ctl = el.tagName ? el.tagName.toLowerCase() : '';
    if (ctl === 'input' || ctl === 'select' || ctl === 'textarea') {
      var typ = (el.getAttribute('type') || '').toLowerCase();
      if ((typ === 'submit' || typ === 'button' || typ === 'reset') && el.value) return cap80(el.value);
      var nm = '', id = el.getAttribute('id');
      if (id && el.ownerDocument) {
        try {
          var esc = (typeof CSS !== 'undefined' && CSS.escape) ? CSS.escape(id) : id.replace(/"/g, '\\"');
          var labs = el.ownerDocument.querySelectorAll('label[for="' + esc + '"]');
          for (var li = 0; li < labs.length; li++) nm += ' ' + labs[li].textContent;
        } catch (e) {}
      }
      if (!nm.trim()) {
        var anc = el.parentElement;
        while (anc) { if (anc.tagName && anc.tagName.toLowerCase() === 'label') { nm = anc.textContent; break; } anc = anc.parentElement; }
      }
      nm = cap80(nm);
      if (nm) return nm;
      var ph = el.getAttribute('placeholder');
      if (ph && ph.trim()) return cap80(ph);
    }
    var alt = el.getAttribute('alt');
    if (alt != null && alt.trim()) return cap80(alt);
    var title = el.getAttribute('title');
    if (title && title.trim()) return cap80(title);
    if (role === 'heading' || role === 'button' || role === 'link') {
      var t2 = cap80(ownText || el.textContent || '');
      if (t2) return t2;
    }
    return null;
  }

  // Real control tags, interactive roles, focusable (tabindex>=0), or cursor:pointer.
  function interactableOf(el, tag, role, cursor) {
    if (tag === 'button' || tag === 'select' || tag === 'textarea') return true;
    if (tag === 'a' && el.getAttribute && el.getAttribute('href') != null) return true;
    if (tag === 'input') {
      var t = (el.getAttribute('type') || '').toLowerCase();
      if (t !== 'hidden') return true;
    }
    if (role && INTERACTIVE_ROLES[role]) return true;
    var ti = el.getAttribute && el.getAttribute('tabindex');
    if (ti != null && ti !== '' && +ti >= 0) return true;
    if (cursor === 'pointer') return true;
    return false;
  }

  // ----- assets

  function newAsset(kind) {
    var key = 'a' + (++assetCount);
    assets[key] = { kind: kind };
    assetPending[key] = true;
    return key;
  }

  function store(key, fields) {
    var a = assets[key];
    var bytes = fields.b64 ? Math.floor(fields.b64.length * 3 / 4) : (fields.svg ? fields.svg.length : 0);
    delete assetPending[key];
    if (bytes > ASSET_MAX_BYTES || assetBytes + bytes > ASSET_TOTAL_BYTES) { a.error = 'too-large'; return; }
    assetBytes += bytes;
    Object.assign(a, fields);
  }

  function fail(key, error) {
    delete assetPending[key];
    assets[key].error = error;
  }

  function fetchBlob(url) {
    var ctl = new AbortController();
    var timer = setTimeout(function () { ctl.abort(); }, ASSET_TIMEOUT_MS);
    return fetch(url, { signal: ctl.signal }).then(function (res) {
      if (!res.ok) throw new Error('fetch');
      return res.blob();
    }).finally(function () { clearTimeout(timer); });
  }

  function blobToBase64(blob) {
    return new Promise(function (resolve, reject) {
      var fr = new FileReader();
      fr.onload = function () { resolve(String(fr.result).split(',')[1] || ''); };
      fr.onerror = function () { reject(new Error('decode')); };
      fr.readAsDataURL(blob);
    });
  }

  function drawScaled(source, sw, sh) {
    var s = Math.min(1, ASSET_MAX_SIDE / Math.max(sw, sh));
    var c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(sw * s));
    c.height = Math.max(1, Math.round(sh * s));
    c.getContext('2d').drawImage(source, 0, 0, c.width, c.height);
    return c;
  }

  function canvasToBase64(c, mime) {
    return new Promise(function (resolve, reject) {
      c.toBlob(function (b) { if (!b) reject(new Error('decode')); else blobToBase64(b).then(resolve, reject); }, mime, 0.92);
    });
  }

  async function elementFallback(key, imgEl) {
    var w = imgEl.naturalWidth, h = imgEl.naturalHeight;
    if (!w || !h) { fail(key, 'decode'); return; }
    try {
      var c = drawScaled(imgEl, w, h);
      store(key, { mime: 'image/png', b64: await canvasToBase64(c, 'image/png'), w: c.width, h: c.height });
    } catch (e) { fail(key, e && e.name === 'SecurityError' ? 'tainted' : 'decode'); }
  }

  async function rasterJob(key, url, imgEl, fallbackW, fallbackH) {
    try {
      var blob = await fetchBlob(url);
      if (blob.type === 'image/svg+xml' || /\.svg([?#]|$)/i.test(url)) {
        assets[key].kind = 'svg';
        var text = await blob.text();
        var w = imgEl && imgEl.naturalWidth ? imgEl.naturalWidth : Math.round(fallbackW);
        var h = imgEl && imgEl.naturalHeight ? imgEl.naturalHeight : Math.round(fallbackH);
        store(key, { svg: text, w: w, h: h });
        return;
      }
      if (blob.size > ASSET_MAX_BYTES) { fail(key, 'too-large'); return; }
      var bmp;
      try { bmp = await createImageBitmap(blob); } catch (e) { throw new Error('decode'); }
      try {
        if (RASTER_MIMES[blob.type] && bmp.width <= ASSET_MAX_SIDE && bmp.height <= ASSET_MAX_SIDE) {
          store(key, { mime: blob.type, b64: await blobToBase64(blob), w: bmp.width, h: bmp.height });
        } else {
          var c = drawScaled(bmp, bmp.width, bmp.height);
          var mime = blob.type === 'image/jpeg' ? 'image/jpeg' : 'image/png';
          store(key, { mime: mime, b64: await canvasToBase64(c, mime), w: c.width, h: c.height });
        }
      } finally { bmp.close(); }
    } catch (e) {
      if (e && e.name === 'AbortError') fail(key, 'timeout');
      else if (imgEl) await elementFallback(key, imgEl);
      else fail(key, e && e.message === 'decode' ? 'decode' : 'fetch');
    }
  }

  function assetForUrl(url, imgEl, w, h) {
    var abs;
    try { abs = new URL(url, (imgEl || document).baseURI).href; } catch (e) { abs = url; }
    if (assetByUrl[abs]) return assetByUrl[abs];
    var key = newAsset('image');
    assetByUrl[abs] = key;
    assetJobs.push(rasterJob(key, abs, imgEl, w, h));
    return key;
  }

  function canvasAsset(el) {
    var key = newAsset('image');
    try {
      var w = el.width, h = el.height;
      if (!w || !h) { fail(key, 'decode'); return key; }
      var src = (w > ASSET_MAX_SIDE || h > ASSET_MAX_SIDE) ? drawScaled(el, w, h) : el;
      var data = src.toDataURL('image/png');
      store(key, { mime: 'image/png', b64: data.split(',')[1] || '', w: src.width, h: src.height });
    } catch (e) { fail(key, e && e.name === 'SecurityError' ? 'tainted' : 'decode'); }
    return key;
  }

  // <use href="#id"> targets living outside the svg (sprite sheets) are copied
  // into a <defs> so the serialized markup stands alone.
  function inlineUseRefs(src, clone) {
    var uses = clone.querySelectorAll('use');
    if (!uses.length) return;
    var root = src.getRootNode(), defs = null;
    for (var i = 0; i < uses.length; i++) {
      var ref = uses[i].getAttribute('href') || uses[i].getAttributeNS('http://www.w3.org/1999/xlink', 'href');
      if (!ref || ref.charAt(0) !== '#') continue;
      var id = ref.slice(1);
      var target = root.getElementById ? root.getElementById(id) : null;
      if (!target || clone.contains(target) || src.contains(target)) continue;
      if (!defs) { defs = src.ownerDocument.createElementNS(SVGNS, 'defs'); clone.insertBefore(defs, clone.firstChild); }
      defs.appendChild(target.cloneNode(true));
    }
  }

  function svgAsset(el, w, h) {
    var key = newAsset('svg');
    try {
      var clone = el.cloneNode(true);
      clone.setAttribute('width', String(Math.round(w)));
      clone.setAttribute('height', String(Math.round(h)));
      if (!clone.getAttribute('xmlns')) clone.setAttribute('xmlns', SVGNS);
      inlineUseRefs(el, clone);
      store(key, { svg: new XMLSerializer().serializeToString(clone), w: Math.round(w), h: Math.round(h) });
    } catch (e) { fail(key, 'decode'); }
    return key;
  }

  // First background-image url() and the FILL/FIT/TILE mode of its layer.
  function bgImage(cs) {
    var layers = splitTopLevel(cs.backgroundImage || '');
    for (var i = 0; i < layers.length; i++) {
      var m = /url\((['"]?)(.*?)\1\)/.exec(layers[i]);
      if (!m) continue;
      var size = splitTopLevel(cs.backgroundSize || '')[i] || '';
      var repeat = splitTopLevel(cs.backgroundRepeat || '')[i] || 'repeat';
      var mode = /\bcontain\b/.test(size) ? 'FIT' : /\bcover\b/.test(size) ? 'FILL' : repeat !== 'no-repeat' ? 'TILE' : 'FILL';
      return { url: m[2], mode: mode };
    }
    return null;
  }

  function imageOf(el, tag, cs, w, h) {
    if (tag === 'img') {
      var src = el.currentSrc || el.src;
      if (!src) return null;
      var fit = cs.objectFit;
      return { asset: assetForUrl(src, el, w, h), mode: fit === 'contain' || fit === 'scale-down' ? 'FIT' : 'FILL' };
    }
    if (tag === 'video') {
      if (!el.poster) return null;
      var vfit = cs.objectFit;
      return { asset: assetForUrl(el.poster, null, w, h), mode: vfit === 'contain' || vfit === 'scale-down' ? 'FIT' : 'FILL' };
    }
    if (tag === 'canvas') return { asset: canvasAsset(el), mode: 'FILL' };
    var bg = bgImage(cs);
    return bg ? { asset: assetForUrl(bg.url, null, w, h), mode: bg.mode } : null;
  }

  async function resolveAssets() {
    if (!assetJobs.length) return;
    var budget = new Promise(function (resolve) { setTimeout(resolve, ASSET_BUDGET_MS); });
    await Promise.race([Promise.all(assetJobs), budget]);
    Object.keys(assetPending).forEach(function (key) { fail(key, 'timeout'); });
  }

  // ----- walk

  function pseudoStyle(el, which) {
    try { return getComputedStyle(el, which); } catch (e) { return null; }
  }

  function hasPseudo(pcs) {
    return !!(pcs && pcs.content && pcs.content !== 'none' && pcs.content !== 'normal');
  }

  function reservePseudo(el, which, parentIdx, inv) {
    var idx = nodes.length;
    nodes.push({ i: idx, parent: parentIdx, tag: which, drop: true });
    pseudoPending[which].push({ el: el, idx: idx, inv: inv });
  }

  function visit(el, parentIdx, inv, depth) {
    if (depth > MAX_DEPTH) return;
    var cs;
    try { cs = getComputedStyle(el); } catch (e) { return; }
    if (cs.display === 'none') return;
    var isHtml = el.namespaceURI === XHTML;
    var tag = (el.localName || el.tagName || 'node').toLowerCase();
    var g = geometry(el, cs, inv, isHtml, tag);
    var rect = g.rect;
    var prune = cs.visibility === 'hidden' || rect.w === 0 || rect.h === 0;
    var myIdx = parentIdx;
    var afterCs = null;

    if (!prune) {
      myIdx = nodes.length;
      if (tag === 'iframe') {
        var doc = null;
        try { doc = el.contentDocument; } catch (e) { doc = null; }
        var frame = { i: myIdx, parent: parentIdx, tag: tag, rect: rect };
        if (g.xf) frame.xf = g.xf;
        frame.text = ''; frame.runs = null;
        frame.styles = styleOf(cs, el, false, g.w, g.h);
        if (!doc) {
          var origin = '?';
          try { origin = new URL(el.src, location.href).origin; } catch (e) {}
          frame.iframe = 'cross-origin'; frame.origin = origin;
        }
        frame.role = roleOf(el, tag); frame.axName = axNameOf(el, frame.role, '');
        frame.interactable = interactableOf(el, tag, frame.role, cs.cursor);
        nodes.push(frame);
        if (g.flag) flagged.push({ i: myIdx, reason: 'transform' });
        if (doc && doc.documentElement) {
          // Inner client rects are relative to the frame's content box, in
          // untransformed px: a pure translation into this frame's layout space.
          var win = doc.defaultView;
          var innerInv = new DOMMatrix().translate(
            g.x + px(cs.borderLeftWidth) + px(cs.paddingLeft) + (win ? win.scrollX : 0),
            g.y + px(cs.borderTopWidth) + px(cs.paddingTop) + (win ? win.scrollY : 0));
          visit(doc.documentElement, myIdx, innerInv, depth + 1);
        }
        return;
      }

      var beforeCs = pseudoStyle(el, '::before');
      afterCs = pseudoStyle(el, '::after');
      var beforeOn = hasPseudo(beforeCs), afterOn = hasPseudo(afterCs);
      var isSvg = tag === 'svg' && !isHtml;
      var rawRuns = [];
      var before = '', after = '';
      var asText = false;
      if (!isSvg && !LEAF[tag]) {
        before = beforeOn ? resolveContent(el, beforeCs).text : '';
        after = afterOn ? resolveContent(el, afterCs).text : '';
        asText = isInlineTextOnly(el) || ((before.trim() || after.trim()) && !hasElementKids(el));
        if (asText) {
          rawRuns = collectRuns(el, cs);
          if (before) rawRuns.unshift(Object.assign({ text: before }, runStyle(beforeCs, decorationOf(beforeCs))));
          if (after) rawRuns.push(Object.assign({ text: after }, runStyle(afterCs, decorationOf(afterCs))));
        }
      }
      var textInfo = normalizeRuns(rawRuns);
      var combined = textInfo.text;

      var role = roleOf(el, tag);
      var level = role === 'heading' ? headingLevel(tag) : null;
      var entry = { i: myIdx, parent: parentIdx, tag: tag, rect: rect };
      if (g.xf) entry.xf = g.xf;
      entry.text = combined;
      entry.runs = textInfo.runs;
      if (combined) entry.lines = lineCount(el, g.invChild, (cs.writingMode || '').indexOf('vertical') === 0);
      entry.styles = styleOf(cs, el, !!combined, g.w, g.h);
      if (isSvg) entry.image = { asset: svgAsset(el, g.w, g.h), mode: 'FILL' };
      else {
        var image = imageOf(el, tag, cs, g.w, g.h);
        if (image) entry.image = image;
      }
      entry.role = role;
      entry.axName = axNameOf(el, role, combined);
      entry.interactable = interactableOf(el, tag, role, cs.cursor);
      if (level != null) entry.level = level;
      nodes.push(entry);

      if (cs.display === 'grid' || cs.display === 'inline-grid') flagged.push({ i: myIdx, reason: 'grid' });
      if (g.flag) flagged.push({ i: myIdx, reason: 'transform' });

      if (asText || isSvg || LEAF[tag]) return;
      if (beforeOn) reservePseudo(el, '::before', myIdx, g.invChild);
    }

    // Pruned (hidden / zero-area) nodes still recurse: display:contents and
    // <slot> hoist their children, and zero-area wrappers may hold laid-out
    // descendants (position:fixed inside).
    var kids = kidsOf(el);
    for (var i = 0; i < kids.length; i++) {
      if (kids[i].nodeType === 1) visit(kids[i], myIdx, g.invChild, depth + 1);
    }
    if (!prune && hasPseudo(afterCs)) reservePseudo(el, '::after', myIdx, g.invChild);
  }

  // ----- pseudo-element measurement: the owner's real pseudo is suppressed by an
  // adopted sheet keyed on a data attribute, and a sentinel <span> carrying every
  // computed property of the pseudo (except `content`) stands in its place so it
  // can be measured like any element.

  function rootWindow(root) {
    return (root.nodeType === 9 ? root : root.ownerDocument).defaultView;
  }

  function measurePseudos(which) {
    var list = pseudoPending[which];
    if (!list.length) return;
    var attr = which === '::before' ? 'data-cap-nb' : 'data-cap-na';
    var roots = [], sheets = [];

    list.forEach(function (p) {
      var pcs = pseudoStyle(p.el, which);
      if (!pcs) return;
      var content = resolveContent(p.el, pcs);
      var span = p.el.ownerDocument.createElement('span');
      for (var i = 0; i < pcs.length; i++) {
        var name = pcs[i];
        if (name === 'content' || name.indexOf('animation') === 0 || name.indexOf('transition') === 0) continue;
        try { span.style.setProperty(name, pcs.getPropertyValue(name)); } catch (e) {}
      }
      span.textContent = content.text;
      p.span = span; p.content = content;
      var root = p.el.getRootNode();
      if (roots.indexOf(root) < 0) roots.push(root);
    });

    roots.forEach(function (root) {
      var win = rootWindow(root), rule = '[' + attr + ']' + which + '{content:none!important}';
      try {
        var sheet = new win.CSSStyleSheet();
        sheet.replaceSync(rule);
        root.adoptedStyleSheets = root.adoptedStyleSheets.concat([sheet]);
        sheets.push({ root: root, sheet: sheet });
      } catch (e) {
        var style = (root.nodeType === 9 ? root : root.ownerDocument).createElement('style');
        style.textContent = rule;
        (root.nodeType === 9 ? root.documentElement : root).appendChild(style);
        sheets.push({ root: root, style: style });
      }
    });

    list.forEach(function (p) {
      if (!p.span) return;
      p.el.setAttribute(attr, '');
      var host = p.el.shadowRoot || p.el;
      if (which === '::before') host.insertBefore(p.span, host.firstChild);
      else host.appendChild(p.span);
    });

    list.forEach(function (p) {
      if (!p.span) return;
      var scs = getComputedStyle(p.span);
      if (scs.display === 'none' || scs.visibility === 'hidden') return;
      var g = geometry(p.span, scs, p.inv, true, 'span');
      if (g.rect.w === 0 || g.rect.h === 0) return;
      var text = p.content.text.replace(/\s+/g, ' ').trim();
      var st = styleOf(scs, p.span, !!text, g.w, g.h);
      var image = null;
      if (!text) {
        var bg = bgImage(scs);
        if (bg) image = { asset: assetForUrl(bg.url, null, g.w, g.h), mode: bg.mode };
      }
      if (!text && !image && !st.bg && !st.border && !st.shadow) return;
      var n = nodes[p.idx];
      delete n.drop;
      n.rect = g.rect;
      if (g.xf) n.xf = g.xf;
      n.text = text;
      n.runs = null;
      if (text) n.lines = lineCount(p.span, g.invChild, (scs.writingMode || '').indexOf('vertical') === 0);
      n.styles = st;
      if (image) n.image = image;
      n.role = null; n.axName = null; n.interactable = false;
      if (scs.display === 'grid' || scs.display === 'inline-grid') flagged.push({ i: p.idx, reason: 'grid' });
      if (g.flag) flagged.push({ i: p.idx, reason: 'transform' });
    });

    list.forEach(function (p) {
      if (p.span) p.span.remove();
      p.el.removeAttribute(attr);
    });
    sheets.forEach(function (s) {
      if (s.sheet) s.root.adoptedStyleSheets = s.root.adoptedStyleSheets.filter(function (x) { return x !== s.sheet; });
      else s.style.remove();
    });
  }

  function compact() {
    var map = new Int32Array(nodes.length).fill(-1);
    var kept = [];
    nodes.forEach(function (n) {
      if (n.drop) return;
      map[n.i] = kept.length;
      n.i = kept.length;
      kept.push(n);
    });
    var kidCount = new Int32Array(kept.length);
    kept.forEach(function (n) {
      n.parent = n.parent < 0 ? -1 : map[n.parent];
      if (n.parent >= 0) kidCount[n.parent]++;
    });
    kept.forEach(function (n) { if (kidCount[n.i]) n.kids = kidCount[n.i]; });
    flagged = flagged.filter(function (f) { return map[f.i] >= 0; })
      .map(function (f) { return { i: map[f.i], reason: f.reason }; });
    nodes = kept;
  }

  var rootInv = new DOMMatrix().translate(window.scrollX, window.scrollY);
  visit(document.documentElement, -1, rootInv, 0);
  measurePseudos('::before');
  measurePseudos('::after');
  compact();
  await resolveAssets();

  return {
    meta: { url: location.href, title: document.title,
      viewport: { w: window.innerWidth, h: window.innerHeight }, dpr: window.devicePixelRatio,
      nodeCount: nodes.length },
    flagged: flagged,
    assets: assets,
    nodes: nodes
  };
})()
