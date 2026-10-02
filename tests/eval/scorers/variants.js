// The Button as a component set: a variant axis for primary|secondary, one for the disabled
// state, all four combinations, a TEXT property driving every label, colors from the tokens.
var pages = evalPages();
var all = nodesOf(pages);
var sets = all.filter(function (n) { return n.type === 'COMPONENT_SET'; });
var set = sets.filter(function (s) { return /button/.test(baseName(s.name)); })[0] || sets[0] || null;
var KIND = /^(primary|secondary)$/i, DIS = /^(disabled|true)$/i, EN = /^(default|enabled|false|rest|normal|idle)$/i;

var m = { setFound: set ? 1 : 0, coverage: 0, axesMatch: 0, labelProperty: 0, variantAutoLayout: 0, colorMatch: 0 };
if (set) {
  var d = set.componentPropertyDefinitions || {};
  var axes = Object.keys(d).filter(function (k) { return d[k].type === 'VARIANT'; });
  var kindAxis = axes.filter(function (k) {
    var o = d[k].variantOptions || [];
    return o.some(function (x) { return /^primary$/i.test(x); }) && o.some(function (x) { return /^secondary$/i.test(x); });
  })[0];
  var stateAxis = axes.filter(function (k) {
    var o = d[k].variantOptions || [];
    return k !== kindAxis && o.some(function (x) { return DIS.test(x); }) && o.some(function (x) { return EN.test(x); });
  })[0];
  m.axesMatch = kindAxis && stateAxis ? 1 : 0;
  var combos = {}, colorOk = 0, colorChecks = 0, labelled = 0, auto = 0;
  var textKeys = Object.keys(d).filter(function (k) { return d[k].type === 'TEXT'; });
  set.children.forEach(function (c) {
    var vp = c.variantProperties || {};
    var kind = kindAxis ? String(vp[kindAxis]).toLowerCase() : null;
    var disabled = stateAxis ? DIS.test(String(vp[stateAxis])) : null;
    if (kind && KIND.test(kind) && disabled !== null) combos[kind + '/' + disabled] = 1;
    if (c.layoutMode && c.layoutMode !== 'NONE') auto++;
    var label = c.findOne(function (n) { return n.type === 'TEXT'; });
    var ref = label && label.componentPropertyReferences;
    if (ref && ref.characters && textKeys.indexOf(ref.characters) !== -1) labelled++;
    var want = disabled ? 'disabled-bg' : kind === 'primary' ? 'primary' : kind === 'secondary' ? 'surface' : null;
    if (want) {
      colorChecks++;
      var fill = solidPaints(c)[0];
      if (fill && near(toHex(fill.color), EVAL.expect.colors[want])) colorOk++;
    }
  });
  m.coverage = share(Object.keys(combos).length, 4);
  m.labelProperty = share(labelled, set.children.length);
  m.variantAutoLayout = share(auto, set.children.length);
  m.colorMatch = share(colorOk, colorChecks);
  m.variantCount = set.children.length;
}
m = Object.assign(await quality(pages), m);
return {
  metrics: m,
  lower: QUALITY_LOWER,
  passed: m.coverage === 1 && m.axesMatch === 1 && m.labelProperty === 1 && m.variantAutoLayout === 1 && m.colorMatch === 1,
};
