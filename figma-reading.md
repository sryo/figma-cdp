# Reading & Planning Figma Designs

How to understand an existing design before modifying it.

## Pre-flight Workflow

Before making any design mutations, gather context. Use the **REST API** when you don't have a browser session, or the **Plugin API** when you're already connected.

### Via REST API (no browser needed)
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
4. **Render current state** (optional — useful for visual comparison):
   ```bash
   python3 /tmp/figma_api.py "v1/images/<FILE_KEY>?ids=<NODE_IDS>&format=png&scale=2"
   ```
   This returns URLs to rendered PNGs.
5. **Plan mutations** based on the read data, then execute via Plugin API.

### Via Plugin API (already connected)

Follow this systematic approach to **understand an existing design** before modifying it:

1. **Navigate to the target node**:
   ```js
   var node = await figma.getNodeByIdAsync('1:2');
   if (!node) throw new Error('Node 1:2 not found');
   figma.viewport.scrollAndZoomIntoView([node]);
   ```
2. **Inspect the node tree** — understand the hierarchy before touching anything:
   ```js
   var info = node.children.map(function(c) {
     return {id: c.id, name: c.name, type: c.type, w: c.width, h: c.height};
   });
   JSON.stringify(info, null, 2);
   ```
3. **Export a screenshot** for visual reference — this is your source of truth:
   ```js
   var bytes = await node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}});
   figma.base64Encode(bytes);
   ```
4. **Extract design values** from the node (typography, colors, spacing):
   ```js
   // Colors (fills are readonly — read only)
   JSON.stringify(node.fills);
   // Typography (on TextNode)
   JSON.stringify({font: node.fontName, size: node.fontSize, align: node.textAlignHorizontal});
   // Auto Layout spacing
   JSON.stringify({padding: [node.paddingTop, node.paddingRight, node.paddingBottom, node.paddingLeft], gap: node.itemSpacing});
   ```
5. **Plan changes** based on the read data, then execute mutations step by step.

## Asset Handling

When extracting images, icons, or SVGs from a design:
- **Export actual assets** from nodes — use `node.exportAsync({format: 'SVG'})` or `node.exportAsync({format: 'PNG'})` to get real asset data.
- **Do NOT create placeholder images** when the actual asset is available in the node. Always extract what's already there.
- **Do NOT import external icon packages** to replace icons that exist in the design. Extract the existing icon via `exportAsync` instead of adding a dependency.
- **Image fills** contain an `imageHash` — retrieve the image data with `figma.getImageByHash(hash).getBytesAsync()`.

## File Structure Best Practices

Designs that follow these conventions are easier to read and modify programmatically:
- **Name layers semantically** — `CardContainer`, `PriceLabel`, not `Group 5` or `Frame 12`.
- **Use variables** for spacing, color, radius, and typography instead of hardcoded values.
- **Use Auto Layout** to express responsive intent — it tells you how the design should reflow.
- **Use annotations and descriptions** on components for behavioral intent that isn't visible in the layout.
