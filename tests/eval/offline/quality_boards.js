// instanceRatio over three pages' worth of states, measured one at a time: a screen of two
// instances beside a board of masters (with a nested icon board), the same board holding a
// stray raw card too, and the screen alone.
var page = await targetPage();
function master(parent, name) { var c = mkFrame(parent, name, 'HORIZONTAL', { component: true }); mkFrame(c, 'Inner', 'HORIZONTAL'); return c; }
function screen() { return mkFrame(page, 'Screen', 'VERTICAL'); }
async function measure() { var m = (await quality(evalPages())).instanceRatio; page.children.slice().forEach(function (n) { n.remove(); }); return m; }

var s = screen(), board = mkFrame(page, 'Components', 'HORIZONTAL'), icons = mkFrame(board, 'Icons', 'HORIZONTAL');
var row = master(board, 'Row'); master(icons, 'Icon/Bell');
s.appendChild(row.createInstance()); s.appendChild(row.createInstance());
var boards = await measure();

s = screen(); board = mkFrame(page, 'Components', 'HORIZONTAL');
row = master(board, 'Row'); mkFrame(board, 'Card', 'VERTICAL');
s.appendChild(row.createInstance()); s.appendChild(row.createInstance());
var mixed = await measure();

s = screen(); row = master(page, 'Row');
s.appendChild(row.createInstance()); s.appendChild(row.createInstance());
var bare = await measure();
return { boards: boards, mixed: mixed, bare: bare };
