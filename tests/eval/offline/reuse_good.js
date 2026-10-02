// The login screen built from the seeded components, as a good session leaves it.
await loadFonts();
var page = await targetPage();
var set = await figma.getNodeByIdAsync(EVAL.seed.buttonSetId);
var input = await figma.getNodeByIdAsync(EVAL.seed.inputId);
function key(n, name) { return Object.keys(n.componentPropertyDefinitions).filter(function (k) { return k.indexOf(name + '#') === 0; })[0]; }
var root = mkFrame(page, 'Login', 'VERTICAL', { gap: 24, pad: [32, 32, 32, 32], fill: 'surface', width: 400 });
mkText(root, 'Welcome back to Lumen', { style: 'Bold', size: 28, name: 'Heading' });
mkText(root, 'Sign in to keep your playlists in sync', { color: 'text-muted', name: 'Subheading' });
[['Work email', 'you@lumen.fm'], ['Password', 'At least 12 characters']].forEach(function (f) {
  var i = input.createInstance();
  root.appendChild(i);
  i.layoutSizingHorizontal = 'FILL';
  var props = {};
  props[key(input, 'Label')] = f[0];
  props[key(input, 'Placeholder')] = f[1];
  i.setProperties(props);
});
mkText(root, 'Forgot your passphrase?', { size: 12, color: 'primary', name: 'Reset link' });
[['Primary', 'Sign in'], ['Secondary', 'Create an account']].forEach(function (b) {
  var v = set.children.filter(function (c) { return c.name === 'Variant=' + b[0] + ', State=Default'; })[0];
  var i = v.createInstance();
  root.appendChild(i);
  i.layoutSizingHorizontal = 'FILL';
  var props = {};
  props[key(set, 'Label')] = b[1];
  i.setProperties(props);
});
return { ok: true };
