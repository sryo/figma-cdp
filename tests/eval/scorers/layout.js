// Store screen: header and card grid in auto layout with hug/fill sizing, the cart badge
// absolute with constraints, cards as instances of the seeded Product card.
var pages = evalPages();
var page = await targetPage();
var nodes = screenNodes(page);
var P = EVAL.expect.products;

function textNode(s) { return nodes.filter(function (n) { return n.type === 'TEXT' && norm(n.characters) === norm(s); })[0] || null; }
// The deepest node holding every one of the texts.
function commonAncestor(texts) {
  var hits = texts.map(textNode).filter(Boolean);
  if (hits.length < texts.length) return null;
  for (var p = hits[0].parent; p && p.type !== 'PAGE'; p = p.parent) {
    var inside = hits.every(function (h) { for (var q = h; q; q = q.parent) if (q === p) return true; return false; });
    if (inside) return p;
  }
  return null;
}
function isAuto(n) { return !!(n && n.layoutMode && n.layoutMode !== 'NONE'); }

var header = commonAncestor(P.nav);
var grid = commonAncestor(P.cards.map(function (c) { return c.title; }));
var cardIds = [EVAL.seed.cardId];
var cards = await instancesOf([page], cardIds);
var badge = textNode('3');
var badgeBox = badge;
while (badgeBox && badgeBox.parent && badgeBox.layoutPositioning !== 'ABSOLUTE' && badgeBox.parent !== header && badgeBox.parent.type !== 'PAGE') {
  badgeBox = badgeBox.parent;
}
var badgeAbs = badgeBox && badgeBox.layoutPositioning === 'ABSOLUTE';
var m = Object.assign(await quality(pages), {
  headerAutoLayout: isAuto(header) && header.layoutMode === 'HORIZONTAL' ? 1 : 0,
  gridAutoLayout: isAuto(grid) ? 1 : 0,
  cardReuse: share(Math.min(cards.length, P.cards.length), P.cards.length),
  badgeConstrained: badgeAbs && badgeBox.constraints && (badgeBox.constraints.horizontal !== 'MIN' || badgeBox.constraints.vertical !== 'MIN') ? 1 : 0,
  copy: copyMatch(P.nav.concat(P.cards.map(function (c) { return c.title; }), P.cards.map(function (c) { return c.price; }),
    ['Add to cart', 'Sold out']), nodes),
});
return {
  metrics: m,
  lower: QUALITY_LOWER,
  passed: m.headerAutoLayout === 1 && m.gridAutoLayout === 1 && m.autoLayoutShare >= 0.9 && m.absoluteStacks === 0 &&
    m.cardReuse === 1 && m.copy >= 0.9,
};
