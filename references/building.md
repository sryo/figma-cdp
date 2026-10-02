# Building and mutating Figma designs

How to create and modify design nodes via the Plugin API.

## Component workflow

See `references/conventions.md` for value precedence, the source → auto layout mapping and naming. Always prefer `component.createInstance()` over recreating structures, and `instance.swapComponent(target)` over rebuilding nested components. Verify visually with `node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}})`.

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

The one recipe for a component set. VARIANT axes come from `Prop=Value` names set BEFORE combining; TEXT, BOOLEAN and INSTANCE_SWAP properties go on the set AFTER combining (a variant inside a set can't take them) and are linked in every variant; the set itself gets auto layout and hugs.

```js
await figma.loadFontAsync({family: 'Inter', style: 'Medium'});
const icon = await figma.getNodeByIdAsync('ICON_COMPONENT_ID');           // a COMPONENT
const base = await __fx.frame({name: 'Variant=Primary, State=Default', component: true, dir: 'H',
  gap: 8, pad: [8, 16], align: 'center', justify: 'center', radius: 8, fill: 'color/bg/primary'});
base.appendChild(icon.createInstance());
await __fx.text('Button', {parent: base, weight: 'Medium', size: 14, color: 'color/text/on-primary'});

const variants = [base];
for (const [name, fill] of [['Variant=Secondary, State=Default', 'color/bg/secondary'],
                            ['Variant=Primary, State=Disabled', 'color/bg/disabled']]) {
  const v = base.clone(); v.name = name; await __fx.bindFill(v, fill); variants.push(v);
}
const set = figma.combineAsVariants(variants, PARENT);
set.name = 'Button';
await __fx.autoLayout(set, {dir: 'H', wrap: true, gap: 16, pad: 16, w: 'hug', h: 'hug'});

const label = set.addComponentProperty('Label', 'TEXT', 'Button');            // returns 'Label#1:2'
const show = set.addComponentProperty('Show Icon', 'BOOLEAN', true);
const swap = set.addComponentProperty('Icon', 'INSTANCE_SWAP', icon.id);
for (const v of set.children) {
  v.findOne(n => n.type === 'TEXT').componentPropertyReferences = {characters: label};
  v.findOne(n => n.type === 'INSTANCE').componentPropertyReferences = {visible: show, mainComponent: swap};
}
return {setId: set.id, variants: set.children.map(c => c.id)};
```

- Axes and values come from the source's prop and state enums, one axis per enum.
- Text that changes per use is a TEXT property, never one variant per string. An optional part is a BOOLEAN on its `visible`; a swappable icon or slot is an INSTANCE_SWAP on its `mainComponent`.
- A property no layer references does nothing; `__fx.audit` counts those as `unlinkedProps`.

Using it: `__fx.instance('Button', {Variant: 'Secondary', Label: 'Cancel', 'Show Icon': false}, {parent})`. Raw API: `inst.setProperties({Variant: 'Secondary', 'Label#1:2': 'Cancel'})`; non-VARIANT names need their `#id` suffix (`references/api-components.md` → ComponentPropertiesMixin).

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

After the spec's assertions pass, `__fx.audit(rootId)` checks what the spec didn't enumerate (`references/execution.md` → Resident helper library): repeated raw subtrees, FIXED frames in auto layout, absolute children at default constraints, groups, default names, raw paints equal to a variable, fixed text in auto layout, components without auto layout, unlinked properties. Every count should be 0. Then the coordinator runs `figma_fidelity.py` against the source manifest (`references/fidelity.md`): off-scale means "not in the source's values", not "not on a default scale".

A worker left with audit counts it can't fix reports `DONE_WITH_CONCERNS` with the ids.

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
