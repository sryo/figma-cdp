await loadFonts();
var root = mkFrame(await targetPage(), 'Example', 'NONE', { fill: 'surface' });
mkText(root, 'Example', {});
return { ok: true };
