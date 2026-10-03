// The Team screen built from new row and header components (copies of the seeded frames),
// while the Customers screen keeps its plain frames: no third raw copy, but nothing linked.
// include: offline/pattern_kit.js
function componentFrom(n, name) {
  var copy = n.clone();
  page.appendChild(copy);
  copy.y = -600;
  var c = figma.createComponentFromNode(copy);
  c.name = name;
  return c;
}
var row = componentFrom(oldRows[0], 'List item');
setTexts(row, ['AB', 'Name', 'Subtitle', 'Status']);
var header = componentFrom(oldHeader, 'App header');
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
