# Execution: eval patterns

The eval patterns for all automation against Figma's Plugin API, through perch.
Connection setup lives in `references/connection.md` (perch, rooms, troubleshooting).

The `python3 <skill-dir>/figma_*.py` helper calls are pre-allowed in Claude Code (`Bash(python3 *figma_*.py *)`); other agents may ask once. Every script below runs as `python3 <skill-dir>/figma_run.py --file <url> -e '<script>'`.

## Eval methods

Run the helpers in place from the skill directory (`<skill-dir>` below); they find `figma_perch.mjs` next to themselves, so nothing is copied to `/tmp`. Don't use heredocs (`<<`), pipes (`|`), or input redirects (`<`) in Bash — agents flag them for approval even with permissions set.

### Inline script (one turn per eval)

Pass the script with `-e` (or `--js`) and run it in the same Bash call that writes it:

```bash
python3 <skill-dir>/figma_run.py -e 'const page = figma.currentPage;
await figma.loadFontAsync({ family: "Inter", style: "Regular" });
return { name: page.name, frames: page.children.length };'
```

- **Result.** Printed as one line of JSON, keys sorted. A plain script returns its completion value (its last expression). A script with top-level `await` or `return` runs as an async function body instead, so its result is what it `return`s; no IIFE needed.
- **Scope.** Each script's top-level `const`/`let` stay in that script; share state across evals through `window.__batchState` (below).
- **Quoting.** The script sits in single quotes, so write JS strings with `"` or backticks; a `'` ends the shell string.
- **Other sources.** A path to a `.js` file (written with the Write tool) works the same, and `-` reads the script from stdin.
- **File.** `--file <figma-url-or-key>` picks the tab (required when several Figma files are open); `FIGMA_FILE` is its default.
- **Timeout.** A script that awaits gets 100s (under the Bash tool's own 120s), or `--timeout <seconds>` (1 to 300) for a longer job such as a big export or `loadAllPagesAsync` on a large file. A script that times out keeps running; the error names `--recover <id>` for its result (Lost replies and timeouts below).

### Batched evals

For ≥3 sequential evals with no intermediate user feedback or state inspection, give them to one `figma_run.py` call: one perch request for all of them. Scripts are `-e '<js>'`, `.js` paths, or `-` (stdin, once), run in the order given:

```bash
python3 <skill-dir>/figma_run.py -e 'window.__batchState = { ids: [] }; return "ready"' /tmp/step2.js -e 'return window.__batchState.ids'
```

With two or more scripts, each result prints under a `== <label> ==` header (the file's basename, `-e[n]` for the nth inline script, `stdin`) as `{"origin": ..., "result": ...}`, or `Evaluation error: ...` (with a `hint:` line under a known error). `--stop` ends the batch at the first script that throws, returns nothing or returns `{error}`; the rest don't run and the exit code is 1. Use it whenever a step builds on the one before. The batch shares one browser tab, so `window.__batchState` persists across the steps the same way it does between separate `figma_run.py` calls.

When NOT to batch: when step N needs to read the result of step N-1 before deciding what step N+1 should do, or when parallel workers each have their own chain (each parallel worker calls `figma_run.py` for its own chain; you don't batch across workers).

## Resident helper library (`--lib`)

`python3 <skill-dir>/figma_run.py --lib -e '<js>'` puts `figma_lib.js` in front of the (first) script. It installs `window.__fx` once per tab; later `--lib` calls skip the install, and a newer copy replaces an older one. Every helper is async; `ref` / `parent` take a node or its id.

| Call | Does |
|------|------|
| `__fx.recon({nodeId, depth, maxChars})` | `{pages, tree, truncated}`: the page list (`*` current) and a flat text tree, 3 levels for a page, full depth for a node, 8000 chars |
| `__fx.inventory({match, maxChars, scope, fresh})` | what the file has to reuse, one line each: `references/reading.md` → Component inventory |
| `__fx.frame({parent, name, dir, gap, pad, align, justify, wrap, w, h, fill, stroke, strokeWeight, radius, clip, component, abs, x, y, constraints})` | a frame (or component), no fill unless given. `dir` V\|H\|NONE; `pad` n, [v,h] or [t,r,b,l]; `align` / `justify` start\|center\|end\|between\|baseline; `w` / `h` a number (FIXED), `'fill'` or `'hug'` (the default with `dir`). `gap`, `pad` and `radius` bind to the FLOAT variable holding the value (scoped `GAP` / `CORNER_RADIUS` first, then all scopes); `__fx.autoLayout` too, dropping a binding a new value no variable holds |
| `__fx.autoLayout(ref, opts)` | the same layout options on an existing frame |
| `__fx.text(chars, {parent, name, family, weight, size, lineHeight, textStyle, color, w, align, abs, x, y, constraints})` | loads the font first; `weight` a style name or a CSS weight (700 → Bold); `textStyle` by name or id; `w` `'fill'` or a width wraps |
| `__fx.icon(svg, {parent, name, component, color})` | an SVG as one auto-layout frame (a component with `component: true`): paths sharing a paint flatten into one vector held where the SVG draws it by padding, so it hugs to the SVG's size; paths with different paints stay apart, absolute and scaling. `color` binds each vector's stroke, or its fill when it has none. `set: 'Icon'` with `name`: the `Name=<name>` variant of that set on the page, made on first use with auto layout and HUG; an existing name returns that variant |
| `__fx.linkCopies([ids], {master, name})` | `master` (default the first id) becomes a component in place, unchanged; a text that differs between copies gets a TEXT property; each other copy with the same structure (every depth) is swapped for an instance at its index keeping its name, position, size, texts, differing fills, visibility and nested instances' components. Returns `{master, props: {layer: key}, linked: [{copy, instance}], raw: [{id, reason}]}` |
| `__fx.instance(idOrKeyOrName, props, {parent, name, w, h, abs, x, y, constraints})` | variant axes in `props` pick the variant (from a variant id, the axes left out keep its values); other properties by short name (`Label`, not `Label#1:2`) |
| `__fx.bindFill(ref, value, field)` | `value` a hex, or a variable or paint style (name, id or object). A hex binds the local variable (else paint style) with exactly that value, else paints raw. Returns `{bound, id}`; `field` `'strokes'` for strokes |
| `__fx.react(ref, [{on, do}], {append})` | sets reactions: `on` `'click'`\|`'hover'`\|`'press'`\|`{key: 27}`\|`{after: ms}`; `do` `'back'`\|`'close'`\|`{to, nav: 'navigate'\|'overlay'\|'swap'\|'change'\|'scroll', anim: 'smart'\|'dissolve'\|'instant'\|'push-left', ms}`. Replaces the list; `append` replaces only the triggers named: `references/prototyping.md` |
| `__fx.overlayFrame({base, name, items, scrim, page})` | an overlay that opens in place: base-sized, see-through, `items` (`{node, x, y}`) at their place over a Scrim that closes, Esc closes |
| `__fx.flow(page, frame, name)` | a named flow starting point on the page, one per frame and name |
| `__fx.audit(rootId, {limit})` | structural problems under a node or page: `{counts, shares, ids, text}` (up to 5 ids each); `text` is empty when clean |

`frame` and `text` take `fill` / `stroke` / `color` the way `bindFill` does, so a source hex lands bound when the file has a matching token.

```js
const s = await __fx.frame({ name: 'Login', dir: 'V', w: 375, gap: 16, pad: 24, fill: '#ffffff' });
await __fx.text('Welcome back', { parent: s, weight: 'Bold', size: 28, color: 'color/text' });
await __fx.instance('Button', { Variant: 'Primary', Label: 'Sign in' }, { parent: s, w: 'fill' });
return (await __fx.audit(s.id)).text;
```

`audit` counts, all best at 0: `rawRepeats` (repeated non-instance subtrees), `fixedInFlow` (frames FIXED on both axes inside auto layout), `absDefaultConstraints` (absolute or no-auto-layout children left at MIN/MIN), `groups`, `defaultNames`, `unboundPaints` (raw paints equal to a local variable), `textFixedInAutoLayout` (textAutoResize NONE), `textOverflow`, `componentsWithoutAutoLayout`, `unlinkedProps` (component properties no layer references), `danglingReactions` (a destination that doesn't resolve), `lostHover` (an instance whose own reactions dropped its main component's hover), `overlayNotFullSize` (an overlay smaller than the screen that opens it). `shares` holds `instanceRatio` and `autoLayoutShare`, higher is better. `text` has one line per nonzero count: the key, the count, its ids (`...` when more were left out) and the fix, e.g. `groups 1 [12:4] -> replace the group with an auto-layout frame`. Return `.text` when you only need what to fix.

## State between evals

`window.__batchState` persists across separate eval calls (same browser tab). Fold steps into one eval unless you need to look at an intermediate result; steps you can't fold go in one `figma_run.py` call:

```bash
python3 <skill-dir>/figma_run.py --lib --file <url> \
  -e 'const f = await __fx.frame({name: "Card", dir: "V", w: 320, gap: 8, pad: 16});
window.__batchState = window.__batchState || {}; window.__batchState.a_cardId = f.id; return f.id' \
  -e 'const card = await figma.getNodeByIdAsync(window.__batchState.a_cardId);
await __fx.text("Card Title", {parent: card, weight: "Bold", size: 24, w: "fill"});
figma.commitUndo(); return card.children.length'
```

Use namespaced keys when parallel workers share the same tab: `a_cardId`, `b_cardId`.

## Verification patterns

### Property check

```js
(async function() {
  var node = await figma.getNodeByIdAsync('NODE_ID');
  return {
    name: node.name, type: node.type,
    layout: node.layoutMode,
    sizing: {h: node.layoutSizingHorizontal, v: node.layoutSizingVertical},
    fills: node.fills !== figma.mixed ? node.fills: 'MIXED',
    parent: node.parent ? {id: node.parent.id, name: node.parent.name}: null,
    childCount: node.children ? node.children.length: 0
  };
})()
```

### Visual export (PNG)

Preview at SCALE 0.5: a 1280-wide screen comes back 640 wide, a quarter of the image tokens on every later turn. Use 1 only to inspect a small detail, cropped to that node.

```js
(async function() {
  var node = await figma.getNodeByIdAsync('NODE_ID');
  var bytes = await node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 0.5}});
  return figma.base64Encode(bytes);
})()
```

### Screenshot of the tab

Without Plugin API: `python3 <skill-dir>/figma_run.py --screenshot /tmp/figma_screenshot.png`. The tab must be the one its window shows.

## Parallelization

When the coordinator launches parallel workers:

1. Workers use namespaced `window.__batchState` keys (e.g., `a_frameId`, `b_frameId`)
2. Workers operate on **independent** areas: no concurrent writes to the same node
3. Each worker runs its own read → execute → verify loop independently
4. The coordinator collects results after all workers complete

### Worker discipline

Coordinator-side dispatch duties (pre-creating target frames, distributing component IDs) live in `SKILL.md`. Workers:
- Call `figma.commitUndo()` after completing each logical unit (sets an undo checkpoint)
- After each `appendChild`, verify `child.parent.id === expectedParent.id` — silent reparenting is a real failure mode in long async scripts (see `gotchas.md` #14)

### Concurrency safety (`--ns`)

Workers in one tab can't see each other's writes as they happen, so the helpers watch for them. A worker passes `--ns <NS>` on every call; the coordinator doesn't set anything up.

- **Claims.** The `rootId` a worker's script returns becomes that worker's frame. A claim lapses after 10 idle minutes.
- **Notes after a write.** When a `--ns` script returns `createdNodeIds` / `mutatedNodeIds` under a frame another worker claimed, or creates a component whose name another worker already used, its value gains `fxNote` saying what crossed. The write stays; the worker reports DONE_WITH_CONCERNS and leaves those nodes alone.
- **Refusal before a write.** When a collaborator in another client (a REMOTE change on the current page) edited a worker's frame since its last eval, its next `--ns` script doesn't run and returns `{applied: false, reason: 'stale', changed: [ids], note}`. The worker re-reads `changed` and sends an adjusted script; the eval after a refusal always runs. Edits made in this same tab (by the user or another worker) are LOCAL and can't be told apart, so they never refuse.

`__fx.presence(ns, value)` and `__fx.stale(ns)` do this; the helpers call them for you.

### Lost replies and timeouts

Each script runs under a request id in the page's ledger (`window.__fxRuns`, the last 50). When the daemon drops a reply, the helper resends the same request once: a script that finished answers from the ledger, one that never ran runs now, and nothing runs twice. A timeout, or a script still running at the resend, names its id: `figma_run.py --file <url> --recover <id>` waits for it (up to `--timeout`) and prints its result; don't poll it with `sleep` (results over 32 KB aren't kept; read the state instead).

### Workers on one file or several

- **Same file**, different frames/pages: all evals share the file's tab, so share state through `window.__batchState` with namespaced keys.
- **Different files**: each worker passes its own `--file`; each file's tab has its own Plugin API context.

## Error handling

A script that throws exits with code 1 and prints the error to stderr. When the message is a known Plugin API error, a `hint:` line under it names the fix and the gotcha behind it:

```
✗ Evaluation error: Error: in set_layoutSizingHorizontal: FILL can only be set on children of auto-layout frames
hint: appendChild into the auto-layout parent first, then set layoutSizing* = "FILL" (gotchas #1)
```

Apply the hint before anything else; it covers unloaded fonts, FILL/HUG outside auto layout, stale or deleted nodes, dynamic-page access, instance children and null lookups.

## Large operations

When processing many nodes in a single eval, yield to prevent freezing:

```js
var nodes = figma.currentPage.findAll();
var BATCH = 50;
for (var i = 0; i < nodes.length; i += BATCH) {
  var batch = nodes.slice(i, i + BATCH);
  // process batch...
  if (i + BATCH < nodes.length) {
    await new Promise(function(r) { setTimeout(r, 0); });
  }
}
```

## Error recovery

When an eval fails mid-loop, follow this pattern:

1. **Read the error**: the helper exits with code 1 and prints the error, and a `hint:` line when it knows the fix (Error handling above)
2. **Don't retry blindly**: read the current state first to understand what succeeded
3. **Return errors, don't throw**: see `references/gotchas.md` #7.

### Reading empty-ish results

Eval can succeed but return values that signal "found nothing": each means something different:

- `null` → the node or resource doesn't exist (check the ID)
- `undefined` → missing `return` statement in your IIFE (you ran code but emitted nothing)
- `[]` → the search ran but matched nothing (check selector / criteria)
- `{count: 0}` / `{length: 0}` → operation completed, matched zero items

Recheck the query before retrying: don't loop on a wrong selector.

Pattern for safe mutations:
```js
(async function() {
  var node = await figma.getNodeByIdAsync('TARGET_ID');
  if (!node) return {error: 'Node TARGET_ID not found'};
  if (node.type !== 'TEXT') return {error: 'Expected TEXT, got ' + node.type};

  // Mixed-font handling: see references/copy.md → Font loading pattern
  try {
    await figma.loadFontAsync(node.fontName);
  } catch (e) {
    return {error: 'Font load failed: ' + e.message};
  }

  node.characters = 'Updated text';
  return {ok: true};
})()
```

## Performance

- **Max ~200 nodes per eval** before Figma slows noticeably. For larger operations, split into multiple evals with yielding.
- **Yield between batches** in long loops: `await new Promise(function(r) { setTimeout(r, 0); })`
- **Batch size: 50 nodes** is safe. 100+ may cause the UI thread to block.
- **Avoid `findAll(cb)` and `findOne(cb)` with type-only predicates** on pages with 1000+ nodes: use `findAllWithCriteria({types: ['TEXT']})` instead of `findAll(n => n.type === 'TEXT')`. For `findOne`, take the first element: `findAllWithCriteria({types: ['INSTANCE']})[0]`. The criteria version is native C++ and 10–50× faster.
- **commitUndo() cost**: see `references/gotchas.md` #8.
- **ComponentNode writes vs InstanceNode reads**: see `references/gotchas.md` #9.

## Assertion verification

Run assertions programmatically after building. Compare actual state against expected spec.

```js
(async function() {
  var rootId = window.__batchState.rootId; // or hardcode the ID
  var node = await figma.getNodeByIdAsync(rootId);
  if (!node) return {allPassed: false, error: 'Root not found'};

  var checks = [];
  function check(what, expected, actual) {
    checks.push({what: what, expected: expected, actual: actual, pass: expected === actual});
  }
  function checkContains(what, expected, actual) {
    checks.push({what: what, expected: 'contains ' + expected, actual: actual,
      pass: actual && actual.indexOf(expected) !== -1});
  }

  // Root checks
  check('root.type', 'FRAME', node.type);
  check('root.name', 'Screens/Login', node.name);
  check('root.childCount', 8, node.children ? node.children.length: 0);

  // Child checks
  var c = node.children || [];
  if (c[0]) check('child0.type', 'INSTANCE', c[0].type);
  if (c[1]) check('child1.characters', 'Welcome back', c[1].type === 'TEXT' ? c[1].characters: null);
  // ... add one check per assertion in spec

  var passed = checks.filter(function(x) { return x.pass; }).length;
  var failed = checks.filter(function(x) { return !x.pass; });
  return {passed: passed, total: checks.length, allPassed: failed.length === 0, failures: failed};
})()
```


Fix only the `failures` and re-verify.

## Section checkpointing

For large multi-section documents, save progress after each verified section. Namespace the checkpoint key with the worker's coordinator-assigned prefix (`NS`, e.g. `'a_'`), same as other `__batchState` keys:

```js
// Save checkpoint after section passes
(async function() {
  var NS = 'a_'; // coordinator-assigned namespace prefix
  window.__batchState = window.__batchState || {};
  var cp = window.__batchState[NS + 'checkpoint'] || {completedSections: [], nodeIds: {}};
  cp.completedSections.push('login');
  cp.nodeIds.login = {frameId: '2:24'};
  cp.currentSection = 'signup'; // next section
  window.__batchState[NS + 'checkpoint'] = cp;
  return cp;
})()
```

```js
// Read checkpoint on resume (start of worker)
(async function() {
  var NS = 'a_'; // coordinator-assigned namespace prefix
  var cp = window.__batchState && window.__batchState[NS + 'checkpoint'];
  return cp || {completedSections: [], nodeIds: {}, currentSection: null};
})()
```

Skip sections in `completedSections`. Resume from `currentSection`. Use `nodeIds` to reference nodes created in earlier sections. `__batchState` dies with the browser tab — if a multi-section worker dies, the coordinator re-dispatches the same spec and the new worker resumes from the checkpoint (or from scratch if the tab itself was lost).

## Rollback

The coordinator runs `figma.saveVersionHistoryAsync('pre <task>')` before any mutating dispatches. On a BLOCKED worker, two options:

- **Targeted:** delete the worker's returned `createdNodeIds` (this is why workers return them).
- **Nuclear:** restore the saved version. Restoring discards ALL concurrent work — only when the file is otherwise quiescent (no other workers or users mid-flight).

`commitUndo()` checkpoints live on the per-client undo stack — NOT a rollback mechanism. That's why the version snapshot exists.
