// The login screen drawn from scratch: a new Button component, raw input frames, an
// off-token blue and a paraphrased heading.
await loadFonts();
var page = await targetPage();
var root = mkFrame(page, 'Frame 1', 'NONE', { fill: 'surface' });
mkText(root, 'Welcome back', { style: 'Bold', size: 28 });
['Work email', 'Password'].forEach(function (l) {
  var f = mkFrame(root, 'Input', 'VERTICAL', { gap: 4 });
  mkText(f, l, { size: 12 });
  mkFrame(f, 'Field', 'HORIZONTAL', { stroke: 'border' });
});
var btn = mkFrame(page, 'Button', 'HORIZONTAL', { component: true, fill: '#2563eb' });
mkText(btn, 'Sign in', { color: 'on-primary' });
return { ok: true };
