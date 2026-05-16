# Building & Mutating Figma Designs

How to create and modify design nodes via the Plugin API.

## Component Workflow

See `references/conventions.md` for atomic design hierarchy, naming (`Atoms/…`, `Molecules/…`, `Screens/…`), and page structure. Always prefer `component.createInstance()` over recreating structures, and `instance.swapComponent(target)` over rebuilding nested components. Verify visually with `node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}})`.

## Constraints & Sizing

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
```

Input/list/stack follow the same pattern: horizontal or vertical `layoutMode`, `counterAxisSizingMode = 'FIXED'` on parent, children `layoutSizingHorizontal = 'FILL'`.

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
- `constraints` is ignored when parent has auto layout — use `layoutSizing*` instead.
- `FILL` requires parent with auto layout; `HUG` requires the node to have children.
- `layoutGrow = 1` is legacy FILL — prefer `layoutSizing*`.
- See `references/gotchas.md` for FILL-after-appendChild and resize-before-sizing-modes rules.

## Post-Mutation Validation

After each mutation, verify before moving on. Assertion patterns live in `references/execution.md` → Assertion Verification. Spot-check: layout/padding/itemSpacing, typography (watch for `figma.mixed`), colors (0-1 range), hierarchy (`child.parent.id`), layoutSizing on auto-layout children, `imageHash` on image fills. Visual export:
```js
var bytes = await node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}});
figma.base64Encode(bytes);
```

## Component Variants

Pattern for creating a component set with variants:
```js
// Create variant components
var primary = figma.createComponent();
primary.name = 'Button/Primary';
primary.resize(120, 40);
primary.layoutMode = 'HORIZONTAL';
primary.primaryAxisAlignItems = 'CENTER';
primary.counterAxisAlignItems = 'CENTER';
primary.fills = [{type: 'SOLID', color: {r: 0.15, g: 0.4, b: 0.95}}];
primary.cornerRadius = 8;

var secondary = primary.clone();
secondary.name = 'Button/Secondary';
secondary.fills = [{type: 'SOLID', color: {r: 0.9, g: 0.9, b: 0.9}}];

// Combine into variant set
var buttonSet = figma.combineAsVariants([primary, secondary], figma.currentPage);
buttonSet.name = 'Button';

// Add a boolean property
buttonSet.addComponentProperty('Disabled', 'BOOLEAN', false);
// NOTE: returns name with #id suffix, e.g. 'Disabled#1:23'
```

Working with instances:
```js
var instance = primary.createInstance();
instance.setProperties({'Variant': 'Secondary'});  // switch variant
// For BOOLEAN/TEXT props, use full name with #suffix from componentPropertyDefinitions
```

## Instance Overrides

Reading and modifying instance overrides:
```js
var inst = await figma.getNodeByIdAsync('INSTANCE_ID');
var main = await inst.getMainComponentAsync();

// Read current overrides
var overrides = inst.overrides; // [{id, overriddenFields}]

// Find nested text and override it
var label = inst.findOne(function(n) { return n.name === 'Label' && n.type === 'TEXT'; });
if (label) {
  // Load the instance's actual font, not a hardcoded one
  if (label.fontName !== figma.mixed) {
    await figma.loadFontAsync(label.fontName);
  }
  label.characters = 'New Label';
}

// Swap a nested component instance
var icon = inst.findOne(function(n) { return n.type === 'INSTANCE'; });
if (icon) {
  var newComp = await figma.importComponentByKeyAsync('COMPONENT_KEY');
  icon.swapComponent(newComp); // preserves overrides
}

// Reset all overrides
inst.removeOverrides();
```

## Image Fills

Applying images to nodes:
```js
// From URL (may hit CORS — use bytes if blocked)
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

## SVG Import

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

## Gradient Fills

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
