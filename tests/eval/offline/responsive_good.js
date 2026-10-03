// notes.html with every layout intent carried over: max-width container, fill/hug/fixed per
// axis, wrapping tags, height-resizing paragraphs, space-between toolbar, pinned FAB.
// include: offline/notes_kit.js
await drawNotes({ maxWidth: true, between: true, wrap: true, paragraphs: true, columns: true, hug: true, fab: true });
return { ok: true };
