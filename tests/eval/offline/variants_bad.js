// Two variants only (no disabled state), no label property, the secondary drawn without auto layout.
await loadFonts();
var page = await targetPage();
var a = mkFrame(page, 'Type=Primary', 'HORIZONTAL', { component: true, fill: 'primary', pad: [12, 16, 12, 16] });
mkText(a, 'Button', { color: 'on-primary' });
var b = mkFrame(page, 'Type=Secondary', 'NONE', { component: true, fill: 'surface' });
mkText(b, 'Button', { color: 'primary' });
figma.combineAsVariants([a, b], page).name = 'Button';
return { ok: true };
