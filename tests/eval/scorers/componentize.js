// Settings list: every row an instance of one row component, toggle state as a variant (or
// at least the right on/off color), not five hand-built frames.
var pages = evalPages();
var page = await targetPage();
var nodes = screenNodes(page);
var rows = EVAL.expect.settings.rows;
var ON = /^(on|true|checked|enabled|yes)$/i, OFF = /^(off|false|unchecked|no)$/i;

function rowLabels(n) {
  return n.findAll(function (x) {
    return x.type === 'TEXT' && rows.some(function (r) { return norm(x.characters) === norm(r.label); });
  }).length;
}
// The outermost instance around a label that holds no other row's label.
function rowInstance(text) {
  var hit = null;
  for (var p = text.parent; p && p.type !== 'PAGE'; p = p.parent) {
    if (rowLabels(p) > 1) break;
    if (p.type === 'INSTANCE') hit = p;
  }
  return hit;
}
function variantState(inst) {
  var found = null;
  [inst].concat(inst.findAll(function (n) { return n.type === 'INSTANCE'; })).forEach(function (i) {
    var props = i.componentProperties || {};
    Object.keys(props).forEach(function (k) {
      if (props[k].type !== 'VARIANT' && props[k].type !== 'BOOLEAN') return;
      var v = String(props[k].value);
      if (found === null && ON.test(v)) found = true;
      else if (found === null && OFF.test(v)) found = false;
    });
  });
  return found;
}
function colorState(n) {
  var on = false, off = false;
  [n].concat(n.findAll ? n.findAll() : []).forEach(function (x) {
    solidPaints(x).forEach(function (p) {
      var h = toHex(p.color);
      if (near(h, EVAL.expect.colors['toggle-on'])) on = true;
      if (near(h, EVAL.expect.colors['toggle-off'])) off = true;
    });
  });
  return on === off ? null : on;
}
// The outermost ancestor of a label holding no other row's label: that row's own subtree.
function rowOf(text) {
  var row = null;
  for (var p = text.parent; p && p.type !== 'PAGE'; p = p.parent) {
    if (rowLabels(p) > 1) break;
    row = p;
  }
  return row;
}

var instanced = 0, stateOk = 0, mains = {}, raw = 0;
for (var i = 0; i < rows.length; i++) {
  var label = nodes.filter(function (n) { return n.type === 'TEXT' && norm(n.characters) === norm(rows[i].label); })[0];
  if (!label) continue;
  var inst = rowInstance(label);
  var row = inst || rowOf(label);
  if (inst) {
    instanced++;
    var main = await inst.getMainComponentAsync();
    if (main) mains[main.parent && main.parent.type === 'COMPONENT_SET' ? main.parent.id : main.id] = 1;
  } else {
    raw++;
  }
  var state = inst ? variantState(inst) : null;
  if (state === null && row) state = colorState(row);
  if (state === rows[i].on) stateOk++;
}
var sets = nodesOf(pages).filter(function (n) { return n.type === 'COMPONENT_SET'; });
var onOff = sets.some(function (s) {
  var d = s.componentPropertyDefinitions || {};
  return Object.keys(d).some(function (k) {
    var o = d[k].variantOptions || [];
    return o.some(function (x) { return ON.test(x); }) && o.some(function (x) { return OFF.test(x); });
  });
});
var copy = copyMatch(EVAL.expect.settings.copy.concat(rows.map(function (r) { return r.label; }),
  rows.map(function (r) { return r.hint; })), nodes);
var m = Object.assign(await quality(pages), {
  rowsInstanced: share(instanced, rows.length),
  rowComponents: Object.keys(mains).length,
  rawRows: raw,
  stateMatch: share(stateOk, rows.length),
  onOffVariant: onOff ? 1 : 0,
  copy: copy,
});
return {
  metrics: m,
  lower: QUALITY_LOWER.concat(['rawRows', 'rowComponents']),
  passed: m.rowsInstanced === 1 && m.rowComponents === 1 && m.stateMatch === 1 && m.onOffVariant === 1 && copy >= 0.9,
};
