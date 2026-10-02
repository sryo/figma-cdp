// Five hand-built row frames, no component.
await loadFonts();
var page = await targetPage();
var screen = mkFrame(page, 'Settings', 'VERTICAL', { fill: 'background', width: 480 });
mkText(screen, 'Listening preferences', { size: 20 });
EVAL.expect.settings.rows.forEach(function (r) {
  var row = mkFrame(screen, 'Row', 'HORIZONTAL', { pad: [16, 16, 16, 16], fill: 'surface' });
  mkText(row, r.label, { size: 16 });
  mkText(row, r.hint, { size: 12, color: 'text-muted' });
  mkFrame(row, 'Toggle', 'HORIZONTAL', { fill: r.on ? 'toggle-on' : 'toggle-off' });
});
return { ok: true };
