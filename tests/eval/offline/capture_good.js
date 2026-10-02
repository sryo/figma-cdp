await loadFonts();
var root = mkFrame(await targetPage(), '[cap:0] Example Domain', 'VERTICAL', { gap: 8, fill: 'surface' });
mkText(root, 'Example Domain', { size: 24, name: '[cap:1] heading' });
mkText(root, 'This domain is for use in documentation examples.', { name: '[cap:2] paragraph' });
return { ok: true };
