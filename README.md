# figma-cdp

A Claude Code skill that automates Figma via Chrome DevTools Protocol — no Figma MCP required. Drives Figma's in-browser Plugin API directly through the [`agent-browser`](https://www.npmjs.com/package/agent-browser) CLI.

## What it does

- Build screens, component libraries, design tokens
- Extract and update copy
- Modify layouts, apply styles and effects
- Coordinator + parallel worker-subagent pattern with spec-driven verification loops (read → plan → execute → verify → fix → report)

## Prerequisites

1. **Chrome** or Chrome Canary (Canary recommended — avoids port conflicts with your everyday Chrome).
2. **`agent-browser`** CLI:
   ```bash
   npm i -g agent-browser && agent-browser install
   ```
3. A Figma file you have edit access to (or create a branch).
4. *(Optional, only for REST features like image rendering and comments)* `FIGMA_TOKEN` environment variable — generate at [figma.com/developers/api](https://www.figma.com/developers/api#access-tokens).

## Install

Clone into Claude Code's skills directory:

```bash
# User-wide (available across all projects):
git clone <repo-url> ~/.claude/skills/figma-cdp

# Or project-scoped:
git clone <repo-url> .claude/skills/figma-cdp
```

Restart Claude Code. The skill auto-activates when you mention Figma or share a Figma URL.

## Usage

Just talk to Claude Code naturally:

- *"Build a login screen in this Figma file: https://www.figma.com/design/…"*
- *"Extract all the copy from the Screens page."*
- *"Add a drop shadow to the hero frame."*
- *"Convert this HTML mockup into Figma components."*

On first run, the skill launches Chrome with remote debugging (`--remote-debugging-port=9222` + `--user-data-dir=/tmp/canary-cdp` — Chrome 136+ requires a non-default profile dir; see `references/execution.md` → Connection), then sends JS evals into Figma's Plugin API via `agent-browser`.

## Layout

```
SKILL.md              Claude-facing entry — how the skill runs
figma-worker.md       Worker prompt template — coordinator fills and spawns via Agent tool
figma_run.py          Helper that base64-encodes JS and pipes to agent-browser
references/           Loaded on demand:
  conventions.md        Atomic design, naming, spacing, typography
  gotchas.md            WRONG/CORRECT examples for common Plugin API pitfalls
  reading.md            Inspecting designs + REST API reference
  building.md           Creating/modifying nodes, components, effects
  copy.md               Text extraction, updates, font loading
  execution.md          Connection setup, eval patterns, performance, error recovery
  api-reference.md      Plugin API methods / types / properties lookup
tests/                Spec scenarios (not wired to any runner)
```

## Troubleshooting

Connection / setup issues: see `references/execution.md` → Troubleshooting.

Common fixes:
- `typeof figma` returns `"undefined"` → ensure you have edit permissions and the page fully loaded; open and close any plugin once to initialize the Plugin API.
- `agent-browser --cdp 9222` can't connect → close other Chrome instances holding port 9222, or use Chrome Canary.
