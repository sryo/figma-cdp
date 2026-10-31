# Figma design conventions

How a source becomes Figma structure, and what to use when nothing decides it. Values below are defaults or examples, never overrides of the source or the file.

## Rule zero: precedence

1. **Source values.** The source manifest (`references/fidelity.md`) and the cited files win: an 18px gap stays 18, a hex absent from the file stays that hex.
2. **File conventions.** The inventory (`references/reading.md` → Component inventory) decides names, tokens and components wherever the source is silent, and how a source value is expressed: bind to the variable or style whose value equals it.
3. **Defaults** (Design defaults below) only when the file is empty and the source says nothing.

Bind only on an exact match. No match: write the source value raw and list it in the report's `assumptions`, or, when the task builds a design system, create the variable from the source token's name.

## Source values → Figma (token-first)

| Source value | Figma |
|---|---|
| Color (token or literal) | `__fx.bindFill(node, value)`: binds the variable (else paint style) with that exact value, else paints raw. Strokes: `'strokes'` |
| Spacing, padding, gap | `node.setBoundVariable('itemSpacing' / 'paddingLeft' ..., v)` when a FLOAT variable scoped `GAP` holds the value, else the number |
| Corner radius | `setBoundVariable('topLeftRadius' ..., v)` with a `CORNER_RADIUS` variable, else `cornerRadius = n` |
| Type (family, size, weight, line height) | `await text.setTextStyleIdAsync(style.id)` when a text style matches all four; else set them and list the text in assumptions if no style fits |
| Shadow, blur | an effect style with the same values (`effectStyleId`), else `effects = [...]` |
| Copy | the manifest string, verbatim, placeholders filled with realistic sample values |

```js
// The bindings __fx.bindFill does for color, written out:
const v = await figma.variables.getVariableByIdAsync('VariableID:1:5');
node.fills = [figma.variables.setBoundVariableForPaint(figma.util.solidPaint('#2563eb'), 'color', v)];
node.setBoundVariable('itemSpacing', gapVar);
```

## Source layout semantics → auto layout

Name the kind of construct, not the syntax; the mapping holds for any source.

| Source layout | Figma |
|---|---|
| Column / vertical stack | `layoutMode = 'VERTICAL'` |
| Row / horizontal stack | `layoutMode = 'HORIZONTAL'` |
| Gap between children | `itemSpacing` |
| Children pushed apart (space-between) | `primaryAxisAlignItems = 'SPACE_BETWEEN'`, no spacer frames |
| Cross-axis alignment (start/center/end/baseline) | `counterAxisAlignItems` `MIN` / `CENTER` / `MAX` / `BASELINE` |
| Child that grows to fill (flex grow, weight, `1fr`, width 100%) | `layoutSizingHorizontal/Vertical = 'FILL'` after `appendChild` |
| Child of a flex parent with no `align-items` (the default stretch), with no cross size or `align-self` of its own | FILL on the cross axis (a column's child FILL across), inline-flex and inline-block items too (a flex parent blockifies them); `align-items` or `align-self` start, center or end → HUG |
| Content-sized element (auto width, hug) | `'HUG'` (auto-layout frames and text only) |
| Fixed size | `resize(w, h)`, then `'FIXED'` |
| Min / max width or height | `minWidth` / `maxWidth` / `minHeight` / `maxHeight` on an auto-layout frame or its child |
| Wrapping row (flex-wrap, flow layout) | `layoutWrap = 'WRAP'` + `counterAxisSpacing`; width FIXED or FILL, never HUG |
| Grid | rows of `HORIZONTAL` frames with FILL children, or `layoutMode = 'GRID'` |
| Paragraph that wraps | text `layoutSizingHorizontal = 'FILL'`, `textAutoResize = 'HEIGHT'` (`__fx.text(chars, {w: 'fill'})`) |
| Single-line label | text `textAutoResize = 'WIDTH_AND_HEIGHT'` |
| Overlay, badge, absolute child | `layoutPositioning = 'ABSOLUTE'` + `constraints` from the anchored edges: right → `MAX`, left+right → `STRETCH`, centered → `CENTER` |
| Children of a frame without auto layout | `constraints` the same way; never leave a pinned-right child at `MIN` |
| Overflow hidden / scroll | `clipsContent = true` |
| Reusable subview | per SKILL.md's component plan: an instance of the matched or new component |

Screen roots: a FIXED width (the device or breakpoint the source targets), height HUG; full-width sections FILL.

## Components

- Build bottom-up: components first, then screens from their instances. A screen holds instances, not raw copies of components.
- Every component has auto layout and hugs or fills; no `layoutMode = 'NONE'` components.
- Variants, properties and the set's own layout: one recipe, `references/building.md` → Component variants.
- Property names match the source's props (`Size`, `State`, `Label`); variant values in Title Case unless the file differs.

## Naming

Match the file. With no convention: components PascalCase (`Button`, `Card`), a `Group/Name` path only when the file groups (`Forms/Input`), internal parts `_Button/Slot`. Every layer gets a name from the source (`Header`, `Price row`); no `Frame 12`. Variables `color/bg/primary`, `space/4`, `radius/md`; styles `Heading/1`, `Body/Large`.

## Design defaults (empty file, silent source)

- **Spacing (4px base):** 4 inside a control (icon to label), 8 between tightly related items, 12-16 inside a card or list item, 24 between groups, 32-48 between sections, 16-24 screen padding (mobile 16, desktop 24+).
- **Type:** one family; display 32-40/Bold, heading 24/Semibold, title 18/Semibold, body 16/Regular, label 14/Medium, caption 12/Regular; line height ~1.25 for headings, ~1.5 for body. Check the font with `figma.listAvailableFontsAsync()` only when `loadFontAsync` fails.
- **Color roles:** background, surface, text, text-muted, border, primary (+ on-primary text), danger; one accent; body text contrast ≥ 4.5:1.
- **Radius:** 4-8 controls, 8-12 cards, full for pills and avatars.
- **Sizes:** touch targets ≥ 44px high; inputs and buttons share a height in a row.
- New top-level frames go right of existing content, never at (0, 0).

## Before reporting

- [ ] Values trace to the manifest or [Reuse]; the rest are in `assumptions`
- [ ] Repeated units are instances; `__fx.audit(rootId)` counts are 0
- [ ] Created and mutated ids returned; `figma.commitUndo()` after each unit
