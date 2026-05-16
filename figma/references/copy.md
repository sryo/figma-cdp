# Copy Management for Figma

Extracting, updating, diffing, and reviewing text content in Figma designs.

> REST API examples use the `/tmp/figma_api.py` helper from `rest-api.md`.

## Copy-Specific Rules

When working on copy/text tasks, these rules apply on top of the general Rules of Engagement in SKILL.md:

- **Only change `characters`** — never modify visual styling (font size, color, alignment, weight) unless explicitly asked. Copy work is about words, not presentation.
- **Never delete text nodes** — only modify content or flag for review via comments. If text should be removed, flag it and let the designer decide.
- **Preserve casing and punctuation style** of surrounding content (e.g., if headings use sentence case, don't introduce title case).
- **Warn about text overflow** — if replacement text is longer than current text and the node has `textAutoResize: 'NONE'` (fixed-size frame), warn the user that text may be silently clipped. Figma gives no error for this.

## Extract All Copy

### Current Page

Use `findAllWithCriteria` — it's a native C++ filter, much faster than `findAll` with a callback on large files.

```js
var textNodes = figma.currentPage.findAllWithCriteria({types: ['TEXT']});
var results = [];
for (var i = 0; i < textNodes.length; i++) {
  var n = textNodes[i];
  var breadcrumb = [];
  var p = n.parent;
  while (p && p.type !== 'PAGE') {
    breadcrumb.push(p.name);
    p = p.parent;
  }
  breadcrumb.reverse();
  results.push({
    id: n.id,
    name: n.name,
    path: breadcrumb.join(' > '),
    text: n.characters,
    font: n.fontName === figma.mixed ? 'MIXED' : n.fontName,
    fontSize: n.fontSize,
    hasMissingFont: n.hasMissingFont
  });
  if (i % 50 === 49) {
    await new Promise(function(r) { setTimeout(r, 0); });
  }
}
JSON.stringify(results, null, 2);
```

### All Pages

For cross-page copy audits, load all pages first. Without this, `findAllWithCriteria` only searches the active page:

```js
await figma.loadAllPagesAsync();
var results = [];
var pages = figma.root.children;
for (var i = 0; i < pages.length; i++) {
  await pages[i].loadAsync();
  var nodes = pages[i].findAllWithCriteria({types: ['TEXT']});
  for (var j = 0; j < nodes.length; j++) {
    var n = nodes[j];
    results.push({
      id: n.id, name: n.name, text: n.characters, page: pages[i].name
    });
    if (results.length % 50 === 0) {
      await new Promise(function(r) { setTimeout(r, 0); });
    }
  }
}
JSON.stringify(results, null, 2);
```

### From Selection

Useful for scoped reviews where the user selects specific frames:

```js
var sel = figma.currentPage.selection;
var results = [];
for (var i = 0; i < sel.length; i++) {
  var node = sel[i];
  if (node.type === 'TEXT') {
    results.push({id: node.id, name: node.name, text: node.characters});
  } else if (node.findAll) {
    var texts = node.findAllWithCriteria({types: ['TEXT']});
    for (var j = 0; j < texts.length; j++) {
      results.push({id: texts[j].id, name: texts[j].name, text: texts[j].characters});
    }
  }
}
JSON.stringify(results);
```

### Inspect Mixed-Font Formatting

When `fontName` returns `figma.mixed`, use `getStyledTextSegments` to see per-range formatting. This is essential before surgical edits to understand what formatting exists:

```js
var node = await figma.getNodeByIdAsync('1:2');
if (node.fontName === figma.mixed) {
  var segments = node.getStyledTextSegments(['fontName', 'fontSize', 'fills']);
  JSON.stringify(segments.map(function(s) {
    return {start: s.start, end: s.end, text: s.characters,
            font: s.fontName.family + ' ' + s.fontName.style, size: s.fontSize};
  }));
}
```

### Via REST API (no browser needed)

Walk the JSON tree from `GET /v1/files/:key` and filter for `type === 'TEXT'` nodes, collecting `id`, `name`, path, and `characters`.

## Preview Before Updating

**Never push text changes without user approval.** Before writing any text:

1. Read current text using the extraction patterns above.
2. Build a diff table showing node name, page, current text, and proposed text.
3. Present the table to the user and ask for confirmation.
4. Check for overflow risk: if proposed text is longer and the node has `textAutoResize: 'NONE'`, warn explicitly.
5. Only after approval, apply changes using the update patterns below.

Format:
```
| Node         | Page | Current              | Proposed             |
|--------------|------|----------------------|----------------------|
| Hero Heading | Home | "Welcome to our site"| "Ship faster with X" |
| CTA Button   | Home | "Learn More"         | "Get Started Free"   |
```

## Update Copy

### Font Loading Pattern

Every text mutation requires fonts to be loaded first. This pattern handles both single-font and mixed-font nodes. **Use it before any `characters` assignment** — fonts do NOT persist across eval calls.

```js
// For a single node:
if (node.fontName !== figma.mixed) {
  await figma.loadFontAsync(node.fontName);
} else {
  var fonts = node.getRangeAllFontNames(0, node.characters.length);
  for (var i = 0; i < fonts.length; i++) {
    await figma.loadFontAsync(fonts[i]);
  }
}
```

When processing multiple nodes, cache loaded fonts to avoid redundant loads:
```js
var loaded = {};
// For each node:
if (node.fontName !== figma.mixed) {
  var fk = node.fontName.family + '|' + node.fontName.style;
  if (!loaded[fk]) { await figma.loadFontAsync(node.fontName); loaded[fk] = true; }
} else {
  var fonts = node.getRangeAllFontNames(0, node.characters.length);
  for (var j = 0; j < fonts.length; j++) {
    var fk = fonts[j].family + '|' + fonts[j].style;
    if (!loaded[fk]) { await figma.loadFontAsync(fonts[j]); loaded[fk] = true; }
  }
}
```

### Find-and-Replace (Global)

Uses `split/join` instead of regex — avoids QuickJS `String.replace` only-first-match behavior:

```js
var textNodes = figma.currentPage.findAllWithCriteria({types: ['TEXT']});
var find = 'Sign Up';
var replace = 'Get Started';
var changed = [];
var loaded = {};
for (var i = 0; i < textNodes.length; i++) {
  var n = textNodes[i];
  if (n.characters.indexOf(find) === -1) continue;
  // Load fonts with caching (see Font Loading Pattern above)
  n.characters = n.characters.split(find).join(replace);
  changed.push({id: n.id, name: n.name, text: n.characters});
}
figma.commitUndo();  // bundle as single undo step
JSON.stringify({updated: changed.length, nodes: changed});
```

### Update by Node ID Map

Pass a map of `{nodeId: newText}` to batch-update specific nodes. Uses `getNodesByIdAsync` for a single batch fetch:

```js
var updates = {'1:23': 'Welcome back', '4:56': 'Continue'};
var keys = Object.keys(updates);
var nodes = await figma.getNodesByIdAsync(keys);
var results = [];
var loaded = {};
for (var i = 0; i < nodes.length; i++) {
  if (!nodes[i] || nodes[i].type !== 'TEXT') {
    results.push({id: keys[i], error: 'not found or not text'});
    continue;
  }
  var node = nodes[i];
  // Load fonts with caching (see Font Loading Pattern above)
  node.characters = updates[keys[i]];
  results.push({id: keys[i], text: node.characters});
}
figma.commitUndo();  // bundle as single undo step
JSON.stringify(results);
```

### Surgical Edits (Preserve Formatting)

Use `insertCharacters` and `deleteCharacters` to edit specific ranges without destroying per-character formatting on untouched segments. This is essential when a node has mixed formatting (e.g., "Click **here** to continue") — replacing the entire `characters` string would destroy the bold/italic/color styling on ranges you didn't intend to change.

```js
var node = await figma.getNodeByIdAsync('1:2');
// Load all fonts in the node
var fonts = node.getRangeAllFontNames(0, node.characters.length);
for (var i = 0; i < fonts.length; i++) { await figma.loadFontAsync(fonts[i]); }

// Delete characters 5-10, then insert new text at position 5
node.deleteCharacters(5, 10);
node.insertCharacters(5, 'replacement');
JSON.stringify({result: node.characters});
```

### Text Inside Component Instances

Overriding text in an instance creates an override — the instance stays linked to its component. Always load the **node's actual font**, not a hardcoded one:

```js
var inst = await figma.getNodeByIdAsync('1:2');
if (!inst) throw new Error('Instance 1:2 not found');
var label = inst.findOne(function(n) { return n.name === 'Label' && n.type === 'TEXT'; });
if (label) {
  // Load fonts (see Font Loading Pattern above) — use label's actual fontName
  label.characters = 'New Label Text';
}
```

## Designer-Agent Feedback Loop

An iterative comment-based workflow for reviewing copy with designers. The Plugin API has no comment support — use the REST API for all comment operations.

### The Cycle

1. AI reads all text and prepares suggestions.
2. AI posts review comments pinned to specific text nodes (see below).
3. Designer sees comments natively in Figma UI, replies or edits text directly.
4. AI polls for new replies — filter by `created_at` > last-known timestamp.
5. AI applies accepted changes or posts revised suggestions.
6. Repeat until designer resolves all comments in the Figma UI.

### Post a Comment Pinned to a Node

```bash
curl -s -X POST \
  -H "X-Figma-Token: $FIGMA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Suggestion: more action-oriented heading",
       "client_meta": {"node_id": "1:2", "node_offset": {"x": 0, "y": 0}}}' \
  "https://api.figma.com/v1/files/$FIGMA_FILE_KEY/comments"
```

### List Comments (for Polling)

```bash
curl -s -H "X-Figma-Token: $FIGMA_TOKEN" \
  "https://api.figma.com/v1/files/$FIGMA_FILE_KEY/comments?as_md=true"
```

Response includes `comments[]` with `id`, `message`, `client_meta.node_id`, `created_at`, `resolved_at`, `user`. Filter by `created_at` > your last-seen timestamp to find new replies.

### Reply to a Comment (Threading)

```bash
curl -s -X POST \
  -H "X-Figma-Token: $FIGMA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Updated — how about: Ship faster with confidence?",
       "comment_id": "PARENT_COMMENT_ID"}' \
  "https://api.figma.com/v1/files/$FIGMA_FILE_KEY/comments"
```

### Delete a Comment

```bash
curl -s -X DELETE \
  -H "X-Figma-Token: $FIGMA_TOKEN" \
  "https://api.figma.com/v1/files/$FIGMA_FILE_KEY/comments/COMMENT_ID"
```

> **`resolved_at` is read-only** — there is no API to resolve or unresolve comments. Only designers can resolve comments in the Figma UI.

> **Rate limit:** ~30 requests/minute. Batch comment posting accordingly.

## Track Changes

### Take a Snapshot

Store all current text as JSON on the document root. Uses `sharedPluginData` so any tool in the `copywriter` namespace can access it:

```js
var textNodes = figma.currentPage.findAllWithCriteria({types: ['TEXT']});
var snapshot = {};
for (var i = 0; i < textNodes.length; i++) {
  snapshot[textNodes[i].id] = {
    name: textNodes[i].name,
    text: textNodes[i].characters
  };
}
figma.root.setSharedPluginData('copywriter', 'snapshot', JSON.stringify(snapshot));
JSON.stringify({stored: Object.keys(snapshot).length, page: figma.currentPage.name});
```

### Diff Against Snapshot

Compare current TEXT nodes against the stored snapshot. Read snapshot from `figma.root.getSharedPluginData('copywriter', 'snapshot')`, build a map of current text by ID, then report three categories: **added** (in current, not in snapshot), **removed** (in snapshot, not in current), **modified** (text differs).

### Version Checkpoints

Save a named version after a review pass:
```js
await figma.saveVersionHistoryAsync('Copy review: 2025-01-15');
```
Retrieve history via REST: `python3 /tmp/figma_api.py "v1/files/<FILE_KEY>/versions"`

## Leave Feedback

Four methods, from lightest to most visible:

### 1. Plugin Data Tags
Invisible metadata — queryable via `findAllWithCriteria`. Good for tooling and status tracking:
```js
node.setSharedPluginData('copywriter', 'status', 'needs-review');

// Query all tagged nodes
var tagged = figma.currentPage.findAllWithCriteria({
  sharedPluginData: {namespace: 'copywriter', name: 'status'}
});
```

### 2. REST API Comments
See the [Designer-Agent Feedback Loop](#designer-agent-feedback-loop) section above for the full comment workflow including posting, threading, polling, and deletion.

### 3. Annotations
Structured review notes attached to nodes. The `annotations` array is readonly — clone with `.slice()`, push, and reassign:
```js
var annots = node.annotations ? node.annotations.slice() : [];
annots.push({ label: 'Copy Review', properties: { note: 'Tone too formal' } });
node.annotations = annots;
```

### 4. Visual Markers
Create a small auto-layout frame positioned next to the target node (at `target.x + target.width + 16`), with a yellow fill, 6px corner radius, and a 12px Inter Regular text label. Append to `target.parent`.

## Review Workflow

End-to-end checklist for a copy review pass:

1. **Snapshot** — store current copy state (`setSharedPluginData`)
2. **Preview** — build a diff table of proposed changes and get user approval before writing
3. **Edit** — apply approved text changes (find-and-replace or by node ID)
4. **Diff** — compare against snapshot to see what changed
5. **Tag** — mark nodes with status (`needs-review`, `approved`, `rejected`)
6. **Comment** — post feedback via REST comments for designer review
7. **Iterate** — poll for designer replies, apply accepted changes, revise rejected ones
8. **Checkpoint** — save a named version (`saveVersionHistoryAsync`)
9. **Clear snapshot** — `figma.root.setSharedPluginData('copywriter', 'snapshot', '')`
