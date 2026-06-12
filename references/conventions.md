# Figma design conventions

Standards for structuring Figma files. Based on Figma's official skills (figma-use, figma-generate-library) and atomic design (atoms → molecules → organisms → screens).

**Everything below is a rule or a pattern. Specific values (colors, fonts, sizes, spacing) are EXAMPLES only: always discover the file's actual values first.**

## Rule zero: discover before creating

Two discoveries, in order:

1. **Source.** If the design mirrors an existing implementation (code repo, live page, screenshot, design file), read it first. Pull real layout, colors, copy, and typography from the source — not from assumptions about what an app with that name "probably" looks like. The skill is code → Figma; the source is the ground truth.
2. **Figma file.** Different files use different naming conventions, variable structures, and component patterns. Match what's already there. See `references/reading.md` for inspection scripts (pages, components, fonts, colors, spacing).

Defaults below apply only when the file has no consistent patterns. Otherwise match what's there (e.g. if the file uses 4px spacing, use 4px).

## Atomic design hierarchy

Build bottom-up: atoms first, then molecules from atom instances, then screens from instances.

| Level | What | Naming pattern |
|-------|------|----------------|
| **Atoms** | Smallest reusable pieces (buttons, inputs, icons, dividers) | `Atoms/Name` |
| **Molecules** | Compositions of atoms (cards, menu items, nav items) | `Molecules/Name` |
| **Organisms** | Complex sections (navigation bars, sidebars, tables) | `Organisms/Name` |
| **Screens** | Full pages composed from instances | `Screens/Name` |

**Rules:**
- Never create raw frames when a component exists: use `component.createInstance()`
- Check existing components before creating new ones
- Screens should contain almost exclusively instances, not raw nodes

## Component naming

| Type | Convention | Example |
|------|-----------|---------|
| Public components | PascalCase, no prefix | `Button`, `Input` |
| With hierarchy | Level/Name | `Atoms/Button`, `Molecules/Header Bar` |
| Sub-components (internal) | `_` prefix + slash | `_Button/Slot`, `_Input/Indicator` |
| Documentation-only | `.` prefix | `.ExampleCard` |
| Variant values | `Property=Value` | `Size=Medium, Style=Primary` |

**Variant property names** should match code props where possible.
**Variant values** use Title Case in Figma.

Match existing naming (e.g. `button-primary`, `btn/primary`).

## Component structure

### Every component must have:
- **Auto Layout**: `layoutMode: 'VERTICAL'` or `'HORIZONTAL'`
- **Proper padding**: `paddingTop/Right/Bottom/Left`
- **Item spacing**: `itemSpacing` for gaps
- **Descriptive name**: match existing naming convention

### Creating variants

Variant component names encode properties as `Property=Value` pairs, e.g. `Size=Medium, Style=Primary`: match the existing naming pattern in the file. Full walkthrough (naming before combining, post-combine positioning, adding properties): see `references/building.md` → Component variants.

### Component properties
```js
// addComponentProperty returns an #id-suffixed key — never hardcode it: see references/api-components.md → ComponentPropertiesMixin
var labelKey = comp.addComponentProperty('Label', 'TEXT', 'Default');

// Link property to child node (REQUIRED or property does nothing)
textNode.componentPropertyReferences = { characters: labelKey };

// Boolean for visibility
var showIconKey = comp.addComponentProperty('Show Icon', 'BOOLEAN', true);
iconNode.componentPropertyReferences = { visible: showIconKey };

// Instance swap (avoids variant explosion for icons, avatars, etc.)
var iconSlotKey = comp.addComponentProperty('Icon', 'INSTANCE_SWAP', iconComp.id);
iconInstance.componentPropertyReferences = { mainComponent: iconSlotKey };
```

**Add properties BEFORE `combineAsVariants`**, not after.

## Page structure

```
Cover
---
Foundations (colors, typography, spacing tokens)
Icons
---
Component pages (one per component or group)
---
Screens
Utilities
```

- **Cover** always first
- **`---`** separator pages between sections
- **Foundations** before components, components before screens
- Match existing page structure if the file already has one

## Variable / token naming

Naming hierarchy, primitives vs semantic, scopes, and code-syntax mapping: see `references/api-components.md` → Variables.

## Style naming

Use `category/name` pattern. Example (adapt to project):
```
Display/Large     Heading/1         Body/Large        Label/Large
Shadow/Subtle     Shadow/Medium     Shadow/Strong
```

## Auto Layout rules

Critical ordering and common gotchas live in `references/gotchas.md`. Patterns below.

### Common patterns
- **Full-width children**: parent `counterAxisSizingMode = 'FIXED'`, child `layoutSizingHorizontal = 'FILL'`
- **Push apart**: `primaryAxisAlignItems = 'SPACE_BETWEEN'`
- **Center**: `primaryAxisAlignItems = 'CENTER'`, `counterAxisAlignItems = 'CENTER'`
- **Push to bottom**: transparent spacer frame with `layoutSizingVertical = 'FILL'`

### Avoid
- Manual x/y inside Auto Layout frames
- `layoutMode = 'NONE'` on components
- `resize()` after setting sizing modes (it resets them to FIXED)

## Color rules

0-1 range, opacity on paint: see `gotchas.md` #3, #4. Read existing colors first; match the palette.

## Typography rules

`lineHeight`/`letterSpacing` use `{unit, value}` format: see `references/gotchas.md`.

**Always discover the file's fonts first** via `figma.listAvailableFontsAsync()`. Don't assume Inter or any specific font. If `loadFontAsync` fails, list available fonts to find the correct style name or pick a fallback.

## Spacing

Use consistent values from a scale. Read existing spacing from the file's Auto Layout frames to discover the project's spacing system.

**Rule:** Pick values from a harmonious scale (e.g., 4/8/12/16/24/32/48). Don't use arbitrary numbers.

## Effects

Match existing file effects when possible. Effects arrays are readonly; clone before mutating (see `references/gotchas.md`). See `references/building.md` for drop shadow / blur / inner shadow examples.

**Corner radius:** read existing radii from the file. Common patterns: small (inputs/buttons), medium (cards), full (avatars = width/2).

## Screen structure

```
Screen Frame (sized to target device, vertical auto layout)
├── Header instance (FILL width)
├── Divider instance (FILL width)
├── Content section (FILL width, auto layout, padding)
│   ├── Section titles
│   └── Component instances (FILL width)
├── Spacer frame (FILL vertical: pushes nav to bottom)
└── Bottom Nav instance (FILL width)
```

- Position screens left-to-right with consistent gaps
- New top-level nodes: always position away from (0,0) to avoid overlapping existing content

**Screen size depends on the project**: discover from existing screens or ask the user. Don't assume a specific device size.

## Incremental workflow

1. **Inspect first**: discover what exists before creating
2. **One thing per eval**: create variables, then components, then layouts in separate calls
3. **Return ALL node IDs**: `return {createdNodeIds: [...], mutatedNodeIds: [...]}`
4. **Validate after each section/checkpoint** (not each property set): the section's assertion block covers per-property checks. Per-step validation pays one `agent-browser` cold-start each — batch reads.
5. **Fix before moving on**: don't build on a broken foundation

## Pre-flight checklist

- [ ] Inspected file conventions before creating (Rule Zero)
- [ ] All repeated elements use component instances (no raw duplicates)
- [ ] Components named to match file's existing convention
- [ ] Auto Layout on every component and screen frame
- [ ] `layoutSizingHorizontal = 'FILL'` set AFTER appendChild
- [ ] Fonts loaded before every text modification
- [ ] Colors in 0-1 range, opacity on paint not in color
- [ ] lineHeight/letterSpacing use `{unit, value}` format
- [ ] All created/mutated node IDs returned
- [ ] Variable scopes set explicitly (never ALL_SCOPES)
- [ ] `figma.commitUndo()` after logical work groups
- [ ] `figma.viewport.scrollAndZoomIntoView()` at the end
- [ ] New top-level nodes positioned away from (0,0)

## Post-build audit

See `references/building.md` → Post-build audit.

## Source → Figma primitives

When translating source code (HTML, SwiftUI, Compose, Flutter, etc.) or prose descriptions into Figma, map source constructs to their nearest Figma primitive rather than translating literally. The mapping is the same regardless of source language:

| Source construct (any language) | Figma primitive |
|---|---|
| Vertical container / column / stack | `layoutMode = 'VERTICAL'` |
| Horizontal container / row | `layoutMode = 'HORIZONTAL'` |
| Z-stack / overlay | child with `layoutPositioning: 'ABSOLUTE'` |
| Padding modifier | `paddingTop` / `paddingLeft` / `paddingRight` / `paddingBottom` |
| Spacing between children | `itemSpacing = N` |
| Fixed-size constraint | `resize(w, h)` + `layoutSizing*: 'FIXED'` |
| Fill-available constraint | `layoutSizingHorizontal/Vertical: 'FILL'` |
| Hug-content constraint | `layoutSizingHorizontal/Vertical: 'HUG'` |
| Background color | `fills = [figma.util.solidPaint('#hex')]` |
| Border / stroke | `strokes = [figma.util.solidPaint('#hex')]` + `strokeWeight = N` |
| Corner radius | `cornerRadius = N` |
| Shadow / elevation | `effects = [{type: 'DROP_SHADOW', ...}]` |
| Reusable subview / partial | check for existing component; otherwise `figma.createComponent()` + `.createInstance()` |

If a source construct doesn't map cleanly, prefer the closest Auto Layout shape and document the divergence in the worker's report rather than forcing a literal translation.
