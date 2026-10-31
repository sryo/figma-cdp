# Fidelity check: Figma against the source

Two helpers compare a built subtree with the implementation it mirrors, deterministically. They run from the skill directory next to `figma_run.py`; `figma_fidelity.py` runs its eval through it, so it works on either backend.

## 1. Source manifest, once, before dispatch

```bash
python3 <skill-dir>/figma_source.py <files-or-dirs the screen mirrors> -o /tmp/figma_source_<slug>.json
```

Pass the files behind the screen being built: its markup or UI code, the style sheets it uses, the theme or token files. An HTML page brings its own `<link rel=stylesheet>` sheets, and a sheet brings its `@import`s. A whole repo works too, but copy from other screens then shows up as missing. The script prints a summary line. The JSON holds:

- `tokens` `[{name, value, kind, src}]`: custom properties, `$`/`@` variables, theme constants with a color value, JSON token files (nested keys and `$value`). References (`var(--x)`, `{a.b}`) are resolved.
- `colors`, `spacing`, `radii`, `fontSizes`, `fontWeights`, `fontFamilies` `[{value, token?, src}]`: every literal color (`#hex`, `rgb()`, `hsl()`, `0x` on a line about color) and every number used for spacing, radius or type, in px (rem × 16).
- `copy` `[{text, src}]`: markup text, copy attributes (`placeholder`, `label`, `value`, ...), prose string literals in UI code, string-table JSON. A markup expression stays as a placeholder (`You have {count} left`) that matches any filled-in value. Comments, scripts, `<title>`, `aria-*`, class lists and identifiers are skipped.
- `variants` `[{component, prop, values, src}]`: string-literal unions, enums, boolean props, class modifiers (`block--mod`).
- `states` `[{component, state, src}]`: pseudo-classes, state-named props (`disabled`, `selected`, ...), state-named modifiers, a `disabled` attribute in markup.
- `components` `[{component, uses, nests, src, css?, fillAcross?}]`: every style block with a paint or type rule (background, border, color, font, shadow; layout-only blocks are scaffolding) and every capitalized tag in UI code, with its uses in the markup and the components used directly inside it. The summary prints them as a second line (`card ×6 (button, list-item) · tabs ×3 (tab)`): each one is a Figma component, and a container holds instances of what it nests. A style block's `css` is its rules, its modifiers and elements included, as `{selector: declarations}` with `var()` names kept (about 1.6 KB, then a `…` count of the rest), so its padding, paints and type come from the manifest. `fillAcross` lists the markup usages (`customers.html:69 in .card`, up to 8) whose column flex parent stretches them across: no `align-items` or stretch on the parent, no width or `align-self` on the child, inline-level or not.

`src` is `file:line`. Give workers the values from the manifest instead of having each one re-read the source.

## 2. Check after workers report DONE

```bash
python3 <skill-dir>/figma_fidelity.py /tmp/figma_source_<slug>.json <rootId> --file <figma-url>
```

One eval collects the subtree's text, solid colors (bound variables resolved to their value), fonts, auto-layout padding and gaps, radii, and the component sets its instances come from. Output, one line per kind with gaps:

```
fidelity 1:23 "Login": 4 gaps
missing copy (1): "Forgot your passphrase?" login.html:19
off-manifest colors (1): #2563eb ×1 (1:37)
unbound (1): #6b7280 ×1 → color/text-muted (1:26)
missing states (1): button: disabled (components.css:13)
not checked (no component in the subtree): toggle
```

- **missing copy**: a manifest string no text layer shows. **invented copy**: a text layer outside component definitions that no manifest string contains.
- **off-manifest** colors (±3 per channel), spacing, radii (a pill radius passes when the source has one ≥ 999), font sizes, weights, fonts.
- **unbound**: a raw value equal to a source token while a local variable scoped for that field holds that value. Bind it to the variable named.
- **missing variants / states**: checked only for components the subtree uses, matched by name. The others are listed as not checked. A state or boolean set per use through instance overrides (a nested instance's variant, a hidden layer) counts.
- **stretched usages hug**: an instance of a component with `fillAcross` that hugs in a column whose name (or its slot's instance's) holds a word of the source parent's classes: `badge customers.html:69 in .card.grow: Customers / Page / Row / Card / Content / Badge (76:4400) → layoutSizingHorizontal = 'FILL'`. Set that, unless the build means it.
- **missing components**: a manifest component used 2+ times with no component in the subtree (defined there or behind an instance) whose name, or a `/` segment of it, holds all its words: `Card header`, `Kit/Card` and `Product card` count for `card`; `Stat card` does not when the source has a `StatCard` too.

A kind the manifest has no entries for is skipped. The first line counts the gaps (`0 gaps` is clean). Exit 0 means the check ran, 2 that it could not. `--json` prints the full report, with every node id. Fix each gap with a targeted edit, or report it as a deliberate deviation, then run the check again.

## 3. Per element, when the source is a page you can walk

The manifest check asks whether a value appears anywhere in the source, so a wrong value on the right element passes. When the source renders as a page, diff each element instead, against a walk of it:

```bash
python3 <skill-dir>/figma_capture.py walk <url>      # spec: /tmp/figma_capture_<slug>.json
python3 <skill-dir>/figma_fidelity.py --elements /tmp/figma_capture_<slug>.json <rootId> --file <figma-url> [--waive <skill-dir>/tests/known_losses.json]
```

Each walked element pairs with the node named `[cap:i]` (what `figma_capture.py import` names), or by text and then geometry when the build has its own names. One line per difference:

```
elements 1:23 "Login": 3 gaps (color 1, position 1, spacing 1), 41 of 43 paired by cap
position [cap:7] 1:40: left/top [24, 16] → x/y [44, 16]
color [cap:9] 1:44: background-color "#2563eb" → fills "#3b82f6"
spacing [cap:12] 1:51: padding/gap [0, 0] → padding/itemSpacing [0, 8]
```

Kinds: `position` (against the parent, > 2 px), `spacing` (every child shifted alike: the parent's padding or gap), `size`, `color` (fill or text color, ΔE2000 > 2.3), `font-size`, `font-weight`, `font-family`, `line-height`, `letter-spacing`, `text`, `radius`, `opacity`, `visibility`, `missing-node` and `extra-node` (with a `weight`: their share of the root's area). `--waive` counts, rather than lists, rows under elements the walker flagged for a documented capture loss. `--json` gives each row's `css_prop` and Figma `prop`, which is what to look up when the importer has no mapping for it (`tests/api/figma_api.mjs lookup <css_prop>` in the dev repo).

To find a loss no property check knows about (a blend mode, a gradient, a mask), add a full-page screenshot of the walked page:

```bash
agent-browser --session capture connect <cdp-port> && agent-browser --session capture open <url>
agent-browser --session capture screenshot --full /tmp/figma_page.png      # a background tab: takes no focus
python3 <skill-dir>/figma_fidelity.py --elements /tmp/figma_capture_<slug>.json <rootId> --file <figma-url> --pixels /tmp/figma_page.png --crops /tmp/figma_crops
```

The subtree is exported as PNG and compared with the screenshot on an 8 px grid, text masked out. Differing regions that overlap no row's element come back as `unexplained [x, y, w, h]` with a source and a Figma crop each. It is a pointer for a person to look at, not a pass/fail.

