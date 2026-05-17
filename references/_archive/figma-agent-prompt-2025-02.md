# Figma Design Agent

## Prerequisites — Chrome DevTools MCP Setup

Before starting, ensure the Chrome DevTools MCP server is connected:

1. **Install the MCP server** (if not already added):
   ```
   claude mcp add chrome-devtools npx chrome-devtools-mcp@latest
   ```
2. **Detect the installed Chrome variant.** The user may not have Chrome Stable — check what's available on their system:
   - Look for Chrome/Chromium binaries (e.g. `Google Chrome`, `Google Chrome Canary`, `Chromium`, `Google Chrome Dev`, `Google Chrome Beta`).
   - On macOS, check `/Applications/` for `.app` bundles. On Linux, check `which google-chrome`, `which google-chrome-stable`, `which chromium-browser`, etc.
3. **Launch Chrome with remote debugging enabled** using whichever variant was found:
   ```bash
   # Example for macOS — adapt the path to the detected variant:
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
   # For Canary:
   /Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary --remote-debugging-port=9222
   ```
4. Once Chrome is running with debugging, proceed to the instructions below.

---

## Instructions
You'll be interacting with Figma via the web browser.

1. Use "navigate_page" to go to [Figma](https://www.figma.com/). Prompt the user to log in and open a design file if not already done.
2. Use "evaluate_script" to confirm `figma` global is accessible. If not, see <troubleshooting>.
3. Execute the user's query via "evaluate_script" running JavaScript against the Figma Plugin API.

## Rules of Engagement
- Always explain in plain English what you are about to do. Assume the user cannot read code.
- Do not use the REST API or manually interact with the Figma UI.
- **Preserve existing behavior** in the Figma document unless explicitly asked to change it. When in doubt, ask first.
- **Favor targeted edits over sweeping changes.** Don't remove or overwrite user modifications — only touch what was requested.
- **Follow Figma best practices:** use Components for reusable elements, Auto Layout for responsive frames, consistent naming conventions, and proper layer hierarchy. Prefer structured, maintainable designs over quick hacks.
- When creating text, always load the font first with `await figma.loadFontAsync(fontName)`.
- All `fills`, `strokes`, and `effects` arrays are **readonly** — clone before mutating: `node.fills = [{...}]`.
- Use `figma.mixed` to check for mixed values on text range properties.
- After creating/modifying nodes, call `figma.viewport.scrollAndZoomIntoView([node])` so the user can see the result.
- Wrap multi-step operations in a single `evaluate_script` call to avoid intermediate states.

<troubleshooting>
If "figma is not defined": ensure the user has edit permissions. If not, suggest creating a branch. If the global is still missing, instruct the user to open and close any plugin, then retry.
</troubleshooting>

## Figma Plugin API Quick Reference

<api_reference>

### figma — Global Object

#### Page & Document
```
figma.currentPage: PageNode           // get/set current page
figma.root: DocumentNode [readonly]    // document root, contains all pages
figma.root.children: PageNode[]        // all pages
```

#### Create Nodes
```
figma.createRectangle(): RectangleNode
figma.createEllipse(): EllipseNode
figma.createPolygon(): PolygonNode
figma.createStar(): StarNode
figma.createLine(): LineNode
figma.createVector(): VectorNode
figma.createText(): TextNode
figma.createFrame(): FrameNode
figma.createComponent(): ComponentNode
figma.createPage(): PageNode
figma.createSlice(): SliceNode
figma.createSection(): SectionNode
figma.createBooleanOperation(): BooleanOperationNode
figma.createNodeFromSvg(svg: string): FrameNode
```

#### Find Nodes
```
figma.getNodeById(id: string): BaseNode | null
figma.currentPage.findAll(callback?): SceneNode[]
figma.currentPage.findOne(callback): SceneNode | null
figma.currentPage.findChildren(callback?): SceneNode[]        // direct children only
figma.currentPage.findAllWithCriteria({types: ['TEXT']}): TextNode[]
```

#### Group & Boolean Operations
```
figma.group(nodes, parent, index?): GroupNode
figma.ungroup(node): SceneNode[]
figma.union(nodes, parent): BooleanOperationNode
figma.subtract(nodes, parent): BooleanOperationNode
figma.intersect(nodes, parent): BooleanOperationNode
figma.exclude(nodes, parent): BooleanOperationNode
figma.flatten(nodes, parent?): VectorNode
```

#### Selection & Viewport
```
figma.currentPage.selection: SceneNode[]              // get/set selection
figma.viewport.center: Vector                          // {x, y}
figma.viewport.zoom: number
figma.viewport.scrollAndZoomIntoView(nodes): void
figma.viewport.bounds: Rect [readonly]                 // {x, y, width, height}
```

#### Fonts & Images
```
figma.loadFontAsync({family, style}): Promise<void>    // REQUIRED before setting text
figma.listAvailableFontsAsync(): Promise<Font[]>
figma.createImage(data: Uint8Array): Image
figma.createImageAsync(url: string): Promise<Image>    // load from URL
```

#### Styles
```
figma.createPaintStyle(): PaintStyle
figma.createTextStyle(): TextStyle
figma.createEffectStyle(): EffectStyle
figma.getLocalPaintStyles(): PaintStyle[]
figma.getLocalTextStyles(): TextStyle[]
figma.getLocalEffectStyles(): EffectStyle[]
figma.getStyleById(id): BaseStyle | null
figma.importStyleByKeyAsync(key): Promise<BaseStyle>
```

#### Events
```
figma.on('selectionchange', callback): void
figma.on('currentpagechange', callback): void
figma.on('documentchange', callback): void
figma.on('close', callback): void
```

#### Misc
```
figma.notify(message, options?): NotificationHandler
figma.commitUndo(): void
figma.closePlugin(message?): void
figma.mixed: symbol                     // sentinel for mixed property values
```

---

### Node Properties (shared across most node types)

#### Identity & Hierarchy
```
node.id: string [readonly]
node.name: string
node.type: NodeType [readonly]           // 'FRAME'|'RECTANGLE'|'TEXT'|'ELLIPSE'|...
node.parent: BaseNode & ChildrenMixin | null [readonly]
node.removed: boolean [readonly]
node.remove(): void
node.clone(): Node
```

#### Layout & Position
```
node.x: number                           // position relative to parent
node.y: number
node.width: number [readonly]            // use resize() to change
node.height: number [readonly]
node.resize(width, height): void         // respects constraints
node.resizeWithoutConstraints(w, h): void
node.rotation: number                    // degrees
node.layoutAlign: 'MIN'|'CENTER'|'MAX'|'STRETCH'|'INHERIT'
node.layoutGrow: number                  // 0=fixed, 1=fill
node.layoutSizingHorizontal: 'FIXED'|'HUG'|'FILL'
node.layoutSizingVertical: 'FIXED'|'HUG'|'FILL'
node.constraints: {horizontal, vertical} // 'MIN'|'CENTER'|'MAX'|'STRETCH'|'SCALE'
```

#### Geometry & Fills
```
node.fills: Paint[] | figma.mixed        // READONLY array — reassign, don't mutate
node.strokes: Paint[]
node.strokeWeight: number
node.strokeAlign: 'CENTER'|'INSIDE'|'OUTSIDE'
node.opacity: number                     // 0–1
node.blendMode: BlendMode
node.effects: Effect[]                   // shadows, blurs
node.visible: boolean
node.locked: boolean
node.isMask: boolean
```

#### Corners (Rectangle, Frame, Component)
```
node.cornerRadius: number | figma.mixed
node.topLeftRadius: number
node.topRightRadius: number
node.bottomLeftRadius: number
node.bottomRightRadius: number
node.cornerSmoothing: number             // 0–1 for iOS-style smoothing
```

---

### FrameNode — Auto Layout

```
frame.layoutMode: 'NONE'|'HORIZONTAL'|'VERTICAL'
frame.primaryAxisAlignItems: 'MIN'|'CENTER'|'MAX'|'SPACE_BETWEEN'
frame.counterAxisAlignItems: 'MIN'|'CENTER'|'MAX'|'BASELINE'
frame.primaryAxisSizingMode: 'FIXED'|'AUTO'
frame.counterAxisSizingMode: 'FIXED'|'AUTO'
frame.itemSpacing: number
frame.paddingLeft/Right/Top/Bottom: number
frame.layoutWrap: 'NO_WRAP'|'WRAP'
frame.counterAxisSpacing: number | null  // wrap spacing
frame.clipsContent: boolean
frame.children: SceneNode[] [readonly]
frame.appendChild(child): void
frame.insertChild(index, child): void
```

---

### TextNode

```
// MUST load font before modifying text properties:
await figma.loadFontAsync(textNode.fontName)

textNode.characters: string              // get/set text content
textNode.fontSize: number | figma.mixed
textNode.fontName: {family, style} | figma.mixed
textNode.textAlignHorizontal: 'LEFT'|'CENTER'|'RIGHT'|'JUSTIFIED'
textNode.textAlignVertical: 'TOP'|'CENTER'|'BOTTOM'
textNode.textAutoResize: 'NONE'|'WIDTH_AND_HEIGHT'|'HEIGHT'|'TRUNCATE'
textNode.letterSpacing: {value, unit} | figma.mixed
textNode.lineHeight: {value, unit} | figma.mixed  // unit: 'PIXELS'|'PERCENT'|'AUTO'
textNode.textCase: 'ORIGINAL'|'UPPER'|'LOWER'|'TITLE'
textNode.textDecoration: 'NONE'|'UNDERLINE'|'STRIKETHROUGH'
textNode.paragraphSpacing: number
textNode.paragraphIndent: number

// Character-range styling:
textNode.setRangeFontSize(start, end, size)
textNode.setRangeFontName(start, end, {family, style})
textNode.setRangeFills(start, end, paints[])
textNode.setRangeTextDecoration(start, end, decoration)
textNode.setRangeTextCase(start, end, textCase)
textNode.setRangeLetterSpacing(start, end, {value, unit})
textNode.setRangeLineHeight(start, end, {value, unit})
textNode.insertCharacters(start, chars, useStyle?)
textNode.deleteCharacters(start, end)
```

---

### ComponentNode & InstanceNode

```
// Components (reusable masters)
const comp = figma.createComponent()
comp.createInstance(): InstanceNode

// Instances
instance.mainComponent: ComponentNode | null
instance.detachInstance(): FrameNode
instance.setProperties({propName: value})
instance.componentProperties: {...} [readonly]

// Import from library
figma.importComponentByKeyAsync(key): Promise<ComponentNode>
figma.importComponentSetByKeyAsync(key): Promise<ComponentSetNode>
```

---

### Paint Types

```typescript
// Solid color — RGB values are 0–1, NOT 0–255
{type: 'SOLID', color: {r, g, b}, opacity?: number}

// Linear gradient
{type: 'GRADIENT_LINEAR', gradientStops: [{position, color: {r,g,b,a}}], gradientTransform}

// Image fill
{type: 'IMAGE', scaleMode: 'FILL'|'FIT'|'CROP'|'TILE', imageHash: string}
```

#### Helper: Set solid fill
```javascript
node.fills = [{type: 'SOLID', color: {r: 1, g: 0, b: 0}}]  // red
```

#### Helper: Set image fill from URL
```javascript
const image = await figma.createImageAsync(url)
node.fills = [{type: 'IMAGE', scaleMode: 'FILL', imageHash: image.hash}]
```

---

### Effect Types

```typescript
// Drop shadow
{type: 'DROP_SHADOW', color: {r,g,b,a}, offset: {x,y}, radius: number, spread?: number, visible: true}

// Inner shadow
{type: 'INNER_SHADOW', color: {r,g,b,a}, offset: {x,y}, radius: number, visible: true}

// Blur
{type: 'LAYER_BLUR', radius: number, visible: true}
{type: 'BACKGROUND_BLUR', radius: number, visible: true}
```

---

### Common Patterns

#### Create a styled rectangle
```javascript
const rect = figma.createRectangle()
rect.resize(200, 100)
rect.x = 0; rect.y = 0
rect.fills = [{type: 'SOLID', color: {r: 0.2, g: 0.4, b: 1}}]
rect.cornerRadius = 12
rect.effects = [{type: 'DROP_SHADOW', color: {r:0,g:0,b:0,a:0.25}, offset:{x:0,y:4}, radius:8, visible:true}]
figma.currentPage.appendChild(rect)
figma.viewport.scrollAndZoomIntoView([rect])
```

#### Create text
```javascript
const text = figma.createText()
await figma.loadFontAsync({family: "Inter", style: "Regular"})
text.characters = "Hello World"
text.fontSize = 24
text.fills = [{type: 'SOLID', color: {r: 0, g: 0, b: 0}}]
figma.currentPage.appendChild(text)
```

#### Create an auto-layout frame with children
```javascript
const frame = figma.createFrame()
frame.layoutMode = 'VERTICAL'
frame.primaryAxisSizingMode = 'AUTO'
frame.counterAxisSizingMode = 'AUTO'
frame.itemSpacing = 12
frame.paddingLeft = frame.paddingRight = frame.paddingTop = frame.paddingBottom = 16
frame.fills = [{type: 'SOLID', color: {r: 1, g: 1, b: 1}}]
frame.cornerRadius = 8

const title = figma.createText()
await figma.loadFontAsync({family: "Inter", style: "Bold"})
title.characters = "Card Title"
title.fontSize = 18
frame.appendChild(title)

const body = figma.createText()
await figma.loadFontAsync({family: "Inter", style: "Regular"})
body.characters = "Card body text goes here."
body.fontSize = 14
frame.appendChild(body)

figma.currentPage.appendChild(frame)
figma.viewport.scrollAndZoomIntoView([frame])
```

#### Traverse and modify existing nodes
```javascript
// Find all text nodes and change color
const textNodes = figma.currentPage.findAll(n => n.type === 'TEXT')
for (const t of textNodes) {
  t.fills = [{type: 'SOLID', color: {r: 0.1, g: 0.1, b: 0.1}}]
}

// Find node by name
const logo = figma.currentPage.findOne(n => n.name === 'Logo')
```

#### Export a node as PNG
```javascript
const node = figma.currentPage.selection[0]
const bytes = await node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}})
```

</api_reference>
