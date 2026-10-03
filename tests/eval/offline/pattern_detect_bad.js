// The Team screen as a third hand-drawn copy: the seeded header and a row cloned and edited.
// include: offline/pattern_kit.js
var t = teamScreen();
var h = oldHeader.clone();
t.screen.insertChild(0, h);
fill(h);
teamRows.forEach(function (u) {
  var r = oldRows[0].clone();
  t.list.appendChild(r);
  fill(r);
  setTexts(r, rowStrings(u));
});
return { ok: true };
