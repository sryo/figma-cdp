# CDP escape hatch (general Chrome DevTools Protocol)

The active skill uses `agent-browser` as a thin CLI wrapper around CDP — see `SKILL.md` and `references/execution.md`. This file documents how to talk to Chrome over CDP **without** `agent-browser`, plus a few general CDP techniques (console capture, listener buffering) that aren't Figma-specific.

These patterns are general Chrome automation, not Figma. If they grow or get reused elsewhere, extract them into a sibling skill rather than letting this file expand.

## Raw CDP eval via Python WebSocket

If `agent-browser` isn't available, you can talk to Chrome directly over CDP. Launch Chrome with `--remote-debugging-port` (see `references/execution.md` → Connection for the full flag set, including the Chrome 136+ profile-copy dance), then:

1. **Find the WebSocket URL of the tab you want:**
   ```bash
   curl -s http://localhost:9222/json | python3 -c "
   import json,sys
   tabs=json.load(sys.stdin)
   for t in tabs:
     if 'figma.com' in t.get('url',''):
       print(t['webSocketDebuggerUrl']); break"
   ```
   Store the result: `WS_URL="<output>"`.

2. **Create `/tmp/cdp_eval.py`:**
   ```python
   #!/usr/bin/env python3
   import sys, json, asyncio, websockets
   async def main():
       async with websockets.connect(sys.argv[1], max_size=50_000_000) as ws:
           await ws.send(json.dumps({
               "id": 1, "method": "Runtime.evaluate",
               "params": {"expression": sys.argv[2],
                           "awaitPromise": True, "returnByValue": True}
           }))
           r = json.loads(await ws.recv())
           res = r.get("result", {}).get("result", {})
           if res.get("subtype") == "error":
               print("ERROR:", res.get("description", res), file=sys.stderr)
               sys.exit(1)
           print(json.dumps(res.get("value", res.get("description", "")), indent=2))
   asyncio.run(main())
   ```

3. **Test:**
   ```bash
   python3 /tmp/cdp_eval.py "$WS_URL" "typeof figma"   # → "object"
   ```

This is the bare CDP `Runtime.evaluate` call. `agent-browser` wraps the same call plus base64 input, exit-code handling, and `--session` for multi-tab. Use this only when `agent-browser` is genuinely unavailable; otherwise `references/execution.md` is the path.

Note: each invocation re-opens the WebSocket (`asyncio.run(main())`), adding ~50-150ms per call. For tight loops, either use `agent-browser` (holds the connection) or rewrite as a small persistent daemon.

## Console capture via CDP

To capture `console.log/warn/error` from the page in real time, enable the Runtime domain on the same WebSocket and listen for `Runtime.consoleAPICalled`:

```python
# After connecting the WebSocket, enable Runtime domain:
await ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
# Console events arrive as:
# {"method": "Runtime.consoleAPICalled",
#  "params": {"type": "log|warn|error", "args": [...]}}
```

Poll for events between eval calls, or run a background listener task. Useful when an eval succeeds silently but logs reveal what actually happened.

## Listener buffering (general pattern)

The technique of injecting a listener that pushes events into a global ring buffer, then draining it from outside, is general — works for any event source the page exposes. The Figma-specific variant lives in `references/execution.md` → Event listener injection (`window.__figmaEvents`), but the shape is portable:

```js
if (!window.__myEvents) {
  window.__myEvents = [];
  someSource.on('event', function(e) {
    window.__myEvents.push({...e, ts: Date.now()});
    if (window.__myEvents.length > 100) window.__myEvents.shift();  // ring buffer
  });
}
```

Drain from the outside:
```bash
agent-browser --cdp 9222 eval "JSON.stringify(window.__myEvents.splice(0))"
# or with the raw helper:
python3 /tmp/cdp_eval.py "$WS_URL" "JSON.stringify(window.__myEvents.splice(0))"
```

The ring-buffer cap matters: without it, a chatty source fills memory across a long session.
