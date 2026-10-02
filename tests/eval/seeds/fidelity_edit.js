// The login screen as an earlier pass drew it, drifted from login.html in three ways: the
// heading copy is short, the primary button is the wrong blue, and the "Forgot your
// passphrase?" link is missing. Returns every seeded node id so the scorer can tell an
// edit from a rebuild.
await loadFonts();
var tokens = seedTokens();
var v = tokens.vars;
var page = await targetPage();
var root = mkFrame(page, 'Login', 'VERTICAL', { gap: 24, pad: [32, 32, 32, 32], radius: 10, fill: 'surface', width: 400, vars: v });
var head = mkFrame(root, 'Header', 'VERTICAL', { gap: 8 });
head.layoutSizingHorizontal = 'FILL';
var heading = mkText(head, 'Welcome back', { style: 'Bold', size: 28, name: 'Heading', vars: v });
mkText(head, 'Sign in to keep your playlists in sync', { size: 14, color: 'text-muted', name: 'Subheading', vars: v });
var form = mkFrame(root, 'Form', 'VERTICAL', { gap: 16 });
form.layoutSizingHorizontal = 'FILL';
[['Work email', 'you@lumen.fm'], ['Password', 'At least 12 characters']].forEach(function (f) {
  var field = mkFrame(form, f[0] + ' field', 'VERTICAL', { gap: 4 });
  field.layoutSizingHorizontal = 'FILL';
  mkText(field, f[0], { style: 'Medium', size: 12, color: 'text-muted', name: 'Label', vars: v });
  var box = mkFrame(field, 'Input', 'HORIZONTAL', { pad: [12, 12, 12, 12], radius: 6, fill: 'surface', stroke: 'border', vars: v });
  box.layoutSizingHorizontal = 'FILL';
  mkText(box, f[1], { size: 14, color: 'text-muted', name: 'Placeholder', vars: v });
});
var primary = mkFrame(form, 'Sign in button', 'HORIZONTAL', { pad: [12, 16, 12, 16], radius: 6, align: 'CENTER', justify: 'CENTER',
  fill: '#2563eb' });
primary.layoutSizingHorizontal = 'FILL';
mkText(primary, 'Sign in', { style: 'Medium', size: 14, color: 'on-primary', name: 'Label', vars: v });
var secondary = mkFrame(form, 'Create account button', 'HORIZONTAL', { pad: [12, 16, 12, 16], radius: 6, align: 'CENTER',
  justify: 'CENTER', fill: 'surface', stroke: 'border', vars: v });
secondary.layoutSizingHorizontal = 'FILL';
mkText(secondary, 'Create an account', { style: 'Medium', size: 14, color: 'primary', name: 'Label', vars: v });
var ids = [root.id].concat(root.findAll().map(function (n) { return n.id; }));
return { rootId: root.id, headingId: heading.id, primaryId: primary.id, ids: ids, variables: tokens.ids };
