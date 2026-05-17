# figma-cdp

Build Figma mockups from code or plain English. The reverse of Figma MCP (which turns Figma into code). Paste HTML, describe a screen, or hand Claude a SwiftUI view, and it builds it in your Figma file.

No Figma MCP required. It drives Figma's Plugin API directly via Chrome DevTools Protocol.

## Install

```bash
git clone https://github.com/sryo/figma-cdp ~/.claude/skills/figma-cdp
```

Claude Code picks up the skill automatically when you mention a Figma URL or ask for a mockup. If it doesn't, restart Claude Code.

Optional: set `FIGMA_TOKEN` if you want REST features like image rendering or comments. Generate a token at [figma.com/developers/api](https://www.figma.com/developers/api#access-tokens).

## Usage

Talk to Claude Code:

- *"Build a login screen in this Figma file: https://www.figma.com/design/…"*
- *"Convert this HTML mockup into Figma components."*
- *"Port this SwiftUI view to Figma."*
- *"Extract all the copy from the Screens page."*
- *"Add a drop shadow to the hero frame."*

On first run, the skill connects to Chrome two ways: attach to your existing Chrome (flip the toggle at `chrome://inspect/#remote-debugging`), or launch a fresh Chrome Canary for debugging. See `references/execution.md` → Connection.

## Troubleshooting

If `typeof figma` returns `"undefined"`, the Plugin API isn't loaded yet — open and close any Figma plugin once to wake it up.

If `agent-browser --cdp <port>` can't connect, see `references/execution.md` → Troubleshooting.
