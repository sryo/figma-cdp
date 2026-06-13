// Capture spec → Figma nodes. Runs in the DEFAULT session on the Figma tab via
// figma_run.py. Reads one batch of the spec from window.__captureSpec (set by the
// caller before each eval — see SKILL.md → Capture import loop) and carries the
// node-index → Figma-id map across batches in window.__batchState.captureIds.
//
// Deterministic tier (conventions.md → Source→Figma primitives):
//   display:flex / simple block-flow container → Auto Layout frame
//   grid / absolute / fixed / transform / overlap → frame layoutMode NONE at rect,
//     name-tagged [capture:grid|abs|transform|overlap].
// Returns {created, flagged:[{nodeId,reason}], fontsFallenBack:[...]}.
(async function () {
  var spec = window.__captureSpec;
  if (!spec || !spec.nodes) return { error: 'window.__captureSpec missing or has no nodes' };

  window.__batchState = window.__batchState || {};
  var idMap = window.__batchState.captureIds = window.__batchState.captureIds || {}; // specIdx → figmaId
  var rectMap = window.__batchState.captureRects = window.__batchState.captureRects || {}; // specIdx → abs rect (cross-batch positioning)
  var report = window.__batchState.captureReport =
    window.__batchState.captureReport || { created: 0, flagged: [], fontsFallenBack: [] };

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

  for (var k = 0; k < spec.nodes.length; k++) {
    var n = spec.nodes[k];
    var st = n.styles || {};
    var node;

    if (n.iframe === 'cross-origin') {
      node = figma.createFrame();
      node.name = n.name || '[capture:iframe]';
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
        node.name = n.tag || 'frame';
      } else {
        node.layoutMode = 'NONE';
        node.resize(Math.max(n.rect.w, 1), Math.max(n.rect.h, 1));
        node.name = '[capture:' + (reason || 'block') + '] ' + (n.tag || 'frame');
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
    if (parentFigmaId) {
      var p = await figma.getNodeByIdAsync(parentFigmaId);
      if (p && 'appendChild' in p) {
        p.appendChild(node);
        // Outside Auto Layout, place by captured rect relative to parent's abs rect.
        if (p.layoutMode === 'NONE') {
          var pr = rectMap[n.parent] || { x: 0, y: 0 };
          node.x = n.rect.x - pr.x; node.y = n.rect.y - pr.y;
        }
      }
    } else {
      node.x = n.rect.x; node.y = n.rect.y;
    }
  }

  return { created: report.created, flagged: report.flagged, fontsFallenBack: report.fontsFallenBack,
    batchDone: spec.nodes.length };
})()
