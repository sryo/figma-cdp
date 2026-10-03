# Fidelity check: Figma against the source

Two helpers compare a built subtree with the implementation it mirrors, deterministically. They run from the skill directory next to `figma_run.py`; `figma_fidelity.py` runs its eval through it, so it works on either backend.

## 1. Source manifest, once, before dispatch

```bash
python3 <skill-dir>/figma_source.py <files-or-dirs the screen mirrors> -o /tmp/figma_source_<slug>.json
```

Pass the files behind the screen being built: its markup or UI code, the style sheets it uses, the theme or token files. A whole repo works too, but copy from other screens then shows up as missing. The script prints a summary line. The JSON holds:

- `tokens` `[{name, value, kind, src}]`: custom properties, `$`/`@` variables, theme constants with a color value, JSON token files (nested keys and `$value`). References (`var(--x)`, `{a.b}`) are resolved.
- `colors`, `spacing`, `radii`, `fontSizes`, `fontWeights`, `fontFamilies` `[{value, token?, src}]`: every literal color (`#hex`, `rgb()`, `hsl()`, `0x` on a line about color) and every number used for spacing, radius or type, in px (rem × 16).
- `copy` `[{text, src}]`: markup text, copy attributes (`placeholder`, `label`, `value`, ...), prose string literals in UI code, string-table JSON. A markup expression stays as a placeholder (`You have {count} left`) that matches any filled-in value. Comments, scripts, `<title>`, `aria-*`, class lists and identifiers are skipped.
- `variants` `[{component, prop, values, src}]`: string-literal unions, enums, boolean props, class modifiers (`block--mod`).
- `states` `[{component, state, src}]`: pseudo-classes, state-named props (`disabled`, `selected`, ...), state-named modifiers, a `disabled` attribute in markup.
- `components` `[{component, uses, nests, src}]`: every style block with a paint or type rule (background, border, color, font, shadow; layout-only blocks are scaffolding) and every capitalized tag in UI code, with its uses in the markup and the components used directly inside it. The summary prints them as a second line (`card ×6 (button, list-item) · tabs ×3 (tab)`): each one is a Figma component, and a container holds instances of what it nests.

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
- **missing components**: a manifest component used 2+ times with no component in the subtree (defined there or behind an instance) whose name, or a `/` segment of it, holds all its words: `Card header`, `Kit/Card` and `Product card` count for `card`; `Stat card` does not when the source has a `StatCard` too.

A kind the manifest has no entries for is skipped. The first line counts the gaps (`0 gaps` is clean). Exit 0 means the check ran, 2 that it could not. `--json` prints the full report, with every node id. Fix each gap with a targeted edit, or report it as a deliberate deviation, then run the check again.
