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

For named component recipes (Button, Card, Input, List), absolute positioning, fixed-frame constraints (when parent is `layoutMode = 'NONE'`), and the key sizing rules, see Layout recipes below. For `FILL`-after-`appendChild` and `resize`-before-sizing-modes, see `references/gotchas.md` #1 and #12.

## Post-mutation validation

After each mutation, verify before moving on. Assertion patterns live in `references/execution.md` → Assertion verification. Spot-check: layout/padding/itemSpacing, typography (watch for `figma.mixed`), colors (0-1 range), hierarchy (`child.parent.id`), layoutSizing on auto-layout children, `imageHash` on image fills. Visual export:
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

// CRITICAL: position children after combining (they stack at 0,0)
buttonSet.children.forEach(function(child, i) { child.x = i * 150; child.y = 0; });
// Resize component set to fit
var maxX = 0;
for (var i = 0; i < buttonSet.children.length; i++) {
  var right = buttonSet.children[i].x + buttonSet.children[i].width;
  if (right > maxX) maxX = right;
}
buttonSet.resizeWithoutConstraints(maxX + 40, buttonSet.children[0].height + 40);

// Add a boolean property — on the ComponentSet, AFTER combining
buttonSet.addComponentProperty('Disabled', 'BOOLEAN', false);
// Returned name carries an #id suffix: see references/api-components.md → ComponentPropertiesMixin
```

Working with instances:
```js
var instance = primary.createInstance();
instance.setProperties({'Style': 'Secondary'});  // switch variant
// BOOLEAN/TEXT props need the full suffixed name (see note above)
```

## Instance overrides

Reading and modifying instance overrides:
```js
var inst = await figma.getNodeByIdAsync('INSTANCE_ID');
var main = await inst.getMainComponentAsync();

// Read current overrides
var overrides = inst.overrides; // [{id, overriddenFields}]

// Override nested TEXT (font loading, override semantics): see references/copy.md → Text inside component instances

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
See `references/api-reference.md` → Utility (`figma.util`) for `rgb`, `rgba`, and `solidPaint` signatures.

## Post-build audit

After explicit assertions pass, run a convention audit on the same subtree. Assertions check the spec we wrote; the audit catches drift from the file's existing conventions that the spec didn't enumerate.

What to check:

- **Raw color paints.** Walk fills and strokes. Flag any `SOLID` paint missing `boundVariables.color`; it should resolve to a color variable from the file.
- **Off-scale spacing.** Read the file's existing auto-layout values to derive the spacing scale. Flag `itemSpacing` or `padding*` values not in that set.
- **Unbound typography.** For each `TEXT` node, check whether its `(fontName, fontSize, lineHeight, letterSpacing)` matches a defined text style. If not, flag.
- **Should-be-instance.** Detect raw frames whose structure matches an existing component. Suggest converting via `component.createInstance()`.
- **Contrast (optional).** For each `TEXT` over a known background fill, run an APCA Lc check. Defaults: ±60 for body, ±75 for small text. Skip when the background isn't resolvable.

Return format:

```js
return {
  audit: [
    {nodeId: '1:23', issue: 'raw-color', suggestion: 'bind fills[0].color to color/bg/primary'},
    {nodeId: '1:25', issue: 'off-scale-spacing', actual: 13, expected: [12, 16, 24]}
  ]
};
```

A worker that finds audit items should report `DONE_WITH_CONCERNS` (not `DONE`), with the audit list in its report. The coordinator decides whether to ask the user to accept the drift or to dispatch a fix worker.

See `references/reading.md` → Reading variable bindings for the helper that resolves `boundVariables` on a node.

## Layout recipes

Concrete Auto Layout patterns for the most common components. Quick-pick the recipe that matches the shape you need, then adjust paddings/spacing. For the FILL-after-`appendChild` rule, see `references/gotchas.md` #1 and #12.

### Decision: constraints vs Auto Layout

- Parent has `layoutMode = 'HORIZONTAL' | 'VERTICAL' | 'GRID'` → children use `layoutSizingHorizontal` / `layoutSizingVertical`. `constraints` is ignored.
- Parent has `layoutMode = 'NONE'` → children use `constraints: {horizontal, vertical}`.
- Mixed: a child can opt out of Auto Layout flow with `layoutPositioning = 'ABSOLUTE'` and then use `constraints` (badges, overlays, floating elements inside an auto-layout frame).

### Button (horizontal, centered, hug both axes)

```js
btn.layoutMode = 'HORIZONTAL';
btn.primaryAxisAlignItems = 'CENTER';
btn.counterAxisAlignItems = 'CENTER';
btn.paddingLeft = btn.paddingRight = 16;
btn.paddingTop = btn.paddingBottom = 8;
btn.itemSpacing = 8;
btn.primaryAxisSizingMode = 'AUTO';      // hug width
btn.counterAxisSizingMode = 'AUTO';      // hug height
```

### Card (vertical, fixed width, image fills width)

```js
card.layoutMode = 'VERTICAL';
card.counterAxisSizingMode = 'FIXED';    // fixed width
card.primaryAxisSizingMode = 'AUTO';     // hug height
image.layoutSizingHorizontal = 'FILL';   // stretch to card width
image.layoutSizingVertical = 'FIXED';    // fixed height
content.layoutSizingHorizontal = 'FILL'; // text area fills width
```

### Input field (horizontal, text fills remaining space)

```js
input.layoutMode = 'HORIZONTAL';
input.counterAxisAlignItems = 'CENTER';
textNode.layoutSizingHorizontal = 'FILL';
icon.layoutSizingHorizontal = 'FIXED';
```

### List / stack (vertical, all children fill width)

```js
list.layoutMode = 'VERTICAL';
list.counterAxisSizingMode = 'FIXED';
// each row:
row.layoutSizingHorizontal = 'FILL';
row.layoutSizingVertical = 'HUG';
```

### Absolute positioning inside Auto Layout

For overlays, badges, or floating elements inside an auto-layout frame:
```js
badge.layoutPositioning = 'ABSOLUTE';    // opt out of auto layout flow
badge.constraints = {horizontal: 'MAX', vertical: 'MIN'};  // pin top-right
```

### Fixed-frame constraints (no Auto Layout)

When parent has `layoutMode = 'NONE'`:
```js
child.constraints = {horizontal: 'MIN', vertical: 'MIN'};         // pin top-left (default)
child.constraints = {horizontal: 'STRETCH', vertical: 'MIN'};     // stretch width, pin top
child.constraints = {horizontal: 'STRETCH', vertical: 'STRETCH'}; // fill parent
child.constraints = {horizontal: 'CENTER', vertical: 'CENTER'};   // center both axes
child.constraints = {horizontal: 'MAX', vertical: 'MAX'};         // pin bottom-right
```

### Key rules

- `FILL` requires the parent to have Auto Layout.
- `HUG` is only valid on auto-layout frames (`layoutMode != 'NONE'`) and text nodes; setting it elsewhere throws.
- `layoutGrow = 1` is the legacy way to set FILL. Prefer `layoutSizing*` properties.
- Set `primaryAxisSizingMode = 'AUTO'` on the parent for hug behavior on the main axis.
- `resize()` after a sizing mode resets the child to `FIXED`. Always resize first, then set sizing modes (see `gotchas.md` #12).
