# Execution: eval patterns

The eval patterns for all automation against Figma's Plugin API, through perch or `agent-browser`.
Connection setup lives in `references/connection.md` (Mode P perch, Mode A attach, Mode B Canary launch, troubleshooting).

`agent-browser` commands and the `python3 <skill-dir>/figma_*.py` helper calls are pre-allowed in Claude Code (`Bash(agent-browser:*)`, `Bash(python3 *figma_*.py *)`); other agents may ask once. Every script below runs as `python3 <skill-dir>/figma_run.py --file <url> -e '<script>'`.

## Eval methods

Run the helpers in place from the skill directory (`<skill-dir>` below); they find `figma_perch.mjs` next to themselves, so nothing is copied to `/tmp`. Both modes take the same arguments and print the same output. Don't use heredocs (`<<`), pipes (`|`), or input redirects (`<`) in Bash — agents flag them for approval even with permissions set.

### Inline script (one turn per eval)

Pass the script with `-e` (or `--js`) and run it in the same Bash call that writes it:

```bash
python3 <skill-dir>/figma_run.py -e 'const page = figma.currentPage;
await figma.loadFontAsync({ family: "Inter", style: "Regular" });
return { name: page.name, frames: page.children.length };'
```

- **Result.** A plain script returns its completion value (its last expression), as CDP's `Runtime.evaluate` does. A script with top-level `await` or `return` runs as an async function body instead, so its result is what it `return`s; no IIFE needed.
- **Scope.** Each script's top-level `const`/`let` stay in that script; share state across evals through `window.__batchState` (below).
- **Quoting.** The script sits in single quotes, so write JS strings with `"` or backticks; a `'` ends the shell string.
- **Other sources.** A path to a `.js` file (written with the Write tool) works the same, and `-` reads the script from stdin.
- **File.** `--file <figma-url-or-key>` picks the tab in Mode P (required when several Figma files are open); `FIGMA_FILE` is its default.
- **Timeout.** In Mode P a script that awaits gets 120s, or `--timeout <seconds>` (1 to 300) for a longer job such as a big export or `loadAllPagesAsync` on a large file.

In Mode A/B the helper base64-encodes the script for `agent-browser eval -b` (port: `FIGMA_CDP_PORT`, else `DevToolsActivePort`, else 9222); in Mode P it runs through perch.

### Batched evals

For ≥3 sequential evals with no intermediate user feedback or state inspection, batch them — one `agent-browser` invocation saves ~200ms per extra script (CLI cold-start). Scripts are `-e '<js>'`, `.js` paths, or `-` (stdin, once), run in the order given:

```bash
python3 <skill-dir>/figma_batch_run.py -e 'window.__batchState = { ids: [] }; return "ready"' /tmp/step2.js -e 'return window.__batchState.ids'
```

Each result prints under a `== <label> ==` header (the file's basename, `-e[n]` for the nth inline script, `stdin`) as `{"origin": ..., "result": ...}`, or `Evaluation error: ...`. The batch shares one browser tab, so `window.__batchState` persists across the steps the same way it does between separate `figma_run.py` invocations.

For evals whose base64 payload approaches macOS `ARG_MAX` (~256KB per arg), switch to `agent-browser batch`'s stdin JSON mode directly — see `agent-browser batch --help`; Mode P has no such cap.

When NOT to batch: when step N needs to read the result of step N-1 before deciding what step N+1 should do, or when parallel workers each have their own chain (each parallel worker calls `figma_run.py` for its own chain; you don't batch across workers).

## Resident helper library (`--lib`)

`python3 <skill-dir>/figma_run.py --lib -e '<js>'` (and `figma_batch_run.py --lib`, on the first script) puts `figma_lib.js` in front of the script. It installs `window.__fx` once per tab; later `--lib` calls skip the install, and a newer copy replaces an older one. Every helper is async; `ref` / `parent` take a node or its id.

| Call | Does |
|------|------|
| `__fx.recon({nodeId, depth, maxChars})` | `{pages, tree, truncated}`: the page list (`*` current) and a flat text tree, 3 levels for a page, full depth for a node, 8000 chars |
| `__fx.inventory({match, maxChars, scope, fresh})` | what the file has to reuse, one line each: `references/reading.md` → Component inventory |
| `__fx.frame({parent, name, dir, gap, pad, align, justify, w, h, fill, stroke, radius, component, abs, x, y, constraints})` | a frame (or component). `dir` V\|H; `pad` n, [v,h] or [t,r,b,l]; `align` / `justify` start\|center\|end\|between; `w` / `h` a number (FIXED), `'fill'` or `'hug'` (the default with `dir`) |
| `__fx.autoLayout(ref, opts)` | the same layout options on an existing frame |
| `__fx.text(chars, {parent, name, family, weight, size, lineHeight, textStyle, color, w, align})` | loads the font first; `textStyle` by name or id; `w` `'fill'` or a width wraps |
| `__fx.instance(idOrKeyOrName, props, {parent, name, w, h})` | variant axes in `props` pick the variant (from a variant id, the axes left out keep its values); other properties by short name (`Label`, not `Label#1:2`) |
| `__fx.bindFill(ref, value, field)` | `value` a hex, or a variable or paint style (name, id or object). A hex binds the local variable (else paint style) with exactly that value, else paints raw. Returns `{bound, id}`; `field` `'strokes'` for strokes |
| `__fx.react(ref, [{on, do}], {append})` | sets reactions: `on` `'click'`\|`'hover'`\|`'press'`\|`{key: 27}`\|`{after: ms}`; `do` `'back'`\|`'close'`\|`{to, nav: 'navigate'\|'overlay'\|'swap'\|'change'\|'scroll', anim: 'smart'\|'dissolve'\|'instant'\|'push-left', ms}`. Replaces the list; `append` replaces only the triggers named: `references/prototyping.md` |
| `__fx.overlayFrame({base, name, items, scrim, page})` | an overlay that opens in place: base-sized, see-through, `items` (`{node, x, y}`) at their place over a Scrim that closes, Esc closes |
| `__fx.flow(page, frame, name)` | a named flow starting point on the page, one per frame and name |
| `__fx.audit(rootId, {limit})` | structural problems under a node or page: `{counts, shares, ids}` (up to 5 ids each) |

`frame` and `text` take `fill` / `stroke` / `color` the way `bindFill` does, so a source hex lands bound when the file has a matching token.

```js
const s = await __fx.frame({ name: 'Login', dir: 'V', w: 375, gap: 16, pad: 24, fill: '#ffffff' });
await __fx.text('Welcome back', { parent: s, weight: 'Bold', size: 28, color: 'color/text' });
await __fx.instance('Button', { Variant: 'Primary', Label: 'Sign in' }, { parent: s, w: 'fill' });
return __fx.audit(s.id);
```

`audit` counts, all best at 0: `rawRepeats` (repeated non-instance subtrees), `fixedInFlow` (frames FIXED on both axes inside auto layout), `absDefaultConstraints` (absolute or no-auto-layout children left at MIN/MIN), `groups`, `defaultNames`, `unboundPaints` (raw paints equal to a local variable), `textFixedInAutoLayout` (textAutoResize NONE), `textOverflow`, `componentsWithoutAutoLayout`, `unlinkedProps` (component properties no layer references), `danglingReactions` (a destination that doesn't resolve), `lostHover` (an instance whose own reactions dropped its main component's hover), `overlayNotFullSize` (an overlay smaller than the screen that opens it). `shares` holds `instanceRatio` and `autoLayoutShare`, higher is better.

## State between evals

`window.__batchState` persists across separate eval calls (same browser tab). Fold steps into one eval unless you need to look at an intermediate result; steps you can't fold go in one `figma_batch_run.py` call:

```bash
python3 <skill-dir>/figma_batch_run.py --lib --file <url> \
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

```js
(async function() {
  var node = await figma.getNodeByIdAsync('NODE_ID');
  var bytes = await node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}});
  return figma.base64Encode(bytes);
})()
```

### Screenshot via agent-browser

For full-page screenshots without Plugin API:

```bash
agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" screenshot /tmp/figma_screenshot.png
```

On either backend (and the only way in Mode P): `python3 <skill-dir>/figma_run.py --screenshot /tmp/figma_screenshot.png`. In Mode P the tab must be the one its window shows.

## Parallelization

When the coordinator launches parallel workers:

1. Workers use namespaced `window.__batchState` keys (e.g., `a_frameId`, `b_frameId`)
2. Workers operate on **independent** areas: no concurrent writes to the same node
3. Each worker runs its own read → execute → verify loop independently
4. The coordinator collects results after all workers complete

### Worker discipline

Coordinator-side dispatch duties (pre-creating target frames, distributing component IDs) live in `SKILL.md`. Workers:
- Call `figma.commitUndo()` after completing each logical unit (sets an undo checkpoint)
- Between operations, read `window.__figmaEvents` via your own cursor (see Event listener injection below — the coordinator injects the listeners; never drain the buffer) to detect external changes (user moved the selection, another worker landed a change) and bail or re-read state if so. Bail = report **BLOCKED** (or **DONE_WITH_CONCERNS** if the unit completed), including what changed
- After each `appendChild`, verify `child.parent.id === expectedParent.id` — silent reparenting is a real failure mode in long async scripts (see `gotchas.md` #14)

### When to use sessions vs shared state

- **Shared state (`window.__batchState`):** Workers on the **same file**, different frames/pages. All evals share one browser tab context.
- **Sessions (`--session worker-a`):** Workers on **different Figma files**. Each session gets its own browser tab with separate Plugin API context.

For same-file parallel work, `window.__batchState` with namespaced keys is correct. Sessions would require opening the same file in multiple tabs.

## Error handling

`agent-browser eval` exits with code 1 on error and prints the error to stderr.

Example error output:
```
✗ Evaluation error: Error: Node not found
```

Check exit codes to detect failures in multi-step operations.

## JSON output

Use `--json` for structured output with success/error metadata:

```bash
agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" eval "figma.currentPage.name" --json
```

Returns:
```json
{"success": true, "data": {"origin": "...", "result": "Page 1"}, "error": null}
```

## Event listener injection

The COORDINATOR injects the listeners once during recon; workers only read.

```js
(async function() {
  if (!window.__figmaEvents) {
    var MAX = 100;
    window.__figmaEvents = [];
    window.__figmaEventsShed = 0; // total entries trimmed off the front of the ring
    function push(e) {
      window.__figmaEvents.push(e);
      if (window.__figmaEvents.length > MAX) {
        window.__figmaEvents.shift();
        window.__figmaEventsShed++;
      }
    }
    figma.on('selectionchange', function() {
      var sel = figma.currentPage.selection.map(function(n) {
        return {id: n.id, name: n.name, type: n.type};
      });
      push({type: 'selection', nodes: sel, ts: Date.now()});
    });
    figma.on('currentpagechange', function() {
      push({type: 'page', name: figma.currentPage.name, ts: Date.now()});
    });
    figma.on('documentchange', function(e) {
      push({type: 'docchange', count: e.documentChanges.length, ts: Date.now()});
    });
  }
  return {ok: true, msg: 'event listeners active'};
})()
```

Reading is non-destructive: never `splice(0)` the buffer — with multiple consumers, a drain steals everyone else's events. Each consumer keeps its own cursor: a position in the monotonically-growing virtual stream (`__figmaEventsShed + buffer length`). The ring sheds oldest entries, so convert the cursor to a buffer index by subtracting the shed count.

```js
(function() {
  var NS = 'a_'; // this consumer's namespace prefix
  window.__batchState = window.__batchState || {};
  var cursor = window.__batchState[NS + 'evCursor'] || 0;
  var shed = window.__figmaEventsShed || 0;
  var events = window.__figmaEvents.slice(Math.max(cursor - shed, 0));
  var missed = Math.max(shed - cursor, 0); // trimmed before this consumer read them
  window.__batchState[NS + 'evCursor'] = shed + window.__figmaEvents.length;
  return {events: events, missed: missed};
})()
```

Poll at 1-2s intervals, not faster — each `agent-browser` invocation cold-starts the CLI (~200ms). The ring buffer holds 100 events, so 1s polling tolerates 100 events/sec before `missed` goes nonzero.

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

1. **Read the error**: `agent-browser` exits with code 1 and prints the error to stderr
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
