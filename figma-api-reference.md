# Figma Plugin API Reference

Source: [`@figma/plugin-typings`](https://github.com/figma/plugin-typings/blob/master/plugin-api.d.ts)
Notation: `[ro]` = readonly, `P<T>` = Promise<T>, types after `//` are abbreviated.

<api_reference>

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

### Variables (`figma.variables`)
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
figma.showUI(html, options?): void
// ShowUIOptions: {width?, height?, visible?, title?, position?: {x,y}, themeColors?}
figma.ui.show() / .hide() / .close()
figma.ui.resize(w, h) / .reposition(x, y)
figma.ui.postMessage(msg, options?): void
figma.ui.on('message', (msg, props) => void)  // props.origin
figma.ui.once(...) / .off(...)
// iframe sends: parent.postMessage({pluginMessage: data}, '*')
```

### Viewport
```
figma.viewport.center: Vector                    // get/set
figma.viewport.zoom: number                      // get/set
figma.viewport.bounds: Rect [ro]
figma.viewport.scrollAndZoomIntoView(nodes): void
```

### Utility (`figma.util`)
```
.rgb(color: string|RGB|RGBA): RGB                // parse hex/rgb/hsl
.rgba(color: string|RGB|RGBA): RGBA
.solidPaint(color, overrides?): SolidPaint
```

### Events
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
.getAnnotationCategoriesAsync(): P<AnnotationCategory[]>
.getAnnotationCategoryByIdAsync(id): P<AnnotationCategory|null>
.addAnnotationCategoryAsync({label, color}): P<AnnotationCategory>
// AnnotationCategoryColor: 'yellow'|'orange'|'red'|'pink'|'violet'|'blue'|'teal'|'green'
```

## Mixins (Shared Node Properties)

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

### ReactionMixin (prototype interactions)
```
reactions: Reaction[] [ro]
setReactionsAsync(reactions): P<void>
```

### PublishableMixin (components, styles)
```
description: string
descriptionMarkdown: string
documentationLinks: DocumentationLink[] [ro]
remote: boolean [ro]
key: string [ro]
getPublishStatusAsync(): P<'UNPUBLISHED'|'CURRENT'|'CHANGED'>
```

### ComponentPropertiesMixin
```
componentPropertyDefinitions: ComponentPropertyDefinitions [ro]
addComponentProperty(name, type, defaultValue, opts?): string
editComponentProperty(name, newValue): string
deleteComponentProperty(name): void
// ComponentPropertyType: 'BOOLEAN'|'TEXT'|'INSTANCE_SWAP'|'VARIANT'
```

### FramePrototypingMixin
```
overflowDirection: 'NONE'|'HORIZONTAL'|'VERTICAL'|'BOTH'
numberOfFixedChildren: number
overlayPositionType: OverlayPositionType [ro]
overlayBackground: OverlayBackground [ro]
overlayBackgroundInteraction: 'NONE'|'CLOSE_ON_CLICK_OUTSIDE' [ro]
```

### VectorLikeMixin
```
vectorNetwork: VectorNetwork
setVectorNetworkAsync(vn): P<void>
vectorPaths: VectorPaths
handleMirroring: 'NONE'|'ANGLE'|'ANGLE_AND_LENGTH'|mixed
```

### Other Mixins
```
// ContainerMixin
expanded: boolean
// AnnotationsMixin
annotations: Annotation[] [ro]
```

## Node Types

### Mixin Inheritance (thin nodes)
| Node | Type | Mixins | Extra |
|------|------|--------|-------|
| GroupNode | `'GROUP'` | ChildrenMixin, BlendMixin, LayoutMixin, ExportMixin, ReactionMixin, ContainerMixin | — |
| RectangleNode | `'RECTANGLE'` | GeometryMixin, BlendMixin, LayoutMixin, ConstraintMixin, CornerMixin, RectangleCornerMixin, IndividualStrokesMixin, ExportMixin, AnnotationsMixin | — |
| SliceNode | `'SLICE'` | LayoutMixin, ExportMixin | no fills/strokes/effects |
| BooleanOperationNode | `'BOOLEAN_OPERATION'` | ChildrenMixin, GeometryMixin, BlendMixin, CornerMixin | `booleanOperation: 'UNION'\|'INTERSECT'\|'SUBTRACT'\|'EXCLUDE'` |
| SectionNode | `'SECTION'` | ChildrenMixin, MinimalFillsMixin | `sectionContentsHidden: boolean` |

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
// Inherits: GeometryMixin, BlendMixin, LayoutMixin, ConstraintMixin, CornerMixin, ExportMixin
```

### LineNode / PolygonNode / StarNode / VectorNode
```
// LineNode: type 'LINE', height always 0
// PolygonNode: type 'POLYGON', pointCount: number
// StarNode: type 'STAR', pointCount: number, innerRadius: number (0-1)
// VectorNode: type 'VECTOR', extends VectorLikeMixin
// All inherit: GeometryMixin, BlendMixin, LayoutMixin, ConstraintMixin, ExportMixin
```

### TextNode
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

### ComponentNode
```
type: 'COMPONENT' [ro]
// Inherits all FrameNode props + PublishableMixin + VariantMixin + ComponentPropertiesMixin
createInstance(): InstanceNode
getInstancesAsync(): P<InstanceNode[]>
instances: InstanceNode[] [ro]
// VariantMixin: variantProperties: {[prop]: value}|null [ro]
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

## Style Objects
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

## Variable Objects
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
```

### Prototype Types
```
Reaction: {trigger, action?, actions?}
Trigger: 'ON_CLICK'|'ON_HOVER'|'ON_PRESS'|'ON_DRAG'|{type:'AFTER_TIMEOUT', timeout}|{type:'MOUSE_*', delay}|{type:'ON_KEY_DOWN', device, keyCodes}|{type:'ON_MEDIA_*'}
Action: 'BACK'|'CLOSE'|{type:'URL', url}|{type:'NODE', destinationId, navigation, transition, ...}|{type:'SET_VARIABLE'|'SET_VARIABLE_MODE'|'CONDITIONAL'|'UPDATE_MEDIA_RUNTIME', ...}
Navigation: 'NAVIGATE'|'SWAP'|'OVERLAY'|'SCROLL_TO'|'CHANGE_TO'
Transition: {type:'DISSOLVE'|'SMART_ANIMATE'|'MOVE_IN'|'MOVE_OUT'|'PUSH'|'SLIDE_IN'|'SLIDE_OUT', easing, duration, direction?}
Easing: {type:'EASE_IN'|'EASE_OUT'|'EASE_IN_AND_OUT'|'LINEAR'|'GENTLE'|'QUICK'|'BOUNCY'|'SLOW'|'CUSTOM_CUBIC_BEZIER'|'CUSTOM_SPRING', ...}
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
```

### SceneNode Union
```
SceneNode = SliceNode | FrameNode | GroupNode | ComponentSetNode | ComponentNode |
  InstanceNode | BooleanOperationNode | VectorNode | StarNode | LineNode | EllipseNode |
  PolygonNode | RectangleNode | TextNode | TextPathNode | TransformGroupNode | SectionNode
```

</api_reference>
