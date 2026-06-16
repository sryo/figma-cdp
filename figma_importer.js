// Capture spec → Figma nodes. Runs in the DEFAULT session on the Figma tab via
// figma_run.py. Reads one batch of the spec from window.__captureSpec (set by the
// caller before each eval — see SKILL.md → Capture import loop) and carries the
// node-index → Figma-id map across batches in window.__batchState.captureIds.
//
// Component-aware: a category→componentId map at window.__captureSpec.components
// (fallback window.__batchState.captureComponents), category a normalized role/kind
// (button, input, link, card, nav, checkbox, ...). A node whose role (else tag) maps
// to a present category is built as an instance of that LOCAL component instead of a
// raw frame. Every created node is named "[cap:<i>] <axName|role|tag>" (keeping any
// existing [capture:*] flag tag) for source↔Figma traceability.
//
// Deterministic tier (conventions.md → Source→Figma primitives):
//   display:flex / simple block-flow container → Auto Layout frame
//   grid / absolute / fixed / transform / overlap → frame layoutMode NONE at rect,
//     name-tagged [capture:grid|abs|transform|overlap].
// Returns {created, flagged:[{nodeId,reason}], fontsFallenBack:[...],
//   instantiated:[{nodeId, category, componentId}]}.
(async function () {
  var spec = window.__captureSpec;
  if (!spec || !spec.nodes) return { error: 'window.__captureSpec missing or has no nodes' };

  window.__batchState = window.__batchState || {};
  var idMap = window.__batchState.captureIds = window.__batchState.captureIds || {}; // specIdx → figmaId
  var rectMap = window.__batchState.captureRects = window.__batchState.captureRects || {}; // specIdx → abs rect (cross-batch positioning)
  var report = window.__batchState.captureReport =
    window.__batchState.captureReport || { created: 0, flagged: [], fontsFallenBack: [], instantiated: [] };
  if (!report.instantiated) report.instantiated = []; // tolerate a report persisted before Change 2

  // Component map from the coordinator: { <category>: <componentId> }, category a
  // normalized role/kind (button, input, link, card, nav, checkbox, ...). Local
  // component ids — resolved with getNodeByIdAsync, then .createInstance().
  var components = (spec.components) ||
    (window.__batchState && window.__batchState.captureComponents) || {};

  var WEIGHT_STYLE = [[700, 'Bold'], [600, 'Bold'], [500, 'Medium'], [400, 'Regular'], [300, 'Regular']];
  var loadedFonts = window.__batchState.captureFonts = window.__batchState.captureFonts || {};

  function weightToStyle(w) {
    var n = parseInt(w, 10); if (!isFinite(n)) n = 400;
    for (var i = 0; i < WEIGHT_STYLE.length; i++) if (n >= WEIGHT_STYLE[i][0]) return WEIGHT_STYLE[i][1];
    return 'Regular';
  }
  async function ensureFont(style) {
    var key = 'Inter|' + style;
    if (loadedFonts[key] !== undefined) return loadedFonts[key];
    try { await figma.loadFontAsync({ family: 'Inter', style: style }); loadedFonts[key] = style; return style; }
    catch (e) {
      if (style !== 'Regular') {
        try { await figma.loadFontAsync({ family: 'Inter', style: 'Regular' });
          loadedFonts[key] = 'Regular';
          if (report.fontsFallenBack.indexOf(style) === -1) report.fontsFallenBack.push(style);
          return 'Regular';
        } catch (e2) {}
      }
      loadedFonts[key] = null; return null;
    }
  }
  function paint(c) { return c ? [{ type: 'SOLID', color: { r: c.r, g: c.g, b: c.b }, opacity: c.a }] : []; }
  function justifyToPrimary(j) {
    if (!j) return 'MIN';
    if (j.indexOf('between') !== -1) return 'SPACE_BETWEEN';
    if (j.indexOf('center') !== -1) return 'CENTER';
    if (j.indexOf('end') !== -1) return 'MAX';
    return 'MIN';
  }

  // A node is an Auto Layout candidate when it is flex, or a plain block container
  // (block display, static/relative position, no transform) — the simple block-flow
  // case. Everything else is a positioned NONE frame.
  function autoLayoutInfo(st) {
    if (st.display === 'flex' || st.display === 'inline-flex') {
      return { mode: st.flexDirection && st.flexDirection.indexOf('column') === 0 ? 'VERTICAL' : 'HORIZONTAL' };
    }
    var positioned = st.position === 'absolute' || st.position === 'fixed' || st.position === 'sticky';
    if ((st.display === 'block' || st.display === 'flow-root') && !positioned && !st.transform) {
      return { mode: 'VERTICAL' };
    }
    return null;
  }

  var flaggedIdx = {};
  (spec.flagged || []).forEach(function (f) { flaggedIdx[f.i] = f.reason; });

  function isText(n) { return (n.text && n.text.trim()) && (!n.tag || n.tag !== 'iframe'); }

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

  // [cap:<i>] <readable> [<existing flag tag>] — bake the source index into every
  // created node so source↔Figma stays traceable. Readable part: axName, else role,
  // else tag. `extra` carries an existing flag tag like "[capture:grid] div".
  function nameFor(n, extra) {
    var readable = (n.axName && n.axName.trim()) || n.role || n.tag || 'node';
    var label = '[cap:' + n.i + '] ' + readable;
    return extra ? label + ' ' + extra : label;
  }

  for (var k = 0; k < spec.nodes.length; k++) {
    var n = spec.nodes[k];
    var st = n.styles || {};
    var node;

    // Component-aware path: a clear category match against the passed-in map →
    // instantiate the local component instead of building a raw frame. Conservative —
    // only on an exact category hit; any failure falls through to the frame logic.
    var category = (n.iframe === 'cross-origin') ? null : categoryOf(n);
    var componentId = category ? components[category] : null;
    var instance = null;
    if (componentId) {
      try {
        var comp = await figma.getNodeByIdAsync(componentId);
        if (comp && typeof comp.createInstance === 'function') {
          instance = comp.createInstance();
          instance.resize(Math.max(n.rect.w, 1), Math.max(n.rect.h, 1));
          // Set the instance's primary text when the node has text and the instance
          // exposes a single text layer.
          if (n.text && n.text.trim()) {
            var txt = instance.findOne(function (c) { return c.type === 'TEXT'; });
            if (txt) {
              try {
                var instStyle = await ensureFont(weightToStyle(st.fontWeight)) || 'Regular';
                if (txt.fontName && txt.fontName !== figma.mixed) {
                  await figma.loadFontAsync(txt.fontName);
                } else {
                  txt.fontName = { family: 'Inter', style: instStyle };
                }
                txt.characters = n.text;
              } catch (e) {}
            }
          }
          instance.name = nameFor(n);
          report.instantiated.push({ nodeId: instance.id, category: category, componentId: componentId });
        }
      } catch (e) { instance = null; }
    }

    if (instance) {
      node = instance;
    } else if (n.iframe === 'cross-origin') {
      node = figma.createFrame();
      node.name = nameFor(n, n.name || '[capture:iframe]');
      node.layoutMode = 'NONE';
      node.resize(Math.max(n.rect.w, 1), Math.max(n.rect.h, 1));
      node.fills = paint(st.bg);
    } else if (isText(n)) {
      node = figma.createText();
      var baseStyle = await ensureFont(weightToStyle(st.fontWeight)) || 'Regular';
      node.fontName = { family: 'Inter', style: baseStyle };
      node.fontSize = st.fontSize || 16;
      node.characters = n.text;
      if (n.runs && n.runs.length > 1) {
        var pos = 0;
        for (var ri = 0; ri < n.runs.length; ri++) {
          var run = n.runs[ri]; var len = (run.text || '').length;
          if (len === 0) continue;
          var rs = await ensureFont(weightToStyle(run.fontWeight)) || 'Regular';
          try { node.setRangeFontName(pos, pos + len, { family: 'Inter', style: rs }); } catch (e) {}
          if (run.fontSize) try { node.setRangeFontSize(pos, pos + len, run.fontSize); } catch (e) {}
          if (run.color) try { node.setRangeFills(pos, pos + len, paint(run.color)); } catch (e) {}
          pos += len;
        }
      } else if (st.color) {
        node.fills = paint(st.color);
      }
      node.name = nameFor(n);
    } else {
      node = figma.createFrame();
      var al = autoLayoutInfo(st);
      var reason = flaggedIdx[n.i];
      if (al && !reason) {
        node.layoutMode = al.mode;
        node.itemSpacing = st.gap || 0;
        if (st.padding) {
          node.paddingTop = st.padding[0]; node.paddingRight = st.padding[1];
          node.paddingBottom = st.padding[2]; node.paddingLeft = st.padding[3];
        }
        node.primaryAxisAlignItems = justifyToPrimary(st.justifyContent);
        node.primaryAxisSizingMode = 'FIXED'; node.counterAxisSizingMode = 'FIXED';
        node.resize(Math.max(n.rect.w, 1), Math.max(n.rect.h, 1));
        node.name = nameFor(n);
      } else {
        node.layoutMode = 'NONE';
        node.resize(Math.max(n.rect.w, 1), Math.max(n.rect.h, 1));
        node.name = nameFor(n, '[capture:' + (reason || 'block') + '] ' + (n.tag || 'frame'));
        report.flagged.push({ nodeId: node.id, reason: reason || 'none' });
      }
      node.fills = paint(st.bg);
      if (st.borderRadius) node.cornerRadius = st.borderRadius;
      if (st.borderWidth && st.borderColor) { node.strokes = paint(st.borderColor); node.strokeWeight = st.borderWidth; }
      if (st.opacity < 1) node.opacity = st.opacity;
      node.clipsContent = false;
    }

    idMap[n.i] = node.id;
    rectMap[n.i] = n.rect;
    report.created++;

    var parentFigmaId = n.parent >= 0 ? idMap[n.parent] : null;
    var p = parentFigmaId ? await figma.getNodeByIdAsync(parentFigmaId) : null;
    // An instance subtree is structurally frozen — appendChild into it throws. When the
    // captured parent became a component instance, leave this child at its absolute rect
    // rather than forcing it inside the frozen instance.
    var canAppend = p && 'appendChild' in p && p.type !== 'INSTANCE';
    if (canAppend) {
      p.appendChild(node);
      // Outside Auto Layout, place by captured rect relative to parent's abs rect.
      if (p.layoutMode === 'NONE') {
        var pr = rectMap[n.parent] || { x: 0, y: 0 };
        node.x = n.rect.x - pr.x; node.y = n.rect.y - pr.y;
      }
    } else {
      node.x = n.rect.x; node.y = n.rect.y;
    }
  }

  return { created: report.created, flagged: report.flagged, fontsFallenBack: report.fontsFallenBack,
    instantiated: report.instantiated, batchDone: spec.nodes.length };
})()
