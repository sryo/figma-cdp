// Two theme collections that drift from tests/design/DESIGN.md (Lede/light: colors/ink differs,
// spacing/gap missing, colors/old unused; Lede/dark: colors/ink missing), plus a collection
// DESIGN.md doesn't name. A plain script over the global `figma`: figma_run.py runs it on the
// stub through perch, and record_inventory.js runs it in place.
(function () {
  var hex = function (h) { return { r: parseInt(h.slice(1, 3), 16) / 255, g: parseInt(h.slice(3, 5), 16) / 255, b: parseInt(h.slice(5, 7), 16) / 255, a: 1 }; };
  function collection(name, vars) {
    var c = figma.variables.createVariableCollection(name);
    Object.keys(vars).forEach(function (n) {
      var v = vars[n], type = typeof v === 'number' ? 'FLOAT' : v.charAt(0) === '#' ? 'COLOR' : 'STRING';
      figma.variables.createVariable(n, c, type).setValueForMode(c.defaultModeId, type === 'COLOR' ? hex(v) : v);
    });
  }
  var type = { 'typography/fs-s/fontFamily': 'Inter', 'typography/fs-s/fontSize': 14, 'typography/fs-s/fontWeight': 500, 'rounded/r-tile': 20 };
  collection('Lede/light', Object.assign({ 'colors/primary': '#2f5bea', 'colors/canvas': '#faf9f6', 'colors/ink': '#000000',
    'colors/on-primary': '#faf9f6' }, type, { 'colors/old': '#ffffff' }));
  collection('Lede/dark', Object.assign({ 'colors/primary': '#2f5bea', 'colors/canvas': '#0e0f13', 'colors/on-primary': '#faf9f6' }, type,
    { 'spacing/gap': 16 }));
  collection('Brand', { 'colors/x': '#123456' });
  return 'seeded';
})();
