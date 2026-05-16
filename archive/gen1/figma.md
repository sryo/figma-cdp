# Figma File Editing via Browser Automation

## Connection Methods

There are two ways to run JS against the Figma Plugin API (`figma` global):

### Option A: Claude in Chrome MCP (if loaded)
If the `mcp__claude-in-chrome__*` tools are available, use `mcp__claude-in-chrome__javascript_tool` to eval JS against the Figma tab. This is the simplest path.

### Option B: CDP via Bash (preferred)
When the chrome-devtools MCP plugin is not loaded, use Chrome's DevTools Protocol over WebSocket with a Python helper:

1. **Launch Chrome Canary** with remote debugging:
   ```bash
   /Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary \
     --remote-debugging-port=9222 --no-first-run \
     --user-data-dir=/tmp/chrome-figma-debug &
   ```
2. **Navigate to Figma** — open the target file in Chrome Canary. Prompt the user to log in if needed.
3. **Find the WebSocket URL**:
   ```bash
   curl -s http://localhost:9222/json | python3 -c "
   import json,sys
   tabs=json.load(sys.stdin)
   for t in tabs:
     if 'figma.com' in t.get('url',''):
       print(t['webSocketDebuggerUrl']); break"
   ```
   Store the result: `WS_URL="<output>"`
4. **Create the CDP eval helper** (`/tmp/cdp_eval.py`) if it doesn't exist:
   ```python
   #!/usr/bin/env python3
   import sys, json, asyncio, websockets
   async def main():
       async with websockets.connect(sys.argv[1], max_size=50_000_000) as ws:
           await ws.send(json.dumps({
               "id": 1, "method": "Runtime.evaluate",
               "params": {"expression": sys.argv[2],
                           "awaitPromise": True, "returnByValue": True}
           }))
           r = json.loads(await ws.recv())
           res = r.get("result", {}).get("result", {})
           if res.get("subtype") == "error":
               print("ERROR:", res.get("description", res), file=sys.stderr)
               sys.exit(1)
           print(json.dumps(res.get("value", res.get("description", "")), indent=2))
   asyncio.run(main())
   ```
5. **Test the connection**:
   ```bash
   python3 /tmp/cdp_eval.py "$WS_URL" "typeof figma"
   ```
   Should return `"object"`.

## Component Workflow

Follow this order when building designs:

1. **Create a "Components" page** if one doesn't exist (`figma.createPage()`, name it "Components").
2. **Build Atoms first** — smallest reusable pieces (icons, badges, chips, single text labels).
3. **Build Molecules from Atom instances** — e.g., an "Expense Row" molecule uses Icon and Text Label atoms.
4. **On the Screens page**, compose views entirely from Molecule/Atom instances.
5. **Use Auto Layout** on all component frames and screen frames.
6. **Name components with hierarchy**: `Atoms/Icon/Camera`, `Molecules/Expense Row`, `Screens/Dashboard`.

**ALWAYS use component instances** — never create raw frames or duplicated structures when a reusable component exists.
- **Atomic composition**: Before creating anything, check if a relevant component exists. Use `component.createInstance()` instead of recreating structures.
- **Swappable slots**: Use `instance.swapComponent(targetComp)` to change nested components rather than rebuilding.
- **Verify visually**: Use `node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}})` to inspect nodes instead of full-page screenshots.

## Constraints & Sizing

Set constraints correctly so components resize properly when reused.

### Auto Layout Components (preferred)
Most components should use Auto Layout. Set sizing on children, not constraints:
```js
// Parent frame setup
frame.layoutMode = 'VERTICAL';           // or 'HORIZONTAL'
frame.primaryAxisSizingMode = 'AUTO';    // hug content on main axis
frame.counterAxisSizingMode = 'FIXED';   // fixed on cross axis
frame.paddingTop = frame.paddingBottom = frame.paddingLeft = frame.paddingRight = 16;
frame.itemSpacing = 8;

// Child fills available width
child.layoutSizingHorizontal = 'FILL';
child.layoutSizingVertical = 'HUG';

// Child stays fixed size
child.layoutSizingHorizontal = 'FIXED';
child.layoutSizingVertical = 'FIXED';

// Child hugs its own content (only works if child has children)
child.layoutSizingHorizontal = 'HUG';
child.layoutSizingVertical = 'HUG';
```

### Common Component Patterns
```js
// Button: horizontal, centered, hug both axes
btn.layoutMode = 'HORIZONTAL';
btn.primaryAxisAlignItems = 'CENTER';
btn.counterAxisAlignItems = 'CENTER';
btn.paddingLeft = btn.paddingRight = 16;
btn.paddingTop = btn.paddingBottom = 8;
btn.itemSpacing = 8;
btn.primaryAxisSizingMode = 'AUTO';      // hug width
btn.counterAxisSizingMode = 'AUTO';      // hug height

// Card: vertical, fixed width, image fills width
card.layoutMode = 'VERTICAL';
card.counterAxisSizingMode = 'FIXED';    // fixed width
card.primaryAxisSizingMode = 'AUTO';     // hug height
image.layoutSizingHorizontal = 'FILL';   // stretch to card width
image.layoutSizingVertical = 'FIXED';    // fixed height
content.layoutSizingHorizontal = 'FILL'; // text area fills width

// Input field: horizontal, text fills remaining space
input.layoutMode = 'HORIZONTAL';
input.counterAxisAlignItems = 'CENTER';
textNode.layoutSizingHorizontal = 'FILL';
icon.layoutSizingHorizontal = 'FIXED';

// List / stack: vertical, all children fill width
list.layoutMode = 'VERTICAL';
list.counterAxisSizingMode = 'FIXED';
// each row:
row.layoutSizingHorizontal = 'FILL';
row.layoutSizingVertical = 'HUG';
```

### Absolute Positioning in Auto Layout
For overlays, badges, or floating elements inside an auto layout frame:
```js
badge.layoutPositioning = 'ABSOLUTE';    // opt out of auto layout flow
badge.constraints = {horizontal: 'MAX', vertical: 'MIN'};  // pin top-right
```

### Fixed Frame Constraints (no Auto Layout)
When parent has `layoutMode = 'NONE'`, use `constraints` on children:
```js
child.constraints = {horizontal: 'MIN', vertical: 'MIN'};       // pin top-left (default)
child.constraints = {horizontal: 'STRETCH', vertical: 'MIN'};   // stretch width, pin top
child.constraints = {horizontal: 'STRETCH', vertical: 'STRETCH'}; // fill parent
child.constraints = {horizontal: 'CENTER', vertical: 'CENTER'};   // center both axes
child.constraints = {horizontal: 'MAX', vertical: 'MAX'};         // pin bottom-right
```

### Key Rules
- **`constraints` is ignored when parent has auto layout** — use `layoutSizingHorizontal`/`layoutSizingVertical` instead.
- **`layoutSizingHorizontal = 'FILL'` requires parent to have auto layout.**
- **`layoutSizingHorizontal = 'HUG'` requires the node to have children** (frames/components only).
- **`layoutGrow = 1`** is the legacy way to set FILL. Prefer `layoutSizing*` properties.
- **Set `primaryAxisSizingMode = 'AUTO'`** on parent for hug behavior on the main axis.

## Rules of Engagement
- Always explain in plain English what you are about to do. Assume the user cannot read code.
- Do not use the REST API or manually interact with the Figma UI.
- **Preserve existing behavior** unless explicitly asked to change it. When in doubt, ask first.
- **Favor targeted edits over sweeping changes.** Don't remove or overwrite user modifications — only touch what was requested.
- **NEVER rebuild from scratch.** Always improve existing content incrementally. Never clear children and recreate — find and update what's already there.
- **Follow Figma best practices:** use Components, Auto Layout, consistent naming, proper layer hierarchy.
- All `fills`, `strokes`, and `effects` arrays are **readonly** — clone before mutating: `node.fills = [{...}]`.
- Use `figma.mixed` to check for mixed values on text range properties.
- After creating/modifying nodes, call `figma.viewport.scrollAndZoomIntoView([node])` so the user can see the result.
- **NEVER call `figma.closePlugin()`.** This kills the plugin context and requires a page reload.

## Workflow: Use the Plugin Console, Not Big Scripts
- **Do NOT write large monolithic scripts.** Work step by step through the plugin console.
- Execute small, focused commands: one operation per eval call.
- For multi-line operations, write to `/tmp/fc.js` and run via:
  ```bash
  cat > /tmp/fc.js << 'JSEOF'
  (async () => {
    // your code
  })()
  JSEOF
  python3 /tmp/cdp_eval.py "$WS_URL" "$(cat /tmp/fc.js)"
  ```
  Keep scripts small (under 50 lines).
- Always check the current state before modifying anything.
- After each step, verify the result before moving to the next step.

### Parallelization (Multi-Agent via CDP)
When building multiple independent screens, use parallel Task agents — one per screen.

**Setup:**
1. Each Task agent receives the `WS_URL` and opens its own CDP WebSocket session.
2. Assign each agent a specific frame or page to work on.
3. All agents share the same `figma` global — avoid concurrent writes to the same node.

**Coordination pattern:**
- **Coordinator agent**: Reads file structure, creates target frames, assigns work, distributes component IDs.
- **Worker agents**: Each builds within its assigned frame. Polls `window.__figmaEvents` between operations to detect external changes.
- Use `figma.commitUndo()` after logical units of work so rollbacks are clean.
- Workers verify `node.parent.id === expectedParent.id` after `appendChild` to catch silent reparenting.

## CDP Enhancements

### Helper Injection
Inject reusable helpers into the page context at session start. These persist for the browser session:
```js
window.__fh = {
  hex: function(h) {
    h = h.replace(/^#/, '');
    if (!/^[0-9A-Fa-f]+$/.test(h)) throw new Error('Invalid hex: ' + h);
    var r, g, b, a = 1;
    if (h.length === 3) { r=parseInt(h[0]+h[0],16)/255; g=parseInt(h[1]+h[1],16)/255; b=parseInt(h[2]+h[2],16)/255; }
    else if (h.length === 6) { r=parseInt(h.substring(0,2),16)/255; g=parseInt(h.substring(2,4),16)/255; b=parseInt(h.substring(4,6),16)/255; }
    else if (h.length === 8) { r=parseInt(h.substring(0,2),16)/255; g=parseInt(h.substring(2,4),16)/255; b=parseInt(h.substring(4,6),16)/255; a=parseInt(h.substring(6,8),16)/255; }
    else throw new Error('Invalid hex length: ' + h.length);
    return {r:r, g:g, b:b, a:a};
  },
  solid: function(hex, opacity) {
    var c = this.hex(hex);
    return [{type:'SOLID', color:{r:c.r, g:c.g, b:c.b}, opacity: opacity !== undefined ? opacity : c.a}];
  }
};
```

### Console Monitoring via CDP
Subscribe to console events for real-time log capture during eval:
```python
# After connecting the WebSocket, enable Runtime domain:
await ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
# Console events arrive as:
# {"method": "Runtime.consoleAPICalled", "params": {"type": "log|warn|error", "args": [...]}}
```
Poll for events between eval calls, or run a background listener.

### Event Listener Injection
Inject Figma event listeners that buffer events into a global array. Poll between operations to stay aware of user actions:
```js
if (!window.__figmaEvents) {
  window.__figmaEvents = [];
  figma.on('selectionchange', function() {
    var sel = figma.currentPage.selection.map(function(n) {
      return {id:n.id, name:n.name, type:n.type};
    });
    window.__figmaEvents.push({type:'selection', nodes:sel, ts:Date.now()});
    if (window.__figmaEvents.length > 100) window.__figmaEvents.shift();
  });
  figma.on('currentpagechange', function() {
    window.__figmaEvents.push({type:'page', name:figma.currentPage.name, ts:Date.now()});
  });
  figma.on('documentchange', function(e) {
    window.__figmaEvents.push({type:'docchange', count:e.documentChanges.length, ts:Date.now()});
    if (window.__figmaEvents.length > 100) window.__figmaEvents.shift();
  });
}
```
Read and drain events: `var events = window.__figmaEvents.splice(0);`

### Batch Processing
For large operations, yield to the event loop between batches to prevent Figma from freezing:
```js
var nodes = figma.currentPage.findAll();
var BATCH = 50;
for (var i = 0; i < nodes.length; i += BATCH) {
  var batch = nodes.slice(i, i + BATCH);
  // process batch...
  if (i + BATCH < nodes.length) {
    await new Promise(function(r) { setTimeout(r, 0); });
  }
}
```

### Result Analysis
After eval, check for silent failures before proceeding:
- `null` → node/resource doesn't exist
- `undefined` → missing return statement
- `[]` (empty array) → search found nothing
- Object with `length === 0` or `count === 0` → operation matched nothing

Log a warning and re-check your query before retrying.

## Gotchas
- **`appendChild` can silently fail in complex async scripts.** Nodes may end up as page-level siblings. Always verify: check `parent.children.length` or `child.parent.id === expectedParent.id`.
- **Font loading does NOT persist across eval calls.** You must call `await figma.loadFontAsync(...)` in every script that touches text properties — even if you loaded the same font previously.
- **Nodes created but not appended** within the same eval can get garbage collected. Always append in the same script that creates them.
- **Overriding text inside instances**: Load the font first, then find the text node:
  ```js
  await figma.loadFontAsync({family: "Inter", style: "Regular"});
  const label = inst.findOne(n => n.name === "Label" && n.type === "TEXT");
  label.characters = "New Text";
  ```
- **Colors use 0–1 range, NOT 0–255.** Hex `#6366f1` = `{r: 0.388, g: 0.4, b: 0.945}`.
- **Script return values must be JSON-serializable.**
- **Each eval call is independent** — fonts, variables, and references from a previous call are NOT available in the next one.
- **No optional chaining (`?.`) or nullish coalescing (`??`) in the plugin sandbox.** Figma uses QuickJS. Use explicit checks: `node && node.parent && node.parent.type` instead of `node?.parent?.type`.
- **`AsyncFunction` constructor is restricted in QuickJS.** Use `eval()` with an async IIFE wrapper: `eval("(async function() { ... })()")`.
- **Large operations can freeze Figma.** Yield to the event loop between batches with `await new Promise(function(r) { setTimeout(r, 0); })`.

<troubleshooting>
If "figma is not defined": ensure the user has edit permissions. If not, suggest creating a branch. If the global is still missing, instruct the user to open and close any plugin, then retry.
</troubleshooting>

## Figma Plugin API Reference

Source: [`@figma/plugin-typings`](https://github.com/figma/plugin-typings/blob/master/plugin-api.d.ts)
Notation: `[ro]` = readonly, `P<T>` = Promise<T>, types after `//` are abbreviated.

<api_reference>

### figma Global

#### Properties
```
figma.root: DocumentNode [ro]
figma.currentPage: PageNode
figma.editorType: 'figma'|'figjam'|'dev'|'slides' [ro]
figma.fileKey: string|undefined [ro]           // private plugins only
figma.apiVersion: string [ro]
figma.pluginId: string [ro]
figma.command: string [ro]
figma.mode: 'default'|'textreview'|'inspect'|'codegen' [ro]
figma.mixed: unique symbol [ro]
figma.hasMissingFont: boolean [ro]
figma.currentUser: User|null [ro]
figma.activeUsers: ActiveUser[] [ro]
figma.skipInvisibleInstanceChildren: boolean
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
figma.createComponentFromNode(node): ComponentNode
figma.createPage(): PageNode
figma.createSlice(): SliceNode
figma.createSection(): SectionNode
figma.createBooleanOperation(): BooleanOperationNode
figma.createNodeFromSvg(svg: string): FrameNode
figma.createNodeFromJSXAsync(jsx): P<SceneNode>
figma.createTextPath(vectorNode, startSegment, startPosition): TextPathNode
```

#### Find & Navigate
```
figma.getNodeByIdAsync(id): P<BaseNode|null>
figma.getNodesByIdAsync(ids): P<(BaseNode|null)[]>
figma.getNodeById(id): BaseNode|null             // DEPRECATED
figma.setCurrentPageAsync(page): P<void>
figma.loadAllPagesAsync(): P<void>
```

#### Group & Boolean
```
figma.group(nodes, parent, index?): GroupNode
figma.ungroup(node): SceneNode[]
figma.union(nodes, parent, index?): BooleanOperationNode
figma.subtract(nodes, parent, index?): BooleanOperationNode
figma.intersect(nodes, parent, index?): BooleanOperationNode
figma.exclude(nodes, parent, index?): BooleanOperationNode
figma.flatten(nodes, parent?, index?): VectorNode
figma.combineAsVariants(components, parent, index?): ComponentSetNode
```

#### Fonts, Images, Media
```
figma.loadFontAsync({family, style}): P<void>
figma.listAvailableFontsAsync(): P<Font[]>
figma.createImage(data: Uint8Array): Image
figma.createImageAsync(url: string): P<Image>
figma.getImageByHash(hash): Image|null
figma.createVideoAsync(data: Uint8Array): P<Video>
figma.base64Encode(data: Uint8Array): string
figma.base64Decode(data: string): Uint8Array
```

#### Styles
```
figma.createPaintStyle(): PaintStyle
figma.createTextStyle(): TextStyle
figma.createEffectStyle(): EffectStyle
figma.createGridStyle(): GridStyle
figma.getLocalPaintStylesAsync(): P<PaintStyle[]>
figma.getLocalTextStylesAsync(): P<TextStyle[]>
figma.getLocalEffectStylesAsync(): P<EffectStyle[]>
figma.getLocalGridStylesAsync(): P<GridStyle[]>
figma.getStyleByIdAsync(id): P<BaseStyle|null>
figma.importStyleByKeyAsync(key): P<BaseStyle>
figma.importComponentByKeyAsync(key): P<ComponentNode>
figma.importComponentSetByKeyAsync(key): P<ComponentSetNode>
figma.getSelectionColors(): {paints: Paint[], styles: PaintStyle[]}|null
// moveLocal*StyleAfter / moveLocal*FolderAfter for reordering
```

#### Variables (`figma.variables`)
```
.createVariable(name, collectionOrId, resolvedType): Variable
.createVariableCollection(name): VariableCollection
.createVariableAlias(variable): VariableAlias
.getVariableByIdAsync(id): P<Variable|null>
.getVariableCollectionByIdAsync(id): P<VariableCollection|null>
.getLocalVariablesAsync(type?): P<Variable[]>
.getLocalVariableCollectionsAsync(): P<VariableCollection[]>
.importVariableByKeyAsync(key): P<Variable>
.setBoundVariableForPaint(paint, field, variable|null): SolidPaint
.setBoundVariableForEffect(effect, field, variable|null): Effect
.setBoundVariableForLayoutGrid(grid, field, variable|null): LayoutGrid
// VariableResolvedDataType: 'BOOLEAN'|'COLOR'|'FLOAT'|'STRING'
```

#### Team Library (`figma.teamLibrary`)
```
.getAvailableLibraryVariableCollectionsAsync(): P<LibraryVariableCollection[]>
.getVariablesInLibraryCollectionAsync(key): P<LibraryVariable[]>
```

#### Client Storage (`figma.clientStorage`) — 5MB limit, local to machine
```
.getAsync(key): P<any>
.setAsync(key, value): P<void>
.deleteAsync(key): P<void>
.keysAsync(): P<string[]>
```

#### UI (`figma.ui`)
```
figma.showUI(html, options?): void
// ShowUIOptions: {width?, height?, visible?, title?, position?: {x,y}, themeColors?}
figma.ui.show() / .hide() / .close()
figma.ui.resize(w, h) / .reposition(x, y)
figma.ui.postMessage(msg, options?): void
figma.ui.on('message', (msg, props) => void)  // props.origin
figma.ui.once(...) / .off(...)
// iframe sends: parent.postMessage({pluginMessage: data}, '*')
```

#### Viewport
```
figma.viewport.center: Vector                    // get/set
figma.viewport.zoom: number                      // get/set
figma.viewport.bounds: Rect [ro]
figma.viewport.scrollAndZoomIntoView(nodes): void
```

#### Utility (`figma.util`)
```
.rgb(color: string|RGB|RGBA): RGB                // parse hex/rgb/hsl
.rgba(color: string|RGB|RGBA): RGBA
.solidPaint(color, overrides?): SolidPaint
```

#### Events
```
// No-arg: 'selectionchange'|'currentpagechange'|'close'
figma.on('run', (e: {command, parameters?}) => void)
figma.on('drop', (e: {node, x, y, absoluteX, absoluteY, items, files}) => boolean)
figma.on('documentchange', (e: {documentChanges}) => void)
figma.on('stylechange', (e: {styleChanges}) => void)
figma.once(...) / figma.off(...)
// DocumentChange types: CREATE|DELETE|PROPERTY_CHANGE|STYLE_CREATE|STYLE_DELETE|STYLE_PROPERTY_CHANGE
// Each has: {type, id, node|style, origin: 'LOCAL'|'REMOTE'}
```

#### Lifecycle
```
figma.notify(msg, opts?): NotificationHandler    // opts: {timeout?, error?, button?: {text, action}}
figma.commitUndo(): void
figma.triggerUndo(): void
figma.saveVersionHistoryAsync(title, desc?): P<VersionHistoryResult>
figma.openExternal(url): void
figma.closePlugin(msg?): void                    // NEVER call in automation
```

#### Annotations (`figma.annotations`)
```
.getAnnotationCategoriesAsync(): P<AnnotationCategory[]>
.getAnnotationCategoryByIdAsync(id): P<AnnotationCategory|null>
.addAnnotationCategoryAsync({label, color}): P<AnnotationCategory>
// AnnotationCategoryColor: 'yellow'|'orange'|'red'|'pink'|'violet'|'blue'|'teal'|'green'
```

### Mixins (Shared Node Properties)

#### BaseNodeMixin (all nodes)
```
id: string [ro]
name: string
type: NodeType [ro]
parent: (BaseNode & ChildrenMixin)|null [ro]
removed: boolean [ro]
isAsset: boolean [ro]
remove(): void
clone(): Node
toString(): string
getCSSAsync(): P<{[key]: string}>
getTopLevelFrame(): FrameNode|undefined
// PluginDataMixin:
getPluginData(key)/setPluginData(key, val)/getPluginDataKeys()
getSharedPluginData(ns, key)/setSharedPluginData(ns, key, val)/getSharedPluginDataKeys(ns)
setRelaunchData(data)/getRelaunchData()
```

#### SceneNodeMixin
```
visible: boolean
locked: boolean
componentPropertyReferences: {visible?, characters?, mainComponent?}|null
boundVariables: {...} [ro]
resolvedVariableModes: {[collectionId]: modeId} [ro]
setBoundVariable(field, variable|null): void
// ExplicitVariableModesMixin:
explicitVariableModes: {[collectionId]: modeId}
setExplicitVariableModeForCollection(collectionOrId, modeId): void
clearExplicitVariableModeForCollection(collectionOrId): void
```

#### ChildrenMixin
```
children: SceneNode[] [ro]
appendChild(child): void
insertChild(index, child): void
findAll(cb?): SceneNode[]
findOne(cb): SceneNode|null
findChildren(cb?): SceneNode[]                   // direct children only
findChild(cb): SceneNode|null
findAllWithCriteria({types?, pluginData?, sharedPluginData?}): SceneNode[]
```

#### DimensionAndPositionMixin
```
x: number
y: number
width: number [ro]
height: number [ro]
minWidth/maxWidth/minHeight/maxHeight: number|null
relativeTransform: Transform
absoluteTransform: Transform [ro]
absoluteBoundingBox: Rect|null [ro]
```

#### LayoutMixin (extends DimensionAndPosition)
```
absoluteRenderBounds: Rect|null [ro]             // includes shadows/strokes
constrainProportions: boolean
rotation: number
layoutSizingHorizontal: 'FIXED'|'HUG'|'FILL'
layoutSizingVertical: 'FIXED'|'HUG'|'FILL'
resize(w, h): void
resizeWithoutConstraints(w, h): void
rescale(scale): void
// AutoLayoutChildrenMixin:
layoutAlign: 'MIN'|'CENTER'|'MAX'|'STRETCH'|'INHERIT'
layoutGrow: number                               // 0=fixed, 1=fill
layoutPositioning: 'AUTO'|'ABSOLUTE'
```

#### AutoLayoutMixin (on frames)
```
layoutMode: 'NONE'|'HORIZONTAL'|'VERTICAL'|'GRID'
primaryAxisAlignItems: 'MIN'|'CENTER'|'MAX'|'SPACE_BETWEEN'
counterAxisAlignItems: 'MIN'|'CENTER'|'MAX'|'BASELINE'
primaryAxisSizingMode: 'FIXED'|'AUTO'
counterAxisSizingMode: 'FIXED'|'AUTO'
counterAxisAlignContent: 'AUTO'|'SPACE_BETWEEN'
itemSpacing: number
counterAxisSpacing: number|null
paddingLeft/paddingRight/paddingTop/paddingBottom: number
layoutWrap: 'NO_WRAP'|'WRAP'
itemReverseZIndex: boolean
strokesIncludedInLayout: boolean
```

#### GridLayoutMixin (CSS Grid on frames)
```
gridRowCount/gridColumnCount: number
gridRowGap/gridColumnGap: number
gridRowSizes/gridColumnSizes: GridTrackSize[]    // {value?, type: 'FLEX'|'FIXED'|'HUG'}
appendChildAt(node, rowIndex, colIndex): void
// GridChildrenMixin (on children):
setGridChildPosition(row, col): void
gridRowAnchorIndex/gridColumnAnchorIndex: number [ro]
gridRowSpan/gridColumnSpan: number
gridChildHorizontalAlign/gridChildVerticalAlign: 'MIN'|'CENTER'|'MAX'|'AUTO'
```

#### GeometryMixin
```
fills: Paint[]|mixed                             // READONLY array — reassign!
fillStyleId: string|mixed
strokes: Paint[]
strokeStyleId: string
strokeWeight: number|mixed
strokeAlign: 'CENTER'|'INSIDE'|'OUTSIDE'
strokeCap: StrokeCap|mixed
strokeJoin: StrokeJoin|mixed
strokeMiterLimit: number
dashPattern: number[]
fillGeometry/strokeGeometry: VectorPaths [ro]
outlineStroke(): VectorNode|null
setFillStyleIdAsync(id)/setStrokeStyleIdAsync(id): P<void>
setFillsAsync(paints)/setStrokesAsync(strokes): P<void>
```

#### IndividualStrokesMixin
```
strokeTopWeight/strokeBottomWeight/strokeLeftWeight/strokeRightWeight: number
```

#### BlendMixin
```
opacity: number                                  // 0-1
blendMode: BlendMode
isMask: boolean
maskType: 'ALPHA'|'VECTOR'|'LUMINANCE'
effects: Effect[]
effectStyleId: string
setEffectStyleIdAsync(id): P<void>
```

#### CornerMixin + RectangleCornerMixin
```
cornerRadius: number|mixed
cornerSmoothing: number                          // 0-1, iOS-style
topLeftRadius/topRightRadius/bottomLeftRadius/bottomRightRadius: number
```

#### ConstraintMixin
```
constraints: {horizontal, vertical}              // 'MIN'|'CENTER'|'MAX'|'STRETCH'|'SCALE'
```

#### ExportMixin
```
exportSettings: ExportSettings[]
exportAsync(settings?): P<Uint8Array>
exportAsync(settings: {format:'SVG_STRING',...}): P<string>
exportAsync(settings: {format:'JSON_REST_V1'}): P<Object>
// ExportSettings: {format:'PNG'|'JPG'|'SVG'|'PDF', constraint?: {type:'SCALE'|'WIDTH'|'HEIGHT', value}, contentsOnly?, suffix?}
```

#### ReactionMixin (prototype interactions)
```
reactions: Reaction[] [ro]
setReactionsAsync(reactions): P<void>
```

#### PublishableMixin (components, styles)
```
description: string
descriptionMarkdown: string
documentationLinks: DocumentationLink[] [ro]
remote: boolean [ro]
key: string [ro]
getPublishStatusAsync(): P<'UNPUBLISHED'|'CURRENT'|'CHANGED'>
```

#### ComponentPropertiesMixin
```
componentPropertyDefinitions: ComponentPropertyDefinitions [ro]
addComponentProperty(name, type, defaultValue, opts?): string
editComponentProperty(name, newValue): string
deleteComponentProperty(name): void
// ComponentPropertyType: 'BOOLEAN'|'TEXT'|'INSTANCE_SWAP'|'VARIANT'
```

#### FramePrototypingMixin
```
overflowDirection: 'NONE'|'HORIZONTAL'|'VERTICAL'|'BOTH'
numberOfFixedChildren: number
overlayPositionType: OverlayPositionType [ro]
overlayBackground: OverlayBackground [ro]
overlayBackgroundInteraction: 'NONE'|'CLOSE_ON_CLICK_OUTSIDE' [ro]
```

#### VectorLikeMixin
```
vectorNetwork: VectorNetwork
setVectorNetworkAsync(vn): P<void>
vectorPaths: VectorPaths
handleMirroring: 'NONE'|'ANGLE'|'ANGLE_AND_LENGTH'|mixed
```

#### Other Mixins
```
// ContainerMixin
expanded: boolean
// AnnotationsMixin
annotations: Annotation[] [ro]
```

### Node Types

#### Mixin Inheritance (thin nodes)
| Node | Type | Mixins | Extra |
|------|------|--------|-------|
| GroupNode | `'GROUP'` | ChildrenMixin, BlendMixin, LayoutMixin, ExportMixin, ReactionMixin, ContainerMixin | — |
| RectangleNode | `'RECTANGLE'` | GeometryMixin, BlendMixin, LayoutMixin, ConstraintMixin, CornerMixin, RectangleCornerMixin, IndividualStrokesMixin, ExportMixin, AnnotationsMixin | — |
| SliceNode | `'SLICE'` | LayoutMixin, ExportMixin | no fills/strokes/effects |
| BooleanOperationNode | `'BOOLEAN_OPERATION'` | ChildrenMixin, GeometryMixin, BlendMixin, CornerMixin | `booleanOperation: 'UNION'\|'INTERSECT'\|'SUBTRACT'\|'EXCLUDE'` |
| SectionNode | `'SECTION'` | ChildrenMixin, MinimalFillsMixin | `sectionContentsHidden: boolean` |

#### DocumentNode
```
type: 'DOCUMENT' [ro]
children: PageNode[] [ro]
documentColorProfile: 'LEGACY'|'SRGB'|'DISPLAY_P3' [ro]
appendChild(page)/insertChild(index, page): void
findAll/findOne/findChildren/findChild/findAllWithCriteria
```

#### PageNode
```
type: 'PAGE' [ro]
guides: Guide[]
selection: SceneNode[]
selectedTextRange: {node: TextNode, start, end}|null
backgrounds/prototypeBackgrounds: Paint[]
prototypeStartNode: FrameNode|GroupNode|ComponentNode|InstanceNode|null [ro]
flowStartingPoints: [{nodeId, name}]
isPageDivider: boolean
loadAsync(): P<void>                            // required for dynamic-page mode
on/once/off('nodechange', cb): void
// NodeChangeEvent: {nodeChanges: [{type:'CREATE'|'DELETE'|'PROPERTY_CHANGE', id, node, origin, properties?}]}
```

#### FrameNode
```
type: 'FRAME' [ro]
// Inherits: AutoLayoutMixin, GeometryMixin, BlendMixin, LayoutMixin, ChildrenMixin,
//   CornerMixin, RectangleCornerMixin, IndividualStrokesMixin, ConstraintMixin,
//   ExportMixin, ReactionMixin, FramePrototypingMixin
clipsContent: boolean
layoutGrids: LayoutGrid[]
gridStyleId: string
guides: Guide[]
inferredAutoLayout: InferredAutoLayoutResult|null [ro]
```

#### EllipseNode
```
type: 'ELLIPSE' [ro]
arcData: {startingAngle, endingAngle, innerRadius}  // radians, innerRadius 0-1
// Inherits: GeometryMixin, BlendMixin, LayoutMixin, ConstraintMixin, CornerMixin, ExportMixin
```

#### LineNode / PolygonNode / StarNode / VectorNode
```
// LineNode: type 'LINE', height always 0
// PolygonNode: type 'POLYGON', pointCount: number
// StarNode: type 'STAR', pointCount: number, innerRadius: number (0-1)
// VectorNode: type 'VECTOR', extends VectorLikeMixin
// All inherit: GeometryMixin, BlendMixin, LayoutMixin, ConstraintMixin, ExportMixin
```

#### TextNode
```
type: 'TEXT' [ro]
// MUST load font before modifying: await figma.loadFontAsync(textNode.fontName)
characters: string
fontSize: number|mixed
fontName: {family, style}|mixed
fontWeight: number|mixed [ro]
textAlignHorizontal: 'LEFT'|'CENTER'|'RIGHT'|'JUSTIFIED'
textAlignVertical: 'TOP'|'CENTER'|'BOTTOM'
textAutoResize: 'NONE'|'WIDTH_AND_HEIGHT'|'HEIGHT'|'TRUNCATE'
textTruncation: 'DISABLED'|'ENDING'
maxLines: number|null
letterSpacing: {value, unit:'PIXELS'|'PERCENT'}|mixed
lineHeight: {value, unit}|{unit:'AUTO'}|mixed
leadingTrim: 'CAP_HEIGHT'|'NONE'|mixed
textCase: 'ORIGINAL'|'UPPER'|'LOWER'|'TITLE'|'SMALL_CAPS'|'SMALL_CAPS_FORCED'|mixed
textDecoration: 'NONE'|'UNDERLINE'|'STRIKETHROUGH'|mixed
paragraphSpacing/paragraphIndent/listSpacing: number
hangingPunctuation/hangingList: boolean
hyperlink: HyperlinkTarget|null|mixed            // {type:'URL'|'NODE', value}
autoRename: boolean
textStyleId: string|mixed
setTextStyleIdAsync(id): P<void>
hasMissingFont: boolean [ro]
openTypeFeatures: {[feature]: boolean}|mixed [ro]
// Range methods (start inclusive, end exclusive, require font loaded):
setRangeFontSize/getRangeFontSize(start, end, value?)
setRangeFontName/getRangeFontName(start, end, value?)
setRangeFills/getRangeFills(start, end, value?)
setRangeTextDecoration/getRangeTextDecoration(start, end, value?)
setRangeTextCase/getRangeTextCase(start, end, value?)
setRangeLetterSpacing/getRangeLetterSpacing(start, end, value?)
setRangeLineHeight/getRangeLineHeight(start, end, value?)
setRangeListOptions/getRangeListOptions(start, end, value?)
setRangeIndentation/getRangeIndentation(start, end, value?)
setRangeHyperlink/getRangeHyperlink(start, end, value?)
setRangeBoundVariable(start, end, field, variable|null)
setRangeTextStyleIdAsync(start, end, styleId)/setRangeFillStyleIdAsync(start, end, styleId)
insertCharacters(start, chars, useStyle?:'BEFORE'|'AFTER')
deleteCharacters(start, end)
getStyledTextSegments(fields, start?, end?): StyledTextSegment[]
getRangeAllFontNames(start, end): FontName[]
```

#### ComponentNode
```
type: 'COMPONENT' [ro]
// Inherits all FrameNode props + PublishableMixin + VariantMixin + ComponentPropertiesMixin
createInstance(): InstanceNode
getInstancesAsync(): P<InstanceNode[]>
instances: InstanceNode[] [ro]
// VariantMixin: variantProperties: {[prop]: value}|null [ro]
```

#### ComponentSetNode
```
type: 'COMPONENT_SET' [ro]
// No figma.createComponentSet()! Use figma.combineAsVariants(components, parent)
defaultVariant: ComponentNode [ro]
variantGroupProperties: {[prop]: {values: string[]}} [ro]
// + PublishableMixin, ComponentPropertiesMixin
```

#### InstanceNode
```
type: 'INSTANCE' [ro]
mainComponent: ComponentNode|null
getMainComponentAsync(): P<ComponentNode|null>
swapComponent(comp): void                        // preserves overrides
detachInstance(): FrameNode
setProperties({propName: value}): void
componentProperties: ComponentProperties [ro]
scaleFactor: number
exposedInstances: InstanceNode[] [ro]
isExposedInstance: boolean
overrides: [{id, overriddenFields}] [ro]
resetOverrides()/removeOverrides(): void
// Inherits all FrameNode props + VariantMixin
```

### Style Objects
```
// BaseStyleMixin (all styles): id [ro], name, type, remove()
//   + PublishableMixin (description, key, remote, getPublishStatusAsync)
//   consumers [ro], getStyleConsumersAsync()
// PaintStyle: type 'PAINT', paints: Paint[]
// TextStyle: type 'TEXT', fontSize, fontName, letterSpacing, lineHeight, leadingTrim,
//   paragraphIndent, paragraphSpacing, listSpacing, textCase, textDecoration,
//   hangingPunctuation, hangingList, setBoundVariable(field, var)
// EffectStyle: type 'EFFECT', effects: Effect[]
// GridStyle: type 'GRID', layoutGrids: LayoutGrid[]
// All support boundVariables [ro]
```

### Variable Objects
```
// Variable (extends PluginDataMixin)
id/key: string [ro]
name/description: string
resolvedType: 'BOOLEAN'|'COLOR'|'FLOAT'|'STRING' [ro]
variableCollectionId: string [ro]
valuesByMode: {[modeId]: VariableValue} [ro]
remote: boolean [ro]
hiddenFromPublishing: boolean
scopes: VariableScope[]
codeSyntax: {WEB?, ANDROID?, iOS?} [ro]
setValueForMode(modeId, value): void
resolveForConsumer(node): {value, resolvedType}
remove(): void
setVariableCodeSyntax(platform, value)/removeVariableCodeSyntax(platform)

// VariableCollection (extends PluginDataMixin)
id/key/defaultModeId: string [ro]
name: string
modes: [{modeId, name}] [ro]
variableIds: string[] [ro]
remote/isExtension: boolean [ro]
hiddenFromPublishing: boolean
addMode(name): string                            // returns modeId
renameMode(modeId, name)/removeMode(modeId)/remove(): void

// VariableScope: 'ALL_SCOPES'|'TEXT_CONTENT'|'CORNER_RADIUS'|'WIDTH_HEIGHT'|'GAP'|
//   '*_FILL(3)'|'STROKE_*'|'EFFECT_*'|'OPACITY'|'FONT_*(4)'|'LINE_HEIGHT'|
//   'LETTER_SPACING'|'PARAGRAPH_SPACING'|'PARAGRAPH_INDENT'
// VariableBindableNodeField: 'height'|'width'|'characters'|'itemSpacing'|'padding*'|
//   'visible'|'*Radius'|'min/maxWidth'|'min/maxHeight'|'counterAxisSpacing'|
//   'stroke*Weight'|'opacity'|'gridRowGap'|'gridColumnGap'
// VariableBindableTextField: 'fontFamily'|'fontSize'|'fontStyle'|'fontWeight'|
//   'letterSpacing'|'lineHeight'|'paragraphSpacing'|'paragraphIndent'
```

### Data Types

#### Paint
```
SolidPaint: {type:'SOLID', color:{r,g,b}, opacity?, visible?, blendMode?}
GradientPaint: {type:'GRADIENT_LINEAR'|'GRADIENT_RADIAL'|'GRADIENT_ANGULAR'|'GRADIENT_DIAMOND',
  gradientStops:[{position:0-1, color:{r,g,b,a}}], gradientTransform}
ImagePaint: {type:'IMAGE', scaleMode:'FILL'|'FIT'|'CROP'|'TILE', imageHash, imageTransform?, filters?}
VideoPaint: {type:'VIDEO', scaleMode, videoHash}
```

#### Effect
```
DropShadowEffect: {type:'DROP_SHADOW', color:RGBA, offset:{x,y}, radius, spread?, visible, blendMode, showShadowBehindNode?}
InnerShadowEffect: {type:'INNER_SHADOW', color:RGBA, offset:{x,y}, radius, spread?, visible, blendMode}
BlurEffect: {type:'LAYER_BLUR'|'BACKGROUND_BLUR', radius, visible}
```

#### Prototype Types
```
Reaction: {trigger, action?, actions?}
Trigger: 'ON_CLICK'|'ON_HOVER'|'ON_PRESS'|'ON_DRAG'|{type:'AFTER_TIMEOUT', timeout}|{type:'MOUSE_*', delay}|{type:'ON_KEY_DOWN', device, keyCodes}|{type:'ON_MEDIA_*'}
Action: 'BACK'|'CLOSE'|{type:'URL', url}|{type:'NODE', destinationId, navigation, transition, ...}|{type:'SET_VARIABLE'|'SET_VARIABLE_MODE'|'CONDITIONAL'|'UPDATE_MEDIA_RUNTIME', ...}
Navigation: 'NAVIGATE'|'SWAP'|'OVERLAY'|'SCROLL_TO'|'CHANGE_TO'
Transition: {type:'DISSOLVE'|'SMART_ANIMATE'|'MOVE_IN'|'MOVE_OUT'|'PUSH'|'SLIDE_IN'|'SLIDE_OUT', easing, duration, direction?}
Easing: {type:'EASE_IN'|'EASE_OUT'|'EASE_IN_AND_OUT'|'LINEAR'|'GENTLE'|'QUICK'|'BOUNCY'|'SLOW'|'CUSTOM_CUBIC_BEZIER'|'CUSTOM_SPRING', ...}
```

#### Layout Types
```
LayoutGrid: {pattern:'ROWS'|'COLUMNS', alignment:'MIN'|'MAX'|'STRETCH'|'CENTER', gutterSize, count, sectionSize?, offset?, visible?, color?}
  | {pattern:'GRID', sectionSize, visible?, color?}
Transform: [[a,b,tx],[c,d,ty]]
Vector: {x, y}   Rect: {x, y, width, height}
RGB: {r, g, b}   RGBA: {r, g, b, a}   FontName: {family, style}
```

#### Other Types
```
HyperlinkTarget: {type:'URL'|'NODE', value: string}
TextListOptions: {type:'ORDERED'|'UNORDERED'|'NONE'}
ArcData: {startingAngle, endingAngle, innerRadius}
BlendMode: 'NORMAL'|'MULTIPLY'|'SCREEN'|'OVERLAY'|'DARKEN'|'LIGHTEN'|... (16 total)
StrokeCap: 'NONE'|'ROUND'|'SQUARE'|'ARROW_LINES'|'ARROW_EQUILATERAL'|'DIAMOND_FILLED'|'TRIANGLE_FILLED'|'CIRCLE_FILLED'
StrokeJoin: 'MITER'|'BEVEL'|'ROUND'
VariableAlias: {type:'VARIABLE_ALIAS', id: string}
VariableValue: boolean|string|number|RGB|RGBA|VariableAlias
Image: {hash [ro], getBytesAsync(): P<Uint8Array>, getSizeAsync(): P<{width, height}>}
Video: {hash [ro]}
User: {id, name, photoUrl, color, sessionId}
```

#### SceneNode Union
```
SceneNode = SliceNode | FrameNode | GroupNode | ComponentSetNode | ComponentNode |
  InstanceNode | BooleanOperationNode | VectorNode | StarNode | LineNode | EllipseNode |
  PolygonNode | RectangleNode | TextNode | TextPathNode | TransformGroupNode | SectionNode
```

</api_reference>
