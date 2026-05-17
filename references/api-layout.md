# API: Layout + shape nodes

Load for building screens, frames, shapes, and any task touching Auto Layout / sizing / constraints. See `references/layout-recipes.md` for ready-to-paste patterns (Button, Card, Input, List) and `references/building.md` for end-to-end build flows.

Cross-refs: `references/api-reference.md` for base mixins; `references/api-styling.md` for fills/strokes/effects; `references/api-components.md` for ComponentNode (which extends FrameNode).

## Create nodes (top-level)

```
figma.createRectangle(): RectangleNode
figma.createEllipse(): EllipseNode
figma.createPolygon(): PolygonNode
figma.createStar(): StarNode
figma.createLine(): LineNode
figma.createVector(): VectorNode
figma.createFrame(): FrameNode
figma.createSlice(): SliceNode
figma.createSection(): SectionNode
figma.createBooleanOperation(): BooleanOperationNode
figma.createNodeFromSvg(svg: string): FrameNode
figma.createNodeFromJSXAsync(jsx): P<SceneNode>
figma.createPage(): PageNode
```

## Group and boolean

```
figma.group(nodes, parent, index?): GroupNode
figma.ungroup(node): SceneNode[]
figma.union(nodes, parent, index?): BooleanOperationNode
figma.subtract(nodes, parent, index?): BooleanOperationNode
figma.intersect(nodes, parent, index?): BooleanOperationNode
figma.exclude(nodes, parent, index?): BooleanOperationNode
figma.flatten(nodes, parent?, index?): VectorNode
// figma.combineAsVariants → see api-components.md
```

## LayoutMixin (extends DimensionAndPosition in api-reference.md)

```
absoluteRenderBounds: Rect|null [ro]             // includes shadows/strokes
constrainProportions: boolean
rotation: number
layoutSizingHorizontal: 'FIXED'|'HUG'|'FILL'
layoutSizingVertical: 'FIXED'|'HUG'|'FILL'
resize(w, h): void
resizeWithoutConstraints(w, h): void
rescale(scale): void
// AutoLayoutChildrenMixin (on children of auto-layout frames):
layoutAlign: 'MIN'|'CENTER'|'MAX'|'STRETCH'|'INHERIT'
layoutGrow: number                               // 0=fixed, 1=fill (legacy; prefer layoutSizing*)
layoutPositioning: 'AUTO'|'ABSOLUTE'
```

## AutoLayoutMixin (on frames)

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

## GridLayoutMixin (CSS Grid on frames)

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

## ConstraintMixin

```
constraints: {horizontal, vertical}              // 'MIN'|'CENTER'|'MAX'|'STRETCH'|'SCALE'
// Ignored when parent has Auto Layout — use layoutSizing* instead.
```

## IndividualStrokesMixin

```
strokeTopWeight/strokeBottomWeight/strokeLeftWeight/strokeRightWeight: number
```

## CornerMixin + RectangleCornerMixin

```
cornerRadius: number|mixed
cornerSmoothing: number                          // 0-1, iOS-style
topLeftRadius/topRightRadius/bottomLeftRadius/bottomRightRadius: number
```

## ContainerMixin

```
expanded: boolean
```

## Node types

### FrameNode
```
type: 'FRAME' [ro]
// Inherits: AutoLayoutMixin, GeometryMixin (api-styling.md), BlendMixin (api-styling.md),
//   LayoutMixin, ChildrenMixin, CornerMixin, RectangleCornerMixin, IndividualStrokesMixin,
//   ConstraintMixin, ExportMixin, ReactionMixin (api-styling.md), FramePrototypingMixin (api-components.md)
clipsContent: boolean
layoutGrids: LayoutGrid[]
gridStyleId: string
guides: Guide[]
inferredAutoLayout: InferredAutoLayoutResult|null [ro]
```

### GroupNode
```
type: 'GROUP' [ro]
// Inherits: ChildrenMixin, BlendMixin, LayoutMixin, ExportMixin, ReactionMixin, ContainerMixin
```

### RectangleNode
```
type: 'RECTANGLE' [ro]
// Inherits: GeometryMixin, BlendMixin, LayoutMixin, ConstraintMixin, CornerMixin,
//   RectangleCornerMixin, IndividualStrokesMixin, ExportMixin, AnnotationsMixin
```

### EllipseNode
```
type: 'ELLIPSE' [ro]
arcData: {startingAngle, endingAngle, innerRadius}  // radians, innerRadius 0-1
// Inherits: GeometryMixin, BlendMixin, LayoutMixin, ConstraintMixin, CornerMixin, ExportMixin
```

### LineNode / PolygonNode / StarNode / VectorNode
```
// LineNode 'LINE' (height always 0); PolygonNode 'POLYGON' (pointCount);
// StarNode 'STAR' (pointCount, innerRadius 0-1); VectorNode 'VECTOR' (+ VectorLikeMixin)
// All inherit Geometry (api-styling.md), Blend (api-styling.md), Layout, Constraint, Export
// VectorPath: {windingRule: 'NONZERO'|'EVENODD'|'NONE', data: SVG-path-string}
//   e.g. node.vectorPaths = [{windingRule: "EVENODD", data: "M 0 0 L 100 0 L 50 100 Z"}]
// VectorNetwork (advanced): {vertices, segments, regions?}: cubic bezier with tangents
// GOTCHA: VectorNode position auto-adjusts to fit vertices; coords relative to node position
```

### VectorLikeMixin
```
vectorNetwork: VectorNetwork
setVectorNetworkAsync(vn): P<void>
vectorPaths: VectorPaths
handleMirroring: 'NONE'|'ANGLE'|'ANGLE_AND_LENGTH'|mixed
```

### BooleanOperationNode
```
type: 'BOOLEAN_OPERATION' [ro]
booleanOperation: 'UNION'|'INTERSECT'|'SUBTRACT'|'EXCLUDE'
// Inherits: ChildrenMixin, GeometryMixin, BlendMixin, CornerMixin
```

### SliceNode / SectionNode
```
// SliceNode 'SLICE': LayoutMixin + ExportMixin (no fills/strokes/effects)
// SectionNode 'SECTION': ChildrenMixin + MinimalFillsMixin. sectionContentsHidden: boolean
```

### TextNode → see `references/api-text.md`

### ComponentNode / ComponentSetNode / InstanceNode → see `references/api-components.md`

## Data types

```
LayoutGrid: {pattern:'ROWS'|'COLUMNS', alignment:'MIN'|'MAX'|'STRETCH'|'CENTER',
             gutterSize, count, sectionSize?, offset?, visible?, color?}
           | {pattern:'GRID', sectionSize, visible?, color?}
GridTrackSize: {value?, type: 'FLEX'|'FIXED'|'HUG'}
Guide: {axis: 'X'|'Y', offset: number}
// Vector, Rect, Transform → see api-reference.md → Common data types
```
