# Reading and understanding Figma designs

How to understand an existing design before modifying it. Always do this before making changes: understanding the current state prevents accidental destruction.

## Coordinator reconnaissance

The coordinator runs this single eval to get page structure before decomposing work. Uses Plugin API (not REST) for accurate, up-to-date data.

Write `/tmp/figma_eval.js`:
```js
(async function() {
  var page = figma.currentPage;
  return {
    page: page.name,
    frames: page.children.map(function(c) {
      return {id: c.id, name: c.name, type: c.type,
              w: c.width, h: c.height,
              childCount: c.children ? c.children.length: 0};
    })
  };
})()
```
Run: `python3 /tmp/figma_run.py /tmp/figma_eval.js`

If a specific node ID was provided, also inspect it: write `/tmp/figma_eval.js`:
```js
(async function() {
  var node = await figma.getNodeByIdAsync('NODE_ID');
  if (!node) return {error: 'Node not found'};
  var info = {
    id: node.id, name: node.name, type: node.type,
    w: node.width, h: node.height
  };
  if (node.layoutMode) info.layout = node.layoutMode;
  if (node.children) {
    info.children = node.children.map(function(c) {
      return {id: c.id, name: c.name, type: c.type,
              w: c.width, h: c.height};
    });
  }
  return info;
})()
```
Run: `python3 /tmp/figma_run.py /tmp/figma_eval.js`

## Worker deep read

Workers run these before modifying anything. These give the full picture that REST API misses (fonts, overrides, auto layout state, component properties).

### Full node inspection

Write `/tmp/figma_eval.js`:
```js
(async function() {
  var node = await figma.getNodeByIdAsync('TARGET_ID');
  if (!node) return {error: 'not found'};
  var info = {
    id: node.id, name: node.name, type: node.type,
    w: node.width, h: node.height
  };
  // Layout
  if (node.layoutMode) {
    info.layout = {
      mode: node.layoutMode,
      primarySizing: node.primaryAxisSizingMode,
      counterSizing: node.counterAxisSizingMode,
      padding: [node.paddingTop, node.paddingRight, node.paddingBottom, node.paddingLeft],
      gap: node.itemSpacing,
      primaryAlign: node.primaryAxisAlignItems,
      counterAlign: node.counterAxisAlignItems
    };
  }
  // Fills
  if (node.fills && node.fills !== figma.mixed) info.fills = node.fills;
  // Typography (TextNode)
  if (node.type === 'TEXT') {
    info.text = node.characters;
    info.font = node.fontName !== figma.mixed ? node.fontName: 'MIXED';
    info.fontSize = node.fontSize;
    info.autoResize = node.textAutoResize;
  }
  // Children
  if (node.children) {
    info.children = node.children.map(function(c) {
      var ci = {id: c.id, name: c.name, type: c.type, w: c.width, h: c.height};
      if (c.layoutSizingHorizontal) ci.hSizing = c.layoutSizingHorizontal;
      if (c.layoutSizingVertical) ci.vSizing = c.layoutSizingVertical;
      return ci;
    });
  }
  // Component info
  if (node.type === 'INSTANCE') {
    var main = await node.getMainComponentAsync();
    info.mainComponent = main ? {id: main.id, name: main.name}: null;
  }
  return info;
})()
```
Run: `python3 /tmp/figma_run.py /tmp/figma_eval.js`

### Flat text tree (preferred recon shape)

For understanding the structure of a page or subtree, this is faster to read than nested JSON and uses fewer tokens.

Write `/tmp/figma_eval.js`:
```js
(async function() {
  var ROOT_ID = null;       // null = currentPage; set a node ID to scope
  var MAX_DEPTH = 10;       // hard depth cap
  var MAX_CHARS = 40000;    // hard output cap

  function summarize(n) {
    var parts = [];
    if (n.type === 'TEXT') {
      var c = n.characters !== figma.mixed ? n.characters : '<mixed>';
      if (c) {
        var preview = c.length > 50 ? c.substring(0, 47) + '...' : c;
        parts.push('"' + preview.replace(/"/g, '\\"').replace(/\n/g, ' ') + '"');
      }
      if (n.fontSize !== figma.mixed) parts.push('fontSize=' + n.fontSize);
    }
    if (n.type === 'INSTANCE' && n.mainComponent) {
      parts.push('→ ' + n.mainComponent.name);
    }
    if ((n.type === 'FRAME' || n.type === 'COMPONENT' || n.type === 'COMPONENT_SET' || n.type === 'SECTION')
        && n.width && n.height) {
      parts.push(Math.round(n.width) + '×' + Math.round(n.height));
    }
    if (n.layoutMode && n.layoutMode !== 'NONE') parts.push('layout=' + n.layoutMode);
    if (n.locked) parts.push('[locked]');
    if (n.visible === false) parts.push('[hidden]');
    return parts.length ? ' ' + parts.join(' ') : '';
  }

  var lines = [];
  function walk(n, depth) {
    if (depth > MAX_DEPTH) return;
    if (n.type === 'SLICE') return;
    var name = (n.name || '').replace(/"/g, '\\"');
    if (name.length > 80) name = name.substring(0, 77) + '...';
    var line = '  '.repeat(depth) + n.type;
    if (name) line += ' "' + name + '"';
    line += ' [' + n.id + ']' + summarize(n);
    lines.push(line);
    if (n.children) {
      for (var i = 0; i < n.children.length; i++) walk(n.children[i], depth + 1);
    }
  }

  var root = ROOT_ID ? await figma.getNodeByIdAsync(ROOT_ID) : figma.currentPage;
  if (!root) return {error: 'Root node ' + ROOT_ID + ' not found'};
  walk(root, 0);

  var out = lines.join('\n');
  if (out.length > MAX_CHARS) {
    return {
      error: 'Output exceeds ' + MAX_CHARS + ' chars (' + out.length + '). ' +
             'Lower MAX_DEPTH or set ROOT_ID to focus on a subtree.',
      lineCount: lines.length,
      preview: out.substring(0, MAX_CHARS)
    };
  }
  return {tree: out, lineCount: lines.length};
})()
```
Run: `python3 /tmp/figma_run.py /tmp/figma_eval.js`

Example output:
```
PAGE "Screens" [0:1]
  FRAME "Screens/Login" [1:23] 1440×900 layout=VERTICAL
    INSTANCE "Avatar/Default" [1:24] → Avatar 80×80
    TEXT "Welcome back" [1:25] fontSize=28
    TEXT "Sign in to your account" [1:26] fontSize=16
    INSTANCE "Input/Email" [1:27] → Input
    INSTANCE "Button/Primary" [1:29] → Button
```

When to use this vs Full node inspection above:
- **Text tree (this):** "What's on this page?" / "What's inside frame 1:23?" — structure, hierarchy, names, IDs.
- **Full node inspection (JSON):** "What are the exact properties of node 1:23?" — fills, layout details, font, padding, sizing modes.

Reach for the text tree first during recon. Drop into JSON inspection only when you need to read or modify specific properties.

Cross-page note: if `ROOT_ID` is on a page other than `currentPage`, call `await figma.loadAllPagesAsync()` once before this script. `getNodeByIdAsync` returns `null` for nodes on unloaded pages.

## Pre-flight workflow

### Via Plugin API (already connected)

Follow this systematic approach:

1. **Navigate to the target node**:
   ```js
   var node = await figma.getNodeByIdAsync('1:2');
   if (!node) throw new Error('Node 1:2 not found');
   figma.viewport.scrollAndZoomIntoView([node]);
   ```
2. **Inspect the node tree**: understand the hierarchy before touching anything:
   ```js
   var info = node.children.map(function(c) {
     return {id: c.id, name: c.name, type: c.type, w: c.width, h: c.height};
   });
   JSON.stringify(info, null, 2);
   ```
3. **Export a screenshot** for visual reference: this is your source of truth:
   ```js
   var bytes = await node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}});
   figma.base64Encode(bytes);
   ```
4. **Extract design values** from the node (typography, colors, spacing):
   ```js
   // Colors (fills are readonly: read only)
   JSON.stringify(node.fills);
   // Typography (on TextNode)
   JSON.stringify({font: node.fontName, size: node.fontSize, align: node.textAlignHorizontal});
   // Auto Layout spacing
   JSON.stringify({padding: [node.paddingTop, node.paddingRight, node.paddingBottom, node.paddingLeft], gap: node.itemSpacing});
   ```
5. **Plan changes** based on the read data, then execute mutations step by step.

### Via REST API (supplementary)

REST API provides read access to any file you have permission to view, without a browser session. See "REST API Reference" at the bottom of this file for endpoints and the helper script.

1. **Extract the file key** from the Figma URL.
2. **Read the file tree**:
   ```bash
   python3 /tmp/figma_api.py "v1/files/<FILE_KEY>?depth=2"
   ```
   This returns pages, top-level frames, and their IDs.
3. **Inspect target nodes** (use comma-separated node IDs):
   ```bash
   python3 /tmp/figma_api.py "v1/files/<FILE_KEY>/nodes?ids=<NODE_IDS>"
   ```
4. **Render current state** (useful for visual comparison):
   ```bash
   python3 /tmp/figma_api.py "v1/images/<FILE_KEY>?ids=<NODE_IDS>&format=png&scale=2"
   ```
   This returns URLs to rendered PNGs.
5. **Plan mutations** based on the read data, then execute via Plugin API.

## Asset handling

When extracting images, icons, or SVGs from a design:
- **Export actual assets** from nodes: use `node.exportAsync({format: 'SVG'})` or `node.exportAsync({format: 'PNG'})` to get real asset data.
- **Do NOT create placeholder images** when the actual asset is available in the node. Always extract what's already there.
- **Do NOT import external icon packages** to replace icons that exist in the design. Extract the existing icon via `exportAsync` instead of adding a dependency.
- **Image fills** contain an `imageHash`: retrieve the image data with `figma.getImageByHash(hash).getBytesAsync()`.

## Reading variable bindings

```js
// Check if a node has variable bindings
var bindings = node.boundVariables;
if (bindings) {
  // bindings is an object like: {fills: [{type:'VARIABLE_ALIAS', id:'VariableID:123'}]}
  var keys = Object.keys(bindings);
  for (var i = 0; i < keys.length; i++) {
    var field = keys[i];
    var alias = bindings[field];
    // Resolve the variable
    var variable = await figma.variables.getVariableByIdAsync(alias.id || alias[0].id);
    if (variable) {
      result.push({field: field, varName: variable.name, type: variable.resolvedType});
    }
  }
}
```

## Reading instance state

```js
var inst = await figma.getNodeByIdAsync('INSTANCE_ID');
if (inst.type !== 'INSTANCE') return {error: 'Not an instance'};

// Get main component
var main = await inst.getMainComponentAsync();
var info = {
  instanceId: inst.id,
  mainComponent: main ? {id: main.id, name: main.name, key: main.key}: null,
  scaleFactor: inst.scaleFactor,
  overrides: inst.overrides,  // [{id, overriddenFields}]: direct overrides only
  properties: inst.componentProperties  // current property values
};

// Check exposed instances (nested instances visible at this level)
info.exposed = inst.exposedInstances.map(function(e) {
  return {id: e.id, name: e.name};
});

return info;
```

## Reading prototype reactions

```js
var node = await figma.getNodeByIdAsync('NODE_ID');
var reactions = node.reactions; // ReadonlyArray<Reaction>
var info = reactions.map(function(r) {
  var entry = {trigger: r.trigger};
  if (r.actions) {
    entry.actions = r.actions.map(function(a) {
      return {type: a.type, destinationId: a.destinationId, navigation: a.navigation};
    });
  }
  return entry;
});
return info;
// NOTE: With dynamic-page access, reactions is readonly: use setReactionsAsync() to modify
```

## REST API reference

Read-only operations without a browser session. Supplementary to the Plugin API.

### Auth setup
1. Generate a **personal access token** at `https://www.figma.com/developers/api#access-tokens`.
2. Store it:
   ```bash
   export FIGMA_TOKEN="figd_..."
   ```

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/files/:key` | Full file tree (pages, frames, nodes) |
| `GET /v1/files/:key/nodes?ids=X,Y` | Specific node subtrees |
| `GET /v1/images/:key?ids=X,Y&format=png` | Render nodes as images |
| `GET /v1/files/:key/components` | Published components |
| `GET /v1/files/:key/styles` | Published styles |
| `GET /v1/files/:key/versions` | Version history |
| `POST /v1/files/:key/comments` | Add a comment |
| `POST|PUT /v1/dev_resources` | Create / update dev resource |

> **Variables REST endpoint** requires Figma Enterprise: not available on free/pro plans. Use the Plugin API `figma.variables.*` instead.

### Helper script

Write `/tmp/figma_api.py` (symmetric with `figma_run.py`: pre-allowed; no permission prompts):

```python
#!/usr/bin/env python3
"""Minimal Figma REST API helper. Usage: python3 /tmp/figma_api.py <endpoint> [--raw]"""
import sys, os, json, urllib.request, urllib.error

TOKEN = os.environ.get("FIGMA_TOKEN", "")
if not TOKEN:
    print("ERROR: Set FIGMA_TOKEN env var", file=sys.stderr); sys.exit(1)

args = [a for a in sys.argv[1:] if a != "--raw"]
raw = "--raw" in sys.argv
if not args:
    print("Usage: python3 /tmp/figma_api.py <endpoint> [--raw]", file=sys.stderr); sys.exit(1)

url = f"https://api.figma.com/{args[0].lstrip('/')}"
req = urllib.request.Request(url, headers={"X-Figma-Token": TOKEN})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr); sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

print(json.dumps(data) if raw else json.dumps(data, indent=2))
```

Example usage:
```bash
# Read file structure
python3 /tmp/figma_api.py "v1/files/ABC123xyz"

# Inspect specific nodes
python3 /tmp/figma_api.py "v1/files/ABC123xyz/nodes?ids=0:1,1:2"

# Render a node as PNG
python3 /tmp/figma_api.py "v1/images/ABC123xyz?ids=1:2&format=png&scale=2"
```

### Rate limits and staleness
- **30 requests/minute**: batch node IDs into single calls where possible.
- REST reads may **lag a few seconds** behind Plugin API writes. After mutations, use Plugin API `exportAsync` for immediate verification.
