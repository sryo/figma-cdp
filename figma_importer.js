// Capture spec → Figma nodes. Runs in the DEFAULT session on the Figma tab, one eval
// per node chunk, driven by `figma_capture.py import` (references/capture.md → Import
// loop). Reads window.__captureSpec {nodes, flagged, components, meta}; assets arrive
// ahead of the chunks in window.__batchState.captureAssets[key]. Cross-batch state in
// window.__batchState: captureIds (i → Figma id), captureRects (i → layout-space rect),
// captureLayout (i → {mode, alignItems, primaryGap}), captureFonts, captureReport.
//
// Component-aware: a category→componentId map at window.__captureSpec.components,
// category a normalized role/kind
// (button, input, link, card, nav, checkbox, ...). A node whose role (else tag) maps
// to a present category is built as an instance of that LOCAL component instead of a
// raw frame. Text whose styles carry box paint (bg, border, image, padding, radius,
// shadow) is wrapped in a HORIZONTAL frame that takes the node's identity. Every
// created node is named "[cap:<i>] <axName|role|tag>" (plus a "[capture:<reason>]"
// tag on flagged nodes) for source↔Figma traceability.
//
// Returns {created, flagged:[{nodeId,reason}], fontsFallenBack:[string],
//   instantiated:[{nodeId, category, componentId}], warnings:[string], batchDone}.
//   reason ∈ grid | block | transform | image.
(async function () {
  var spec = window.__captureSpec;
  if (!spec || !spec.nodes) return { error: 'window.__captureSpec missing or has no nodes' };

  var bs = window.__batchState = window.__batchState || {};
  var idMap = bs.captureIds = bs.captureIds || {};
  var rectMap = bs.captureRects = bs.captureRects || {};
  var layoutMap = bs.captureLayout = bs.captureLayout || {};
  var assets = bs.captureAssets = bs.captureAssets || {};
  var fontCache = bs.captureFonts = bs.captureFonts || {};
  var report = bs.captureReport = bs.captureReport ||
    { created: 0, flagged: [], fontsFallenBack: [], instantiated: [], warnings: [] };
  var components = spec.components || {};
  var meta = spec.meta || {};
  var flaggedIdx = {};
  (spec.flagged || []).forEach(function (f) { flaggedIdx[f.i] = f.reason; });

  function warn(n, what, e) {
    report.warnings.push('[cap:' + n.i + '] ' + what + ': ' + (e && e.message ? e.message : String(e)));
  }
  function rgba(c) { return { r: c.r, g: c.g, b: c.b, a: c.a === undefined ? 1 : c.a }; }
  function paint(c) {
    return c ? [{ type: 'SOLID', color: { r: c.r, g: c.g, b: c.b }, opacity: c.a === undefined ? 1 : c.a }] : [];
  }
  function size(v) { return Math.max(v || 0, 1); }

  // ---- fonts ----------------------------------------------------------------

  var WEIGHT_STYLE = { 100: 'Thin', 200: 'ExtraLight', 300: 'Light', 400: 'Regular', 500: 'Medium',
    600: 'SemiBold', 700: 'Bold', 800: 'ExtraBold', 900: 'Black' };
  var GENERIC_FAMILY = { 'sans-serif': 1, serif: 1, monospace: 1, 'system-ui': 1, '-apple-system': 1,
    cursive: 1, fantasy: 1, emoji: 1, math: 1 };

  function styleFor(weight, italic) {
    var w = parseInt(weight, 10); if (!isFinite(w)) w = 400;
    w = Math.min(900, Math.max(100, Math.round(w / 100) * 100));
    var base = WEIGHT_STYLE[w];
    if (!italic) return base;
    return base === 'Regular' ? 'Italic' : base + ' Italic';
  }
  function familyFor(f) {
    var fam = (f || '').trim();
    var lower = fam.toLowerCase();
    if (!fam || GENERIC_FAMILY[lower] || lower.indexOf('ui-') === 0) return 'Inter';
    return fam;
  }
  // Ladder: exact → same family Regular → Inter same style → Inter Regular. The first
  // rung that loads is cached per requested (family, style); any rung past the first
  // is a substitution, reported once.
  async function resolveFont(family, weight, italic) {
    var fam = familyFor(family), style = styleFor(weight, italic);
    var key = fam + '|' + style;
    if (Object.prototype.hasOwnProperty.call(fontCache, key)) return fontCache[key];
    var ladder = [{ family: fam, style: style }, { family: fam, style: 'Regular' },
      { family: 'Inter', style: style }, { family: 'Inter', style: 'Regular' }];
    var tried = {};
    for (var i = 0; i < ladder.length; i++) {
      var f = ladder[i], fk = f.family + '|' + f.style;
      if (tried[fk]) continue;
      tried[fk] = true;
      try { await figma.loadFontAsync(f); } catch (e) { continue; }
      fontCache[key] = f;
      if (fk !== key) report.fontsFallenBack.push(fam + '/' + style + ' → ' + f.family + '/' + f.style);
      return f;
    }
    fontCache[key] = null;
    return null;
  }

  // ---- text -----------------------------------------------------------------

  var DECORATION = { underline: 'UNDERLINE', 'line-through': 'STRIKETHROUGH' };
  var TEXT_CASE = { uppercase: 'UPPER', lowercase: 'LOWER', capitalize: 'TITLE' };
  var TEXT_ALIGN = { left: 'LEFT', start: 'LEFT', center: 'CENTER', right: 'RIGHT', end: 'RIGHT', justify: 'JUSTIFIED' };

  function isText(n) { return !!(n.text && n.text.trim()) && n.tag !== 'iframe'; }

  async function applyRuns(node, n, st) {
    var pos = 0, total = node.characters.length;
    for (var i = 0; i < n.runs.length; i++) {
      var run = n.runs[i], len = (run.text || '').length;
      if (!len) continue;
      var end = Math.min(pos + len, total);
      if (end <= pos) break;
      var font = await resolveFont(run.fontFamily || st.fontFamily, run.fontWeight || st.fontWeight,
        (run.fontStyle || st.fontStyle) === 'italic');
      try {
        if (font) node.setRangeFontName(pos, end, font);
        if (run.fontSize) node.setRangeFontSize(pos, end, run.fontSize);
        if (run.color) node.setRangeFills(pos, end, paint(run.color));
        node.setRangeTextDecoration(pos, end, DECORATION[run.textDecoration] || 'NONE');
      } catch (e) { warn(n, 'run ' + i, e); }
      pos = end;
    }
  }

  async function buildText(n, st) {
    var node = figma.createText();
    var font = await resolveFont(st.fontFamily, st.fontWeight, st.fontStyle === 'italic');
    if (!font) { warn(n, 'font', 'nothing loadable for ' + familyFor(st.fontFamily)); return node; }
    node.fontName = font;
    node.characters = n.text;
    node.fontSize = st.fontSize || 16;
    if (st.lineHeight) node.lineHeight = { unit: 'PIXELS', value: st.lineHeight };
    if (st.letterSpacing) node.letterSpacing = { unit: 'PIXELS', value: st.letterSpacing };
    if (TEXT_ALIGN[st.textAlign]) node.textAlignHorizontal = TEXT_ALIGN[st.textAlign];
    if (DECORATION[st.textDecoration]) node.textDecoration = DECORATION[st.textDecoration];
    if (TEXT_CASE[st.textTransform]) node.textCase = TEXT_CASE[st.textTransform];
    if (st.color) node.fills = paint(st.color);
    if (n.runs && n.runs.length > 1) await applyRuns(node, n, st);
    return node;
  }

  // ---- frames ---------------------------------------------------------------

  function layoutFor(n, st) {
    var d = st.display || 'block';
    if (d === 'flex' || d === 'inline-flex') {
      return { mode: (st.flexDirection || 'row').indexOf('column') === 0 ? 'VERTICAL' : 'HORIZONTAL' };
    }
    if (d === 'block' || d === 'flow-root' || d === 'inline-block' || d === 'list-item') return { mode: 'VERTICAL' };
    var grid = d === 'grid' || d === 'inline-grid';
    return { mode: 'NONE', reason: grid ? 'grid' : (n.kids ? 'block' : null) };
  }
  function primaryAlign(j) {
    if (!j) return 'MIN';
    if (j.indexOf('between') !== -1 || j.indexOf('around') !== -1 || j.indexOf('evenly') !== -1) return 'SPACE_BETWEEN';
    if (j.indexOf('center') !== -1) return 'CENTER';
    if (j.indexOf('end') !== -1) return 'MAX';
    return 'MIN';
  }
  function counterAlign(a, mode) {
    if (a === 'center') return 'CENTER';
    if (a === 'flex-end' || a === 'end') return 'MAX';
    if (a === 'baseline' && mode === 'HORIZONTAL') return 'BASELINE';
    return 'MIN';
  }

  // Computed `overflow` is a shorthand: one token, or two when the axes differ (CSS
  // coerces a lone `visible` to `auto`), so every token is non-visible or none is.
  var CLIPPING = { hidden: 1, clip: 1, auto: 1, scroll: 1 };
  function clips(st) {
    var tokens = (st.overflow || '').split(/\s+/).filter(Boolean);
    return tokens.length > 0 && tokens.every(function (t) { return !!CLIPPING[t]; });
  }

  function applyLayout(node, st, mode, w, h) {
    node.layoutMode = mode;
    if (mode !== 'NONE') { node.primaryAxisSizingMode = 'FIXED'; node.counterAxisSizingMode = 'FIXED'; }
    node.resize(w, h);
    var primaryGap = 0;
    if (mode !== 'NONE') {
      var horizontal = mode === 'HORIZONTAL';
      primaryGap = (horizontal ? st.columnGap : st.gap) || 0;
      node.itemSpacing = primaryGap;
      if (st.padding) {
        node.paddingTop = st.padding[0]; node.paddingRight = st.padding[1];
        node.paddingBottom = st.padding[2]; node.paddingLeft = st.padding[3];
      }
      node.primaryAxisAlignItems = primaryAlign(st.justifyContent);
      node.counterAxisAlignItems = counterAlign(st.alignItems, mode);
      if (st.flexWrap === 'wrap' || st.flexWrap === 'wrap-reverse') {
        node.layoutWrap = 'WRAP';
        node.counterAxisSpacing = (horizontal ? st.gap : st.columnGap) || 0;
      }
    }
    node.clipsContent = clips(st);
    return primaryGap;
  }

  // Returns {paint} or {error} for the node's image asset; the decoded hash is cached on
  // the asset so nodes sharing a URL upload once.
  function imageFill(n) {
    var a = assets[n.image.asset];
    if (!a) return { error: 'missing' };
    if (a.error) return { error: a.error };
    if (a.kind !== 'image' || !a.b64) return { error: 'missing' };
    try {
      if (!a.hash) a.hash = figma.createImage(figma.base64Decode(a.b64)).hash;
      return { paint: { type: 'IMAGE', imageHash: a.hash, scaleMode: n.image.mode || 'FILL' } };
    } catch (e) { warn(n, 'createImage', e); return { error: 'decode' }; }
  }

  // A parsable svg asset as a FrameNode scaled to the captured box; null when the
  // node's image is not a vector asset. Throws when Figma rejects the markup.
  function svgNodeFor(n, w, h) {
    var a = n.image && assets[n.image.asset];
    if (!a || a.kind !== 'svg' || a.error || !a.svg) return null;
    var node = figma.createNodeFromSvg(a.svg);
    if (node.width > 0 && Math.abs(node.width - w) > 0.5) node.rescale(w / node.width);
    node.resize(w, h);
    return node;
  }

  function fillsFor(n, st, skipImage) {
    var fills = paint(st.bg), error = null;
    if (n.image && !skipImage) {
      var img = imageFill(n);
      if (img.paint) fills.push(img.paint); else error = img.error;
    }
    return { fills: fills, error: error };
  }
  function hasBoxPaint(n, st) {
    return !!(st.bg || st.border || n.image || st.radius || st.radii || (st.shadow && st.shadow.length) ||
      (st.padding && st.padding.some(function (v) { return v > 0; })));
  }

  function effectsFor(st) {
    var fx = [];
    (st.shadow || []).forEach(function (s) {
      fx.push({ type: s.inset ? 'INNER_SHADOW' : 'DROP_SHADOW', color: rgba(s.color),
        offset: { x: s.x, y: s.y }, radius: s.blur || 0, spread: s.spread || 0, visible: true, blendMode: 'NORMAL' });
    });
    if (st.blur) fx.push({ type: 'LAYER_BLUR', radius: st.blur, visible: true });
    if (st.bgBlur) fx.push({ type: 'BACKGROUND_BLUR', radius: st.bgBlur, visible: true });
    return fx;
  }

  function applyBox(node, n, st) {
    if (st.radii) {
      node.topLeftRadius = st.radii[0]; node.topRightRadius = st.radii[1];
      node.bottomRightRadius = st.radii[2]; node.bottomLeftRadius = st.radii[3];
    } else if (st.radius) {
      node.cornerRadius = st.radius;
    }
    if (st.border) {
      node.strokes = paint(st.border.color);
      node.strokeAlign = 'INSIDE';
      var w = st.border.w;
      if (typeof w === 'number') node.strokeWeight = w;
      else {
        node.strokeTopWeight = w[0]; node.strokeRightWeight = w[1];
        node.strokeBottomWeight = w[2]; node.strokeLeftWeight = w[3];
      }
    }
    applyBlend(node, n, st);
  }
  function applyBlend(node, n, st) {
    var fx = effectsFor(st);
    if (fx.length) try { node.effects = fx; } catch (e) { warn(n, 'effects', e); }
    if (st.opacity !== undefined && st.opacity < 1) node.opacity = st.opacity;
  }

  // ---- naming / components ----------------------------------------------------

  // Normalize a node's role (preferred) else tag to a component-map category key.
  // Conservative: only emit a category we actually understand, so a stray role can
  // never silently divert a node to the wrong component.
  var ROLE_CATEGORY = {
    button: 'button', link: 'link', textbox: 'input', combobox: 'input',
    checkbox: 'checkbox', radio: 'radio', navigation: 'nav', tab: 'tab',
    menuitem: 'menuitem', list: 'list', listitem: 'listitem', img: 'img',
    heading: 'heading', banner: 'banner', contentinfo: 'contentinfo', region: 'card'
  };
  var TAG_CATEGORY = {
    button: 'button', a: 'link', input: 'input', textarea: 'input',
    select: 'input', nav: 'nav', img: 'img'
  };
  function categoryOf(n) {
    if (n.role && ROLE_CATEGORY[n.role]) return ROLE_CATEGORY[n.role];
    if (n.tag && TAG_CATEGORY[n.tag]) return TAG_CATEGORY[n.tag];
    return null;
  }

  // [cap:<i>] <readable> [<flag tag>] — readable is axName, else role, else tag; the
  // root takes the page title. `extra` carries a flag tag like "[capture:grid] div".
  function nameFor(n, extra) {
    var readable = (n.i === 0 && meta.title && meta.title.trim()) ||
      (n.axName && n.axName.trim()) || n.role || n.tag || 'node';
    var label = '[cap:' + n.i + '] ' + readable;
    return extra ? label + ' ' + extra : label;
  }

  async function instantiate(n, st, category, componentId) {
    var comp = await figma.getNodeByIdAsync(componentId);
    if (!comp || typeof comp.createInstance !== 'function') return null;
    var instance = comp.createInstance();
    instance.resize(size(n.rect.w), size(n.rect.h));
    if (n.text && n.text.trim()) {
      var txt = instance.findOne(function (c) { return c.type === 'TEXT'; });
      if (txt) {
        try {
          var names = txt.fontName === figma.mixed
            ? txt.getRangeAllFontNames(0, txt.characters.length) : [txt.fontName];
          for (var j = 0; j < names.length; j++) await figma.loadFontAsync(names[j]);
          txt.characters = n.text;
        } catch (e) { warn(n, 'instance text', e); }
      }
    }
    instance.name = nameFor(n);
    report.instantiated.push({ nodeId: instance.id, category: category, componentId: componentId });
    return instance;
  }

  // ---- placement --------------------------------------------------------------

  // CSS matrix(a,b,c,d,e,f) maps x' = a·x + c·y + e, y' = b·x + d·y + f; Figma's
  // Transform is row-major [[a,b,tx],[c,d,ty]] with x' = a·x + b·y + tx, so the CSS
  // b/c swap rows.
  function setTransform(node, xf, x, y) {
    if (xf) node.relativeTransform = [[xf[0], xf[2], x + xf[4]], [xf[1], xf[3], y + xf[5]]];
    else { node.x = x; node.y = y; }
  }
  function isPureRotation(xf) {
    return Math.abs(xf[0] - xf[3]) < 1e-3 && Math.abs(xf[1] + xf[2]) < 1e-3 &&
      Math.abs(xf[0] * xf[0] + xf[1] * xf[1] - 1) < 1e-3;
  }
  // CSS rotates clockwise (y-down); Figma's `rotation` is counter-clockwise degrees.
  function rotationOf(xf) { return -Math.atan2(xf[1], xf[0]) * 180 / Math.PI; }

  var MIN_MAX = [['minW', 'minWidth'], ['maxW', 'maxWidth'], ['minH', 'minHeight'], ['maxH', 'maxHeight']];

  // ---- main loop --------------------------------------------------------------

  for (var k = 0; k < spec.nodes.length; k++) {
    var n = spec.nodes[k];
    var st = n.styles || {};

    var parentFigmaId = n.parent >= 0 ? idMap[n.parent] : null;
    var p = parentFigmaId ? await figma.getNodeByIdAsync(parentFigmaId) : null;
    // An instance subtree is structurally frozen — appendChild into it throws. Children
    // of an instantiated node stay at their absolute rect instead.
    var canAppend = !!(p && 'appendChild' in p && p.type !== 'INSTANCE');
    var pl = (canAppend && layoutMap[n.parent]) || { mode: 'NONE' };
    var pr = (canAppend && rectMap[n.parent]) || { x: 0, y: 0 };
    var autoParent = canAppend && pl.mode !== 'NONE';
    var positioned = st.position === 'absolute' || st.position === 'fixed';
    var inFlow = autoParent && !positioned;
    var pureRotation = n.xf ? isPureRotation(n.xf) : false;

    var grow = false, stretch = false;
    if (inFlow) {
      var sz = st.sz || ['auto', 'auto'];
      var pi = pl.mode === 'HORIZONTAL' ? 0 : 1, ci = 1 - pi;
      grow = st.flexGrow > 0 || sz[pi] === 'pct';
      var selfStretches = ['auto', 'normal', 'stretch'].indexOf(st.alignSelf || 'auto') !== -1;
      var parentStretches = ['normal', 'stretch'].indexOf(pl.alignItems || 'normal') !== -1;
      var inlineLevel = (st.display || '').indexOf('inline') === 0;
      stretch = (sz[ci] === 'auto' || sz[ci] === 'pct') && selfStretches && parentStretches && !inlineLevel;
    }

    var node = null, kind = null;
    var layoutReason = null, imageReason = null, imageDetail = null;
    var layout = { mode: 'NONE' };
    var primaryGap = 0;

    // 1. component instance
    var category = (n.iframe === 'cross-origin') ? null : categoryOf(n);
    var componentId = category ? components[category] : null;
    if (componentId) {
      try { node = await instantiate(n, st, category, componentId); }
      catch (e) { warn(n, 'instantiate ' + category, e); node = null; }
      if (node) kind = 'instance';
    }

    // 2. cross-origin iframe placeholder
    if (!node && n.iframe === 'cross-origin') {
      node = figma.createFrame();
      kind = 'placeholder';
      applyLayout(node, st, 'NONE', size(n.rect.w), size(n.rect.h));
      node.fills = paint(st.bg);
      node.name = nameFor(n, n.origin ? '[capture:iframe ' + n.origin + ']' : '[capture:iframe]');
    }

    // 3. text — a TextNode's fills are its glyph color, so box paint goes on a
    // HORIZONTAL wrapper frame that owns the node's identity; the text sits inside,
    // over an svg background mounted as an absolute child when the asset is vector.
    if (!node && isText(n)) {
      var text = await buildText(n, st);
      if (hasBoxPaint(n, st)) {
        node = figma.createFrame();
        kind = 'textbox';
        layout = { mode: 'HORIZONTAL' };
        primaryGap = applyLayout(node, st, 'HORIZONTAL', size(n.rect.w), size(n.rect.h));
        node.primaryAxisAlignItems = st.textAlign === 'center' ? 'CENTER' : 'MIN';
        node.counterAxisAlignItems = 'CENTER';
        var svgBg = null;
        try { svgBg = svgNodeFor(n, size(n.rect.w), size(n.rect.h)); }
        catch (e) { warn(n, 'createNodeFromSvg', e); imageReason = 'image'; imageDetail = 'decode'; }
        var boxFills = fillsFor(n, st, !!svgBg || !!imageReason);
        node.fills = boxFills.fills;
        if (boxFills.error) { imageReason = 'image'; imageDetail = boxFills.error; }
        applyBox(node, n, st);
        if (svgBg) {
          node.appendChild(svgBg);
          svgBg.layoutPositioning = 'ABSOLUTE';
          svgBg.x = 0; svgBg.y = 0;
          svgBg.name = '[cap:' + n.i + '] svg';
        }
        node.appendChild(text);
        text.name = '[cap:' + n.i + '] text';
        if ((n.lines || 1) > 1) {
          var pad = st.padding || [0, 0, 0, 0];
          text.resize(size(n.rect.w - pad[1] - pad[3]), size(n.rect.h - pad[0] - pad[2]));
          text.textAutoResize = 'HEIGHT';
          try { text.layoutAlign = 'STRETCH'; } catch (e) { warn(n, 'text layoutAlign', e); }
        } else {
          text.textAutoResize = 'WIDTH_AND_HEIGHT';
        }
      } else {
        node = text;
        kind = 'text';
        applyBlend(node, n, st);
      }
    }

    // 4. inline svg / svg asset
    if (!node && n.image) {
      try {
        node = svgNodeFor(n, size(n.rect.w), size(n.rect.h));
        if (node) {
          kind = 'svg';
          if (st.bg) node.fills = paint(st.bg);
          applyBox(node, n, st);
          node.clipsContent = clips(st);
        }
      } catch (e) {
        warn(n, 'createNodeFromSvg', e);
        node = null; imageReason = 'image'; imageDetail = 'decode';
      }
    }

    // 5. frame
    if (!node) {
      node = figma.createFrame();
      kind = 'frame';
      layout = layoutFor(n, st);
      layoutReason = layout.reason || null;
      primaryGap = applyLayout(node, st, layout.mode, size(n.rect.w), size(n.rect.h));
      var frameFills = fillsFor(n, st, !!imageReason);
      node.fills = frameFills.fills;
      if (frameFills.error) { imageReason = 'image'; imageDetail = frameFills.error; }
      applyBox(node, n, st);
    }

    // One reason per node: image error, then layout demotion, then the walker's own
    // flag, then an in-flow transform Auto Layout can't express.
    var xfReason = (inFlow && n.xf && !pureRotation) ? 'transform' : null;
    var reason = imageReason || layoutReason || flaggedIdx[n.i] || xfReason || null;
    if (kind !== 'instance' && kind !== 'placeholder') {
      node.name = reason
        ? nameFor(n, '[capture:' + reason + (imageDetail ? ' ' + imageDetail : '') + '] ' + (n.tag || kind))
        : nameFor(n);
    }
    if (reason) report.flagged.push({ nodeId: node.id, reason: reason });

    idMap[n.i] = node.id;
    rectMap[n.i] = n.rect;
    layoutMap[n.i] = layout.mode !== 'NONE'
      ? { mode: layout.mode, alignItems: kind === 'textbox' ? 'center' : (st.alignItems || 'normal'), primaryGap: primaryGap }
      : { mode: 'NONE' };
    report.created++;

    if (canAppend) {
      p.appendChild(node);
      if (!node.parent || node.parent.id !== p.id) warn(n, 'appendChild', 'reparent failed');
    }

    if (kind === 'text') {
      if ((n.lines || 1) > 1 || stretch) {
        node.resize(size(n.rect.w), size(n.rect.h));
        node.textAutoResize = 'HEIGHT';
      } else {
        node.textAutoResize = 'WIDTH_AND_HEIGHT';
      }
    }

    var rx = canAppend ? n.rect.x - pr.x : n.rect.x;
    var ry = canAppend ? n.rect.y - pr.y : n.rect.y;
    if (inFlow) {
      try {
        if (grow) node.layoutGrow = 1;
        if (stretch) node.layoutAlign = 'STRETCH';
      } catch (e) { warn(n, 'layoutAlign', e); }
      if (n.xf && pureRotation) {
        var deg = rotationOf(n.xf);
        if (Math.abs(deg) > 1e-6) try { node.rotation = deg; } catch (e) { warn(n, 'rotation', e); }
      }
    } else {
      if (autoParent) try { node.layoutPositioning = 'ABSOLUTE'; } catch (e) { warn(n, 'layoutPositioning', e); }
      try { setTransform(node, n.xf, rx, ry); } catch (e) { warn(n, 'transform', e); }
    }

    if (autoParent || layout.mode !== 'NONE') {
      for (var m = 0; m < MIN_MAX.length; m++) {
        var v = st[MIN_MAX[m][0]];
        if (v !== undefined) try { node[MIN_MAX[m][1]] = v; } catch (e) { warn(n, MIN_MAX[m][1], e); }
      }
    }
  }

  return { created: report.created, flagged: report.flagged, fontsFallenBack: report.fontsFallenBack,
    instantiated: report.instantiated, warnings: report.warnings, batchDone: spec.nodes.length };
})()
