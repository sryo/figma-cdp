# Layout recipes

Concrete Auto Layout patterns for the most common components. Quick-pick the recipe that matches the shape you need, then adjust paddings/spacing.

For the underlying rules (FILL/HUG requirements, `layoutGrow` legacy, etc.), see `references/building.md` → Constraints and sizing. For the FILL-after-`appendChild` rule, see `references/gotchas.md` → #1 and #12.

## Decision: constraints vs Auto Layout

- Parent has `layoutMode = 'HORIZONTAL' | 'VERTICAL' | 'GRID'` → children use `layoutSizingHorizontal` / `layoutSizingVertical`. `constraints` is ignored.
- Parent has `layoutMode = 'NONE'` → children use `constraints: {horizontal, vertical}`.
- Mixed: a child can opt out of Auto Layout flow with `layoutPositioning = 'ABSOLUTE'` and then use `constraints` (badges, overlays, floating elements inside an auto-layout frame).

## Button (horizontal, centered, hug both axes)

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

## Card (vertical, fixed width, image fills width)

```js
card.layoutMode = 'VERTICAL';
card.counterAxisSizingMode = 'FIXED';    // fixed width
card.primaryAxisSizingMode = 'AUTO';     // hug height
image.layoutSizingHorizontal = 'FILL';   // stretch to card width
image.layoutSizingVertical = 'FIXED';    // fixed height
content.layoutSizingHorizontal = 'FILL'; // text area fills width
```

## Input field (horizontal, text fills remaining space)

```js
input.layoutMode = 'HORIZONTAL';
input.counterAxisAlignItems = 'CENTER';
textNode.layoutSizingHorizontal = 'FILL';
icon.layoutSizingHorizontal = 'FIXED';
```

## List / stack (vertical, all children fill width)

```js
list.layoutMode = 'VERTICAL';
list.counterAxisSizingMode = 'FIXED';
// each row:
row.layoutSizingHorizontal = 'FILL';
row.layoutSizingVertical = 'HUG';
```

## Absolute positioning inside Auto Layout

For overlays, badges, or floating elements inside an auto-layout frame:
```js
badge.layoutPositioning = 'ABSOLUTE';    // opt out of auto layout flow
badge.constraints = {horizontal: 'MAX', vertical: 'MIN'};  // pin top-right
```

## Fixed-frame constraints (no Auto Layout)

When parent has `layoutMode = 'NONE'`:
```js
child.constraints = {horizontal: 'MIN', vertical: 'MIN'};         // pin top-left (default)
child.constraints = {horizontal: 'STRETCH', vertical: 'MIN'};     // stretch width, pin top
child.constraints = {horizontal: 'STRETCH', vertical: 'STRETCH'}; // fill parent
child.constraints = {horizontal: 'CENTER', vertical: 'CENTER'};   // center both axes
child.constraints = {horizontal: 'MAX', vertical: 'MAX'};         // pin bottom-right
```

## Key rules

- `FILL` requires the parent to have Auto Layout.
- `HUG` requires the node to have children (frames/components only).
- `layoutGrow = 1` is the legacy way to set FILL. Prefer `layoutSizing*` properties.
- Set `primaryAxisSizingMode = 'AUTO'` on the parent for hug behavior on the main axis.
- `resize()` after a sizing mode resets the child to `FIXED`. Always resize first, then set sizing modes (see `gotchas.md` #12).
