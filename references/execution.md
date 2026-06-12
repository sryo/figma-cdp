# Execution: connection and CDP patterns

How to connect to Figma's Plugin API via `agent-browser` and the eval patterns for all automation.

`agent-browser` commands are pre-allowed (`Bash(agent-browser:*)`) — no prompts.

## Connection

### Quick start

1. **Test existing connection**: skip the rest if `typeof figma` returns `"object"`:
   ```bash
   agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" eval "typeof figma" 2>/dev/null && echo "connected"
   ```

2. **Connect to Chrome.** Two paths — try Mode A first.

   #### Mode A — Attach to your running Chrome (recommended)

   No relaunch, no profile copy, no flags. Works with your already-logged-in Figma session.

   1. In your normal Chrome window, open `chrome://inspect/#remote-debugging` once and enable "Discover network targets". Chrome now exposes CDP on a local port for the lifetime of the browser session.
   2. Find the port (Chrome writes it on launch):
      ```bash
      cat "$HOME/Library/Application Support/Google/Chrome/DevToolsActivePort" | head -1
      # Linux:   ~/.config/google-chrome/DevToolsActivePort
      # Brave:   ~/Library/Application Support/BraveSoftware/Brave-Browser/DevToolsActivePort
      # Canary:  ~/Library/Application Support/Google/Chrome Canary/DevToolsActivePort
      ```
   3. Use that port in place of 9222 — e.g. if it printed `54321`, run `agent-browser --cdp 54321 eval "typeof figma"`.
   4. Export the port for the helper scripts so they pick it up automatically:
      ```bash
      export FIGMA_CDP_PORT=54321
      ```
      Both `figma_run.py` and `figma_batch_run.py` read `FIGMA_CDP_PORT` (default 9222 if unset).
   5. The first time the agent touches a tab, Chrome may show an "Allow debugging?" prompt. Accept once per tab.

   Trade-offs: requires the one-time toggle; the port changes between Chrome restarts (re-read `DevToolsActivePort` and re-export `FIGMA_CDP_PORT`). If you can't enable the toggle (managed Chrome, etc.), use Mode B.

   #### Mode B — Launch a dedicated Chrome Canary (fallback)

   Chrome 136+ refuses `--remote-debugging-port` on the default user-data-dir (security hardening; stops malicious pages from connecting to a logged-in session), so you must pass `--user-data-dir`. To preserve your Figma login, copy your default Canary profile right before launching:
   ```bash
   rm -rf /tmp/canary-cdp && \
     cp -R "$HOME/Library/Application Support/Google/Chrome Canary" /tmp/canary-cdp
   ```
   Launch against the copy:
   ```bash
   /Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary \
     --remote-debugging-port=9222 \
     --user-data-dir=/tmp/canary-cdp \
     '--remote-allow-origins=*' \
     "FIGMA_URL_HERE" &
   ```
   Wait for CDP to be ready before the first eval (Chrome opens the port before it's actually answering):
   ```bash
   for i in $(seq 1 60); do
     curl -sf http://127.0.0.1:9222/json/version > /dev/null && break
     sleep 0.5
   done
   curl -sf http://127.0.0.1:9222/json/version > /dev/null \
     || { echo "CDP never came up on 9222" >&2; exit 1; }
   ```
   Without the post-loop check, a 30s timeout exits cleanly and the next `agent-browser` call fails with an opaque CDP error.
   Why these flags:
   - `--user-data-dir`: Chrome 136+ won't expose CDP on the default profile path.
   - `--remote-allow-origins=*`: Chrome 111+ silently rejects CDP requests without this; the rejection presents as a 404 on `/json/version` even though the port is listening. Quote the flag to stop the shell from globbing the `*`.
   - Profile copy: preserves your Figma cookies so you don't have to re-log-in.

   Re-copy each session. The copy is ~640M and goes stale over time (Chrome appears to rotate keys in the live profile, after which the copy stops being accepted). Stale-copy symptoms: `agent-browser --cdp 9222` reports "EOF while parsing" and `curl http://localhost:9222/json/version` returns an empty body / 404. Fix: kill Canary, re-copy, relaunch.

   No saved Figma login? Use a fresh profile dir and log in once:
   ```bash
   rm -rf /tmp/canary-fresh
   /Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary \
     --remote-debugging-port=9222 \
     --user-data-dir=/tmp/canary-fresh \
     --no-first-run --no-default-browser-check \
     '--remote-allow-origins=*' \
     "https://www.figma.com" &
   ```

3. **Copy the helpers to `/tmp/`**: `figma_run.py` (single eval) and `figma_batch_run.py` (multiple evals in one CLI invocation). Both read `FIGMA_CDP_PORT` (default 9222), base64-encode the JS, and shell out to `agent-browser eval -b` / `agent-browser batch`.

   Install `agent-browser` once: `npm i -g agent-browser && agent-browser install`.

### Troubleshooting

If `typeof figma` returns `"undefined"`:
1. Ensure user has **edit permissions** (or create a branch).
2. Wait for page to fully load, retry.
3. Have user **open and close any plugin** to initialize the Plugin API, retry. (`window.figma` is a guarded getter that returns undefined until a plugin run populates its backing store. The plugin can be anything: first available in the menu is fine.)

If `agent-browser --cdp 9222` fails to connect (Mode B):
1. Check that CDP responds: `curl -s http://localhost:9222/json/version | head -2`. Expected: JSON starting with `"Browser": "Chrome/..."`. An empty body / 404 means Chrome's listening but disallowing CDP routes — usually a stale profile copy or a missing `--remote-allow-origins=*` flag. Re-copy the profile and relaunch.
2. Close other Chrome instances holding port 9222.
3. Prefer Chrome Canary to avoid conflicts with your regular Chrome.

If Mode A attach fails:
1. Confirm the toggle is enabled at `chrome://inspect/#remote-debugging`.
2. Re-read `DevToolsActivePort` — the port changes on every Chrome restart.
3. If the "Allow debugging?" modal didn't appear, try clicking the Figma tab to bring it foreground, then retry.

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

### Coordinator vs worker roles

**Coordinator** (the parent agent invoking `figma-worker.md`):
- Reads file structure and creates target frames up front
- Assigns each worker a specific frame or page
- Distributes the component IDs each worker needs

**Workers**:
- Build only within their assigned frame
- Call `figma.commitUndo()` after completing each logical unit (sets an undo checkpoint)
- Between operations, poll `window.__figmaEvents` (see Event listener injection below) to detect external changes (user moved the selection, another worker landed a change) and bail or re-read state if so
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

Write `/tmp/figma_listeners.js`:
```js
(async function() {
  if (!window.__figmaEvents) {
    var MAX = 100;
    window.__figmaEvents = [];
    function push(e) {
      window.__figmaEvents.push(e);
      if (window.__figmaEvents.length > MAX) window.__figmaEvents.shift();
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

Read and drain events:
```bash
agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" eval "JSON.stringify(window.__figmaEvents.splice(0))"
```

Drain at 1-2s intervals, not faster — each `agent-browser` invocation cold-starts the CLI (~200ms). The ring buffer holds 100 events, so 1s polling tolerates 100 events/sec without loss.

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
3. **Return errors, don't throw**: `return {error: 'msg'}` keeps the eval alive. `throw` crashes it and you lose context.

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

  // Load fonts — see references/copy.md → Font loading pattern (handles mixed)
  try {
    if (node.fontName !== figma.mixed) {
      await figma.loadFontAsync(node.fontName);
    } else {
      var fonts = node.getRangeAllFontNames(0, node.characters.length);
      for (var i = 0; i < fonts.length; i++) await figma.loadFontAsync(fonts[i]);
    }
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
- **commitUndo() is expensive**: call once per user-visible change, not per property set.
- **Don't alternate** between writing to a ComponentNode and reading from its InstanceNode: Figma recalculates instances on every component change. Batch all component writes first, then read instances.

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

If `allPassed: false`, fix only the `failures` and re-verify. Max 3 retries before BLOCKED.

## Section checkpointing

For large multi-section documents, save progress after each verified section:

```js
// Save checkpoint after section passes
(async function() {
  window.__batchState = window.__batchState || {};
  var cp = window.__batchState.checkpoint || {completedSections: [], nodeIds: {}};
  cp.completedSections.push('login');
  cp.nodeIds.login = {frameId: '2:24'};
  cp.currentSection = 'signup'; // next section
  window.__batchState.checkpoint = cp;
  return cp;
})()
```

```js
// Read checkpoint on resume (start of worker)
(async function() {
  var cp = window.__batchState && window.__batchState.checkpoint;
  return cp || {completedSections: [], nodeIds: {}, currentSection: null};
})()
```

Skip sections in `completedSections`. Resume from `currentSection`. Use `nodeIds` to reference nodes created in earlier sections.
