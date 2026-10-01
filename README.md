# figma-cdp

Build Figma mockups from code or plain English. The reverse of Figma MCP (which turns Figma into code). Paste HTML, describe a screen, or hand Claude a SwiftUI view, and it builds it in your Figma file.

No Figma MCP required. It drives Figma's Plugin API directly in your open Figma tab, through [perch](https://github.com/sryo/perch) on macOS (recommended: no debug port, no "allow remote debugging" prompt) or through Chrome DevTools Protocol.

## Install

```bash
git clone https://github.com/sryo/figma-cdp ~/.claude/skills/figma-cdp
```

Claude Code picks up the skill automatically when you mention a Figma URL or ask for a mockup. If it doesn't, restart Claude Code.

Recommended on macOS: install [perch](https://github.com/sryo/perch) at `~/Documents/perch` (or set `PERCH_DIR`). figma-cdp then uses it by default, keeps it warm between calls (about 100 to 200 ms per script, faster than CDP), and never asks Chrome for remote debugging.

Optional: set `FIGMA_TOKEN` if you want REST features like image rendering or comments. Generate a token at [figma.com/developers/api](https://www.figma.com/developers/api#access-tokens).

## Usage

Talk to Claude Code:

- *"Build a login screen in this Figma file: https://www.figma.com/design/…"*
- *"Convert this HTML mockup into Figma components."*
- *"Port this SwiftUI view to Figma."*
- *"Extract all the copy from the Screens page."*
- *"Add a drop shadow to the hero frame."*

With perch installed, the helpers run scripts in your open Figma tab over AppleScript: no debugging toggle, no "allow remote debugging" prompt. See `references/connection.md` → Mode P.

Without perch, the skill connects to Chrome over CDP: attach to your existing Chrome (flip the toggle at `chrome://inspect/#remote-debugging`), or launch a fresh Chrome Canary for debugging. `FIGMA_BACKEND=cdp` forces this path. See `references/connection.md`.

## Troubleshooting

If `typeof figma` returns `"undefined"`, the Plugin API isn't loaded yet — open and close any Figma plugin once to wake it up.

If `agent-browser --cdp <port>` can't connect, see `references/connection.md` → Troubleshooting.

Run the offline helper tests with `python3 tests/perch_backend_test.py`.
