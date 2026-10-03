// harbor-pages/notes.html: each element the CSS lays out, found by its strings, checked for the
// Figma property that carries the same intent (source.py ROLES):
//   found            share of the layout elements located whole (90% of their strings inside)
//   sizingMatch      FILL/HUG/FIXED per axis on container, toolbar, columns, main, sidebar, tag
//                    row, tags, FAB and the toolbar buttons
//   maxWidth         the container's maxWidth is 1120 (0.5: some other max width)
//   wrap             the tag row wraps
//   paragraphResize  share of paragraph checks passing: FILL width, textAutoResize HEIGHT
//   spaceBetween     the toolbar spreads its groups with SPACE_BETWEEN
//   spacerFrames     empty, paintless frames on the screen standing in for spacing
//   fabPinned        the FAB is out of flow (absolute, or in a frame without auto layout)
//                    with MAX/MAX constraints
//   sidebarWidth     the sidebar is 280 wide
// plus copy, inventedCopy and quality().
var pages = evalPages();
var page = await targetPage();
var N = EVAL.expect.screens.notes, R = EVAL.expect.roles;
var read = await readScreens(page, [N], EVAL.expect);
var screen = read.screens[0].region;
function isAL(n) { return !!(n && n.layoutMode && n.layoutMode !== 'NONE'); }
function whole(r) {
  var n = r.inst || r.region;
  return n && countIn(read.sc.held(n), r.u.texts) >= 0.9 * r.u.texts.length ? n : null;
}
var els = read.recs.filter(function (r) { return R[r.u.c] || r.u.c === 'Button'; });
var byRole = {};
els.forEach(function (r) { (byRole[r.u.c] = byRole[r.u.c] || []).push({ rec: r, node: whole(r) }); });
function one(c) { return (byRole[c] || [])[0] || { node: null }; }

var ok = 0, checks = 0;
els.forEach(function (r) {
  var want = R[r.u.c] || EVAL.expect.sizing[r.u.c], n = whole(r);
  if (want.h) { checks++; if (n && n.layoutSizingHorizontal === want.h) ok++; }
  if (want.v) { checks++; if (n && n.layoutSizingVertical === want.v) ok++; }
});
var paraOk = 0, paraChecks = 0;
N.paragraphs.forEach(function (p) {
  var want = norm(p);
  var t = read.sc.texts.filter(function (x) {
    return (!screen || isInside(x.node, screen)) && (x.s === want || (x.s.length >= 40 && want.indexOf(x.s) !== -1));
  })[0];
  paraChecks += 2;
  if (t && t.node.layoutSizingHorizontal === R.paragraph.h) paraOk++;
  if (t && t.node.textAutoResize === R.paragraph.textAutoResize) paraOk++;
});
var container = one('container').node, toolbar = one('toolbar').node, tagRow = one('tagRow').node;
var fab = one('fab').node, sidebar = one('sidebar').node;
var mw = container && typeof container.maxWidth === 'number' ? container.maxWidth : null;
function painted(n) {
  return ['fills', 'strokes'].some(function (k) {
    var v = n[k];
    return v && v !== figma.mixed && v.some(function (p) { return p.visible !== false && (p.opacity === undefined || p.opacity > 0); });
  }) || (n.effects && n.effects.length > 0);
}
var spacers = screen ? [screen].concat(screen.findAll()).filter(function (n) {
  if ((n.type !== 'FRAME' && n.type !== 'RECTANGLE') || inInstance(n) || !isShown(n)) return false;
  return !painted(n) && !(n.findAll && n.findAll(function (c) { return c.type === 'TEXT' || painted(c); }).length);
}).length : 0;
var m = Object.assign(await quality(pages), {
  found: share(els.filter(function (r) { return R[r.u.c] && whole(r); }).length, els.filter(function (r) { return R[r.u.c]; }).length),
  sizingMatch: share(ok, checks),
  maxWidth: mw !== null && Math.abs(mw - R.container.maxWidth) <= 2 ? 1 : mw ? 0.5 : 0,
  wrap: tagRow && tagRow.layoutWrap === R.tagRow.wrap ? 1 : 0,
  paragraphResize: share(paraOk, paraChecks),
  spaceBetween: toolbar && isAL(toolbar) && toolbar.primaryAxisAlignItems === R.toolbar.justify ? 1 : 0,
  spacerFrames: spacers,
  fabPinned: fab && (fab.layoutPositioning === 'ABSOLUTE' || !isAL(fab.parent)) && fab.constraints &&
    fab.constraints.horizontal === R.fab.pin[0] && fab.constraints.vertical === R.fab.pin[1] ? 1 : 0,
  sidebarWidth: sidebar && Math.abs(sidebar.width - R.sidebar.width) <= 2 ? 1 : 0,
  copy: copyMatch(N.strings, screenRegionNodes(read)),
  inventedCopy: inventedCopy(read, N.strings),
});
return {
  metrics: m,
  lower: QUALITY_LOWER.concat(['spacerFrames', 'inventedCopy']),
  passed: m.found === 1 && m.sizingMatch >= 0.9 && m.maxWidth === 1 && m.wrap === 1 && m.paragraphResize === 1 &&
    m.spaceBetween === 1 && m.spacerFrames === 0 && m.fabPinned === 1 && m.copy >= 0.95,
};
