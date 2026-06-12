# Building and mutating Figma designs

How to create and modify design nodes via the Plugin API.

## Component workflow

See `references/conventions.md` for atomic design hierarchy, naming (`Atoms/…`, `Molecules/…`, `Screens/…`), and page structure. Always prefer `component.createInstance()` over recreating structures, and `instance.swapComponent(target)` over rebuilding nested components. Verify visually with `node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}})`.

## Constraints and sizing

### Auto Layout components (preferred)
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

// Child hugs its own content. `HUG` is only valid on auto-layout frames (`layoutMode != 'NONE'`) and text nodes; setting it elsewhere throws.
child.layoutSizingHorizontal = 'HUG';
child.layoutSizingVertical = 'HUG';
```

For named component recipes (Button, Card, Input, List), absolute positioning, fixed-frame constraints (when parent is `layoutMode = 'NONE'`), and the key sizing rules (`FILL` requires auto-layout parent, `HUG` only valid on auto-layout frames and text nodes, legacy `layoutGrow`), see `references/layout-recipes.md`. For `FILL`-after-`appendChild` and `resize`-before-sizing-modes, see `references/gotchas.md` #1 and #12.

## Post-mutation validation

After each mutation, verify before moving on. Assertion patterns live in `references/execution.md` → Assertion Verification. Spot-check: layout/padding/itemSpacing, typography (watch for `figma.mixed`), colors (0-1 range), hierarchy (`child.parent.id`), layoutSizing on auto-layout children, `imageHash` on image fills. Visual export:
```js
var bytes = await node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}});
figma.base64Encode(bytes);
```

## Component variants

Pattern for creating a component set with variants. VARIANT properties derive from `Prop=Value` node names set BEFORE combining; BOOLEAN/TEXT/INSTANCE_SWAP properties are added on the ComponentSet AFTER combining (they cannot be added to a variant inside a set):
```js
// Create variant components — name them 'Prop=Value' BEFORE combining
var primary = figma.createComponent();
primary.name = 'Style=Primary';
primary.resize(120, 40);
primary.layoutMode = 'HORIZONTAL';
primary.primaryAxisAlignItems = 'CENTER';
primary.counterAxisAlignItems = 'CENTER';
primary.fills = [{type: 'SOLID', color: {r: 0.15, g: 0.4, b: 0.95}}];
primary.cornerRadius = 8;

var secondary = primary.clone();
secondary.name = 'Style=Secondary';
secondary.fills = [{type: 'SOLID', color: {r: 0.9, g: 0.9, b: 0.9}}];

// Combine into variant set
var buttonSet = figma.combineAsVariants([primary, secondary], figma.currentPage);
buttonSet.name = 'Button';

// Add a boolean property — on the ComponentSet, AFTER combining
buttonSet.addComponentProperty('Disabled', 'BOOLEAN', false);
// NOTE: returns name with #id suffix, e.g. 'Disabled#1:23'
```

Working with instances:
```js
var instance = primary.createInstance();
instance.setProperties({'Style': 'Secondary'});  // switch variant
// For BOOLEAN/TEXT props, use full name with #suffix from componentPropertyDefinitions
```

## Instance overrides

Reading and modifying instance overrides:
```js
var inst = await figma.getNodeByIdAsync('INSTANCE_ID');
var main = await inst.getMainComponentAsync();

// Read current overrides
var overrides = inst.overrides; // [{id, overriddenFields}]

// Find nested text and override it (compound predicate: filter by type natively, then by name in JS)
var label = inst.findAllWithCriteria({types: ['TEXT']}).find(function(n) { return n.name === 'Label'; });
if (label) {
  // Load the instance's actual font, not a hardcoded one (for mixed fonts: copy.md → Font loading pattern)
  if (label.fontName !== figma.mixed) {
    await figma.loadFontAsync(label.fontName);
  }
  label.characters = 'New Label';
}

// Swap a nested component instance (type-only predicate)
var icon = inst.findAllWithCriteria({types: ['INSTANCE']})[0];
if (icon) {
  var newComp = await figma.importComponentByKeyAsync('COMPONENT_KEY');
  icon.swapComponent(newComp); // preserves overrides
}

// Reset all overrides
inst.removeOverrides();
```

## Image fills

Applying images to nodes:
```js
// From URL (may hit CORS: use bytes if blocked)
var image = await figma.createImageAsync('https://example.com/photo.jpg');
var rect = figma.createRectangle();
rect.resize(400, 300);
rect.fills = [{type: 'IMAGE', imageHash: image.hash, scaleMode: 'FILL'}];
// Supported formats: PNG, JPG, GIF. Max: 4096x4096

// From an existing node's image
var existingFill = sourceNode.fills[0];
if (existingFill.type === 'IMAGE') {
  var img = figma.getImageByHash(existingFill.imageHash);
  var size = await img.getSizeAsync(); // {width, height}
  var bytes = await img.getBytesAsync(); // Uint8Array
}
```

## SVG import

```js
// Create a node from SVG string
var svgNode = figma.createNodeFromSvg('<svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 2L2 22h20L12 2z" fill="currentColor"/></svg>');
svgNode.name = 'Icons/Warning';
// Returns a FrameNode containing vector children
// Resize as needed: svgNode.resize(48, 48);
```

## Effects

Creating shadows and blurs:
```js
// Drop shadow
node.effects = [{
  type: 'DROP_SHADOW',
  color: {r: 0, g: 0, b: 0, a: 0.25},
  offset: {x: 0, y: 4},
  radius: 8,
  spread: 0,
  visible: true,
  blendMode: 'NORMAL'
}];

// Multiple effects (keep existing + add new)
var effects = node.effects.slice(); // clone readonly array
effects.push({
  type: 'LAYER_BLUR',
  radius: 4,
  visible: true
});
node.effects = effects;

// Inner shadow
node.effects = [{
  type: 'INNER_SHADOW',
  color: {r: 0, g: 0, b: 0, a: 0.1},
  offset: {x: 0, y: 2},
  radius: 4,
  visible: true,
  blendMode: 'NORMAL'
}];
```

## Gradient fills

```js
// Linear gradient (top to bottom, blue to purple)
node.fills = [{
  type: 'GRADIENT_LINEAR',
  gradientStops: [
    {position: 0, color: {r: 0.15, g: 0.4, b: 0.95, a: 1}},
    {position: 1, color: {r: 0.5, g: 0.2, b: 0.8, a: 1}}
  ],
  gradientTransform: [[1, 0, 0], [0, 1, 0]]  // identity = top-to-bottom
}];

// Radial gradient
node.fills = [{
  type: 'GRADIENT_RADIAL',
  gradientStops: [
    {position: 0, color: {r: 1, g: 1, b: 1, a: 1}},
    {position: 1, color: {r: 0, g: 0, b: 0, a: 0.5}}
  ],
  gradientTransform: [[0.5, 0, 0.25], [0, 0.5, 0.25]]
}];
```

## Hex colors

Use the built-ins instead of hand-rolling the hex → 0-1 conversion (`gotchas.md` #3):
```js
node.fills = [figma.util.solidPaint('#6366f1')];          // hex → SolidPaint
node.fills = [figma.util.solidPaint('#6366f1', {opacity: 0.5})];
```
See `references/api-reference.md` → `figma.util` for `rgb`, `rgba`, and `solidPaint` signatures.
