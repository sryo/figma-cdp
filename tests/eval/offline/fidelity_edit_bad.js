// The screen rebuilt from scratch beside a deleted original: right content, new ids.
await loadFonts();
(await figma.getNodeByIdAsync(EVAL.seed.rootId)).remove();
var page = await targetPage();
var root = mkFrame(page, 'Login', 'VERTICAL', { gap: 24, fill: 'surface' });
EVAL.expect.login.copy.forEach(function (s) { mkText(root, s, {}); });
return { ok: true };
