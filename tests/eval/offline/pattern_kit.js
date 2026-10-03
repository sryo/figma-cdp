// Shared by the pattern-detect end states: the seeded Customers screen's parts, and a Team
// screen frame beside it with the team.html rows' strings at hand.
await loadFonts();
var page = await targetPage();
var oldScreen = page.children.filter(function (n) { return n.name === 'Customers'; })[0];
var oldRows = oldScreen.findAll(function (n) { return n.name === 'Row'; });
var oldHeader = oldScreen.findOne(function (n) { return n.name === 'Header'; });
var teamRows = EVAL.expect.screens.team.usages.filter(function (u) { return u.c === 'ListItem'; });
// A row's strings in drawing order: initials, name, subtitle, badge.
function rowStrings(u) { return [u.kids[0].anchors[0], u.anchors[0], u.anchors[1], u.kids[1].anchors[0]]; }
function textsOf(n) { return n.findAll(function (t) { return t.type === 'TEXT'; }); }
function setTexts(n, list) { textsOf(n).forEach(function (t, i) { t.characters = list[i]; }); }
function fill(n) { n.layoutSizingHorizontal = 'FILL'; return n; }
function teamScreen() {
  var screen = mkFrame(page, 'Team', 'VERTICAL', { fill: 'background', width: 480 });
  screen.x = 600;
  var body = fill(mkFrame(screen, 'Content', 'VERTICAL', { gap: 24, pad: [32, 32, 32, 32] }));
  mkText(body, 'Team', { style: 'Bold', size: 28, name: 'Title' });
  var list = fill(mkFrame(body, 'List', 'VERTICAL', { fill: 'surface', stroke: 'border', radius: 10 }));
  return { screen: screen, body: body, list: list };
}
