// Store screen in auto layout: header (brand, nav, cart with an absolute, constrained badge)
// over a wrapping grid of Product card instances.
await loadFonts();
var page = await targetPage();
var card = await figma.getNodeByIdAsync(EVAL.seed.cardId);
function key(n, name) { return Object.keys(n.componentPropertyDefinitions).filter(function (k) { return k.indexOf(name + '#') === 0; })[0]; }
var screen = mkFrame(page, 'Store', 'VERTICAL', { fill: 'background', width: 1200 });
var header = mkFrame(screen, 'Header', 'HORIZONTAL', { pad: [16, 24, 16, 24], fill: 'surface', stroke: 'border', align: 'CENTER', justify: 'SPACE_BETWEEN' });
header.layoutSizingHorizontal = 'FILL';
mkText(header, 'Lumen', { style: 'Bold', size: 20, color: 'primary', name: 'Brand' });
var nav = mkFrame(header, 'Nav', 'HORIZONTAL', { gap: 24 });
['Discover', 'Library', 'Store'].forEach(function (l) { mkText(nav, l, { color: l === 'Store' ? 'text' : 'text-muted' }); });
var cart = mkFrame(header, 'Cart', 'HORIZONTAL', {});
mkText(cart, '🛒', { name: 'Cart icon' });
var badge = mkFrame(cart, 'Badge', 'HORIZONTAL', { fill: 'badge', radius: 999, pad: [0, 4, 0, 4] });
badge.layoutPositioning = 'ABSOLUTE';
badge.constraints = { horizontal: 'MAX', vertical: 'MIN' };
mkText(badge, '3', { size: 12, color: 'on-primary', name: 'Count' });
var grid = mkFrame(screen, 'Grid', 'HORIZONTAL', { gap: 24, pad: [32, 32, 32, 32] });
grid.layoutWrap = 'WRAP';
grid.layoutSizingHorizontal = 'FILL';
var cards = EVAL.expect.products.cards;
for (var n = 0; n < cards.length; n++) {
  var c = cards[n];
  var i = card.createInstance();
  grid.appendChild(i);
  var props = {};
  props[key(card, 'Title')] = c.title;
  props[key(card, 'Price')] = c.price;
  i.setProperties(props);
  var cta = i.findOne(function (x) { return x.type === 'INSTANCE'; });
  var set = (await cta.getMainComponentAsync()).parent;
  var lp = {};
  lp[key(set, 'Label')] = c.cta;
  if (c.cta === 'Sold out') lp.State = 'Disabled';
  cta.setProperties(lp);
}
return { ok: true };
