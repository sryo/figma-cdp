# Fidelity check: Figma against the source

Two helpers compare a built subtree with the implementation it mirrors, deterministically. Copy both, with `figma_run.py`, to `/tmp/`. `figma_fidelity.py` runs its eval through `figma_run.py`, so it works on either backend.

## 1. Source manifest, once, before dispatch

```bash
python3 /tmp/figma_source.py <files-or-dirs the screen mirrors> -o /tmp/figma_source_<slug>.json
```

Pass the files behind the screen being built: its markup or UI code, the style sheets it uses, the theme or token files. A whole repo works too, but copy from other screens then shows up as missing. The script prints a one-line summary. The JSON holds:

- `tokens` `[{name, value, kind, src}]`: custom properties, `$`/`@` variables, theme constants with a color value, JSON token files (nested keys and `$value`). References (`var(--x)`, `{a.b}`) are resolved.
- `colors`, `spacing`, `radii`, `fontSizes`, `fontWeights`, `fontFamilies` `[{value, token?, src}]`: every literal color (`#hex`, `rgb()`, `hsl()`, `0x` on a line about color) and every number used for spacing, radius or type, in px (rem × 16).
- `copy` `[{text, src}]`: markup text, copy attributes (`placeholder`, `label`, `value`, ...), prose string literals in UI code, string-table JSON. Comments, scripts, `<title>`, `aria-*`, class lists and identifiers are skipped.
- `variants` `[{component, prop, values, src}]`: string-literal unions, enums, boolean props, class modifiers (`block--mod`).
- `states` `[{component, state, src}]`: pseudo-classes, state-named props (`disabled`, `selected`, ...), state-named modifiers, a `disabled` attribute in markup.

`src` is `file:line`. Give workers the values from the manifest instead of having each one re-read the source.

## 2. Check after workers report DONE

```bash
python3 /tmp/figma_fidelity.py /tmp/figma_source_<slug>.json <rootId> --file <figma-url>
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
- **unbound**: a raw value equal to a source token while a file variable holds that value. Bind it to the variable named.
- **missing variants / states**: checked only for components the subtree uses, matched by name. The others are listed as not checked.

A kind the manifest has no entries for is skipped. Exit 0 means no gaps, 1 means gaps, 2 means the check could not run. `--json` prints the full report, with every node id. Fix each gap with a targeted edit, or report it as a deliberate deviation, then run the check again.
