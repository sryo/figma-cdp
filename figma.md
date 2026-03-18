# Figma File Editing — Hybrid Architecture

## Architecture Overview

Two layers, each used for what it does best:

| Layer | Transport | Best for |
|-------|-----------|----------|
| **REST API** | HTTP (`api.figma.com`) | Reading file structure, rendering images, managing comments/dev resources |
| **Plugin API** | Browser (Chrome MCP / DevTools MCP / CDP) | **All design mutations** — create, edit, delete nodes; also reading via `exportAsync` |

**Typical workflow:**
1. **REST API** — read the file tree, inspect target nodes, render current state as images
2. **Plan** mutations based on the read data
3. **Plugin API** — execute design changes via browser automation
4. **REST API** `GET /v1/images` or Plugin API `exportAsync` — verify the result

> The Plugin API remains the **only way** to create/modify/delete design nodes.
> REST is a read-oriented layer that eliminates the need for a browser session when you only need to inspect a file.

## URL Parsing

Figma URLs contain the file key after `/design/`, `/file/`, or `/proto/`, and optionally a `node-id` query parameter:
```
https://www.figma.com/design/ABC123xyz/My-File?node-id=1-2
  → file key = ABC123xyz
  → node ID  = 1:2
```
Extract them:
```bash
# File key
echo "$FIGMA_URL" | sed -E 's|.*(design|file|proto)/([^/]+).*|\2|'

# Node ID (convert hyphens to colons — URLs use `1-2`, Plugin API expects `1:2`)
echo "$FIGMA_URL" | sed -E 's|.*node-id=([^&]+).*|\1|' | tr '-' ':'
```
Use the node ID with `figma.getNodeByIdAsync('1:2')` to jump directly to a specific node.

## When You Receive a Figma URL

Follow these steps in order whenever a user shares a Figma URL:

1. **Parse the URL** — extract the file key and node ID using the bash commands in [URL Parsing](#url-parsing) above.
2. **Establish connection** — load `figma-connection.md` and connect to the browser via Chrome MCP or CDP. Navigate to the Figma URL.
3. **Check access** — if the file requires login or the user isn't authenticated, tell them to log in to Figma in the browser and let you know when they're ready. Do not proceed until the file is accessible.
4. **Read the file** — use REST API (`GET /v1/files/:key?depth=2`) to understand the file structure. If a node ID was provided, inspect that node with `GET /v1/files/:key/nodes?ids=X`.
5. **Render the target** — use REST API (`GET /v1/images/:key`) to get a PNG of the target node(s) for visual context.
6. **Understand before acting** — load `figma-reading.md` and follow the pre-flight workflow to understand the design before modifying anything.
7. **Load the right skill file** — based on the user's task, load the appropriate file from the [Skill Files](#skill-files) table below (building, copy, etc.).
8. **Execute and verify** — make changes via Plugin API, then verify with `exportAsync` or REST image render.

## Rules of Engagement
- Always explain in plain English what you are about to do. Assume the user cannot read code.
- Use the **REST API** for reading file structure and rendering images. Use the **Plugin API** for all design mutations. Do not manually interact with the Figma UI.
- **Preserve existing behavior** unless explicitly asked to change it. When in doubt, ask first.
- **Favor targeted edits over sweeping changes.** Don't remove or overwrite user modifications — only touch what was requested.
- **NEVER rebuild from scratch.** Always improve existing content incrementally. Never clear children and recreate — find and update what's already there.
- **Follow Figma best practices:** use Components, Auto Layout, consistent naming, proper layer hierarchy.
- After creating/modifying nodes, call `figma.viewport.scrollAndZoomIntoView([node])` so the user can see the result.
- **NEVER call `figma.closePlugin()`.** This kills the plugin context and requires a page reload.

## Gotchas
- **All `fills`, `strokes`, and `effects` arrays are readonly** — clone before mutating: `node.fills = [{...}]`. Use `figma.mixed` to check for mixed values on text range properties.
- **`appendChild` can silently fail in complex async scripts.** Nodes may end up as page-level siblings. Always verify: check `parent.children.length` or `child.parent.id === expectedParent.id`.
- **Font loading does NOT persist across eval calls.** You must call `await figma.loadFontAsync(...)` in every script that touches text properties — even if you loaded the same font previously.
- **Nodes created but not appended** within the same eval can get garbage collected. Always append in the same script that creates them.
- **Overriding text inside instances**: Load the node's actual font first, then set characters. See `figma-copy.md` "Text Inside Component Instances" for the full pattern with mixed-font handling.
- **Colors use 0–1 range, NOT 0–255.** Hex `#6366f1` = `{r: 0.388, g: 0.4, b: 0.945}`.
- **Script return values must be JSON-serializable.**
- **Each eval call is independent** — fonts, variables, and references from a previous call are NOT available in the next one.
- **No optional chaining (`?.`) or nullish coalescing (`??`) in the plugin sandbox.** Figma uses QuickJS. Use explicit checks: `node && node.parent && node.parent.type` instead of `node?.parent?.type`.
- **`AsyncFunction` constructor is restricted in QuickJS.** Use `eval()` with an async IIFE wrapper: `eval("(async function() { ... })()")`.
- **Large operations can freeze Figma.** Yield to the event loop between batches with `await new Promise(function(r) { setTimeout(r, 0); })`.

<troubleshooting>
If "figma is not defined": ensure the user has edit permissions. If not, suggest creating a branch. If the global is still missing, instruct the user to open and close any plugin, then retry.
</troubleshooting>

## Skill Files

Load these as needed based on the task at hand:

| File | When to load |
|------|-------------|
| `figma-connection.md` | Setting up browser connection (Chrome MCP, DevTools MCP auto-connect, or CDP via Bash) |
| `figma-rest-api.md` | Reading files, rendering images, or managing comments via HTTP — no browser needed |
| `figma-reading.md` | Understanding an existing design before modifying it (pre-flight, asset extraction, design values) |
| `figma-building.md` | Creating or modifying design nodes (components, Auto Layout, constraints, validation) |
| `figma-cdp.md` | Advanced CDP patterns (console workflow, parallelization, event listeners, batch processing) |
| `figma-copy.md` | Extracting, updating, diffing, and reviewing text content (UX writing, copy management) |
| `figma-api-reference.md` | Looking up Plugin API methods, node types, mixins, or data types |
