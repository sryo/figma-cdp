// A "read-only" session that renamed a frame on its way through.
var page = await targetPage();
page.children[0].name = 'Step 1';
return { ok: true };
