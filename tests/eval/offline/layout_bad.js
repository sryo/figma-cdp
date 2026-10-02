// The store screen as absolutely placed layers: no auto layout, raw card frames.
await loadFonts();
var page = await targetPage();
var screen = mkFrame(page, 'Frame 3', 'NONE', { fill: 'background' });
var header = mkFrame(screen, 'Header', 'NONE', { fill: 'surface' });
['Lumen', 'Discover', 'Library', 'Store', '3'].forEach(function (t, i) { var n = mkText(header, t, {}); n.x = i * 80; });
var grid = mkFrame(screen, 'Grid', 'NONE', {});
EVAL.expect.products.cards.forEach(function (c, i) {
  var f = mkFrame(grid, 'Card', 'NONE', { fill: 'surface' });
  f.x = i * 260;
  mkText(f, c.title, {});
  mkText(f, c.price, {});
});
return { ok: true };
