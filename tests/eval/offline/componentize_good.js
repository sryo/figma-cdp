// One Settings row component set (State=On|Off) with Label and Hint text properties,
// instanced once per row.
await loadFonts();
var page = await targetPage();
var lib = mkFrame(page, 'Components', 'HORIZONTAL', { gap: 40 });
var variants = [], labels = [], hints = [];
['On', 'Off'].forEach(function (state) {
  var c = mkFrame(lib, 'State=' + state, 'HORIZONTAL', { component: true, pad: [16, 16, 16, 16], gap: 16, fill: 'surface', stroke: 'border', width: 480 });
  var text = mkFrame(c, 'Copy', 'VERTICAL', { gap: 4 });
  text.layoutSizingHorizontal = 'FILL';
  labels.push(mkText(text, 'Setting', { size: 16, name: 'Label' }));
  hints.push(mkText(text, 'Hint', { size: 12, color: 'text-muted', name: 'Hint' }));
  var toggle = mkFrame(c, 'Toggle', 'HORIZONTAL', { pad: [2, 2, 2, 2], radius: 999, fill: state === 'On' ? 'toggle-on' : 'toggle-off' });
  var knob = figma.createEllipse();
  knob.name = 'Knob';
  toggle.appendChild(knob);
  knob.resize(20, 20);
  knob.fills = [paintOf('surface')];
  variants.push(c);
});
var set = figma.combineAsVariants(variants, lib);
set.name = 'Settings row';
var lk = set.addComponentProperty('Label', 'TEXT', 'Setting');
var hk = set.addComponentProperty('Hint', 'TEXT', 'Hint');
labels.forEach(function (t) { t.componentPropertyReferences = { characters: lk }; });
hints.forEach(function (t) { t.componentPropertyReferences = { characters: hk }; });
var screen = mkFrame(page, 'Settings', 'VERTICAL', { fill: 'background', width: 480 });
screen.y = 300;
mkText(screen, 'Listening preferences', { size: 20, name: 'Title' });
EVAL.expect.settings.rows.forEach(function (r) {
  var i = variants[r.on ? 0 : 1].createInstance();
  screen.appendChild(i);
  i.layoutSizingHorizontal = 'FILL';
  var props = {};
  props[lk] = r.label; props[hk] = r.hint;
  i.setProperties(props);
  i.name = 'Settings row';
});
return { ok: true };
