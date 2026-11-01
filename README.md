# figma-cdp

figma-cdp builds Figma screens from your code or a plain description, using your real copy, colors, spacing and components. If your repo has a DESIGN.md, it also keeps design and code in sync: it shows where Figma and the code disagree, and proposes the fix as a pull request or a new page in Figma, never changing either on its own.

## Install

```bash
git clone https://github.com/sryo/figma-cdp ~/.agents/skills/figma-cdp
mkdir -p ~/.claude/skills && ln -sfn ~/.agents/skills/figma-cdp ~/.claude/skills/figma-cdp
```

One copy serves Codex, GitHub Copilot and Claude Code. Restart your agent if it doesn't pick up the skill.

You need a Mac with [perch](https://github.com/sryo/perch) and a Figma file open in Chrome, Arc or Safari, or in a perch room.

Optional: for image rendering or comments, give your agent a [Figma personal access token](https://www.figma.com/developers/api#access-tokens).

## Use

- *"Mock up the settings screen from ~/Code/myapp in this Figma file: https://www.figma.com/design/…"*
- *"Convert this HTML mockup into Figma components."*
- *"Make the login frame match the current implementation."*
- *"Extract all the copy from the Screens page."*
- *"Write a DESIGN.md from this app's CSS."*
- *"Check where [Lede](https://github.com/sryo/lede)'s Figma file and code have drifted."*
- *"Propose the Figma color changes as a pull request."*

## Known gaps
- Syncing needs your browser signed in to Figma, so it runs on your Mac, not on a server.
