# Execution: CDP eval patterns

The eval patterns for all automation against Figma's Plugin API via `agent-browser`.
Connection setup lives in `references/connection.md` (Mode A attach, Mode B Canary launch, troubleshooting).

`agent-browser` commands and the `python3 /tmp/figma_*.py` helper invocations are pre-allowed (`Bash(agent-browser:*)`, `Bash(python3 /tmp/figma_run.py:*)`, `Bash(python3 /tmp/figma_batch_run.py:*)`) — no prompts.

## Eval methods

Don't use heredocs (`<<`), pipes (`|`), or input redirects (`<`) in Bash — they trigger Claude Code safety warnings even with permissions set.

### From file via helper (recommended)

Write `.js` with the Write tool (no Bash needed), then execute:

```bash
python3 /tmp/figma_run.py /tmp/figma_eval.js
```

The helper reads `FIGMA_CDP_PORT` (default 9222), base64-encodes the script, and passes it to `agent-browser eval -b`.

### Simple expressions

For one-liners (no helper needed):

```bash
agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" eval "figma.currentPage.name"
agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" eval "figma.currentPage.children.length"
```

### Batched evals

For ≥3 sequential evals with no intermediate user feedback or state inspection, batch them — one `agent-browser` invocation saves ~200ms per extra script (CLI cold-start).

Write the steps as separate `.js` files, then:
```bash
python3 /tmp/figma_batch_run.py /tmp/step1.js /tmp/step2.js /tmp/step3.js
```

Output is the three results separated by blank lines. The batch shares one browser tab, so `window.__batchState` persists across the steps the same way it does between separate `figma_run.py` invocations.

For evals whose base64 payload approaches macOS `ARG_MAX` (~256KB per arg), switch to `agent-browser batch`'s stdin JSON mode directly — see `agent-browser batch --help`.

When NOT to batch: when step N needs to read the result of step N-1 before deciding what step N+1 should do, or when parallel workers each have their own chain (each parallel worker calls `figma_run.py` for its own chain; you don't batch across workers).

## State between evals

`window.__batchState` persists across separate eval calls (same browser tab).

> The three-step example below demonstrates persistence — useful when you need to observe intermediate state. In real worker code, **fold the steps into one eval** unless you need that observation. For sequential steps you can't merge, use `figma_batch_run.py` (one CLI cold-start instead of three).

**Step 1**: Write `/tmp/figma_step1.js`:
```js
(async function() {
  window.__batchState = window.__batchState || {};
  var frame = figma.createFrame();
  frame.name = 'Card';
  frame.resize(320, 200);
  frame.layoutMode = 'VERTICAL';
  frame.paddingTop = frame.paddingBottom = frame.paddingLeft = frame.paddingRight = 16;
  frame.itemSpacing = 8;
  window.__batchState.a_cardId = frame.id;
  return {ok: true, id: frame.id};
})()
```
Run: `python3 /tmp/figma_run.py /tmp/figma_step1.js`

**Step 2**: Write `/tmp/figma_step2.js`:
```js
(async function() {
  var card = await figma.getNodeByIdAsync(window.__batchState.a_cardId);
  await figma.loadFontAsync({family: 'Inter', style: 'Bold'});
  var title = figma.createText();
  title.fontName = {family: 'Inter', style: 'Bold'};
  title.fontSize = 24;
  title.characters = 'Card Title';
  card.appendChild(title);
  title.layoutSizingHorizontal = 'FILL';
  return {ok: true, id: title.id};
})()
```
Run: `python3 /tmp/figma_run.py /tmp/figma_step2.js`

**Step 3**: Write `/tmp/figma_step3.js`:
```js
(async function() {
  var card = await figma.getNodeByIdAsync(window.__batchState.a_cardId);
  figma.viewport.scrollAndZoomIntoView([card]);
  figma.commitUndo();
  return {ok: true, childCount: card.children.length};
})()
```
Run: `python3 /tmp/figma_run.py /tmp/figma_step3.js`

Use namespaced keys when parallel workers share the same tab: `a_frameId`, `b_frameId`.

## Verification patterns

### Property check

Write `/tmp/figma_eval.js`:
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
Run: `python3 /tmp/figma_run.py /tmp/figma_eval.js`

### Visual export (PNG)

Write `/tmp/figma_eval.js`:
```js
(async function() {
  var node = await figma.getNodeByIdAsync('NODE_ID');
  var bytes = await node.exportAsync({format: 'PNG', constraint: {type: 'SCALE', value: 2}});
  return figma.base64Encode(bytes);
})()
```
Run: `python3 /tmp/figma_run.py /tmp/figma_eval.js`

### Screenshot via agent-browser

For full-page screenshots without Plugin API:

```bash
agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" screenshot /tmp/figma_screenshot.png
```

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

Write `/tmp/figma_listeners.js`:
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
Run: `python3 /tmp/figma_run.py /tmp/figma_listeners.js`

Reading is non-destructive: never `splice(0)` the buffer — with multiple consumers, a drain steals everyone else's events. Each consumer keeps its own cursor: a position in the monotonically-growing virtual stream (`__figmaEventsShed + buffer length`). The ring sheds oldest entries, so convert the cursor to a buffer index by subtracting the shed count.

Write `/tmp/figma_events_read.js`:
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
Run: `python3 /tmp/figma_run.py /tmp/figma_events_read.js`

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

Pattern for safe mutations (`/tmp/figma_eval.js`):
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

Write `/tmp/figma_verify.js`:
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

Run: `python3 /tmp/figma_run.py /tmp/figma_verify.js`

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
