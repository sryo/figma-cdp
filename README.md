# figma-cdp

Code → Figma. The reverse of Figma MCP.

|  | direction |
|---|---|
| Figma MCP | design → code |
| figma-cdp | code → design |

Figma MCP reads designs out of Figma and turns them into code. This goes the other way: you describe what you want, or paste in HTML, and Claude Code builds it in Figma for you.

No Figma MCP required. It drives Figma's Plugin API directly via Chrome DevTools Protocol.

## Install

```bash
npm i -g agent-browser && agent-browser install
git clone https://github.com/sryo/figma-cdp ~/.claude/skills/figma-cdp
```

The skill activates on its own when you mention a Figma URL or ask for a mockup. Restart Claude Code if it doesn't.

Optional: set `FIGMA_TOKEN` if you want REST features like image rendering or comments. Generate a token at [figma.com/developers/api](https://www.figma.com/developers/api#access-tokens).

## Usage

Talk to Claude Code:

- *"Build a login screen in this Figma file: https://www.figma.com/design/…"*
- *"Convert this HTML mockup into Figma components."*
- *"Extract all the copy from the Screens page."*
- *"Add a drop shadow to the hero frame."*

The first run launches Chrome with remote debugging on port 9222.

## Troubleshooting

If `typeof figma` returns `"undefined"`, open and close any Figma plugin to initialize the Plugin API.

If `agent-browser --cdp 9222` can't connect, close other Chrome instances on port 9222 or use Chrome Canary.
