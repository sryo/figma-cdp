# figma-cdp

figma-cdp builds Figma mockups from code or plain English. The reverse of Figma MCP (which turns Figma into code). Point your agent at your app's code, paste HTML, or describe a screen, and it builds it in your Figma file.

It reads your real code first, so the mockup uses your actual copy, colors and spacing. It reuses the components already in your file, turns repeated pieces into components with variants, and checks the result against your code before it says it's done.

No Figma MCP required. It works directly in the Figma file you have open in your browser.

## Install

```bash
git clone https://github.com/sryo/figma-cdp ~/.agents/skills/figma-cdp
mkdir -p ~/.claude/skills && ln -sfn ~/.agents/skills/figma-cdp ~/.claude/skills/figma-cdp
```

One copy serves Codex, GitHub Copilot and Claude Code.

Your agent picks up the skill when you mention a Figma URL or ask for a mockup. If it doesn't, restart it.

On a Mac, also install [perch](https://github.com/sryo/perch) and Node 18 or later. figma-cdp uses perch automatically: it's faster, it works in Chrome, Arc or Safari, and your browser won't ask you to allow remote debugging. In Arc, keep the Figma tab showing in its window while your agent works.

Optional: for image rendering or comments, give your agent a [Figma personal access token](https://www.figma.com/developers/api#access-tokens).

## Use

Talk to your agent:

- *"Mock up the settings screen from ~/Code/myapp in this Figma file: https://www.figma.com/design/…"*
- *"Convert this HTML mockup into Figma components."*
- *"Port this SwiftUI view to Figma."*
- *"Make the login frame match the current implementation."*
- *"Extract all the copy from the Screens page."*
- *"Add a drop shadow to the hero frame."*

Without perch, figma-cdp needs [agent-browser](https://github.com/vercel-labs/agent-browser); your agent can install it. The first run asks you to turn on remote debugging in Chrome (the toggle at `chrome://inspect/#remote-debugging`), or opens a separate Chrome Canary for it.

## Troubleshooting

If your agent says Figma's plugin system isn't ready, open and close any Figma plugin once.

If a long job times out, ask your agent to give it more time.

If your agent can't connect to the browser, see `references/connection.md` → Troubleshooting.

Working on the skill itself? AGENTS.md has the architecture, the tests and the live evals.
