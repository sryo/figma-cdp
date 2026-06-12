# Figma Plugin API reference (universal)

Source: [`@figma/plugin-typings`](https://github.com/figma/plugin-typings/blob/master/plugin-api.d.ts).
Notation: `[ro]` = readonly, `P<T>` = Promise<T>, types after `//` are abbreviated.

Universal API — `figma` global, find/navigate, lifecycle, events, viewport, base mixins. **Topical APIs live in sibling files:**

- `references/api-text.md` — TextNode, range methods, font loading
- `references/api-layout.md` — FrameNode, shape nodes, Layout / AutoLayout / Grid / Constraint mixins
- `references/api-components.md` — Component, ComponentSet, Instance, Variables, Styles
- `references/api-styling.md` — Blend mixin, gradient/image paints, Effect, Prototype types, FramePrototypingMixin

## Quick lookup: most used

```
figma.currentPage: PageNode                  figma.root: DocumentNode [ro]
figma.getNodeByIdAsync(id): P<BaseNode>      figma.commitUndo(): void
figma.viewport.scrollAndZoomIntoView(nodes)  figma.notify(msg, opts?)
figma.util.rgb(string|RGB|RGBA): RGB         figma.util.solidPaint(color, overrides?): SolidPaint
figma.loadFontAsync({family, style})         // see api-text.md
figma.createFrame() / .createRectangle() ... // see api-layout.md
figma.createComponent() / .createInstance()  // see api-components.md
node.findAllWithCriteria({types:['TEXT']})   // native C++ filter — fast
```

## `figma` global

### Properties
```
figma.root: DocumentNode [ro]
figma.currentPage: PageNode
figma.editorType: 'figma'|'figjam'|'dev'|'slides'|'buzz' [ro]
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

### Find and navigate
```
figma.getNodeByIdAsync(id): P<BaseNode|null>
figma.getNodesByIdAsync(ids): P<(BaseNode|null)[]>
figma.getNodeById(id): BaseNode|null             // DEPRECATED
figma.setCurrentPageAsync(page): P<void>
figma.loadAllPagesAsync(): P<void>
```

### Lifecycle
```
figma.notify(msg, opts?): NotificationHandler    // opts: {timeout?, error?, button?: {text, action}}
figma.commitUndo(): void
figma.triggerUndo(): void
figma.saveVersionHistoryAsync(title, desc?): P<VersionHistoryResult>
figma.openExternal(url): void
figma.closePlugin(msg?): void                    // — never call from automation (see figma-worker.md Rules)
```

### Events
```
figma.on / .once / .off (event, callback)
// No-arg events: 'selectionchange'|'currentpagechange'|'close'
// With event arg: 'run'|'drop'|'documentchange'|'stylechange'|'textreview'|
//   'timerstart'|'timerpause'|'timerresume'|'timerstop'|'timeradjust'|'timerdone'
// 'drop' cb returns false to prevent default. DropEvent: {node, x, y, absoluteX, absoluteY, items, files, dropMetadata?}
// DocumentChange: {type: CREATE|DELETE|PROPERTY_CHANGE|STYLE_*, id, node|style, origin: 'LOCAL'|'REMOTE'}
// NOTE: callbacks run async; code after figma.on() executes before callback fires
```

### Viewport
```
figma.viewport.center: Vector                    // get/set
figma.viewport.zoom: number                      // get/set
figma.viewport.bounds: Rect [ro]
figma.viewport.scrollAndZoomIntoView(nodes): void
figma.viewport.slidesView: 'grid'|'single-slide' // Figma Slides only
figma.viewport.canvasView: 'grid'|'single-asset'  // Figma Slides/Buzz only
```

### Utility (`figma.util`)
```
.rgb(color: string|RGB|RGBA): RGB                // parse hex/rgb/hsl
.rgba(color: string|RGB|RGBA): RGBA
.solidPaint(color, overrides?): SolidPaint
```

### Client storage (`figma.clientStorage`): 5MB limit, local to machine
```
.getAsync(key): P<any>
.setAsync(key, value): P<void>
.deleteAsync(key): P<void>
.keysAsync(): P<string[]>
```

### Annotations (`figma.annotations`)
```
.getAnnotationCategoriesAsync() / .getAnnotationCategoryByIdAsync(id) / .addAnnotationCategoryAsync({label, color})
// Color: 'yellow'|'orange'|'red'|'pink'|'violet'|'blue'|'teal'|'green'
// (AnnotationsMixin on nodes → see api-components.md)
```

> **`figma.ui.*` is omitted** — it's for plugins that render their own panel inside Figma. CDP automation workers never use it.

## Base mixins (on every node)

### BaseNodeMixin
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

### SceneNodeMixin
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

### ChildrenMixin
```
children: SceneNode[] [ro]
appendChild(child): void
insertChild(index, child): void
findAll(cb?): SceneNode[]
findOne(cb): SceneNode|null
findChildren(cb?): SceneNode[]                   // direct children only
findChild(cb): SceneNode|null
findAllWithCriteria({types?, pluginData?, sharedPluginData?}): SceneNode[]  // PREFERRED — native C++
```

### DimensionAndPositionMixin
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

### ExportMixin
```
exportSettings: ExportSettings[]
exportAsync(settings?): P<Uint8Array>
exportAsync(settings: {format:'SVG_STRING',...}): P<string>
exportAsync(settings: {format:'JSON_REST_V1'}): P<Object>
// ExportSettings: {format:'PNG'|'JPG'|'SVG'|'PDF', constraint?: {type:'SCALE'|'WIDTH'|'HEIGHT', value}, contentsOnly?, suffix?}
```

### GeometryMixin (fills, strokes)
On every paintable node (frames, shapes, text — not groups/slices).
```
fills: Paint[]|mixed                             // READONLY array — reassign, don't push!
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
```
SolidPaint: {type:'SOLID', color:{r,g,b}, opacity?, visible?, blendMode?}
```
Hex → SolidPaint: `figma.util.solidPaint('#6366f1')` (see Utility above). Gradient / image / video paints → `references/api-styling.md` → Paint types.

## Top-level nodes

### DocumentNode
```
type: 'DOCUMENT' [ro]
children: PageNode[] [ro]
documentColorProfile: 'LEGACY'|'SRGB'|'DISPLAY_P3' [ro]
appendChild(page)/insertChild(index, page): void
findAll/findOne/findChildren/findChild/findAllWithCriteria
```

### PageNode
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

### SceneNode union
```
SceneNode = SliceNode | FrameNode | GroupNode | ComponentSetNode | ComponentNode |
  InstanceNode | BooleanOperationNode | VectorNode | StarNode | LineNode | EllipseNode |
  PolygonNode | RectangleNode | TextNode | TextPathNode | TransformGroupNode | SectionNode
```

## Common data types

```
Transform: [[a,b,tx],[c,d,ty]]
Vector: {x, y}   Rect: {x, y, width, height}
RGB: {r, g, b}   RGBA: {r, g, b, a}   FontName: {family, style}
User: {id, name, photoUrl, color, sessionId}
```

## Dynamic page access

With `"documentAccess": "dynamic-page"`, use async variants: `getInstancesAsync()`, `getMainComponentAsync()`, `setVectorNetworkAsync()`, `setReactionsAsync()`, `setFillStyleIdAsync()` / `setStrokeStyleIdAsync()` / `setEffectStyleIdAsync()`, `getStyleConsumersAsync()`. Non-current pages need `page.loadAsync()` first.
