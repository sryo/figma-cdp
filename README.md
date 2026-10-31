# figma-cdp

figma-cdp builds Figma mockups from code or plain English, the reverse of Figma MCP. Point your agent at your app's code, paste HTML, or describe a screen, and it builds it in the Figma file you have open in your browser, using your real copy, colors, spacing and components.

## Install

```bash
git clone https://github.com/sryo/figma-cdp ~/.agents/skills/figma-cdp
mkdir -p ~/.claude/skills && ln -sfn ~/.agents/skills/figma-cdp ~/.claude/skills/figma-cdp
```

One copy serves Codex, GitHub Copilot and Claude Code. Restart your agent if it doesn't pick up the skill.

You need a Figma file open in your browser, plus one of:
- On a Mac, [perch](https://github.com/sryo/perch) and Node 18 or later: faster, works in Chrome, Arc or Safari, and no remote-debugging prompt.
- Otherwise agent-browser, which your agent can install. The first run asks you to turn on remote debugging in Chrome.

Optional: for image rendering or comments, give your agent a [Figma personal access token](https://www.figma.com/developers/api#access-tokens).

## Use

- *"Mock up the settings screen from ~/Code/myapp in this Figma file: https://www.figma.com/design/…"*
- *"Convert this HTML mockup into Figma components."*
- *"Make the login frame match the current implementation."*
- *"Extract all the copy from the Screens page."*
