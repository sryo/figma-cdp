// DOM → flat capture spec. Returns {nodes:[...], flagged:[...], meta:{...}}.
// Runs in the SOURCE page (agent-browser --session capture). Result returns over
// the CDP WebSocket; figma_capture.py persists it to /tmp. No Figma API here.
//
// Each node (flat DFS-preorder): see SPEC SCHEMA in figma_capture.py / SKILL.md.
(function () {
  var nodes = [];
  var flagged = [];

  function px(v) { var n = parseFloat(v); return isFinite(n) ? n : 0; }

  // rgb()/rgba() → {r,g,b in 0..1, a in 0..1} or null for transparent/none.
  function parseColor(s) {
    if (!s) return null;
    var m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    var p = m[1].split(',').map(function (x) { return parseFloat(x); });
    var a = p.length > 3 ? p[3] : 1;
    if (a === 0) return null;
    return { r: p[0] / 255, g: p[1] / 255, b: p[2] / 255, a: a };
  }

  // Strip CSS quoting from a `content` value; '' / none / normal → no glyphs.
  function pseudoText(el, which) {
    var cs;
    try { cs = getComputedStyle(el, which); } catch (e) { return ''; }
    var c = cs.content;
    if (!c || c === 'none' || c === 'normal') return '';
    var q = c.match(/^["'](.*)["']$/);
    return q ? q[1] : (c.indexOf('url(') === 0 ? '' : c);
  }

  function styleOf(cs) {
    return {
      display: cs.display,
      position: cs.position,
      flexDirection: cs.flexDirection,
      justifyContent: cs.justifyContent,
      alignItems: cs.alignItems,
      gap: px(cs.rowGap || cs.gap),
      columnGap: px(cs.columnGap || cs.gap),
      padding: [px(cs.paddingTop), px(cs.paddingRight), px(cs.paddingBottom), px(cs.paddingLeft)],
      bg: parseColor(cs.backgroundColor),
      color: parseColor(cs.color),
      fontSize: px(cs.fontSize),
      fontWeight: cs.fontWeight,
      fontFamily: cs.fontFamily,
      textAlign: cs.textAlign,
      lineHeight: cs.lineHeight === 'normal' ? null : px(cs.lineHeight),
      borderRadius: px(cs.borderTopLeftRadius),
      borderColor: parseColor(cs.borderTopColor),
      borderWidth: px(cs.borderTopWidth),
      opacity: parseFloat(cs.opacity),
      transform: cs.transform === 'none' ? null : cs.transform,
      overflow: cs.overflow
    };
  }

  // A node is "inline text only" if every child is a text node (with glyphs) or
  // an inline element that itself is inline-text-only — i.e. it merges to one run
  // set with no block boxes inside.
  function isInlineTextOnly(el) {
    if (!el.childNodes.length) return false;
    var sawText = false;
    for (var i = 0; i < el.childNodes.length; i++) {
      var c = el.childNodes[i];
      if (c.nodeType === 3) { if (c.nodeValue.trim()) sawText = true; continue; }
      if (c.nodeType !== 1) continue;
      var d;
      try { d = getComputedStyle(c).display; } catch (e) { return false; }
      if (d.indexOf('inline') !== 0) return false; // block-level child → not pure text
      if (!isInlineTextOnly(c) && c.textContent.trim()) {
        // inline element with no element children but with text is fine
        if (c.children.length) return false;
      }
      if (c.textContent.trim()) sawText = true;
    }
    return sawText;
  }

  // Collect text runs of an inline-text-only subtree, splitting where span styles
  // (color/weight/size/decoration) differ from the inherited base.
  function collectRuns(el, baseCs) {
    var runs = [];
    function walk(node, cs) {
      for (var i = 0; i < node.childNodes.length; i++) {
        var c = node.childNodes[i];
        if (c.nodeType === 3) {
          var t = c.nodeValue.replace(/\s+/g, ' ');
          if (t.trim() === '' && t === '') continue;
          runs.push({ text: t, color: parseColor(cs.color), fontSize: px(cs.fontSize),
            fontWeight: cs.fontWeight, decoration: cs.textDecorationLine || cs.textDecoration });
        } else if (c.nodeType === 1) {
          var ccs;
          try { ccs = getComputedStyle(c); } catch (e) { ccs = cs; }
          walk(c, ccs);
        }
      }
    }
    walk(el, baseCs);
    // Merge adjacent runs that share style.
    var merged = [];
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i], last = merged[merged.length - 1];
      if (last && last.color + '|' + last.fontSize + '|' + last.fontWeight + '|' + last.decoration ===
          r.color + '|' + r.fontSize + '|' + r.fontWeight + '|' + r.decoration) {
        last.text += r.text;
      } else {
        merged.push({ text: r.text, color: r.color, fontSize: r.fontSize, fontWeight: r.fontWeight, decoration: r.decoration });
      }
    }
    var full = merged.map(function (m) { return m.text; }).join('').replace(/\s+/g, ' ').trim();
    return { text: full, runs: merged.length > 1 ? merged : null };
  }

  function flagReason(st) {
    if (st.display === 'grid' || st.display === 'inline-grid') return 'grid';
    if (st.position === 'absolute' || st.position === 'fixed' || st.position === 'sticky') return 'abs';
    if (st.transform) return 'transform';
    return null;
  }

  // dx/dy: cumulative offset (for same-origin iframe recursion). depth budget guards
  // against pathological trees.
  function visit(el, parentIdx, dx, dy, depth) {
    if (depth > 60) return;
    var cs;
    try { cs = getComputedStyle(el); } catch (e) { return; }
    var hidden = cs.display === 'none' || cs.visibility === 'hidden';
    var r = el.getBoundingClientRect();
    var rect = { x: Math.round((r.left + dx) * 100) / 100, y: Math.round((r.top + dy) * 100) / 100,
      w: Math.round(r.width * 100) / 100, h: Math.round(r.height * 100) / 100 };
    var zeroArea = rect.w === 0 || rect.h === 0;
    var prune = hidden || zeroArea;

    var myIdx = -1;
    var st = styleOf(cs);
    var tag = el.tagName ? el.tagName.toLowerCase() : 'node';

    if (!prune) {
      // Cross-origin iframe → placeholder; do not attempt to reach its document.
      if (tag === 'iframe') {
        var doc = null;
        try { doc = el.contentDocument; } catch (e) { doc = null; }
        if (!doc) {
          var origin = '?';
          try { origin = new URL(el.src, location.href).origin; } catch (e) {}
          myIdx = nodes.length;
          nodes.push({ i: myIdx, parent: parentIdx, tag: 'iframe', rect: rect, text: '',
            styles: st, runs: null, name: '[capture:iframe ' + origin + ']', iframe: 'cross-origin' });
          return; // placeholder frame, no children
        }
      }

      var before = pseudoText(el, '::before');
      var after = pseudoText(el, '::after');
      var textInfo = { text: '', runs: null };
      var asText = isInlineTextOnly(el) || ((before || after) && el.children.length === 0);
      if (asText) textInfo = collectRuns(el, cs);
      var combined = (before + textInfo.text + after);
      // Keep runs and combined text consistent: fold pseudo glyphs in as their own
      // runs (element's own style), so the importer can rely on either field alone.
      if (textInfo.runs && (before || after)) {
        var pseudoRun = { color: parseColor(cs.color), fontSize: px(cs.fontSize),
          fontWeight: cs.fontWeight, decoration: cs.textDecorationLine || cs.textDecoration };
        if (before) textInfo.runs.unshift(Object.assign({ text: before }, pseudoRun));
        if (after) textInfo.runs.push(Object.assign({ text: after }, pseudoRun));
      }

      myIdx = nodes.length;
      var entry = { i: myIdx, parent: parentIdx, tag: tag, rect: rect,
        text: combined, styles: st, runs: textInfo.runs, name: null };
      nodes.push(entry);

      var fr = flagReason(st);
      if (fr) flagged.push({ i: myIdx, reason: fr });

      if (asText) return; // merged: children folded into this text node

      // Same-origin iframe: recurse into its document with a rect offset.
      if (tag === 'iframe') {
        var idoc;
        try { idoc = el.contentDocument; } catch (e) { idoc = null; }
        if (idoc && idoc.documentElement) {
          visit(idoc.documentElement, myIdx, rect.x, rect.y, depth + 1);
        }
        return;
      }
    }

    // Recurse into children even when pruned (the spike probe: a hidden/zero-area
    // node can still contain laid-out descendants, e.g. position:fixed inside).
    var nextParent = prune ? parentIdx : myIdx;
    var kids = el.children;
    for (var i = 0; i < kids.length; i++) visit(kids[i], nextParent, dx, dy, depth + 1);
  }

  visit(document.documentElement, -1, 0, 0, 0);

  return {
    nodes: nodes,
    flagged: flagged,
    meta: { url: location.href, title: document.title,
      viewport: { w: window.innerWidth, h: window.innerHeight }, nodeCount: nodes.length }
  };
})()
