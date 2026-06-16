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

They never collide. Hand the node spec between them via a **`/tmp/<key>.json` file**, never a shared tab.

```bash
agent-browser --session capture open <url>          # 'open', not 'navigate'/'goto'
agent-browser --session capture eval -b <walker_b64>  # walk the page in the capture tab
# walker result returns over the CDP WebSocket → persist to /tmp/<key>.json
# then import reads that file and evals against the DEFAULT session's Figma tab
```

**Active-tab nondeterminism warning.** A sessionless `eval` runs in whatever tab is marked `→` in `agent-browser tab list` (last opened or last selected). With a Figma tab AND a source tab both open in the default session this is **nondeterministic**. Never run a capture eval sessionless when a Figma tab is open — that's the whole reason the source page lives in `--session capture`.

**Public-vs-authenticated limitation.** An isolated `--session capture` context does **not** share the user's Chrome cookies/login. So v1 captures **public/unauthenticated** pages well. An authenticated page would need the walk to run as a second tab *inside* the logged-in default context (select it by index before each walker eval, accepting the active-tab nondeterminism that brings). v1 = public pages via `--session capture`; auth pages are a documented limitation, not yet supported.

**Close before import.** Close the capture session before the first importer eval so only the Figma tab is live in the default session. After capture, confirm the default session still binds the Figma tab (`agent-browser eval "typeof figma"` → `"object"`).

## Spec format

The walker emits one JSON document, persisted to `/tmp/<key>.json`. The importer reads it in ≤200-node chunks (eval results travel over the CDP WebSocket, so ARG_MAX constrains only the importer's *input*, not the walker's output). This schema is **frozen** — the importer and this doc mirror it exactly.

Envelope (under the agent-browser `data.result` wrapper):

```
meta     { nodeCount, title, url, viewport: {w, h} }
flagged  [ {i, reason} ]          # reason ∈ "grid" | "abs" | "transform"
nodes    [ <node> ]               # flat, DFS-preorder, root is i=0
```

`flagged` is the **capture-side divergence input**: every node the walker already knows can't auto-layout deterministically. The importer tags these subtrees and adds its own substitutions (font, fallback rung) to produce the final divergence report.

Each `node`:

| Field | Shape | Notes |
|---|---|---|
| `i` | int | DFS-preorder index; root = 0 |
| `parent` | int | parent's `i`; `-1` for root |
| `tag` | string | lowercase HTML tag (`div`, `h1`, `p`, `span`) |
| `name` | null | Figma name slot — importer fills it |
| `rect` | `{x, y, w, h}` | CSS px, viewport-relative |
| `text` | string | full text content; `""` for containers |
| `runs` | null \| `[{text, color, fontSize, fontWeight, decoration}]` | inline runs only when spans differ; else null and `text` is authoritative |
| `styles` | object | computed styles, normalized — see below |
| `role` | string \| null | explicit ARIA `role` attribute (first token, trimmed) if present, else IMPLICIT-ROLE by tag (see Semantic layer); unknown tag → `null` (NOT `"generic"`) |
| `axName` | string \| null | best-effort accessible name, ≤80 chars whitespace-collapsed; resolution order aria-label → aria-labelledby joined text → (form controls) button `value` / `<label for>` / wrapping `<label>` / `placeholder` → alt → title → (heading/button/link only) trimmed own text → null |
| `interactable` | bool | conservative true when tag ∈ {button, select, textarea}; OR `a[href]`; OR `input` with `type != hidden`; OR role ∈ {button, link, textbox, combobox, checkbox, radio, menuitem, tab}; OR `tabindex>=0`; OR computed `cursor === 'pointer'`; else false |
| `level` | int (1..6) | **heading nodes only** — h1→1 … h6→6. Heading depth rides here, NOT encoded in `role` (which is the bare string `"heading"`) |

`role`, `axName`, `interactable` are present on **every** normal node and on the cross-origin iframe placeholder (`role:null, axName:null, interactable:false`); `level` is present only on headings.

#### Semantic layer (role / axName / interactable)

The walker computes a lightweight semantic layer in-page (no CDP join). `role` is the explicit `role` attribute if the author set one (open string — `search`, `note`, `tab`, `menuitem` all seen live), else the IMPLICIT-ROLE by tag:

- `button`→button, `a` (only with `href`; bare `a` → null), `nav`→navigation, `header`→banner, `footer`→contentinfo, `main`→main, `aside`→complementary, `ul`/`ol`→list, `li`→listitem, `h1..h6`→heading (+ `level`), `textarea`→textbox, `select`→combobox, `img`→img, `table`→table, `form`→form, `section`→region, `article`→article, `label`→label.
- `input` by `type`: checkbox→checkbox, radio→radio, button/submit/reset/image→button, range→slider, hidden→null, else (incl. default)→textbox.
- Unknown tag → `null`.

`axName` feeds Figma layer naming, not spec-perfect AX. It resolves the common name sources in-page — including form-control labels (`<label for=id>`, wrapping `<label>`, button `value`, `placeholder`) — so e.g. a GitHub login `<input>` whose name lives in a sibling `<label for>` resolves to "Username or email address". Exotic name-computation cases (`aria-owns`, full precedence chains) are the native-AXTree upgrade below. `interactable` is conservative — no false positives over correctness.

#### Accuracy upgrade path — native AXTree join (NOT built in this phase)

This in-page role map is a deliberate v1. The fidelity upgrade is a native `Accessibility.getFullAXTree` join over the agent-browser CDP surface, keyed by `backendNodeId`, replacing the heuristic `role`/`axName` with Chrome's computed accessibility tree (which resolves `<label for>`, `aria-owns`, name-computation precedence, and the full ARIA role taxonomy). That join is the documented next rung, **not implemented here** — the in-page map ships first because it is self-contained in the one walker eval with no CDP dependency.

`styles`:

```
display flexDirection justifyContent alignItems gap columnGap
padding[t,r,b,l]
bg color borderColor          # {r,g,b,a} in 0..1; bg is null when transparent
borderWidth borderRadius
fontFamily fontSize fontWeight lineHeight textAlign
opacity overflow position transform
```

Colors arrive pre-parsed to 0..1 `{r,g,b,a}` (map straight to SolidPaint; `bg: null` → no fill). `transform` is the raw matrix string or null.

### Divergence-report contract

Each importer eval returns the running divergence report — the work-list for cleanup — accumulated across batches in `window.__batchState.captureReport`:

```
created          int                          # total Figma nodes created across all batches
flagged          [ {nodeId, reason} ]         # nodeId = created Figma node ID; reason ∈ "grid"|"abs"|"transform"|"block"|"none"
fontsFallenBack  [ string ]                    # Inter styles requested but unavailable, fell back to Regular (e.g. ["Medium"])
instantiated     [ {nodeId, category, componentId} ]  # nodes built as a component instance instead of a raw frame
```

`instantiated` lists every node the importer reused a local component for: `nodeId` = the Figma instance id, `category` = the normalized role/kind key that matched (see Component instantiation below), `componentId` = the local component id used. Accumulated across batches in `window.__batchState.captureReport` alongside `flagged`/`fontsFallenBack`.

The per-eval return also carries `batchDone` (int) — nodes processed in that batch. Every `flagged` subtree (NONE-frame demotion) and every font substitution appears. The importer writes the spec-index → Figma-node-ID map to `window.__batchState.captureIds` so cleanup workers resolve `i` to a real node.

### Component instantiation contract

The coordinator inventories local components (`references/reading.md` → Component inventory) and passes a category→component map to the importer as `window.__captureSpec.components` (fallback `window.__batchState.captureComponents`). Shape: `{ <category>: <componentId> }` where `componentId` is a **local** Figma component node id (resolved via `figma.getNodeByIdAsync`, NOT a published key).

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

A node instantiates **only** on an exact category hit present in the map: the importer does `figma.getNodeByIdAsync(componentId)` → `createInstance()`, resizes to the captured `rect`, sets the instance's primary text layer (`findOne(c => c.type === 'TEXT')`) from the node text, and names it (source-ref below). No match, or no component map → it falls through to the existing frame logic (conservative — no guessed instantiation). Instance subtrees are structurally frozen, so a captured child of a node that became an instance is placed at its absolute rect rather than appended into the frozen instance.

### Source-ref node naming

Every created node is named `[cap:<i>] <readable>` where `readable = axName || role || tag` (the same three fields the walker emits). Existing `[capture:*]` flag tags are kept as a suffix — e.g. `[cap:42] [capture:grid] div`, and a cross-origin iframe becomes `[cap:42] [capture:iframe <origin>]`. Text and instance nodes are named too. This compact source-index ref is what makes source↔Figma traceable for review and a future visual diff.

## CSS → Figma mapping

The deterministic import reads each node's computed `styles` and maps to the nearest Figma primitive, same as `conventions.md` → Source → Figma primitives but keyed on computed CSS. (This is the ONE allowed CSS-property table — AGENTS.md carries a carve-out to the no-per-language-tables rule for it.) The semantic `role` runs alongside this style mapping: it drives layer naming (source-ref above) and component selection (Component instantiation contract above) — a node that hits a category in the component map becomes an instance and skips the style→frame mapping below.

| Computed CSS construct | Figma primitive |
|---|---|
| `display: flex` + `flexDirection: row` | `layoutMode = 'HORIZONTAL'` |
| `display: flex` + `flexDirection: column` | `layoutMode = 'VERTICAL'` |
| `display: block` (simple non-overlapping flow) | `layoutMode = 'VERTICAL'` (inferred stack) |
| `justifyContent: space-between` | `primaryAxisAlignItems = 'SPACE_BETWEEN'` |
| `justifyContent / alignItems: center` | `primaryAxisAlignItems` / `counterAxisAlignItems = 'CENTER'` |
| `gap` / `columnGap` | `itemSpacing = N` |
| `padding: [t,r,b,l]` | `paddingTop/Right/Bottom/Left` |
| `bg: {r,g,b,a}` | `fills = [{type:'SOLID', color:{r,g,b}, opacity:a}]` (SolidPaint) |
| `bg: null` | no fill |
| `color: {r,g,b,a}` (on text) | text `fills` SolidPaint |
| `borderColor` + `borderWidth` | `strokes = [SolidPaint]` + `strokeWeight` |
| `borderRadius` | `cornerRadius = N` |
| `fontWeight: "400" / "700" / …` | Inter style (`Regular` / `Bold` / mapped weight) |
| `fontSize`, `lineHeight` | `fontSize`; `lineHeight` as `{unit, value}` |
| `display: grid` | `layoutMode = 'NONE'` frame, name-tagged `[capture:grid]` |
| `position: absolute` / `fixed` | `layoutMode = 'NONE'` frame, name-tagged `[capture:abs]` |
| `transform: matrix(...)` | `layoutMode = 'NONE'` frame at AABB rect, name-tagged `[capture:transform]` |

NONE-tagged frames are placed at their captured `rect` coordinates; their `[capture:*]` name is the cleanup work-list marker. v1 renders **all** text in Inter — `fontWeight` maps to an Inter style by weight; the captured `fontFamily` rides in the spec but is not yet applied — see Risks → fonts.

## Fallback ladder + cleanup

**Deterministic import first.** The coordinator runs the importer inline over the spec in ≤200-node chunks. Per node, three rungs:

1. **Exact** — `display: flex` (and simple non-overlapping block flow) → Auto Layout straight from computed styles.
2. **Geometric** — anything tagged `grid` / `abs` / `transform` → `layoutMode = 'NONE'` frame at the rect AABB, `[capture:*]`-named.
3. **Rasterize** *(manual / future — no automated path in v1)* — when even geometry won't reconstruct (overlap, unreadable structure), screenshot the region and drop it in by hand on the cleanup pass.

Each drop down a rung is one divergence-report entry.

**Then cleanup, worker-driven.** The `[capture:*]`-tagged subtrees are the work-list. The coordinator reads the divergence report, groups flagged subtrees, and dispatches **cleanup workers** via `figma-worker.md` — one per flagged area — with concrete assertions resolved through `captureIdMap`, e.g.:

```
- node 1:42 (was spec i=5, [capture:grid]): layoutMode is not 'NONE'
- node 1:51 (was spec i=8, [capture:abs]): layoutPositioning == 'ABSOLUTE', constraints set
```

**Budget scope.** The SKILL.md 20-operation / 25-assertion worker budget governs **only the cleanup workers** — they make per-node judgment calls and split like any other dispatch. It does **not** govern the deterministic import: that's coordinator-inline with no per-node judgment, so a 500-node page is one inline pass, not 25 workers. (A 500-node import modeled as worker ops would force absurd splitting; capture sidesteps the rule by not being agentic.)

## Risks and limitations

- **Cross-origin iframes.** Captured as a single empty **placeholder** frame named `[capture:iframe <origin>]`; the walker cannot recurse into them — CDP frame-target routing is beyond the agent-browser surface we depend on (AGENTS.md Ceiling). Same-origin iframes are walked inline with rect offsets.
- **grid / transform / pseudo-elements.** `display: grid` and `transform` are deterministically demoted to NONE frames (rungs above), never guessed into Auto Layout — they land on the cleanup work-list. `::before` / `::after` are read via `getComputedStyle(el, '::before')` and merged into the owning node; complex generated content is best-effort.
- **Fonts.** v1 renders **all** text in **Inter** — the captured `fontFamily` is not yet applied (it rides in the spec for a future font-matching pass). `fontWeight` → Inter style: ≥700 `Bold`, ≥500 `Medium`, else `Regular`. If that Inter style fails to load, the importer falls back to `Regular` and records the requested style in `fontsFallenBack`. Never assume a weight loaded — substitution is always reported.
- **Images, SVG, and `<canvas>` are not captured in v1 — no pixels cross over.** The walker records geometry and computed styles only, so an `<img>` arrives as an empty frame at its layout box (size and position preserved, fill = its computed `backgroundColor`, usually transparent); `background-image`, inline `<svg>`, and `<canvas>` contribute only their box. Real pixels are future work: image fills via a source-tab `fetch` (sidesteps CORS) and inline SVG via `figma.createNodeFromSvg`. Until then, image-bearing nodes are best handled on the cleanup pass — drop a real asset into the empty frame by hand or via a follow-up worker.
