# Copy Management for Figma

Extracting, updating, diffing, and reviewing text content in Figma designs.

## Extract All Copy

### Via Plugin API

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
  // Yield every 50 nodes to avoid freezing Figma
  if (i % 50 === 49) {
    await new Promise(function(r) { setTimeout(r, 0); });
  }
}
JSON.stringify(results, null, 2);
```

### Via REST API (no browser needed)

Walk the JSON tree from `GET /v1/files/:key` and filter for TEXT nodes:

```bash
python3 -c "
import json, sys
data = json.load(sys.stdin)
def walk(node, path=''):
    if node.get('type') == 'TEXT':
        print(json.dumps({'id': node['id'], 'name': node['name'], 'path': path, 'text': node['characters']}))
    for child in node.get('children', []):
        walk(child, path + ' > ' + node['name'] if path else node['name'])
for page in data['document']['children']:
    walk(page)
" < /tmp/figma_file.json
```

## Update Copy

### Font Loading Helper

Every text mutation requires fonts to be loaded first. For nodes with mixed fonts, use `getRangeAllFontNames` to get all unique fonts in a single native call:

```js
var node = await figma.getNodeByIdAsync('1:2');
if (!node || node.type !== 'TEXT') throw new Error('Node not found or not text');
// Single font
if (node.fontName !== figma.mixed) {
  await figma.loadFontAsync(node.fontName);
} else {
  // Mixed fonts — getRangeAllFontNames returns deduplicated FontName[] in one call
  var fonts = node.getRangeAllFontNames(0, node.characters.length);
  for (var i = 0; i < fonts.length; i++) {
    await figma.loadFontAsync(fonts[i]);
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
  // Load fonts (see "Font Loading Helper" above) — cache across nodes
  if (n.fontName !== figma.mixed) {
    var key = n.fontName.family + '|' + n.fontName.style;
    if (!loaded[key]) { await figma.loadFontAsync(n.fontName); loaded[key] = true; }
  } else {
    var fonts = n.getRangeAllFontNames(0, n.characters.length);
    for (var j = 0; j < fonts.length; j++) {
      var key = fonts[j].family + '|' + fonts[j].style;
      if (!loaded[key]) { await figma.loadFontAsync(fonts[j]); loaded[key] = true; }
    }
  }
  n.characters = n.characters.split(find).join(replace);
  changed.push({id: n.id, name: n.name, text: n.characters});
}
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
  // Load fonts (see "Font Loading Helper" above) — cache across nodes
  if (node.fontName !== figma.mixed) {
    var key = node.fontName.family + '|' + node.fontName.style;
    if (!loaded[key]) { await figma.loadFontAsync(node.fontName); loaded[key] = true; }
  } else {
    var fonts = node.getRangeAllFontNames(0, node.characters.length);
    for (var j = 0; j < fonts.length; j++) {
      var key = fonts[j].family + '|' + fonts[j].style;
      if (!loaded[key]) { await figma.loadFontAsync(fonts[j]); loaded[key] = true; }
    }
  }
  node.characters = updates[keys[i]];
  results.push({id: keys[i], text: node.characters});
}
JSON.stringify(results);
```

### Text Inside Component Instances

Overriding text in an instance creates an override — the instance stays linked to its component:

```js
var inst = await figma.getNodeByIdAsync('1:2');
if (!inst) throw new Error('Instance 1:2 not found');
var label = inst.findOne(function(n) { return n.name === 'Label' && n.type === 'TEXT'; });
if (label) {
  // Load the node's actual font, not a hardcoded one
  if (label.fontName !== figma.mixed) {
    await figma.loadFontAsync(label.fontName);
  } else {
    var fonts = label.getRangeAllFontNames(0, label.characters.length);
    for (var i = 0; i < fonts.length; i++) { await figma.loadFontAsync(fonts[i]); }
  }
  label.characters = 'New Label Text';
}
```

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

Compare current text nodes against the stored snapshot — reports added, removed, and modified nodes:

```js
var raw = figma.root.getSharedPluginData('copywriter', 'snapshot');
if (!raw) throw new Error('No snapshot found — take one first');
var prev = JSON.parse(raw);
var textNodes = figma.currentPage.findAllWithCriteria({types: ['TEXT']});
var current = {};
for (var i = 0; i < textNodes.length; i++) {
  current[textNodes[i].id] = textNodes[i].characters;
}
var added = [], removed = [], modified = [];
var curKeys = Object.keys(current);
for (var i = 0; i < curKeys.length; i++) {
  if (!prev[curKeys[i]]) { added.push({id: curKeys[i], text: current[curKeys[i]]}); }
  else if (prev[curKeys[i]].text !== current[curKeys[i]]) {
    modified.push({id: curKeys[i], was: prev[curKeys[i]].text, now: current[curKeys[i]]});
  }
}
var prevKeys = Object.keys(prev);
for (var i = 0; i < prevKeys.length; i++) {
  if (!current[prevKeys[i]]) { removed.push({id: prevKeys[i], was: prev[prevKeys[i]].text}); }
}
JSON.stringify({added: added, removed: removed, modified: modified}, null, 2);
```

### Version Checkpoints

Save a named version after a review pass. Retrieve history via REST:

```js
// Plugin API — save a checkpoint
await figma.saveVersionHistoryAsync('Copy review: 2025-01-15');
```

```bash
# REST API — list version history
python3 /tmp/figma_api.py "v1/files/<FILE_KEY>/versions"
```

## Leave Feedback

Four methods, from lightest to most visible:

### 1. Plugin Data Tags

Invisible metadata — queryable via `findAllWithCriteria`. Good for tooling and status tracking:

```js
// Tag a node
var node = await figma.getNodeByIdAsync('1:2');
node.setSharedPluginData('copywriter', 'status', 'needs-review');

// Query all tagged nodes
var tagged = figma.currentPage.findAllWithCriteria({
  sharedPluginData: {namespace: 'copywriter', name: 'status'}
});
var results = tagged.map(function(n) {
  return {id: n.id, name: n.name, status: n.getSharedPluginData('copywriter', 'status')};
});
JSON.stringify(results);
```

### 2. REST API Comments

Shows in Figma's sidebar. Pinned to a specific node:

```bash
curl -X POST "https://api.figma.com/v1/files/<FILE_KEY>/comments" \
  -H "X-Figma-Token: $FIGMA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "This copy needs legal review", "client_meta": {"node_id": "1:2"}}'
```

### 3. Annotations

Structured review notes attached to nodes. The `annotations` array is readonly — clone with `.slice()`, push, and reassign:

```js
var node = await figma.getNodeByIdAsync('1:2');
var annots = node.annotations ? node.annotations.slice() : [];
annots.push({
  label: 'Copy Review',
  properties: {
    note: 'Tone too formal — try casual voice'
  }
});
node.annotations = annots;
```

### 4. Visual Markers

Create a small colored sticky-note frame near the target node — visible to designers in-canvas:

```js
var target = await figma.getNodeByIdAsync('1:2');
if (!target) throw new Error('Node 1:2 not found');
var marker = figma.createFrame();
marker.name = 'Copy Note';
marker.fills = [{type: 'SOLID', color: {r: 1, g: 0.8, b: 0.2}}];
marker.cornerRadius = 6;
marker.layoutMode = 'HORIZONTAL';
marker.primaryAxisSizingMode = 'AUTO';
marker.counterAxisSizingMode = 'AUTO';
marker.paddingLeft = marker.paddingRight = 8;
marker.paddingTop = marker.paddingBottom = 4;
marker.x = target.absoluteTransform[0][2] + target.width + 16;
marker.y = target.absoluteTransform[1][2];

await figma.loadFontAsync({family: 'Inter', style: 'Regular'});
var label = figma.createText();
label.characters = 'Needs shorter CTA';
label.fontSize = 12;
label.fills = [{type: 'SOLID', color: {r: 0.2, g: 0.2, b: 0.2}}];
marker.appendChild(label);

if (target.parent) {
  target.parent.appendChild(marker);
}
```

## Review Workflow

End-to-end checklist for a copy review pass:

1. **Snapshot** — store current copy state (`setSharedPluginData`)
2. **Edit** — make text changes (find-and-replace or by node ID)
3. **Diff** — compare against snapshot to see what changed
4. **Tag** — mark nodes with status (`needs-review`, `approved`, `rejected`)
5. **Comment** — leave detailed feedback via REST comments or annotations
6. **Checkpoint** — save a named version (`saveVersionHistoryAsync`)
7. **Clear snapshot** — remove stale data when the review cycle is complete:
   ```js
   figma.root.setSharedPluginData('copywriter', 'snapshot', '');
   ```
