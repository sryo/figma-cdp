---
name: figma
description: "Automate Figma design work — read files, create/edit designs, manage copy, and verify results using the hybrid REST API + Plugin API architecture. Use this skill whenever the user shares a Figma URL, asks to modify a Figma design, wants to extract or update copy/text in Figma, needs to build UI components or screens programmatically, or references Figma files in any way. Also trigger when the user mentions design automation, Figma plugins, or working with design nodes — even if they don't explicitly say 'Figma'."
---

# Figma Design Automation

Automate Figma design work through a hybrid architecture: **REST API** for reading and **Plugin API** for mutations.

## Architecture

| Layer | Transport | Best for |
|-------|-----------|----------|
| **REST API** | HTTP (`api.figma.com`) | Reading file structure, rendering images, managing comments/dev resources |
| **Plugin API** | Browser (Chrome MCP / DevTools MCP / CDP) | **All design mutations** — create, edit, delete nodes; also reading via `exportAsync` |

The Plugin API is the **only way** to create, modify, or delete design nodes. REST is a read-oriented layer that eliminates the need for a browser session when you only need to inspect a file.

## When You Receive a Figma URL

Follow these steps in order:

1. **Parse the URL** — extract the file key and node ID:
   ```bash
   # File key (after /design/, /file/, or /proto/)
   echo "$FIGMA_URL" | sed -E 's|.*(design|file|proto)/([^/]+).*|\2|'
   # Node ID (URLs use hyphens, Plugin API expects colons)
   echo "$FIGMA_URL" | sed -E 's|.*node-id=([^&]+).*|\1|' | tr '-' ':'
   ```
2. **Establish connection** — read `references/connection.md` and connect via Chrome MCP, DevTools MCP, or CDP. Navigate to the Figma URL.
3. **Check access** — if the file requires login, tell the user to log in and let you know when ready. Do not proceed until the file is accessible.
4. **Read the file** — use REST API (`GET /v1/files/:key?depth=2`) to understand the file structure. If a node ID was provided, inspect that node with `GET /v1/files/:key/nodes?ids=X`. See `references/rest-api.md` for endpoints and the helper script.
5. **Render the target** — use REST API (`GET /v1/images/:key`) to get a PNG of the target node(s) for visual context.
6. **Understand before acting** — read `references/reading.md` and follow the pre-flight workflow to understand the design before modifying anything.
7. **Load the right reference** — based on the user's task, read the appropriate file from the table below.
8. **Execute and verify** — make changes via Plugin API, then verify with `exportAsync` or REST image render.

## Reference Files

Load these as needed based on the task:

| File | When to load |
|------|-------------|
| `references/connection.md` | Setting up browser connection (Chrome MCP, DevTools MCP, or CDP via Bash) |
| `references/rest-api.md` | Reading files, rendering images, or managing comments via HTTP — no browser needed |
| `references/reading.md` | Understanding an existing design before modifying it (pre-flight, asset extraction) |
| `references/building.md` | Creating or modifying design nodes (components, Auto Layout, constraints, validation) |
| `references/copy.md` | Extracting, updating, diffing, and reviewing text content (UX writing, copy management) |
| `references/cdp.md` | Advanced CDP patterns (console workflow, parallelization, event listeners, batch processing) |
| `references/api-reference.md` | Looking up Plugin API methods, node types, mixins, or data types |

## Rules of Engagement

- Always explain in plain English what you are about to do. Assume the user cannot read code.
- Use the **REST API** for reading file structure and rendering images. Use the **Plugin API** for all design mutations. Do not manually interact with the Figma UI.
- **Preserve existing behavior** unless explicitly asked to change it. When in doubt, ask first.
- **Favor targeted edits over sweeping changes.** Don't remove or overwrite user modifications — only touch what was requested.
- **NEVER rebuild from scratch.** Always improve existing content incrementally. Never clear children and recreate — find and update what's already there.
- **Follow Figma best practices:** use Components, Auto Layout, consistent naming, proper layer hierarchy.
- After creating/modifying nodes, call `figma.viewport.scrollAndZoomIntoView([node])` so the user can see the result.
- **NEVER call `figma.closePlugin()`.** This kills the plugin context and requires a page reload.

## Critical Gotchas

These are the most common pitfalls when scripting Figma — ignoring them causes silent failures:

- **`fills`, `strokes`, and `effects` arrays are readonly** — clone before mutating: `node.fills = [{...}]`. Use `figma.mixed` to check for mixed values on text range properties.
- **`appendChild` can silently fail in complex async scripts.** Nodes may end up as page-level siblings. Always verify: check `parent.children.length` or `child.parent.id === expectedParent.id`.
- **Font loading does NOT persist across eval calls.** Call `await figma.loadFontAsync(...)` in every script that touches text properties — even if you loaded the same font previously.
- **Nodes created but not appended** within the same eval can get garbage collected. Always append in the same script that creates them.
- **Colors use 0-1 range, NOT 0-255.** Hex `#6366f1` = `{r: 0.388, g: 0.4, b: 0.945}`.
- **Script return values must be JSON-serializable.** Each eval call is independent — fonts, variables, and references from a previous call are NOT available.
- **Text overflow is silent.** When a text node has `textAutoResize: 'NONE'` (fixed-size frame), longer replacement text gets clipped with no error. Always check this property before writing longer text and warn the user.
- **Overriding text inside instances**: Load the node's actual font first (not a hardcoded one), then set characters. See `references/copy.md` "Text Inside Component Instances" for the full pattern with mixed-font handling.
- **No optional chaining (`?.`) or nullish coalescing (`??`) in the plugin sandbox.** Figma uses QuickJS. Use explicit checks: `node && node.parent && node.parent.type`.
- **`AsyncFunction` constructor is restricted in QuickJS.** Use `eval()` with an async IIFE wrapper: `eval("(async function() { ... })()")`.
- **Large operations can freeze Figma.** Yield to the event loop between batches with `await new Promise(function(r) { setTimeout(r, 0); })`.
