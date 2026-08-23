# Live-page capture (URL → Figma)

Load when the source is a live URL to import into Figma: a rendered web page becomes Figma nodes by walking the live DOM, not by reconstructing a screenshot. The pipeline is coordinator-inline and deterministic; agentic cleanup workers handle only the constructs it can't place deterministically.

## When to use

- The user gives a public web URL and wants it in Figma.
- Replaces the screenshot-reconstruction slow path in `references/reading.md`.
- Not for: authenticated pages (see Session choreography → limitation), code repos (use the no-source-URL branch — read the code, don't render it).

## Session choreography

Empirically verified (Canary 151 @ CDP 9333). Do exactly this; the routing rules below are not assumptions.

**Bind, don't `--cdp`-retarget.** `agent-browser connect <port>` binds the default session to that port. Once bound, a later bare `--cdp <otherport>` is **ignored** — the call still hits the originally-bound port. To retarget, run `connect <port>` again. The capture helper MUST NOT assume `--cdp` retargets a live session; it `connect`s explicitly.

```bash
agent-browser connect "${FIGMA_CDP_PORT:-9222}"   # binds the default session
```

**Two isolated sessions, never one shared tab.**

- **Source page** runs in `--session capture` — its own isolated tab set. A `--session capture` eval always hits the capture tab regardless of what the default session's active tab is doing.
- **Figma import** runs in the **default** session on the Figma tab (Mode A — the user's existing logged-in tab).

They never collide. The spec crosses between them as a **`/tmp` file**, never a shared tab. The helper does both halves:

```bash
python3 /tmp/figma_capture.py walk <url> [wait_ms]                 # capture session → /tmp/figma_capture_<slug>.json
python3 /tmp/figma_capture.py import /tmp/figma_capture_<slug>.json --components '<json-or-path>'   # default session
```

`walk` connects the capture session, `open`s the URL (`open`, not `navigate`/`goto`), waits `wait_ms` (default 2000) for the page to settle, then evals `figma_walker.js` — an async IIFE that agent-browser awaits. Asset fetches run inside the source tab during that eval; the envelope returns over the CDP WebSocket, so ARG_MAX never constrains the walker's output, only the importer's input (which the helper chunks).

**Active-tab nondeterminism warning.** A sessionless `eval` runs in whatever tab is marked `→` in `agent-browser tab list` (last opened or last selected). With a Figma tab AND a source tab both open in the default session this is **nondeterministic**. Never run a capture eval sessionless when a Figma tab is open — that's the whole reason the source page lives in `--session capture`.

**Public-vs-authenticated limitation.** An isolated `--session capture` context does **not** share the user's Chrome cookies/login, so captures cover **public/unauthenticated** pages. An authenticated page would need the walk to run as a second tab *inside* the logged-in default context (select it by index before the walker eval, accepting the active-tab nondeterminism that brings) — a documented limitation, not supported.

**Close before import.** Close the capture session before the first importer eval so only the Figma tab is live in the default session. After capture, confirm the default session still binds the Figma tab (`agent-browser eval "typeof figma"` → `"object"`).

## Spec format

One JSON document per walk, persisted to `/tmp/figma_capture_<slug>.json`. The schema is **frozen** — walker, importer, helper, and this doc mirror it exactly. Keys at their default are **omitted**, never null-filled.

### Envelope

```
meta     { url, title, viewport:{w,h}, dpr, nodeCount }
flagged  [ {i, reason} ]        reason ∈ "grid" | "transform"
assets   { <key>: asset }       key "a1", "a2", … — one per resolved URL (deduped), per canvas, per inline svg
nodes    [ node ]               flat, DFS-preorder, root i=0 (documentElement)
```

`flagged` carries only what the importer cannot place deterministically: `grid` (display grid / inline-grid) and `transform` (own transform is 3D, non-affine, or singular). Positioned children are not flagged — the importer places them (see Import loop).

### asset

```
{ kind:"image", mime:"image/png"|"image/jpeg"|"image/webp"|"image/gif", b64:"<base64>", w:int, h:int }
{ kind:"svg",   svg:"<svg …>…</svg>", w:int, h:int }
{ kind:"image"|"svg", error:"fetch"|"tainted"|"too-large"|"timeout"|"decode" }     no bytes
```

### node

| Field | Shape | Rule |
|---|---|---|
| `i` | int | DFS-preorder index, root 0 |
| `parent` | int | parent `i`; −1 for root |
| `tag` | string | lowercase tag; `"::before"` / `"::after"` for pseudo-element nodes |
| `rect` | `{x,y,w,h}` | **layout space** — every ancestor transform and the node's own transform undone; page coordinates (the scroll offset is folded in, so a scrolled capture still lands at page origin); 2 dp |
| `xf` | `[a,b,c,d,e,f]` | only when the element has a 2D affine own transform (see Geometry); omitted otherwise |
| `text` | string | merged text content; `""` for containers |
| `runs` | null \| `[run]` | only when inline spans differ; run = `{text, color, fontSize, fontWeight, fontStyle, textDecoration, fontFamily}` (full values; `fontStyle` "normal"/"italic"; `textDecoration` "none"/"underline"/"line-through") |
| `lines` | int ≥ 1 | text nodes only — number of line boxes (see Text) |
| `kids` | int ≥ 1 | number of emitted child nodes (after pruning/hoisting, pseudo nodes included); omitted when 0 |
| `styles` | object | **sparse** — keys omitted at their default (table below) |
| `image` | `{asset, mode}` | when the node renders an image: asset key + `mode` ∈ FILL \| FIT \| TILE. `<img>`/`<video>`: object-fit contain/scale-down → FIT, else FILL. background-image: background-size contain → FIT, cover → FILL, otherwise repeat ≠ no-repeat → TILE else FILL. canvas/svg → FILL. A text node carries `image` only from `background-image`; the importer paints it on the text's wrapper frame |
| `role` | string \| null | explicit ARIA `role` attribute (first token, trimmed) if present, else IMPLICIT-ROLE by tag (see Semantic layer); unknown tag → `null` (NOT `"generic"`) |
| `axName` | string \| null | best-effort accessible name, ≤80 chars whitespace-collapsed; resolution order aria-label → aria-labelledby joined text → (form controls) button `value` / `<label for>` / wrapping `<label>` / `placeholder` → alt → title → (heading/button/link only) trimmed own text → null |
| `interactable` | bool | conservative true when tag ∈ {button, select, textarea}; OR `a[href]`; OR `input` with `type != hidden`; OR role ∈ {button, link, textbox, combobox, checkbox, radio, menuitem, tab}; OR `tabindex>=0`; OR computed `cursor === 'pointer'`; else false |
| `level` | int (1..6) | **heading nodes only** — h1→1 … h6→6. Heading depth rides here, NOT encoded in `role` (which is the bare string `"heading"`) |
| `iframe` | `"cross-origin"` | placeholder only, plus `origin` (string); no children |

`role`, `axName`, `interactable` are present on **every** node; pseudo-element nodes and the cross-origin iframe placeholder carry `role:null, axName:null, interactable:false`. `level` is present only on headings.

### styles (sparse — default ⇒ key omitted)

Layout — any node:

| Key | Default | Value when present |
|---|---|---|
| `display` | `"block"` | raw computed value (flex, inline-flex, grid, inline-grid, inline, inline-block, flow-root, list-item, table, table-cell, contents, …) |
| `position` | `"static"` | absolute \| fixed \| relative \| sticky |
| `flexDirection` | `"row"` | column \| row-reverse \| column-reverse |
| `flexWrap` | `"nowrap"` | wrap \| wrap-reverse |
| `justifyContent` | `"normal"` | raw |
| `alignItems` | `"normal"` | raw |
| `alignSelf` | `"auto"` | raw |
| `flexGrow` | `0` | number |
| `gap` | `0` | row-gap px |
| `columnGap` | `0` | column-gap px |
| `padding` | `[0,0,0,0]` | `[t,r,b,l]` px |
| `overflow` | `"visible"` | hidden \| clip \| auto \| scroll |
| `sz` | `["auto","auto"]` | `[w,h]` **specified**-size category from `el.computedStyleMap()`: keyword auto / fit-content / min-content / max-content → `"auto"`; px → `"px"`; percent or keyword stretch → `"pct"`; anything else → `"other"`; `computedStyleMap` unavailable → `["px","px"]` |
| `minW` `maxW` `minH` `maxH` | absent | px number, only when specified in px (`minW`/`minH` of 0 omitted) |

Box — any node:

| Key | Default | Value when present |
|---|---|---|
| `bg` | null | `{r,g,b,a}` 0..1; omitted when transparent (alpha 0) |
| `radius` | `0` | px, all four corners equal |
| `radii` | absent | `[tl,tr,br,bl]` px when corners differ (`radius` then omitted) |
| `border` | absent | `{w: number \| [t,r,b,l], color:{r,g,b,a}}` — omitted when every side is 0 / style none\|hidden / color alpha 0; `w` is a number when all four equal; color = first non-zero side's |
| `shadow` | absent | `[{x,y,blur,spread,color:{r,g,b,a},inset:bool}]` parsed from computed box-shadow (Chrome order `<color> <x> <y> <blur> <spread> [inset]`, comma-split outside parens) |
| `opacity` | `1` | number |
| `blur` | `0` | px from `filter: blur(Npx)` |
| `bgBlur` | `0` | px from `backdrop-filter: blur(Npx)` |

Text — ONLY on nodes whose `text` is non-empty (containers omit all of these):

| Key | Default | Value when present |
|---|---|---|
| `color` | null | `{r,g,b,a}` |
| `fontFamily` | `""` | first family in the stack, quotes stripped (`"Inter"`, `"Helvetica Neue"`, `"sans-serif"`) |
| `fontSize` | `16` | px |
| `fontWeight` | `400` | number |
| `fontStyle` | `"normal"` | italic |
| `lineHeight` | null | px number (`normal` → omitted) |
| `letterSpacing` | `0` | px |
| `textAlign` | `"start"` | left \| center \| right \| justify \| end |
| `textDecoration` | `"none"` | underline \| line-through (first token of text-decoration-line) |
| `textTransform` | `"none"` | uppercase \| lowercase \| capitalize |

Colors arrive pre-parsed to 0..1 `{r,g,b,a}` — map straight to SolidPaint.

## Geometry & transforms

`rect` is **layout space**: the box as CSS laid it out before any transform, ancestors' included, at page-viewport origin with scroll 0. The walker carries the accumulated inverse of ancestor transforms down the tree as a `DOMMatrix`; each element's width/height come from `offsetWidth/Height` when it has an own transform or sits under a rotated/skewed ancestor (bounding boxes inflate under rotation) and from `getBoundingClientRect` (scaled by the ancestor inverse) otherwise, and its top-left is the inverse-mapped visual center minus the own-transformed center. A same-origin iframe's content enters as a pure translation to the frame's content box (border + padding + inner scroll) in layout space — inner client rects are already untransformed. `display:none` subtrees are skipped outright; `visibility:hidden` and zero-area nodes are pruned but their children still walk, hoisted to the nearest kept ancestor.

`xf = [a,b,c,d,e,f]` is present only when the element (HTMLElement only) has a 2D affine own transform — CSS `transform`, `translate`, `rotate`, `scale` composed about `transform-origin` (percent `translate` resolved against the element's own size). It is expressed relative to the node's untransformed top-left:

```
P_parent = rect.xy + [[a, c], [b, d]] · p + [e, f]
```

No transform → no `xf`. A `matrix3d` whose depth components are identity (`translateZ(0)` hacks) is flattened to 2D. A 3D, non-affine, or singular (|det| < 1e-6) own transform → no `xf`, the node is flagged `transform`, and its subtree is measured as if the transform were absent.

## Pseudo-elements

`::before` / `::after` on a **container** (an owner that is not inline text) with computed `content` ∉ {none, normal} become nodes of their own: `tag` `"::before"` / `"::after"`, `parent` = owner, placed in preorder immediately after the owner (`::before`) or after the owner's subtree (`::after`), `role:null, axName:null, interactable:false`, `styles` and `image` like any node. They are measured after the walk with sentinel spans: the real pseudo is suppressed through an adopted stylesheet (`[data-cap-nb]::before{content:none!important}` / `[data-cap-na]::after{…}`, one per document or shadow root touched); a `<span>` carrying every computed property of `getComputedStyle(owner, pseudo)` except `content`, with the resolved content as its text (quoted strings unescaped, `attr()` resolved, counters and `url()` → `""`), is prepended/appended and measured with the owner's inverse matrix; its `background-image` is collected as an image asset. Spans, marker attributes, and sheets are removed afterwards. A slot is dropped (indices compacted) when its rect has zero area or it has neither text, image, bg, border, nor shadow (clearfix). Pseudo glyphs on **inline-text** owners fold into the owner's `text` / `runs` instead, as runs carrying the pseudo's own computed style. `::marker` is not captured.

## Shadow DOM and slots

Rendered children follow one rule everywhere (inline-text test, run collection, recursion): `el.shadowRoot ? shadowRoot.childNodes : <slot> inside a ShadowRoot ? assignedNodes({flatten:true}) : el.childNodes`. Closed shadow roots are unreachable → the host is a leaf. `<slot>` and `display:contents` elements have no box → pruned, children hoisted to the parent.

## Text

`text` is the merged content of an inline-text node; `runs` is non-null only when inline spans differ, each run carrying full values. `lines` (text nodes only) counts line boxes: `Range.selectNodeContents(el).getClientRects()` clustered when midlines are within 1 px or fragments overlap by more than half the smaller height (mixed font sizes on one line); vertical writing modes cluster horizontally. `lines > 1` is what makes the importer size the text node to its rect instead of auto-sizing it.

## Assets

Sources: `<img>` (currentSrc), `<picture>` (its `<img>`), `<video>` (poster only), `<canvas>` (`toDataURL` png), inline `<svg>` (outerHTML with explicit width/height attributes set to the computed px; never recursed — the svg node has no children; `<use href="#id">` targets outside the svg are copied into a `<defs>` so the markup stands alone), `background-image: url(...)` on elements and pseudo-elements (first url only; gradients ignored). A `src` ending in `.svg` or a response of `image/svg+xml` → kind `svg` with the text.

Fetch runs in the source tab during the walk: `fetch(url)` → blob → base64, all in parallel, 8 s per asset, 20 s global budget (anything still pending → `error:"timeout"`). An `<img>` whose fetch fails is drawn to a canvas → png (tainted canvas → `error:"tainted"`). Rasters over 4096 px on a side are drawn scaled to 4096 (Figma's `createImage` limit). Assets over 4 MB raw are skipped (`error:"too-large"`); collection stops past 24 MB total (`error:"too-large"`). Bytes that won't decode → `error:"decode"`.

Assets are deduped by resolved URL, so many nodes may reference one key through `image: {asset, mode}`.

## Semantic layer (role / axName / interactable)

The walker computes a lightweight semantic layer in-page (no CDP join). `role` is the explicit `role` attribute if the author set one (open string — `search`, `note`, `tab`, `menuitem` all seen live), else the IMPLICIT-ROLE by tag:

- `button`→button, `a` (only with `href`; bare `a` → null), `nav`→navigation, `header`→banner, `footer`→contentinfo, `main`→main, `aside`→complementary, `ul`/`ol`→list, `li`→listitem, `h1..h6`→heading (+ `level`), `textarea`→textbox, `select`→combobox, `img`→img, `table`→table, `form`→form, `section`→region, `article`→article, `label`→label.
- `input` by `type`: checkbox→checkbox, radio→radio, button/submit/reset/image→button, range→slider, hidden→null, else (incl. default)→textbox.
- Unknown tag → `null`.

`axName` feeds Figma layer naming, not spec-perfect AX. It resolves the common name sources in-page — including form-control labels (`<label for=id>`, wrapping `<label>`, button `value`, `placeholder`) — so e.g. a GitHub login `<input>` whose name lives in a sibling `<label for>` resolves to "Username or email address". Exotic name-computation cases (`aria-owns`, full precedence chains) are the native-AXTree upgrade below. `interactable` is conservative — no false positives over correctness.

#### Accuracy upgrade path — native AXTree join (NOT built in this phase)

This in-page role map is a deliberate v1. The fidelity upgrade is a native `Accessibility.getFullAXTree` join over the agent-browser CDP surface, keyed by `backendNodeId`, replacing the heuristic `role`/`axName` with Chrome's computed accessibility tree (which resolves `<label for>`, `aria-owns`, name-computation precedence, and the full ARIA role taxonomy). That join is the documented next rung, **not implemented here** — the in-page map ships first because it is self-contained in the one walker eval with no CDP dependency.

## Import loop

The helper runs the whole deterministic loop — never hand-roll chunk evals. After the component inventory (`references/reading.md` → Component inventory):

```bash
python3 /tmp/figma_capture.py import /tmp/figma_capture_<slug>.json --components '{"button":"1:2","input":"1:7"}'
```

It targets the default session (`--cdp`, same port resolution as `figma_run.py`) and evals, in order:

1. **Reset** — deletes the capture keys of `window.__batchState` (`captureIds`, `captureRects`, `captureLayout`, `captureReport`, `captureFonts`, `captureAssets`) and seeds `captureAssets = {}`. Every import starts clean.
2. **Assets** — per asset, one eval setting `captureAssets[key]` to the metadata (`kind, mime, w, h, error` — no bytes), then the `b64` / `svg` string appended in ≤150 KB pieces (`a.b64 = (a.b64 || '') + piece`). The importer reads only finished objects.
3. **Node chunks** — consecutive nodes packed by JSON size (≤150 KB per chunk, a node is never split, order preserved). Each eval is `window.__captureSpec = {nodes, flagged, components, meta};` followed by `figma_importer.js`. `flagged`, `components`, and `meta` repeat in every chunk; `meta.title` names the root `[cap:0] <title>`.
4. **Report** — the last eval's return printed as JSON, then `created=N flagged=N fontsFallenBack=N instantiated=N warnings=N`.

Every eval's base64 stays under 300 KB (macOS ARG_MAX headroom). An eval whose result is missing, carries `error`, or exits non-zero stops the run with the error printed and exit 1 — fix and re-run (the reset makes a re-run safe). `--dry-run <dir>` writes each eval to `<dir>/NN_<kind>.js` instead of running it — inspect chunking without a Figma tab. `node tests/importer_stub.js <spec.json>` runs the importer over a spec against a stub Plugin API (font-before-characters enforced) and prints the report — the no-Figma smoke check after touching the importer.

Cross-batch state in `window.__batchState`:

| Key | Shape | Role |
|---|---|---|
| `captureIds` | `{i → figmaNodeId}` | cleanup workers resolve a spec index to a real node |
| `captureRects` | `{i → rect}` | parents from earlier chunks position later children |
| `captureLayout` | `{i → {mode:'HORIZONTAL'\|'VERTICAL'\|'NONE', alignItems, primaryGap}}` | parent layout for the placement rules |
| `captureReport` | divergence report (below), cumulative — `flagged`, `fontsFallenBack`, `instantiated`, `warnings` | |
| `captureFonts` | font-ladder cache per (family, weight, italic) | |
| `captureAssets` | `{key → asset}` | streamed by the helper, read by the importer; `figma.createImage` results are cached on the asset as `asset.hash`, so nodes sharing a URL upload once |

### Component instantiation contract

`--components` (inline JSON or a file path) is the category→component map the importer receives as `window.__captureSpec.components` in every chunk. Shape: `{ <category>: <componentId> }` where `componentId` is a **local** Figma component node id (resolved via `figma.getNodeByIdAsync`, NOT a published key).

The importer derives a node's category from `role` first, else `tag`:

| Category | role → | tag → |
|---|---|---|
| `button` | button | button |
| `link` | link | a |
| `input` | textbox, combobox | input, textarea, select |
| `checkbox` | checkbox | — |
| `radio` | radio | — |
| `nav` | navigation | nav |
| `tab` | tab | — |
| `menuitem` | menuitem | — |
| `list` | list | — |
| `listitem` | listitem | — |
| `img` | img | img |
| `heading` | heading | — |
| `banner` | banner | — |
| `contentinfo` | contentinfo | — |
| `card` | region | — |

A node instantiates **only** on an exact category hit present in the map: the importer does `figma.getNodeByIdAsync(componentId)` → `createInstance()`, resizes to the captured `rect`, sets the instance's primary text layer (`findOne(c => c.type === 'TEXT')`) from the node text, and names it (source-ref below). No match, or no component map → it falls through to the frame logic (conservative — no guessed instantiation). Instance subtrees are structurally frozen, so a captured child of a node that became an instance is placed at its absolute rect rather than appended into the frozen instance.

### Source-ref node naming

Every created node is named `[cap:<i>] <readable>` where `readable = axName || role || tag`; the root (i=0) is `[cap:0] <meta.title>` when the title is non-empty. Flag tags are a suffix — `[cap:42] [capture:grid] div`, `[cap:42] [capture:image tainted] img`, `[cap:42] [capture:iframe <origin>]`. Text and instance nodes are named too. A text node built with a wrapper frame (box paint — see the mapping table) gives the wrapper the `[cap:<i>]` name and the `captureIds` / `captureRects` / `captureLayout` entries; its TEXT child is `[cap:<i>] text`. This compact source-index ref is what makes source↔Figma traceable for review and a future visual diff.

## Divergence report

Accumulated in `window.__batchState.captureReport`; every node-chunk eval returns the cumulative report plus `batchDone`:

```
created          int                                   Figma nodes created so far
flagged          [ {nodeId, reason} ]                  reason ∈ "grid" | "block" | "transform" | "image"
fontsFallenBack  [ "<family>/<style> → <used family>/<used style>" ]   each substitution once
instantiated     [ {nodeId, category, componentId} ]   nodes built as a component instance
warnings         [ "[cap:<i>] <what>: <message>" ]     any try/catch'd Plugin API failure (e.g. an svg that fails to parse)
batchDone        int                                   nodes processed in this chunk
```

One reason string per flagged node, identical in the name tag and the report:

- `grid` — display grid / inline-grid → NONE frame, children at their layout-space rects.
- `block` — any other non-flex, non-block-flow display (inline, table*, contents, …) **with children** (`kids` present) → NONE frame. A NONE leaf (img, inline svg, a pseudo with only a bg) stays NONE but unflagged.
- `transform` — the walker flagged a 3D / non-affine own transform, or an in-flow Auto Layout child has an `xf` that is neither a pure rotation nor a pure translation (it keeps its slot; geometry is approximate).
- `image` — the node's asset carries an `error` → no image fill, `[capture:image <error>]`.

When several apply, one wins: `image` > `grid` / `block` > walker `transform` > in-flow `transform`.

## CSS → Figma mapping

The deterministic import reads each node's sparse `styles` and maps to the nearest Figma primitive, same as `conventions.md` → Source → Figma primitives but keyed on computed CSS. (This is the ONE allowed CSS-property table — AGENTS.md carries a carve-out to the no-per-language-tables rule for it.) The semantic `role` runs alongside: it drives layer naming (source-ref above) and component selection (Component instantiation contract above) — a node that hits a category in the component map becomes an instance and skips the mapping below.

| Spec construct | Figma |
|---|---|
| `display` flex / inline-flex + `flexDirection` row / row-reverse | `layoutMode = 'HORIZONTAL'` (reverse keeps DOM order) |
| `display` flex / inline-flex + `flexDirection` column / column-reverse | `layoutMode = 'VERTICAL'` (reverse keeps DOM order) |
| `display` omitted (block) / flow-root / inline-block / list-item | `layoutMode = 'VERTICAL'` (inferred stack) |
| `display` grid / inline-grid | `layoutMode = 'NONE'`, `[capture:grid]` |
| `display` inline / table* / contents / anything else | `layoutMode = 'NONE'`; `[capture:block]` only when `kids` present (leaves stay unflagged) |
| every frame | `resize(rect.w, rect.h)`, `primaryAxisSizingMode = counterAxisSizingMode = 'FIXED'` — captured rects are truth, never hug |
| `flexWrap` wrap / wrap-reverse | `layoutWrap = 'WRAP'`, `counterAxisSpacing` = the other gap |
| `justifyContent` | `primaryAxisAlignItems`: space-between / space-around / space-evenly → SPACE_BETWEEN, center → CENTER, flex-end / end → MAX, else MIN |
| `alignItems` | `counterAxisAlignItems`: center → CENTER, flex-end / end → MAX, baseline → BASELINE (HORIZONTAL only), else MIN |
| `gap` / `columnGap` | `itemSpacing` = `columnGap` (HORIZONTAL) or `gap` (VERTICAL) |
| `padding` `[t,r,b,l]` | `paddingTop / Right / Bottom / Left` |
| `overflow` hidden / clip / auto / scroll | `clipsContent = true` (else false) |
| `flexGrow` > 0, or `sz` `"pct"` along the parent's primary axis | `layoutGrow = 1` |
| `sz` `"auto"` / `"pct"` along the counter axis AND `alignSelf` auto / normal / stretch AND parent `alignItems` normal / stretch | `layoutAlign = 'STRETCH'` (else INHERIT); never for inline-level children (`display` starting with `inline`) of block-flow parents |
| `minW` `maxW` `minH` `maxH` | `minWidth` `maxWidth` `minHeight` `maxHeight` |
| `position` absolute / fixed inside an Auto Layout parent | `layoutPositioning = 'ABSOLUTE'`, placed at `rect − parentRect` |
| child of a NONE parent, or root | `x, y = rect − parentRect` (absolute rect when no parent) |
| `xf` on an absolute or NONE-parent child | `relativeTransform = [[a, c, rx+e], [b, d, ry+f]]` |
| `xf` translate-only on an in-flow Auto Layout child | dropped — flow position wins, not flagged |
| `xf` pure rotation on an in-flow Auto Layout child | `rotation = −atan2(b, a)·180/π` |
| `xf` neither pure rotation nor translate-only on an in-flow child | stays in flow, `[capture:transform]` |
| `iframe` `"cross-origin"` | empty placeholder frame `[capture:iframe <origin>]` |
| `bg` | `fills = [{type:'SOLID', color:{r,g,b}, opacity:a}]` |
| `image` (asset kind image) | `fills += [{type:'IMAGE', imageHash: createImage(base64Decode(b64)).hash, scaleMode: mode}]` after `bg` |
| `image` (asset kind svg) | `figma.createNodeFromSvg(svg)` resized to `rect`, in place of a frame |
| `image` (asset with `error`) | no image fill, `[capture:image <error>]` |
| `radius` / `radii` | `cornerRadius` / `topLeftRadius topRightRadius bottomRightRadius bottomLeftRadius` |
| `border` | `strokes = [SolidPaint]`, `strokeWeight` (number) or `strokeTop/Right/Bottom/LeftWeight` (array), `strokeAlign = 'INSIDE'` |
| `shadow` | `effects += {type: DROP_SHADOW \| INNER_SHADOW (inset), color:{r,g,b,a}, offset:{x,y}, radius: blur, spread, visible:true, blendMode:'NORMAL'}` |
| `blur` / `bgBlur` | `effects += {type: LAYER_BLUR \| BACKGROUND_BLUR, radius, visible:true}` |
| `opacity` | `opacity` |
| `color` (text) | text `fills` SolidPaint |
| `fontFamily` + `fontWeight` + `fontStyle` | `fontName` via the font ladder below |
| `fontSize` | `fontSize` |
| `lineHeight` / `letterSpacing` | `{unit:'PIXELS', value}` |
| `textAlign` | `textAlignHorizontal`: left / start → LEFT, center → CENTER, right / end → RIGHT, justify → JUSTIFIED |
| `textDecoration` | `textDecoration`: underline → UNDERLINE, line-through → STRIKETHROUGH |
| `textTransform` | `textCase`: uppercase → UPPER, lowercase → LOWER, capitalize → TITLE |
| `runs` | `setRangeFontName / setRangeFontSize / setRangeFills / setRangeTextDecoration` per run |
| `lines` > 1, or the text node gets `layoutAlign STRETCH` | `resize(rect.w, rect.h)` then `textAutoResize = 'HEIGHT'`; otherwise `textAutoResize = 'WIDTH_AND_HEIGHT'` |
| text node with `bg`, `border`, `image`, non-zero `padding`, `radius` / `radii`, or `shadow` | wrapper FRAME (HORIZONTAL Auto Layout, FIXED to rect, padding and box paint/effects on the frame, `primaryAxisAlignItems` CENTER when `textAlign` center else MIN, `counterAxisAlignItems` CENTER) holding the TEXT node; every placement rule applies to the wrapper |

**Font ladder** per (family, weight, italic): style name from weight — 100 Thin, 200 ExtraLight, 300 Light, 400 Regular, 500 Medium, 600 SemiBold, 700 Bold, 800 ExtraBold, 900 Black — plus ` Italic` when italic (`Regular Italic` → `Italic`). Generic families (sans-serif, serif, monospace, system-ui, -apple-system, ui-*, cursive, fantasy, emoji, math) go to Inter directly. Try `{family, style}` → `{family, Regular}` → `{Inter, style}` → `{Inter, Regular}`; cached in `captureFonts`; every substitution lands once in `fontsFallenBack`. Never assume a font loaded — substitution is always reported.

## Fallback ladder + cleanup

**Deterministic import first.** `figma_capture.py import` runs the whole spec inline. Per node, three rungs:

1. **Exact** — flex and block-flow containers → Auto Layout from the sparse styles; positioned children → ABSOLUTE inside them; 2D transforms → `rotation` / `relativeTransform`; images → fills; inline svg → vector nodes.
2. **Geometric** — `grid` / `block` displays → `layoutMode = 'NONE'` frame at the rect; children placed at their layout-space rects (with `relativeTransform` when they carry `xf`).
3. **Rasterize** *(manual — no automated path)* — when even geometry won't reconstruct (overlap, unreadable structure), screenshot the region and drop it in by hand on the cleanup pass.

Each drop down a rung is one divergence-report entry.

**Then cleanup, worker-driven.** The `[capture:*]`-tagged nodes are the work-list: `grid`, `block`, `transform`, `image`. The coordinator reads the report, groups flagged subtrees, and dispatches **cleanup workers** via `figma-worker.md` — one per flagged area — with concrete assertions resolved through `captureIds`, e.g.:

```
- node 1:42 (was spec i=5, [capture:grid]): layoutMode is not 'NONE'
- node 1:51 (was spec i=8, [capture:image tainted]): fills.some(f => f.type === 'IMAGE')
```

**Budget scope.** The SKILL.md 20-operation / 25-assertion worker budget governs **only the cleanup workers** — they make per-node judgment calls and split like any other dispatch. It does **not** govern the deterministic import: that's coordinator-inline with no per-node judgment, so a 500-node page is one helper invocation, not 25 workers. (A 500-node import modeled as worker ops would force absurd splitting; capture sidesteps the rule by not being agentic.)

## Risks and limitations

- **Cross-origin iframes.** Captured as a single empty **placeholder** frame named `[capture:iframe <origin>]`; the walker cannot recurse into them — CDP frame-target routing is beyond the agent-browser surface we depend on (AGENTS.md Ceiling). Same-origin iframes are walked inline in layout space.
- **Images, svg, canvas — CORS-bound.** Pixels cross over only when the source tab can read them: a cross-origin `<img>` whose server blocks `fetch` falls back to a canvas draw, and a tainted canvas yields `error:"tainted"` — an empty box tagged `[capture:image tainted]` on the cleanup list. Same for `timeout` / `too-large` / `decode` / `fetch`. `<video>` contributes its poster only; `<canvas>` is a snapshot.
- **Fonts.** Real families are tried first through the ladder; anything missing in Figma degrades toward Inter and is reported in `fontsFallenBack`. Generic families (sans-serif, serif, monospace, system-ui, …) map to Inter directly and are not reported as substitutions. Variable-font axes, optical sizes, and weights outside the 100–900 names are not matched.
- **Mixed content.** Text sitting directly beside block-level siblings is lost — the inline-text test requires every rendered child to be inline, and a container node carries no text. Wrap-free CMS markup (`<div>Hello <p>…</p></div>`) drops the bare "Hello".
- **`mask-image` icons** arrive as solid boxes (only the element's bg color survives the capture); gradient and `mask` paints are not modelled.
- **grid / non-flow displays.** Demoted to NONE frames (`grid` / `block`), never guessed into Auto Layout — they land on the cleanup work-list.
- **Still out:** 3D and non-affine transforms (flagged `transform`, subtree flattened), gradient fills (`bg` is solid-only; gradient `background-image` is ignored), CSS-variable / design-token recovery (computed values only — nothing binds to Figma variables), cross-origin iframes, native AXTree (Semantic layer → upgrade path).
