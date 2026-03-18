# Figma Connection Setup

How to get a working `figma` global for Plugin API access.

There are three ways to run JS against the Figma Plugin API (`figma` global):

## Option A: Claude in Chrome MCP (preferred)
If the `mcp__claude-in-chrome__*` tools are available, use `mcp__claude-in-chrome__javascript_tool` to eval JS against the Figma tab. This is the simplest path — no setup required.

## Option B: Chrome DevTools MCP with Auto-Connect
Uses the `chrome-devtools-mcp` server to connect to your existing Chrome session. Reuses your logged-in Figma session — no separate browser launch or manual WebSocket discovery needed.

**Requirements:** Chrome 144+ with remote debugging enabled.

### One-time Chrome setup
1. Open `chrome://inspect/#remote-debugging` in Chrome.
2. Enable remote debugging and follow the dialog to allow connections.

### MCP server config
Add to your MCP client config (e.g., Claude Code `settings.json`):
```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": [
        "chrome-devtools-mcp@latest",
        "--autoConnect"
      ]
    }
  }
}
```

### How it works
- The MCP server discovers your running Chrome instance and requests a debug session.
- Chrome shows a permission dialog — you must click **Allow**.
- A banner ("An automated test software is controlling Chrome") appears while active.
- The server exposes CDP tools: JS eval, network inspection, console access, performance profiling.

### When to prefer this over Option A
- You need DevTools data (network requests, performance traces, console logs) alongside Figma edits.
- You want to reuse an already-authenticated Chrome session without installing the Claude in Chrome extension.

## Option C: CDP via Bash (manual fallback)
When neither MCP option is available, use Chrome's DevTools Protocol over WebSocket with a Python helper:

1. **Launch Chrome Canary** with remote debugging and navigate to the URL:
   ```bash
   /Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary \
     --remote-debugging-port=9222 --no-first-run \
     --user-data-dir=/tmp/chrome-figma-debug \
     "FIGMA_URL_HERE" &
   ```
2. **Navigate to Figma** — open the target file in Chrome Canary. Prompt the user to log in if needed.
3. **Find the WebSocket URL**:
   ```bash
   curl -s http://localhost:9222/json | python3 -c "
   import json,sys
   tabs=json.load(sys.stdin)
   for t in tabs:
     if 'figma.com' in t.get('url',''):
       print(t['webSocketDebuggerUrl']); break"
   ```
   Store the result: `WS_URL="<output>"`
4. **Create the CDP eval helper** (`/tmp/cdp_eval.py`) if it doesn't exist:
   ```python
   #!/usr/bin/env python3
   import sys, json, asyncio, websockets
   if len(sys.argv) < 3:
       print("Usage: python3 /tmp/cdp_eval.py <ws_url> <expression>", file=sys.stderr); sys.exit(1)
   async def main():
       try:
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
       except (ConnectionRefusedError, websockets.exceptions.InvalidURI) as e:
           print(f"Connection failed: {e}", file=sys.stderr); sys.exit(1)
       except Exception as e:
           print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)
   asyncio.run(main())
   ```
5. **Test the connection**:
   ```bash
   python3 /tmp/cdp_eval.py "$WS_URL" "typeof figma"
   ```
   Should return `"object"`.
