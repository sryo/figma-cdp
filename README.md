# figma-cdp

**Code → Figma.** The reverse of Figma MCP.

| | direction |
|---|---|
| Figma MCP | design → code |
| **figma-cdp** | **code → design** |

Turn ideas, copy, and intent into Figma mockups. Drives Figma's Plugin API directly via Chrome DevTools Protocol — no Figma MCP needed.

## Install

```bash
npm i -g agent-browser && agent-browser install
git clone <repo-url> ~/.claude/skills/figma-cdp
```

Restart Claude Code. The skill auto-activates on Figma URLs or mockup requests.

Optional: set `FIGMA_TOKEN` for REST features (image rendering, comments) — generate at [figma.com/developers/api](https://www.figma.com/developers/api#access-tokens).

## Usage

Talk to Claude Code:

- *"Build a login screen in this Figma file: https://www.figma.com/design/…"*
- *"Convert this HTML mockup into Figma components."*
- *"Extract all the copy from the Screens page."*
- *"Add a drop shadow to the hero frame."*

First run launches Chrome with remote debugging on port 9222.

## Troubleshooting

- `typeof figma` → `"undefined"`: open and close any Figma plugin to initialize the Plugin API.
- `agent-browser --cdp 9222` won't connect: close other Chrome instances on port 9222, or use Chrome Canary.
