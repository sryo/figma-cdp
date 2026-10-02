// The three diffs fixed in place.
await loadFonts();
var heading = await figma.getNodeByIdAsync(EVAL.seed.headingId);
heading.characters = 'Welcome back to Lumen';
var primary = await figma.getNodeByIdAsync(EVAL.seed.primaryId);
primary.fills = [paintOf('primary')];
var form = primary.parent;
var link = mkText(form, 'Forgot your passphrase?', { size: 12, color: 'primary', name: 'Reset link' });
form.insertChild(form.children.indexOf(primary), link);
return { ok: true };
