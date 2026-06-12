# API: Components, instances, variables, styles

Load for component creation, variant work, instance overrides, variables, styles, and any design-system task. See `references/building.md` → Component variants for end-to-end patterns and `references/conventions.md` for naming/atomic-design rules.

Cross-refs: `references/api-reference.md` for base mixins; `references/api-layout.md` for FrameNode (which Components inherit from); `references/api-styling.md` for fills/strokes/effects mixins.

## Create (top-level)

```
figma.createComponent(): ComponentNode
figma.createComponentFromNode(node: SceneNode): ComponentNode
// ComponentSet: no createComponentSet() — use figma.combineAsVariants(variants, parent, index?)
// Instance: component.createInstance()
```

## ComponentNode

```
type: 'COMPONENT' [ro]
// Inherits all FrameNode props (see api-layout.md) + PublishableMixin + VariantMixin
//   + ComponentPropertiesMixin
createInstance(): InstanceNode
createSlot(): SlotNode
getInstancesAsync(): P<InstanceNode[]>
instances: InstanceNode[] [ro]                   // throws with dynamic-page: use getInstancesAsync
// VariantMixin.variantProperties (DEPRECATED, use componentProperties)
```

## ComponentSetNode

```
type: 'COMPONENT_SET' [ro]
// No figma.createComponentSet()! Use figma.combineAsVariants(components, parent, index?)
defaultVariant: ComponentNode [ro]
variantGroupProperties: {[prop]: {values: string[]}} [ro]
// + PublishableMixin, ComponentPropertiesMixin
```

## InstanceNode

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
// Subtree is structurally frozen — no appendChild/insertChild/remove/reorder inside an
//   instance. Use overrides, setProperties, swapComponent, edit the main component, or
//   detachInstance() as a last resort.
```

## ComponentPropertiesMixin

```
componentPropertyDefinitions: ComponentPropertyDefinitions [ro]
addComponentProperty(name, type, defaultValue, opts?): string  // returns name with #id suffix
editComponentProperty(name, newValue): string
deleteComponentProperty(name): void
// ComponentPropertyType: 'BOOLEAN'|'TEXT'|'INSTANCE_SWAP'|'VARIANT'
// BOOLEAN/TEXT/INSTANCE_SWAP names are #id-suffixed (e.g. 'Label#4:0').
// Use the full suffixed name in setProperties / editComponentProperty.
// VARIANT names take priority on collision.
```

## PublishableMixin (components, styles)

```
description: string
descriptionMarkdown: string
documentationLinks: DocumentationLink[] [ro]
remote: boolean [ro]
key: string [ro]
getPublishStatusAsync(): P<'UNPUBLISHED'|'CURRENT'|'CHANGED'>
```

## FramePrototypingMixin (on frames/components)

```
overflowDirection: 'NONE'|'HORIZONTAL'|'VERTICAL'|'BOTH'
numberOfFixedChildren: number
overlayPositionType: OverlayPositionType [ro]
overlayBackground: OverlayBackground [ro]
overlayBackgroundInteraction: 'NONE'|'CLOSE_ON_CLICK_OUTSIDE' [ro]
```

## Variables (`figma.variables`)

```
.createVariable(name, collectionOrId, resolvedType): Variable
.createVariableCollection(name): VariableCollection
.createVariableAlias(variable): VariableAlias
.createVariableAliasByIdAsync(variableId): P<VariableAlias>
.getVariableByIdAsync(id): P<Variable|null>
.getVariableCollectionByIdAsync(id): P<VariableCollection|null>
.getLocalVariablesAsync(type?): P<Variable[]>
.getLocalVariableCollectionsAsync(): P<VariableCollection[]>
.importVariableByKeyAsync(key): P<Variable>
.extendLibraryCollectionByKeyAsync(key, name): P<...>   // Enterprise
.setBoundVariableForPaint|Effect|LayoutGrid(item, field, variable|null)
//   Each RETURNS A NEW object — reassign the result into fills/effects/layoutGrids,
//   or the binding is a silent no-op.
// ResolvedType: 'BOOLEAN'|'COLOR'|'FLOAT'|'STRING'
```

### Variable object
```
id/key: string [ro]
name: string
description: string
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
setVariableCodeSyntax(platform, value)
removeVariableCodeSyntax(platform)
```

### VariableCollection object
```
id/key/defaultModeId: string [ro]
name: string
modes: [{modeId, name}] [ro]
variableIds: string[] [ro]
remote/isExtension: boolean [ro]
hiddenFromPublishing: boolean
addMode(name): string                            // returns modeId
renameMode(modeId, name)/removeMode(modeId)/remove(): void
// Extended collections (Enterprise): collection.extend(name),
//   valuesByModeForCollectionAsync, removeOverrideForMode,
//   variableOverrides, removeOverridesForVariable
```

### Scopes and bindable fields
```
VariableScope: 'ALL_SCOPES'|'TEXT_CONTENT'|'CORNER_RADIUS'|'WIDTH_HEIGHT'|'GAP'|
  'FRAME_FILL'|'SHAPE_FILL'|'TEXT_FILL'|'STROKE_*'|'EFFECT_*'|'OPACITY'|'FONT_*'|
  'LINE_HEIGHT'|'LETTER_SPACING'|'PARAGRAPH_*'

VariableBindableNodeField: height/width/characters/itemSpacing/padding*/visible/
  *Radius/min|maxWidth|Height/counterAxisSpacing/stroke*Weight/opacity/
  gridRow|ColumnGap

VariableBindableTextField: fontFamily/fontSize/fontStyle/fontWeight/letterSpacing/
  lineHeight/paragraph*

VariableAlias: {type:'VARIABLE_ALIAS', id: string}
VariableValue: boolean|string|number|RGB|RGBA|VariableAlias
```

## Team library (`figma.teamLibrary`)

```
.getAvailableLibraryVariableCollectionsAsync(): P<LibraryVariableCollection[]>
.getVariablesInLibraryCollectionAsync(key): P<LibraryVariable[]>
```

## Styles

### Top-level create / get
```
figma.create{Paint|Text|Effect|Grid}Style(): Style
figma.getLocal{Paint|Text|Effect|Grid}StylesAsync(): P<Style[]>
figma.getStyleByIdAsync(id), .importStyleByKeyAsync(key)
figma.importComponentByKeyAsync(key), .importComponentSetByKeyAsync(key)
figma.getSelectionColors(): {paints, styles}|null
```

### Style objects
```
// BaseStyleMixin: id, name, type, remove() + PublishableMixin + consumers / getStyleConsumersAsync()
// PaintStyle  'PAINT': paints: Paint[]
// TextStyle   'TEXT':  typography props + setBoundVariable(field, var)
// EffectStyle 'EFFECT': effects: Effect[]
// GridStyle   'GRID':  layoutGrids: LayoutGrid[]
// All support boundVariables [ro]
```

## AnnotationsMixin (on nodes)

```
annotations: Annotation[] [ro]
// node.annotations = newArray;   // readonly array — clone, push, reassign
// See figma.annotations in api-reference.md → Annotations for categories.
```

## `figma.combineAsVariants`

```
figma.combineAsVariants(components: ComponentNode[], parent, index?): ComponentSetNode
// VARIANT properties derive from 'Prop=Value' node names set BEFORE combining.
// BOOLEAN/TEXT/INSTANCE_SWAP properties: add on the ComponentSet AFTER combining
//   (they cannot be added to a variant inside a set).
```
