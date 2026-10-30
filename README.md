# figma-cdp

Build Figma mockups from code or plain English. The reverse of Figma MCP (which turns Figma into code). Point your agent at your app's code, paste HTML, or describe a screen, and it builds it in your Figma file.

It reads your real code first, so the mockup uses your actual copy, colors and spacing. It reuses the components already in your file, turns repeated pieces into components with variants, and checks the result against your code before it says it's done.

No Figma MCP required. It works directly in the Figma file you have open in your browser.

## Install

```bash
git clone https://github.com/sryo/figma-cdp ~/.claude/skills/figma-cdp
```

That's Claude Code's skills folder. Codex and GitHub Copilot look in `~/.agents/skills`, so for those clone into `~/.agents/skills/figma-cdp` instead.

Your agent picks up the skill when you mention a Figma URL or ask for a mockup. If it doesn't, restart it.

On a Mac, also install [perch](https://github.com/sryo/perch). figma-cdp uses it automatically: it's faster, it works in Chrome, Arc or Safari, and your browser won't ask you to allow remote debugging. In Arc, keep the Figma tab showing in its window while your agent works.

Optional: set `FIGMA_TOKEN` if you want REST features like image rendering or comments. Generate a token at [figma.com/developers/api](https://www.figma.com/developers/api#access-tokens).

## Usage

Talk to your agent:

- *"Mock up the settings screen from ~/Code/myapp in this Figma file: https://www.figma.com/design/…"*
- *"Convert this HTML mockup into Figma components."*
- *"Port this SwiftUI view to Figma."*
- *"Make the login frame match the current implementation."*
- *"Extract all the copy from the Screens page."*
- *"Add a drop shadow to the hero frame."*

Without perch, the first run asks you to turn on remote debugging in Chrome (the toggle at `chrome://inspect/#remote-debugging`), or opens a separate Chrome Canary for it.

## Troubleshooting

If `typeof figma` returns `"undefined"`, the Plugin API isn't loaded yet. Open and close any Figma plugin once to wake it up.

If a long job in Figma stops with a timeout (a big export, a large file loading), it gets two minutes by default. Your agent can give it up to five with `--timeout 300`.

If `agent-browser --cdp <port>` can't connect, see `references/connection.md` → Troubleshooting.

Working on the skill itself? AGENTS.md has the architecture, the tests and the live evals.
