// The fixture's login screen (tests/eval/fixtures/app/login.html) on the stub, for
// tests/fidelity_test.py. Runs after tests/eval/lib.js with EVAL = {prefix, expect, bad}.
// Good: every value from the source, colors bound to variables, root gap bound to space/6,
// buttons instances of a Button set with Variant × State, fields instances of an Input. Bad drifts in one way per check:
// short heading, missing link, invented copy, an off-palette blue, an unbound token color,
// an 18 gap, a 7 radius, a 15 font size, a Roboto font, the root gap left unbound, and a
// Button set with neither Secondary nor Disabled, and fields drawn as plain frames.
await loadFonts();
await figma.loadFontAsync({ family: 'Roboto', style: 'Regular' });
var bad = !!EVAL.bad;
var tokens = seedTokens();
var v = tokens.vars;
var page = figma.currentPage;
var floats = figma.variables.createVariableCollection(EVAL.prefix + ' space');
var space6 = figma.variables.createVariable('space/6', floats, 'FLOAT');
space6.setValueForMode(floats.modes[0].modeId, 24);

var lib = mkFrame(page, 'Library', 'HORIZONTAL', { gap: 16 });
var set;
if (bad) {
  var only = mkFrame(lib, 'Variant=Primary, State=Default', 'HORIZONTAL',
    { component: true, pad: [12, 16, 12, 16], gap: 8, align: 'CENTER', justify: 'CENTER', radius: 6, fill: 'primary', vars: v });
  var lbl = mkText(only, 'Button', { style: 'Medium', size: 14, color: 'on-primary', name: 'Label', vars: v });
  set = figma.combineAsVariants([only], lib);
  set.name = 'Button';
  lbl.componentPropertyReferences = { characters: set.addComponentProperty('Label', 'TEXT', 'Button') };
} else {
  set = buildButtonSet(lib, v);
}
var input = bad ? null : buildInput(lib, v);
var labelKey = Object.keys(set.componentPropertyDefinitions).filter(function (k) { return k.indexOf('Label') === 0; })[0];
function button(parent, variant, label) {
  var main = set.children.filter(function (c) { return c.name === 'Variant=' + variant + ', State=Default'; })[0];
  var inst = main.createInstance();
  parent.appendChild(inst);
  var props = {};
  props[labelKey] = label;
  inst.setProperties(props);
  return inst;
}

var root = mkFrame(page, 'Login', 'VERTICAL', { gap: 24, pad: [32, 32, 32, 32], radius: 10, fill: 'surface', width: 400, vars: v });
if (!bad) root.setBoundVariable('itemSpacing', space6);
var head = mkFrame(root, 'Header', 'VERTICAL', { gap: 8 });
mkText(head, bad ? 'Welcome back' : 'Welcome back to Lumen', { style: 'Bold', size: 28, name: 'Heading', vars: v });
var sub = mkText(head, 'Sign in to keep your playlists in sync', { size: bad ? 15 : 14, color: 'text-muted', name: 'Subheading',
  vars: bad ? null : v });
var form = mkFrame(root, 'Form', 'VERTICAL', { gap: bad ? 18 : 16 });
[['Work email', 'you@lumen.fm'], ['Password', 'At least 12 characters']].forEach(function (f, i) {
  if (!bad) {
    var inst = input.createInstance();
    form.appendChild(inst);
    var props = {};
    Object.keys(input.componentPropertyDefinitions).forEach(function (k) { props[k] = k.indexOf('Label') === 0 ? f[0] : f[1]; });
    inst.setProperties(props);
    return;
  }
  var field = mkFrame(form, f[0] + ' field', 'VERTICAL', { gap: 4 });
  var label = mkText(field, f[0], { style: 'Medium', size: 12, color: 'text-muted', name: 'Label', vars: v });
  if (i === 1) label.fontName = { family: 'Roboto', style: 'Regular' };
  var box = mkFrame(field, 'Input', 'HORIZONTAL', { pad: [12, 12, 12, 12], radius: i === 0 ? 7 : 6, fill: 'surface',
    stroke: 'border', vars: v });
  mkText(box, f[1], { size: 14, color: 'text-muted', name: 'Placeholder', vars: v });
});
if (bad) mkText(form, 'Remember me', { size: 12, name: 'Remember', vars: v });
else mkText(form, 'Forgot your passphrase?', { size: 12, color: 'primary', name: 'Reset link', vars: v });
var primary = button(form, 'Primary', 'Sign in');
if (bad) primary.fills = [{ type: 'SOLID', color: fromHex('#2563eb') }];
if (bad) {
  var raw = mkFrame(form, 'Create account button', 'HORIZONTAL', { pad: [12, 16, 12, 16], radius: 6, fill: 'surface', stroke: 'border', vars: v });
  mkText(raw, 'Create an account', { style: 'Medium', size: 14, color: 'primary', vars: v });
} else {
  button(form, 'Secondary', 'Create an account');
}
return { rootId: root.id, subId: sub.id, primaryId: primary.id, formId: form.id };
