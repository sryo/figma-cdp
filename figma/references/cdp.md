# CDP Workflow & Advanced Patterns

Advanced execution patterns via Chrome DevTools Protocol. Requires a working connection — see `connection.md` for `$WS_URL` setup and the `/tmp/cdp_eval.py` helper.

## Plugin Console Workflow
- **Do NOT write large monolithic scripts.** Work step by step through the plugin console.
- Execute small, focused commands: one operation per eval call.
- For multi-line operations, write to `/tmp/fc.js` and run via:
  ```bash
  cat > /tmp/fc.js << 'JSEOF'
  (async () => {
    // your code
  })()
  JSEOF
  python3 /tmp/cdp_eval.py "$WS_URL" "$(cat /tmp/fc.js)"
  ```
  Keep scripts small (under 50 lines).
- Always check the current state before modifying anything.
- After each step, verify the result before moving to the next step.

## Parallelization (Multi-Agent)
When building multiple independent screens, use parallel Task agents — one per screen.

**Setup:**
1. Each Task agent receives the `WS_URL` and opens its own CDP WebSocket session.
2. Assign each agent a specific frame or page to work on.
3. All agents share the same `figma` global — avoid concurrent writes to the same node.

**Coordination pattern:**
- **Coordinator agent**: Uses the **REST API** (no browser needed) to read file structure, plan work, and distribute component IDs. Can also create target frames via Plugin API before dispatching workers.
- **Worker agents**: Each builds within its assigned frame using the Plugin API via CDP. Polls `window.__figmaEvents` between operations to detect external changes.
- Use `figma.commitUndo()` after logical units of work so rollbacks are clean.
- Workers verify `node.parent.id === expectedParent.id` after `appendChild` to catch silent reparenting.

## Console Monitoring via CDP
Subscribe to console events for real-time log capture during eval:
```python
# After connecting the WebSocket, enable Runtime domain:
await ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
# Console events arrive as:
# {"method": "Runtime.consoleAPICalled", "params": {"type": "log|warn|error", "args": [...]}}
```
Poll for events between eval calls, or run a background listener.

## Event Listener Injection
Inject Figma event listeners that buffer events into a global array. Poll between operations to stay aware of user actions:
```js
if (!window.__figmaEvents) {
  window.__figmaEvents = [];
  figma.on('selectionchange', function() {
    var sel = figma.currentPage.selection.map(function(n) {
      return {id:n.id, name:n.name, type:n.type};
    });
    window.__figmaEvents.push({type:'selection', nodes:sel, ts:Date.now()});
    if (window.__figmaEvents.length > 100) window.__figmaEvents.shift();
  });
  figma.on('currentpagechange', function() {
    window.__figmaEvents.push({type:'page', name:figma.currentPage.name, ts:Date.now()});
    if (window.__figmaEvents.length > 100) window.__figmaEvents.shift();
  });
  figma.on('documentchange', function(e) {
    window.__figmaEvents.push({type:'docchange', count:e.documentChanges.length, ts:Date.now()});
    if (window.__figmaEvents.length > 100) window.__figmaEvents.shift();
  });
}
```
Read and drain events: `var events = window.__figmaEvents.splice(0);`

## Batch Processing
For large operations, yield to the event loop between batches to prevent Figma from freezing:
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

