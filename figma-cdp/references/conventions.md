# Figma Design Conventions

Standards for structuring Figma files programmatically. Based on Figma's official skill patterns (figma-use, figma-generate-library) and atomic design methodology.

**Everything below is a rule or a pattern. Specific values (colors, fonts, sizes, spacing) are EXAMPLES only — always discover the file's actual values first.**

## Rule Zero: Discover Before Creating

**Always inspect the file before creating anything.** Different files use different naming conventions, variable structures, and component patterns. Match what's already there.

See `references/reading.md` for inspection scripts (pages, components, fonts, colors, spacing).

**When to use defaults below:** Only when the file is empty or has no consistent patterns.
**When to match existing:** Always. If the file uses Roboto, use Roboto. If it uses 4px spacing, use 4px.

## Atomic Design Hierarchy

Build bottom-up: atoms first, then molecules from atom instances, then screens from instances.

| Level | What | Naming pattern |
|-------|------|----------------|
| **Atoms** | Smallest reusable pieces (buttons, inputs, icons, dividers) | `Atoms/Name` |
| **Molecules** | Compositions of atoms (cards, menu items, nav items) | `Molecules/Name` |
| **Organisms** | Complex sections (navigation bars, sidebars, tables) | `Organisms/Name` |
| **Screens** | Full pages composed from instances | `Screens/Name` |

**Rules:**
- Never create raw frames when a component exists — use `component.createInstance()`
- Check existing components before creating new ones
- Screens should contain almost exclusively instances, not raw nodes

## Component Naming

| Type | Convention | Example |
|------|-----------|---------|
| Public components | PascalCase, no prefix | `Button`, `Input` |
| With hierarchy | Level/Name | `Atoms/Button`, `Molecules/Header Bar` |
| Sub-components (internal) | `_` prefix + slash | `_Button/Slot`, `_Input/Indicator` |
| Documentation-only | `.` prefix | `.ExampleCard` |
| Variant values | `Property=Value` | `Size=Medium, Style=Primary` |

**Variant property names** should match code props where possible.
**Variant values** use Title Case in Figma.

**Always check existing naming in the file first.** If the file uses `button-primary` or `btn/primary`, follow that pattern.

## Component Structure

### Every component must have:
- **Auto Layout** — `layoutMode: 'VERTICAL'` or `'HORIZONTAL'`
- **Proper padding** — `paddingTop/Right/Bottom/Left`
- **Item spacing** — `itemSpacing` for gaps
- **Descriptive name** — match existing naming convention

### Creating variants
```js
// Name encodes variant properties — match existing naming pattern in file
var primary = figma.createComponent();
primary.name = 'Size=Medium, Style=Primary';

var secondary = figma.createComponent();
secondary.name = 'Size=Medium, Style=Secondary';

var cs = figma.combineAsVariants([primary, secondary], figma.currentPage);
cs.name = 'Button';

// CRITICAL: position children after combining (they stack at 0,0)
cs.children.forEach(function(child, i) { child.x = i * 150; child.y = 0; });
// Resize component set to fit
var maxX = 0;
for (var i = 0; i < cs.children.length; i++) {
  var right = cs.children[i].x + cs.children[i].width;
  if (right > maxX) maxX = right;
}
cs.resizeWithoutConstraints(maxX + 40, cs.children[0].height + 40);
```

### Component properties
```js
// addComponentProperty returns a KEY STRING — never hardcode it
var labelKey = comp.addComponentProperty('Label', 'TEXT', 'Default');
// labelKey === "Label#4:0" (unpredictable suffix)

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

## Page Structure

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

## Variable / Token Naming

Use slash-separated hierarchy: `{category}/{subcategory}/{role}` — e.g. `color/bg/primary`, `spacing/md`, `radius/lg`. Adapt names and values to the project.

### Primitives vs Semantic
- **Primitives** — raw values, hidden scope (`[]`): e.g. `blue/500`, `gray/100`
- **Semantic** — alias primitives, specific scopes: e.g. `color/bg/primary` → alias of primitive

### Variable scopes (always set explicitly)
```js
// Default ALL_SCOPES pollutes every picker — never use it
bgVar.scopes = ['FRAME_FILL', 'SHAPE_FILL'];      // backgrounds
textColorVar.scopes = ['TEXT_FILL'];                 // text colors
spacingVar.scopes = ['GAP', 'WIDTH_HEIGHT'];         // spacing
radiusVar.scopes = ['CORNER_RADIUS'];                // radii
borderVar.scopes = ['STROKE_COLOR'];                 // borders
```

### Code syntax mapping
```js
// Figma name → Code name (different audiences, different conventions)
// color/bg/primary → var(--color-bg-primary)     [WEB]
// color/bg/primary → colorBgPrimary              [ANDROID]
// color/bg/primary → Color.bgPrimary             [iOS]
v.setVariableCodeSyntax('WEB', 'var(--color-bg-primary)');
// CRITICAL: var() wrapper REQUIRED for WEB or Dev Mode shows raw hex
```

## Style Naming

Use `category/name` pattern. Example (adapt to project):
```
Display/Large     Heading/1         Body/Large        Label/Large
Shadow/Subtle     Shadow/Medium     Shadow/Strong
```

## Auto Layout Rules

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

## Color Rules

0-1 range, opacity on paint (not in color) — see `references/gotchas.md`. **Always read existing colors from the file** before applying new ones; match the palette.

## Typography Rules

`lineHeight`/`letterSpacing` use `{unit, value}` format — see `references/gotchas.md`.

**Always discover the file's fonts first** via `figma.listAvailableFontsAsync()`. Don't assume Inter or any specific font. If `loadFontAsync` fails, list available fonts to find the correct style name or pick a fallback.

## Spacing

Use consistent values from a scale. Read existing spacing from the file's Auto Layout frames to discover the project's spacing system.

**Rule:** Pick values from a harmonious scale (e.g., 4/8/12/16/24/32/48). Don't use arbitrary numbers.

## Effects

Match existing file effects when possible. Effects arrays are readonly — clone before mutating (see `references/gotchas.md`). See `references/building.md` for drop shadow / blur / inner shadow examples.

**Corner radius:** read existing radii from the file. Common patterns: small (inputs/buttons), medium (cards), full (avatars = width/2).

## Screen Structure

```
Screen Frame (sized to target device, vertical auto layout)
├── Header instance (FILL width)
├── Divider instance (FILL width)
├── Content section (FILL width, auto layout, padding)
│   ├── Section titles
│   └── Component instances (FILL width)
├── Spacer frame (FILL vertical — pushes nav to bottom)
└── Bottom Nav instance (FILL width)
```

- Position screens left-to-right with consistent gaps
- New top-level nodes: always position away from (0,0) to avoid overlapping existing content

**Screen size depends on the project** — discover from existing screens or ask the user. Don't assume a specific device size.

## Incremental Workflow

From Figma's official figma-use skill:

1. **Inspect first** — discover what exists before creating
2. **One thing per eval** — create variables, then components, then layouts in separate calls
3. **Return ALL node IDs** — `return {createdNodeIds: [...], mutatedNodeIds: [...]}`
4. **Validate after each step** — read back properties, export screenshots
5. **Fix before moving on** — don't build on a broken foundation

## Pre-Flight Checklist

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
