// Readies the SOURCE page for figma_walker.js; figma_capture.py runs it in the same eval, just
// before the walker. An expression: an async function of {width, height, scheme, scroll}
// returning {notes, width}.
//   width   a page narrower or wider than this (the browser window's size) loads again in a
//           same-origin frame this wide, so its media queries see the width the design is for;
//           the walker then walks the frame (window.__fxWalkWin). 0 keeps the window's width.
//   scheme  'light' makes prefers-color-scheme: light rules apply and dark ones not, whatever the
//           browser's setting; 'page' leaves them.
//   scroll  scrolls through the page and back, so scroll-revealed and lazy content is there.
(async function (o) {
  if (typeof document === 'undefined' || typeof window === 'undefined') return { notes: [], width: 0 };
  var notes = [], win = window, doc = document;
  // A background tab stretches setTimeout to seconds, so waits yield through a MessageChannel,
  // which it doesn't throttle, until the time is up.
  var ch = new MessageChannel(), queue = [];
  ch.port1.onmessage = function () { var f = queue.shift(); if (f) f(); };
  var tick = function () { return new Promise(function (r) { queue.push(r); ch.port2.postMessage(0); }); };
  var sleep = async function (ms) { var end = Date.now() + ms; while (Date.now() < end) await tick(); };

  if (o.width && Math.round(window.innerWidth) !== o.width) {
    var f = document.createElement('iframe');
    f.setAttribute('data-fx-capture', '');
    f.style.cssText = 'position:fixed;left:0;top:0;border:0;margin:0;z-index:2147483647;background:#fff;width:' + o.width + 'px;height:' + (o.height || 900) + 'px';
    var loaded = new Promise(function (r) { f.onload = r; });
    f.src = location.href;
    document.documentElement.appendChild(f);
    await Promise.race([loaded, sleep(20000)]);
    var ok = false;
    try { ok = !!f.contentDocument && f.contentDocument.readyState === 'complete' && f.contentWindow.location.href !== 'about:blank'; } catch (e) { ok = false; }
    if (ok) {
      await sleep(1500);
      win = f.contentWindow; doc = f.contentDocument;
      notes.push('laid out at ' + o.width + 'px in a frame; the window is ' + Math.round(window.innerWidth) + 'px');
    } else {
      f.remove();
      notes.push('the page would not load in a frame, so it lays out at the window\'s ' + Math.round(window.innerWidth) + 'px');
    }
  }

  if (o.scheme === 'light') {
    var n = 0;
    var fix = function (list) {
      for (var i = 0; i < list.length; i++) {
        var r = list[i];
        if (r.media && /prefers-color-scheme/.test(r.media.mediaText)) {
          var t = r.media.mediaText;
          r.media.mediaText = /prefers-color-scheme:\s*dark/.test(t) ? 'not all' : t.replace(/\(\s*prefers-color-scheme:\s*light\s*\)/g, 'all');
          n++;
        }
        if (r.cssRules) { try { fix(r.cssRules); } catch (e) {} }
      }
    };
    for (var s = 0; s < doc.styleSheets.length; s++) { try { fix(doc.styleSheets[s].cssRules); } catch (e) {} }
    Array.prototype.forEach.call(doc.querySelectorAll('source[media*="prefers-color-scheme"]'), function (el) {
      if (/dark/.test(el.getAttribute('media'))) { el.remove(); n++; }
    });
    doc.documentElement.style.colorScheme = 'light';
    if (n) { notes.push('light mode: ' + n + ' color-scheme rules set to light'); await sleep(300); }
  }

  if (o.scroll) {
    var steps = 0, y = 0;
    while (y < doc.documentElement.scrollHeight && steps < 80) {
      win.scrollTo(0, y);
      await sleep(60);
      y += Math.max(200, win.innerHeight * 0.8);
      steps++;
    }
    win.scrollTo(0, 0);
    await sleep(900);
    notes.push('scrolled through the page in ' + steps + ' steps');
    // A background tab renders no frames, so scroll-into-view callbacks may never run: content still
    // waiting to fade in (opacity 0 with an opacity transition, in the flow) is shown as it would end.
    var shown = 0;
    Array.prototype.forEach.call(doc.body ? doc.body.querySelectorAll('*') : [], function (el) {
      var cs = win.getComputedStyle(el);
      if (cs.opacity === '0' && /opacity|all/.test(cs.transitionProperty) && cs.position !== 'fixed' && cs.position !== 'absolute' && el.getAttribute('aria-hidden') !== 'true') {
        el.style.setProperty('transition', 'none', 'important');
        el.style.setProperty('opacity', '1', 'important');
        if (cs.transform !== 'none') el.style.setProperty('transform', 'none', 'important');
        shown++;
      }
    });
    if (shown) notes.push('showed ' + shown + ' elements still waiting to fade in');
    if (document.visibilityState === 'hidden') notes.push('the page tab is in the background, where the page\'s own scroll-into-view scripts never run: '
      + 'what they add is missing; walk in a room (rooms up <name>) or with the tab shown to get it');
  }

  window.__fxWalkWin = win === window ? null : win;
  return { notes: notes, width: Math.round(win.innerWidth) };
})
