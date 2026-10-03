// The Customers screen as hand-drawn files often hold it: an app header and four list rows
// that share one structure but are plain frames, not instances. Returns the screen's content
// in source.py's usage format, so the scorer can find the rows again however they are renamed
// or turned into components.
await loadFonts();
var tokens = seedTokens(), v = tokens.vars;
var page = await targetPage();
var ROWS = [['Priya Raman', 'Northwind Studio', 'PR', 'Active', 'success'], ['Marco Diaz', 'Diaz & Co.', 'MD', 'Trial', 'warning'],
  ['Lena Ortiz', 'Brightline', 'LO', 'Invited', 'neutral'], ['Jonah Bell', 'Bell Hardware', 'JB', 'Past due', 'danger']];

function use(c, props, anchors, kids) {
  var texts = anchors.slice();
  kids.forEach(function (k) { texts = texts.concat(k.texts); });
  return { c: c, props: props, anchors: anchors, texts: texts, kids: kids, items: [],
    key: c === 'Icon' ? null : anchors[0] || texts[0] || null };
}
function avatar(parent, initials) {
  var a = mkFrame(parent, 'Avatar', 'HORIZONTAL', { align: 'CENTER', justify: 'CENTER', radius: 999, fill: 'avatar-bg', vars: v });
  a.resize(32, 32);
  a.layoutSizingHorizontal = 'FIXED';
  a.layoutSizingVertical = 'FIXED';
  mkText(a, initials, { style: 'Medium', size: 12, color: 'avatar-text', name: 'Initials', vars: v });
}
function fill(n) { n.layoutSizingHorizontal = 'FILL'; return n; }

var screen = mkFrame(page, 'Customers', 'VERTICAL', { fill: 'background', width: 480, vars: v });
var header = fill(mkFrame(screen, 'Header', 'HORIZONTAL', { justify: 'SPACE_BETWEEN', align: 'CENTER', pad: [12, 24, 12, 24],
  fill: 'surface', stroke: 'border', vars: v }));
mkText(header, 'Harbor', { style: 'Bold', size: 20, color: 'primary', name: 'Brand', vars: v });
var actions = mkFrame(header, 'Actions', 'HORIZONTAL', { gap: 16, align: 'CENTER' });
var bell = mkFrame(actions, 'Bell', 'NONE', {});
bell.resize(20, 20);
var glyph = figma.createRectangle();
glyph.name = 'Glyph';
bell.appendChild(glyph);
glyph.resize(16, 12);
glyph.fills = [paintOf('text-muted', v)];
avatar(actions, 'AK');
var body = fill(mkFrame(screen, 'Content', 'VERTICAL', { gap: 24, pad: [32, 32, 32, 32] }));
mkText(body, 'Customers', { style: 'Bold', size: 28, name: 'Title', vars: v });
var list = fill(mkFrame(body, 'List', 'VERTICAL', { fill: 'surface', stroke: 'border', radius: 10, vars: v }));
var usages = [use('AppHeader', {}, ['Harbor'], [use('Icon', { name: 'bell' }, [], []), use('Avatar', { size: 'sm' }, ['AK'], [])])];
ROWS.forEach(function (r) {
  var row = fill(mkFrame(list, 'Row', 'HORIZONTAL', { gap: 12, align: 'CENTER', pad: [12, 16, 12, 16] }));
  avatar(row, r[2]);
  var copy = fill(mkFrame(row, 'Copy', 'VERTICAL', { gap: 2 }));
  mkText(copy, r[0], { style: 'Medium', name: 'Name', vars: v });
  mkText(copy, r[1], { size: 12, color: 'text-muted', name: 'Company', vars: v });
  var badge = mkFrame(row, 'Status', 'HORIZONTAL', { pad: [2, 8, 2, 8], radius: 999, fill: r[4] + '-bg', vars: v });
  mkText(badge, r[3], { style: 'Medium', size: 12, color: r[4] + '-text', name: 'Label', vars: v });
  usages.push(use('ListItem', { selected: 'false' }, [r[0], r[1]],
    [use('Avatar', { size: 'sm' }, [r[2]], []), use('Badge', { tone: r[4] }, [r[3]], [])]));
});
var strings = ['Harbor', 'AK', 'Customers'];
ROWS.forEach(function (r) { strings.push(r[0], r[1], r[2], r[3]); });
return { variables: tokens.ids, screen: { title: 'Customers', strings: strings, paragraphs: [], usages: usages } };
