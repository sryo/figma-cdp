// Every box at fixed size as measured: no max width, a spacer in the toolbar, one unwrapped
// tag line, auto-width paragraphs, fixed columns, fixed tags and buttons, an unpinned FAB.
// include: offline/notes_kit.js
await drawNotes({ maxWidth: false, between: false, wrap: false, paragraphs: false, columns: false, hug: false, fab: false });
return { ok: true };
