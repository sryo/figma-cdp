// Columns, tags and paragraphs right; the container is a fixed 1120 frame, the toolbar pushes
// its buttons right with a spacer frame, and the FAB is absolute but not pinned.
// include: offline/notes_kit.js
await drawNotes({ maxWidth: false, between: false, wrap: true, paragraphs: true, columns: true, hug: true, fab: false });
return { ok: true };
