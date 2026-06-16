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

  // --- Semantic layer (Phase 6, Change 1) ---
  // Cheap, in-page ARIA approximation for Figma layer naming + component matching.
  // NOT a spec-compliant accname/role computation — the native Accessibility.getFullAXTree
  // join (over CDP, keyed by backendNodeId) is the accuracy upgrade, documented in capture.md.

  // Implicit ARIA role by tag. Tags absent here resolve to null (no "generic" noise).
  var IMPLICIT_ROLE = {
    button: 'button', nav: 'navigation', header: 'banner', footer: 'contentinfo',
    main: 'main', aside: 'complementary', ul: 'list', ol: 'list', li: 'listitem',
    select: 'combobox', textarea: 'textbox', img: 'img', table: 'table',
    form: 'form', section: 'region', article: 'article', label: 'label'
  };
  // Roles that, when explicit or implicit, mark a node as a real control.
  var INTERACTIVE_ROLES = { button: 1, link: 1, textbox: 1, combobox: 1,
    checkbox: 1, radio: 1, menuitem: 1, tab: 1 };

  // Resolve role: explicit aria role attribute wins, else implicit-by-tag.
  // a[href]→link (bare <a> stays null), input→textbox unless its type is a known control.
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
    if (tag.length === 2 && tag.charAt(0) === 'h' && tag >= 'h1' && tag <= 'h6') return 'heading';
    return IMPLICIT_ROLE[tag] || null;
  }

  // Heading level 1..6 for h1..h6 (role + separate level convention), else null.
  function headingLevel(tag) {
    if (tag.length === 2 && tag.charAt(0) === 'h' && tag >= 'h1' && tag <= 'h6') return +tag.charAt(1);
    return null;
  }

  function cap80(s) {
    s = (s || '').replace(/\s+/g, ' ').trim();
    return s.length > 80 ? s.slice(0, 80) : s;
  }

  // Cheap accessible name: aria-label, else aria-labelledby joined text, else alt,
  // else title, else trimmed text for heading/button/link, else null.
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
    // Form controls: button value, then <label for=id> / wrapping <label>, then placeholder.
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

  // Conservative control check: real control tags, interactive roles, focusable
  // (tabindex>=0), or cursor:pointer.
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
            styles: st, runs: null, name: '[capture:iframe ' + origin + ']', iframe: 'cross-origin',
            role: null, axName: null, interactable: false });
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

      var role = roleOf(el, tag);
      var level = role === 'heading' ? headingLevel(tag) : null;

      myIdx = nodes.length;
      var entry = { i: myIdx, parent: parentIdx, tag: tag, rect: rect,
        text: combined, styles: st, runs: textInfo.runs, name: null,
        role: role, axName: axNameOf(el, role, combined),
        interactable: interactableOf(el, tag, role, cs.cursor) };
      if (level != null) entry.level = level;
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
