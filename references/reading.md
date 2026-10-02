# Reading and understanding Figma designs

How to understand an existing design before modifying it. Always do this before making changes: understanding the current state prevents accidental destruction.

## Coordinator reconnaissance

One eval returns the page list and a flat text tree, plus the reuse inventory (below):

```bash
python3 <skill-dir>/figma_run.py --lib --file <url> -e 'return [await __fx.recon({nodeId: "1:23"}), (await __fx.inventory()).text]'
```

`__fx.recon({nodeId, depth, maxChars})` walks the current page 3 levels deep, or a node at full depth, and stops at 8000 chars with `truncated: true`; a `+N` suffix marks children past `depth`. Example `tree`:
```
PAGE "Screens" [0:1]
  FRAME "Screens/Login" [1:23] 1440x900 auto:V
    INSTANCE "Avatar" [1:24] -> Avatar 80x80
    TEXT "Welcome back" [1:25] 28px
    INSTANCE "Button" [1:29] -> Button {Variant=Primary} 120x40 auto:H
    FRAME "Footer" [1:30] 1440x64 auto:H +3
```

Use the tree for structure, names and ids; read exact properties (fills, padding, sizing, fonts) with Full node inspection below only for the nodes you will change. A node on another page: `await figma.loadAllPagesAsync()` first, since `getNodeByIdAsync` returns `null` for nodes on unloaded pages.

## Worker deep read

Workers run these before modifying anything. These give the full picture that REST API misses (fonts, overrides, auto layout state, component properties).

### Full node inspection

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

## Component inventory (run before building anything new)

One call lists what the file already has to reuse: local component sets (variant axes collapsed, no per-variant ids) and components with their property names, library components the file already uses, local paint / text / effect styles, variables by collection with default-mode values (aliases resolved), and raw frames repeated on the current page (de facto components).

Run `__fx.inventory()` with `figma_run.py --lib`. Its `text` holds one line each:
```
SET Button [1:2] Variant=Primary|Secondary; State=Default|Disabled props: Label:TEXT
COMP Input [1:9] props: Label:TEXT, Placeholder:TEXT
LIB Avatar [3:4] key=0f3c... uses=12 Size=sm|md
PAINT Brand/Primary [S:ab12,] #2563eb
TEXTSTYLE Body [S:cd34,] Inter Regular 16/24
EFFECT Shadow/md [S:ef56,] DROP_SHADOW 0,4 blur 12 #0000001a
VARS Tokens [VariableCollectionId:1:3] modes: Light|Dark
  color/primary [VariableID:1:5] #2563eb =blue/600
PATTERN x3 FRAME:H[TEXT,FRAME:V[TEXT,TEXT]] ~320x64 ids: 1:20, 1:31, 1:42
```
`{match: 'button|input'}` keeps matching lines (a matching variable keeps its collection header); output stops at `maxChars` (8000) with `truncated: true`. The scan is cached in `window.__batchState.fxInventory`, so later calls in the tab, workers' included, filter it instead of rescanning; `{fresh: true}` rescans after creating components, styles or variables.

If nothing fits, create. Otherwise instantiate the match with `__fx.instance(id, props)` (a LIB row by its key) and bind colors with `__fx.bindFill`. See `references/api-components.md` for property formats.

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

REST API provides read access to any file you have permission to view, without a browser session. See `references/rest-api.md` for endpoints, auth, and the `figma_api.py` helper.

Workflow:
1. **Extract the file key** from the Figma URL.
2. **Read the file tree**: `python3 /tmp/figma_api.py "v1/files/<FILE_KEY>?depth=2"` — returns pages, top-level frames, and their IDs.
3. **Inspect target nodes**: `python3 /tmp/figma_api.py "v1/files/<FILE_KEY>/nodes?ids=<NODE_IDS>"`.
4. **Render current state** (useful for visual comparison): `python3 /tmp/figma_api.py "v1/images/<FILE_KEY>?ids=<NODE_IDS>&format=png&scale=2"` — returns URLs to rendered PNGs.
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

## REST API

The REST API reference (auth, endpoints, `figma_api.py` helper, comment operations, rate limits) lives in `references/rest-api.md`.
