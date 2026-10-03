// Draws harbor-pages/notes.html in auto layout for the responsive end states. Each knob is one
// thing the CSS asks for; false draws the common wrong version instead:
//   maxWidth    container FILL with maxWidth 1120 (else FIXED 1120, no max)
//   between     toolbar SPACE_BETWEEN (else MIN plus a FILL spacer frame)
//   wrap        tag row WRAP (else one NO_WRAP line)
//   paragraphs  paragraphs FILL width, textAutoResize HEIGHT (else WIDTH_AND_HEIGHT, one long line)
//   columns     main FILL beside a FIXED 280 sidebar, both hugging height (else both FIXED)
//   hug         tags and buttons HUG (else FIXED)
//   fab         FAB absolute, pinned MAX/MAX (else absolute, left at MIN/MIN)
async function drawNotes(k) {
  await loadFonts();
  var page = await targetPage();
  var N = EVAL.expect.screens.notes;
  function find(us, c) {
    for (var i = 0; i < us.length; i++) { if (us[i].c === c) return us[i]; var f = find(us[i].kids, c); if (f) return f; }
    return null;
  }
  function all(us, c) { var out = []; us.forEach(function (u) { if (u.c === c) out.push(u); out = out.concat(all(u.kids, c)); }); return out; }
  function fill(n) { n.layoutSizingHorizontal = 'FILL'; return n; }
  function hug(n) { if (k.hug) { n.layoutSizingHorizontal = 'HUG'; n.layoutSizingVertical = 'HUG'; } else { n.layoutSizingHorizontal = 'FIXED'; n.layoutSizingVertical = 'FIXED'; } return n; }
  function button(parent, u) {
    var b = mkFrame(parent, 'Button', 'HORIZONTAL', { gap: 8, pad: [8, 16, 8, 16], radius: 6, align: 'CENTER',
      fill: u.props.variant === 'secondary' ? 'surface' : 'primary', stroke: u.props.variant === 'secondary' ? 'border' : null });
    mkText(b, u.key, { style: 'Medium', color: u.props.variant === 'secondary' ? 'text' : 'on-primary', name: 'Label' });
    return hug(b);
  }
  var screen = mkFrame(page, N.title, 'VERTICAL', { fill: 'background', width: 1440, align: 'CENTER' });
  screen.resize(1440, 900);
  screen.layoutSizingVertical = 'FIXED';
  var head = fill(mkFrame(screen, 'App header', 'HORIZONTAL', { justify: 'SPACE_BETWEEN', align: 'CENTER', pad: [12, 24, 12, 24], fill: 'surface', stroke: 'border' }));
  mkText(head, 'Harbor', { style: 'Bold', size: 20, color: 'primary', name: 'Brand' });
  var act = mkFrame(head, 'Actions', 'HORIZONTAL', { gap: 16, align: 'CENTER' });
  var bell = mkFrame(act, 'Bell', 'HORIZONTAL', {});
  var glyph = figma.createRectangle(); glyph.name = 'Glyph'; bell.appendChild(glyph); glyph.fills = [paintOf('text-muted')];
  var av = mkFrame(act, 'Avatar', 'HORIZONTAL', { radius: 999, fill: 'avatar-bg', align: 'CENTER', justify: 'CENTER' });
  mkText(av, 'AK', { size: 12, color: 'avatar-text', name: 'Initials' });

  var layout = mkFrame(screen, 'Layout', 'VERTICAL', { gap: 24, pad: [32, 24, 32, 24] });
  if (k.maxWidth) { fill(layout); layout.maxWidth = 1120; } else { layout.resize(1120, layout.height); layout.layoutSizingHorizontal = 'FIXED'; }
  var tb = find(N.usages, 'toolbar');
  var toolbar = fill(mkFrame(layout, 'Toolbar', 'HORIZONTAL', { align: 'CENTER', justify: k.between ? 'SPACE_BETWEEN' : 'MIN' }));
  var titles = mkFrame(toolbar, 'Title', 'VERTICAL', { gap: 4 });
  mkText(titles, tb.anchors[0], { style: 'Bold', size: 28, name: 'Heading' });
  mkText(titles, tb.anchors[1], { color: 'text-muted', name: 'Meta' });
  if (!k.between) fill(mkFrame(toolbar, 'Spacer', 'HORIZONTAL', {}));
  var actions = mkFrame(toolbar, 'Actions', 'HORIZONTAL', { gap: 12 });
  tb.kids.forEach(function (u) { button(actions, u); });

  var columns = fill(mkFrame(layout, 'Columns', 'HORIZONTAL', { gap: 32 }));
  var mainU = find(N.usages, 'main'), side = find(N.usages, 'sidebar');
  var main = mkFrame(columns, 'Article', 'VERTICAL', { gap: 16 });
  var aside = mkFrame(columns, 'Sidebar', 'VERTICAL', { gap: 12, pad: [16, 16, 16, 16], fill: 'surface', stroke: 'border', radius: 10, width: 280 });
  if (k.columns) { fill(main); aside.layoutSizingVertical = 'HUG'; }
  else { main.resize(760, 600); main.layoutSizingHorizontal = 'FIXED'; main.layoutSizingVertical = 'FIXED'; aside.resize(280, 600); aside.layoutSizingVertical = 'FIXED'; }
  mkText(main, mainU.anchors[0], { style: 'Medium', size: 20, name: 'Heading' });
  var tags = fill(mkFrame(main, 'Tags', 'HORIZONTAL', { gap: 8 }));
  if (k.wrap) tags.layoutWrap = 'WRAP';
  all(N.usages, 'tag').forEach(function (u) {
    var t = mkFrame(tags, 'Tag', 'HORIZONTAL', { pad: [4, 12, 4, 12], radius: 999, fill: 'surface', stroke: 'border' });
    mkText(t, u.key, { size: 12, name: 'Label' });
    hug(t);
  });
  N.paragraphs.forEach(function (p) {
    var t = mkText(main, p, { size: 16, name: 'Paragraph' });
    if (k.paragraphs) { t.layoutSizingHorizontal = 'FILL'; t.textAutoResize = 'HEIGHT'; }
  });
  side.anchors.forEach(function (s, i) { mkText(aside, s, { color: i === 0 ? 'text' : i === side.anchors.length - 1 ? 'text-muted' : 'primary', name: i ? 'Link' : 'Heading' }); });

  var fabU = find(N.usages, 'fab');
  var fab = mkFrame(screen, 'FAB', 'HORIZONTAL', { gap: 8, pad: [12, 16, 12, 16], radius: 999, fill: 'primary', align: 'CENTER' });
  var plus = mkFrame(fab, 'Plus', 'HORIZONTAL', {});
  var g2 = figma.createRectangle(); g2.name = 'Glyph'; plus.appendChild(g2); g2.fills = [paintOf('on-primary')];
  mkText(fab, fabU.key, { style: 'Medium', color: 'on-primary', name: 'Label' });
  hug(fab);
  fab.layoutPositioning = 'ABSOLUTE';
  fab.x = 1440 - 24 - 140; fab.y = 900 - 24 - 48;
  fab.constraints = k.fab ? { horizontal: 'MAX', vertical: 'MAX' } : { horizontal: 'MIN', vertical: 'MIN' };
  return screen;
}
