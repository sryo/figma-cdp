// The first seeded row and the header become components in place, the other three rows are
// swapped for instances, and the Team screen is built from instances of both.
// include: offline/pattern_kit.js
var row = figma.createComponentFromNode(oldRows[0]);
row.name = 'List item';
oldRows.slice(1).forEach(function (r) {
  var strings = textsOf(r).map(function (t) { return t.characters; });
  var i = row.createInstance();
  r.parent.insertChild(r.parent.children.indexOf(r), i);
  fill(i);
  setTexts(i, strings);
  r.remove();
});
var header = figma.createComponentFromNode(oldHeader);
header.name = 'App header';
var t = teamScreen();
var h = header.createInstance();
t.screen.insertChild(0, h);
fill(h);
teamRows.forEach(function (u) {
  var i = row.createInstance();
  t.list.appendChild(i);
  fill(i);
  setTexts(i, rowStrings(u));
});
return { ok: true };
