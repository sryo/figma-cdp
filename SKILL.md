---
name: figma-cdp
description: "Code → Figma mockups. The reverse of Figma MCP, which goes design → code. Use this to build screens in Figma, edit copy and layouts, or convert UI code into a Figma file. Drives the Plugin API via the agent-browser CLI over Chrome DevTools Protocol. Triggers on Figma URLs, building or editing UI in Figma, code-to-Figma conversion, copy work, and design system tasks."
allowed-tools: Bash(agent-browser:*), Bash(python3 /tmp/figma_run.py:*), Bash(python3 /tmp/figma_batch_run.py:*)
---

# Figma design automation

Code → Figma. The reverse of Figma MCP. Drives Figma's Plugin API via `agent-browser` in a read → modify → verify loop.

Plugin API (`agent-browser --cdp <port> eval`) for everything. REST is only for image rendering and comments.

You are a coordinator. For non-trivial work, you inspect the page, decompose into independent units, write specs with verifiable assertions, and dispatch each spec to a worker subagent. For trivial work (single eval, single node, no assertions), run inline — workers pay off at scale, not on renames.

## Setup

1. **`agent-browser` installed?** Run `which agent-browser`. If it returns nothing, install it: `npm i -g agent-browser && agent-browser install`.
2. **Chrome connected?** Run `agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" eval "typeof figma"`. Should return `"object"`. If not, see `references/connection.md` (Mode A attach vs Mode B launch). Mode A: the helpers read `DevToolsActivePort` automatically when `FIGMA_CDP_PORT` is unset; exporting it is optional (it wins when set) but still required for raw `agent-browser` one-liners, which don't do the fallback.
3. **Helper scripts.** Copy `figma_run.py` (single eval) and `figma_batch_run.py` (multi-eval) to `/tmp/`.

## When you receive a Figma URL

1. Parse the file key (after `/design/`, `/file/`, `/proto/`) and the node ID (query param, hyphens become colons).
2. Reconnaissance: use the flat text tree pattern in `references/reading.md` → Flat text tree to get the page structure. Switch to Full node inspection only when you need specific properties.
3. Inventory local components: run `references/reading.md` → Component inventory. Note every Component / ComponentSet that exists; any worker that needs a button, card, input, icon, etc. should instantiate the matching one instead of building raw frames. New components only when nothing fits.
4. Decide whether to dispatch a worker (see Work decomposition) or run inline.
5. If dispatching: pre-create the target frames and assign each worker a specific frame or page — a worker builds only within its assigned frame. Fill in `figma-worker.md` with [Task], [Target Nodes], and [Reference], pass to the Agent tool. List the component IDs the worker should reuse so it doesn't rebuild from scratch. Run workers in parallel when their units share no state.
6. Collect results and check each worker's status (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED — `figma-worker.md` defines the emit contract).
7. Summarize back to the user: sections completed, node IDs created/modified, assertions that needed retries, escalations, next steps.

## When you receive a mockup request without a source URL

Triggers: "build a mockup of <app>", "design <project>'s dashboard", "make a Figma file for coro / avis / stow / etc." — anything that names an existing app, screen, or feature instead of pointing at a Figma file.

The skill is **code → Figma**: the source artifact already exists. Discover it before designing.

1. **Locate the source.** Check `~/Documents/<name>` (case-insensitive — `coro` may live in `~/Documents/concerto`, `stow` in `~/Documents/Stow`). If not there, ask the user for the repo path or fetch the GitHub URL. Treat portfolio blurbs and README descriptions as hints, not substitutes for the code.
2. **Read the actual UI** — components, routes, styles, screenshots, design tokens. Get the real layout, real colors, real typography, real copy. The mockup mirrors the implementation; do not generate from the app's name or category.
3. **If the app has no UI yet** (a CLI, a library, a backend service), say so and ask the user what surface to design — don't invent screens.
4. **Then proceed from step 3 of the Figma-URL branch** (decompose, dispatch workers). Each worker spec must cite the specific source files it should mirror (e.g. `concerto/dashboard/src/components/column.tsx`).

## Work decomposition

**Skip the worker** for tasks under ~5 operations or ~3 assertions — run inline. Single-property dispatch pays overhead without buying verification.

**One worker** when units overlap, run sequentially, or stay under 20 operations. **Parallel workers** for independent areas (different pages or frames) that share no state. Never parallelize the same nodes, or chains where one worker depends on another's output.

If a worker's task list exceeds 20 operations or its assertion block exceeds 25 items, split it. Hard rule.

### Task boundaries

Each worker gets explicit, self-contained instructions: real node IDs like `1:23 (TextNode "Hero Heading")` instead of "the heading", an exact end state instead of "make it better", verifiable assertions to run after building, and no TBDs.

### Spec format with assertions

Coordinator provides verifiable assertions; workers check after building. The full spec template (Task / Target Nodes / Assertions / Sections) lives in `figma-worker.md`.

### Large documents: section checkpointing

For large tasks (e.g., converting an HTML site to Figma), break into sections. Workers complete and verify one section at a time, checkpoint progress in `window.__batchState.checkpoint`, and resume from the last completed section if re-launched. See `figma-worker.md` for the checkpoint pattern.

## Files

Worker template (the coordinator fills it in and passes it to the Agent tool):

- `figma-worker.md`: spec-driven worker prompt with a verification loop

References, loaded on demand:

| File | Load for |
|------|----------|
| `references/conventions.md` | Atomic design, naming, spacing, colors, typography. Always include for workers |
| `references/gotchas.md` | WRONG/CORRECT examples for common API pitfalls. Always include for workers |
| `references/reading.md` | Understanding design before modifying |
| `references/rest-api.md` | REST endpoints for image rendering and comments |
| `references/building.md` | Creating or modifying nodes, components, images, effects + Auto Layout patterns for Button, Card, Input, List + constraints decision table |
| `references/copy.md` | Text extraction, updates, font loading patterns |
| `references/connection.md` | Connection setup: Mode A attach, Mode B Canary launch, troubleshooting. Coordinator-only — load during setup |
| `references/execution.md` | Eval patterns, batched evals, state persistence, error recovery, performance |
| `references/api-reference.md` | Universal API: `figma` global, find/navigate, lifecycle, events, viewport, base mixins, GeometryMixin (fills/strokes) + hex helper. Start here, then load topical files below |
| `references/api-text.md` | TextNode + range methods + font loading. Load for copy/text work |
| `references/api-layout.md` | FrameNode, shape nodes, Layout / AutoLayout / Grid / Constraint mixins. Load for building screens |
| `references/api-components.md` | Component, ComponentSet, Instance, Variables, Styles. Load for component / variant / design-system work |
| `references/api-styling.md` | Blend mixin, gradient/image paints, Effect, Reaction + FramePrototypingMixin, Prototype types. Load for color / shadow / prototype work (solid fills/strokes live in api-reference.md) |

## Before dispatch

- [ ] Target nodes named with exact IDs, not descriptions
- [ ] Each target ID verified to exist (`getNodeByIdAsync` returns a node, not null)
- [ ] End state is exact (no "make it better")
- [ ] Assertions list every verifiable check
- [ ] Task fits under the complexity budget (20 ops, 25 assertions)

## Rules

- Explain in plain English what you'll do.
- Never use Chrome MCP tools (`mcp__claude-in-chrome__*`). Always use `agent-browser`.
- Read state before writing. Inspect the Plugin API before mutating anything.
- **Code → Figma means the source artifact already exists.** Before designing, locate and read it — repo, component file, README screenshots, or live page. Never generate from the app's name or category alone.
- Preserve existing behavior unless asked.
- Make targeted edits; don't rebuild.
- Follow Figma conventions: components, Auto Layout, consistent naming, proper hierarchy.
