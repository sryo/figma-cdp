# Figma Plugin API Reference

Source: [`@figma/plugin-typings`](https://github.com/figma/plugin-typings/blob/master/plugin-api.d.ts)
Notation: `[ro]` = readonly, `P<T>` = Promise<T>, types after `//` are abbreviated.

## Quick Lookup — Most Used

```
figma.createFrame(): FrameNode              figma.createText(): TextNode
figma.createRectangle(): RectangleNode      figma.createEllipse(): EllipseNode
figma.createComponent(): ComponentNode      figma.createNodeFromSvg(svg): FrameNode
figma.getNodeByIdAsync(id): P<BaseNode>     figma.loadFontAsync({family, style}): P<void>
figma.createImage(bytes): Image             figma.createImageAsync(url): P<Image>
figma.base64Encode(bytes): string           figma.commitUndo(): void
figma.viewport.scrollAndZoomIntoView(nodes) figma.currentPage: PageNode

node.fills = [{type:'SOLID', color:{r,g,b}}]   // clone before mutating!
node.layoutMode = 'VERTICAL'|'HORIZONTAL'       // enables Auto Layout
node.layoutSizingHorizontal = 'FILL'|'HUG'|'FIXED'
node.appendChild(child)                          // verify parent after!
node.exportAsync({format:'PNG', constraint:{type:'SCALE', value:2}}): P<Uint8Array>
node.findAllWithCriteria({types:['TEXT']}): SceneNode[]  // fast native C++ filter
```

## Table of Contents

- [figma Global](#figma-global) — Properties, create nodes, find/navigate, fonts/images, styles, variables, events, lifecycle
- [Mixins](#mixins) — BaseNode, SceneNode, Children, Layout, AutoLayout, Geometry, Blend, Corner, Constraint, Export
- [Node Types](#node-types) — Document, Page, Frame, Text, Component, Instance, shapes
- [Style Objects](#style-objects) — Paint, Text, Effect, Grid styles
- [Variable Objects](#variable-objects) — Variable, VariableCollection, scopes, bindings
- [Data Types](#data-types) — Paint, Effect, Prototype, Layout types

## figma Global

### Properties
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

### Create Nodes
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

### Find & Navigate
```
figma.getNodeByIdAsync(id): P<BaseNode|null>
figma.getNodesByIdAsync(ids): P<(BaseNode|null)[]>
figma.getNodeById(id): BaseNode|null             // DEPRECATED
figma.setCurrentPageAsync(page): P<void>
figma.loadAllPagesAsync(): P<void>
```

### Group & Boolean
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

### Fonts, Images, Media
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

### Styles
```
figma.create{Paint|Text|Effect|Grid}Style()
figma.getLocal{Paint|Text|Effect|Grid}StylesAsync(): P<Style[]>
figma.getStyleByIdAsync(id), .importStyleByKeyAsync(key)
figma.importComponentByKeyAsync(key), .importComponentSetByKeyAsync(key)
figma.getSelectionColors(): {paints, styles}|null
```

### Variables (`figma.variables`)
```
.createVariable(name, collectionOrId, resolvedType), .createVariableCollection(name)
.createVariableAlias(variable), .createVariableAliasByIdAsync(variableId)
.getVariableByIdAsync(id), .getVariableCollectionByIdAsync(id)
.getLocalVariablesAsync(type?), .getLocalVariableCollectionsAsync()
.importVariableByKeyAsync(key), .extendLibraryCollectionByKeyAsync(key, name) // Enterprise
.setBoundVariableForPaint|Effect|LayoutGrid(item, field, variable|null)
// ResolvedType: 'BOOLEAN'|'COLOR'|'FLOAT'|'STRING'
```

### Team Library (`figma.teamLibrary`)
```
.getAvailableLibraryVariableCollectionsAsync(): P<LibraryVariableCollection[]>
.getVariablesInLibraryCollectionAsync(key): P<LibraryVariable[]>
```

### Client Storage (`figma.clientStorage`) — 5MB limit, local to machine
```
.getAsync(key): P<any>
.setAsync(key, value): P<void>
.deleteAsync(key): P<void>
.keysAsync(): P<string[]>
```

### UI (`figma.ui`)
```
figma.showUI(html, options?)  // {width?, height?, visible?, title?, position?, themeColors?}
figma.ui.show() / .hide() / .close() / .resize(w,h) / .reposition(x,y) / .postMessage(msg, opts?)
figma.ui.on / .once / .off ('message', (msg, props) => void)  // props.origin
// iframe sends: parent.postMessage({pluginMessage: data}, '*')
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

### Events
```
figma.on / .once / .off (event, callback)
// No-arg events: 'selectionchange'|'currentpagechange'|'close'
// With event arg: 'run'|'drop'|'documentchange'|'stylechange'|'textreview'|
//   'timerstart'|'timerpause'|'timerresume'|'timerstop'|'timeradjust'|'timerdone'
// 'drop' cb returns false to prevent default. DropEvent: {node, x, y, absoluteX, absoluteY, items, files, dropMetadata?}
// DocumentChange: {type: CREATE|DELETE|PROPERTY_CHANGE|STYLE_*, id, node|style, origin: 'LOCAL'|'REMOTE'}
// NOTE: callbacks run async — code after figma.on() executes before callback fires
```

### Lifecycle
```
figma.notify(msg, opts?): NotificationHandler    // opts: {timeout?, error?, button?: {text, action}}
figma.commitUndo(): void
figma.triggerUndo(): void
figma.saveVersionHistoryAsync(title, desc?): P<VersionHistoryResult>
figma.openExternal(url): void
figma.closePlugin(msg?): void                    // NEVER call in automation
```

### Annotations (`figma.annotations`)
```
.getAnnotationCategoriesAsync() / .getAnnotationCategoryByIdAsync(id) / .addAnnotationCategoryAsync({label, color})
// Color: 'yellow'|'orange'|'red'|'pink'|'violet'|'blue'|'teal'|'green'
```

## Mixins

### BaseNodeMixin (all nodes)
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
findAllWithCriteria({types?, pluginData?, sharedPluginData?}): SceneNode[]
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

### LayoutMixin (extends DimensionAndPosition)
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

### AutoLayoutMixin (on frames)
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

### GridLayoutMixin (CSS Grid on frames)
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

### GeometryMixin
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

### IndividualStrokesMixin
```
strokeTopWeight/strokeBottomWeight/strokeLeftWeight/strokeRightWeight: number
```

### BlendMixin
```
opacity: number                                  // 0-1
blendMode: BlendMode
isMask: boolean
maskType: 'ALPHA'|'VECTOR'|'LUMINANCE'
effects: Effect[]
effectStyleId: string
setEffectStyleIdAsync(id): P<void>
```

### CornerMixin + RectangleCornerMixin
```
cornerRadius: number|mixed
cornerSmoothing: number                          // 0-1, iOS-style
topLeftRadius/topRightRadius/bottomLeftRadius/bottomRightRadius: number
```

### ConstraintMixin
```
constraints: {horizontal, vertical}              // 'MIN'|'CENTER'|'MAX'|'STRETCH'|'SCALE'
```

### ExportMixin
```
exportSettings: ExportSettings[]
exportAsync(settings?): P<Uint8Array>
exportAsync(settings: {format:'SVG_STRING',...}): P<string>
exportAsync(settings: {format:'JSON_REST_V1'}): P<Object>
// ExportSettings: {format:'PNG'|'JPG'|'SVG'|'PDF', constraint?: {type:'SCALE'|'WIDTH'|'HEIGHT', value}, contentsOnly?, suffix?}
```

### Other Mixins
```
// ReactionMixin: reactions [ro], setReactionsAsync(reactions)
// PublishableMixin: description, descriptionMarkdown, documentationLinks [ro], remote [ro], key [ro], getPublishStatusAsync()
// ComponentPropertiesMixin: componentPropertyDefinitions [ro], addComponentProperty(), editComponentProperty(), deleteComponentProperty()
// FramePrototypingMixin: overflowDirection, numberOfFixedChildren, overlayPositionType [ro], overlayBackground [ro]
// VectorLikeMixin: vectorNetwork, setVectorNetworkAsync(), vectorPaths, handleMirroring
// ContainerMixin: expanded
// AnnotationsMixin: annotations [ro]
```

## Node Types

### Mixin Inheritance (thin nodes)
- `GroupNode` `'GROUP'` — Children, Blend, Layout, Export, Reaction, Container
- `RectangleNode` `'RECTANGLE'` — Geometry, Blend, Layout, Constraint, Corner, RectangleCorner, IndividualStrokes, Export, Annotations
- `SliceNode` `'SLICE'` — Layout, Export (no fills/strokes/effects)
- `BooleanOperationNode` `'BOOLEAN_OPERATION'` — Children, Geometry, Blend, Corner. Extra: `booleanOperation: 'UNION'|'INTERSECT'|'SUBTRACT'|'EXCLUDE'`
- `SectionNode` `'SECTION'` — Children, MinimalFills. Extra: `sectionContentsHidden: boolean`

For full mixin inheritance, see `@figma/plugin-typings`.

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

### FrameNode
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

### EllipseNode
```
type: 'ELLIPSE' [ro]
arcData: {startingAngle, endingAngle, innerRadius}  // radians, innerRadius 0-1
```

### LineNode / PolygonNode / StarNode / VectorNode
```
// LineNode 'LINE' (height always 0); PolygonNode 'POLYGON' (pointCount);
// StarNode 'STAR' (pointCount, innerRadius 0-1); VectorNode 'VECTOR' (+ VectorLikeMixin)
// All inherit Geometry, Blend, Layout, Constraint, Export
// VectorPath: {windingRule: 'NONZERO'|'EVENODD'|'NONE', data: SVG-path-string}
//   e.g. node.vectorPaths = [{windingRule: "EVENODD", data: "M 0 0 L 100 0 L 50 100 Z"}]
// VectorNetwork (advanced): {vertices, segments, regions?} — cubic bezier with tangents
// GOTCHA: VectorNode position auto-adjusts to fit vertices; coords relative to node position
```

### TextNode
```
type: 'TEXT' [ro]
// MUST load font before modifying layout-affecting props:
//   REQUIRE font: characters, fontSize, fontName, textStyleId, textCase, textDecoration, letterSpacing, lineHeight
//   NO font needed: fills, strokes, strokeWeight, opacity, blendMode, visible
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
//   get/setRange{FontSize|FontName|Fills|TextDecoration|TextCase|LetterSpacing|
//     LineHeight|ListOptions|Indentation|Hyperlink}(start, end, value?)
//   setRangeBoundVariable(start, end, field, variable|null)
//   insertCharacters(start, chars, useStyle?:'BEFORE'|'AFTER')
//   deleteCharacters(start, end)
//   getStyledTextSegments(fields, start?, end?), getRangeAllFontNames(start, end)
```

### ComponentNode
```
type: 'COMPONENT' [ro]
// Inherits all FrameNode props + PublishableMixin + VariantMixin + ComponentPropertiesMixin
createInstance(): InstanceNode
createSlot(): SlotNode
getInstancesAsync(): P<InstanceNode[]>
instances: InstanceNode[] [ro]                   // throws with dynamic-page — use getInstancesAsync
// VariantMixin.variantProperties (DEPRECATED, use componentProperties)
// ComponentPropertiesMixin: componentPropertyDefinitions [ro], addComponentProperty/
//   editComponentProperty/deleteComponentProperty. BOOLEAN/TEXT/INSTANCE_SWAP props
//   auto-suffixed with #uniqueId — use full name (with #) in setProperties/editComponentProperty.
//   VARIANT props have priority on name collision.
```

### ComponentSetNode
```
type: 'COMPONENT_SET' [ro]
// No figma.createComponentSet()! Use figma.combineAsVariants(components, parent)
defaultVariant: ComponentNode [ro]
variantGroupProperties: {[prop]: {values: string[]}} [ro]
// + PublishableMixin, ComponentPropertiesMixin
```

### InstanceNode
```
type: 'INSTANCE' [ro]
mainComponent: ComponentNode|null                // setting clears ALL overrides
getMainComponentAsync(): P<ComponentNode|null>   // required for dynamic-page
swapComponent(comp): void                        // preserves overrides via heuristics
detachInstance(): FrameNode                      // also detaches ancestor instances
setProperties({propName: value}): void           // use full name#id for non-VARIANT
componentProperties [ro], scaleFactor, exposedInstances [ro], isExposedInstance
overrides: [{id, overriddenFields}] [ro]         // direct only, not inherited
removeOverrides(): void                          // resetOverrides() is DEPRECATED
// Inherits FrameNode + VariantMixin. PERF: don't alternate component writes + instance reads.
```

## Style Objects
```
// BaseStyleMixin: id, name, type, remove() + PublishableMixin + consumers / getStyleConsumersAsync()
// PaintStyle 'PAINT': paints. TextStyle 'TEXT': typography props + setBoundVariable.
// EffectStyle 'EFFECT': effects. GridStyle 'GRID': layoutGrids. All: boundVariables [ro]
```

## Variable Objects
```
// Variable: id/key, name, description, resolvedType: 'BOOLEAN'|'COLOR'|'FLOAT'|'STRING',
//   variableCollectionId, valuesByMode, scopes: VariableScope[], codeSyntax: {WEB?, ANDROID?, iOS?}
//   .setValueForMode(modeId, value), .resolveForConsumer(node), .remove()
//   .setVariableCodeSyntax(platform, value), .removeVariableCodeSyntax(platform)
// VariableCollection: id/key/defaultModeId, name, modes: [{modeId, name}], variableIds
//   .addMode(name) → modeId, .renameMode/removeMode/remove
// Extended collections (Enterprise): collection.extend(name), valuesByModeForCollectionAsync,
//   removeOverrideForMode, variableOverrides, removeOverridesForVariable
// VariableScope: 'ALL_SCOPES'|'TEXT_CONTENT'|'CORNER_RADIUS'|'WIDTH_HEIGHT'|'GAP'|
//   'FRAME_FILL'|'SHAPE_FILL'|'TEXT_FILL'|'STROKE_*'|'EFFECT_*'|'OPACITY'|'FONT_*'|
//   'LINE_HEIGHT'|'LETTER_SPACING'|'PARAGRAPH_*'
// Bindable fields: node — height/width/characters/itemSpacing/padding*/visible/*Radius/
//   min|maxWidth|Height/counterAxisSpacing/stroke*Weight/opacity/gridRow|ColumnGap
//   text — fontFamily/fontSize/fontStyle/fontWeight/letterSpacing/lineHeight/paragraph*
```

## Data Types

### Paint
```
SolidPaint: {type:'SOLID', color:{r,g,b}, opacity?, visible?, blendMode?}
GradientPaint: {type:'GRADIENT_LINEAR'|'GRADIENT_RADIAL'|'GRADIENT_ANGULAR'|'GRADIENT_DIAMOND',
  gradientStops:[{position:0-1, color:{r,g,b,a}}], gradientTransform}
ImagePaint: {type:'IMAGE', scaleMode:'FILL'|'FIT'|'CROP'|'TILE', imageHash, imageTransform?, filters?}
VideoPaint: {type:'VIDEO', scaleMode, videoHash}
```

### Effect
```
DropShadowEffect: {type:'DROP_SHADOW', color:RGBA, offset:{x,y}, radius, spread?, visible, blendMode, showShadowBehindNode?}
InnerShadowEffect: {type:'INNER_SHADOW', color:RGBA, offset:{x,y}, radius, spread?, visible, blendMode}
BlurEffect: {type:'LAYER_BLUR'|'BACKGROUND_BLUR', radius, visible}
  // Progressive variant (Beta): {blurType:'PROGRESSIVE', startRadius, startOffset:Vector, endOffset:Vector}
  //   offsets normalized (0,0)=top-left, (1,1)=bottom-right
// Beta effects (rare): NoiseEffect, TextureEffect, GlassEffect — see plugin-typings if needed
```

### Prototype Types
```
Reaction: {trigger, action?, actions?}
Trigger: 'ON_CLICK'|'ON_HOVER'|'ON_PRESS'|'ON_DRAG'|{type:'AFTER_TIMEOUT'|'MOUSE_*'|'ON_KEY_DOWN'|'ON_MEDIA_*', ...}
Action: 'BACK'|'CLOSE'|{type:'URL'|'NODE'|'SET_VARIABLE'|'SET_VARIABLE_MODE'|'CONDITIONAL'|'UPDATE_MEDIA_RUNTIME', ...}
Navigation: 'NAVIGATE'|'SWAP'|'OVERLAY'|'SCROLL_TO'|'CHANGE_TO'
Transition: {type:'DISSOLVE'|'SMART_ANIMATE'|'MOVE_IN'|'MOVE_OUT'|'PUSH'|'SLIDE_IN'|'SLIDE_OUT', easing, duration, direction?}
Easing: {type:'EASE_IN|OUT|IN_AND_OUT'|'LINEAR'|'GENTLE'|'QUICK'|'BOUNCY'|'SLOW'|'CUSTOM_CUBIC_BEZIER'|'CUSTOM_SPRING', ...}
```

### Layout Types
```
LayoutGrid: {pattern:'ROWS'|'COLUMNS', alignment:'MIN'|'MAX'|'STRETCH'|'CENTER', gutterSize, count, sectionSize?, offset?, visible?, color?}
  | {pattern:'GRID', sectionSize, visible?, color?}
Transform: [[a,b,tx],[c,d,ty]]
Vector: {x, y}   Rect: {x, y, width, height}
RGB: {r, g, b}   RGBA: {r, g, b, a}   FontName: {family, style}
```

### Other Types
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
SceneNode = SliceNode | FrameNode | GroupNode | ComponentSetNode | ComponentNode |
  InstanceNode | BooleanOperationNode | VectorNode | StarNode | LineNode | EllipseNode |
  PolygonNode | RectangleNode | TextNode | TextPathNode | TransformGroupNode | SectionNode
```

## Dynamic Page Access & Image Constraints

With `"documentAccess": "dynamic-page"`, use async variants: `getInstancesAsync()`, `getMainComponentAsync()`, `setVectorNetworkAsync()`, `setReactionsAsync()`, `setFillStyleIdAsync()` / `setStrokeStyleIdAsync()` / `setEffectStyleIdAsync()`, `getStyleConsumersAsync()`. Non-current pages need `page.loadAsync()` first.

Images: PNG/JPG/GIF, max 4096×4096, live as node fills (not standalone). CORS can block `createImageAsync(url)` — use base64 bytes if so.
