# Building & Mutating Figma Designs

How to create and modify design nodes via the Plugin API.

## Component Workflow

Follow this order when building designs:

1. **Create a "Components" page** if one doesn't exist (`figma.createPage()`, name it "Components").
2. **Build Atoms first** — smallest reusable pieces (icons, badges, chips, single text labels).
3. **Build Molecules from Atom instances** — e.g., an "Expense Row" molecule uses Icon and Text Label atoms.
4. **On the Screens page**, compose views entirely from Molecule/Atom instances.
5. **Use Auto Layout** on all component frames and screen frames.
6. **Name components with hierarchy**: `Atoms/Icon/Camera`, `Molecules/Expense Row`, `Screens/Dashboard`.

**Always use component instances** — never create raw frames or duplicated structures when a reusable component exists.
- **Atomic composition**: Before creating anything, check if a relevant component exists. Use `component.createInstance()` instead of recreating structures.
- **Swappable slots**: Use `instance.swapComponent(targetComp)` to change nested components rather than rebuilding.
- **Verify visually**: Use `node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}})` to inspect nodes instead of full-page screenshots.

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

## Post-Mutation Validation

After making changes, verify the result before moving on:

1. **Visual check** — export the modified node and compare against the intended design:
   ```js
   var bytes = await node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}});
   figma.base64Encode(bytes);
   ```
2. **Layout** — spacing, alignment, and sizing match intent. Check `itemSpacing`, `padding*`, `width`, `height`.
3. **Typography** — font family, size, weight, and line height are correct. Watch for `figma.mixed` on text range properties.
4. **Colors** — fills and strokes match exactly (remember: 0-1 range, not 0-255).
5. **Hierarchy** — nodes are parented correctly. Verify `child.parent.id === expectedParent.id`.
6. **Auto Layout** — `layoutSizingHorizontal`/`layoutSizingVertical` are set correctly on children. Test by resizing the parent frame.
7. **Constraints** — if not using Auto Layout, verify `constraints` on children for proper resize behavior.
8. **Assets** — images and icons render correctly. Check `imageHash` is not null on image fills.

> Only proceed to the next step after the current mutation passes validation.
