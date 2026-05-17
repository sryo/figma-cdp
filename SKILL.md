---
name: figma-cdp
description: "Code → Figma mockups. The reverse of Figma MCP, which goes design → code. Use this to build screens in Figma, edit copy and layouts, or convert UI code into a Figma file. Drives the Plugin API via the agent-browser CLI over Chrome DevTools Protocol. Triggers on Figma URLs, building or editing UI in Figma, code-to-Figma conversion, copy work, and design system tasks."
allowed-tools: Bash(agent-browser:*)
---

# Figma design automation

Code → Figma. The reverse of Figma MCP. Drives Figma's Plugin API via `agent-browser` in a read → modify → verify loop.

Plugin API (`agent-browser --cdp <port> eval`) for everything. REST is only for image rendering and comments.

You are a coordinator. For non-trivial work, you inspect the page, decompose into independent units, write specs with verifiable assertions, and dispatch each spec to a worker subagent. For trivial work (single eval, single node, no assertions), run inline — workers pay off at scale, not on renames.

## Setup

1. **`agent-browser` installed?** Run `which agent-browser`. If it returns nothing, install it: `npm i -g agent-browser && agent-browser install`.
2. **Chrome connected?** Run `agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" eval "typeof figma"`. Should return `"object"`. If not, see `references/execution.md` → Connection (Mode A attach vs Mode B launch). Mode A: export `FIGMA_CDP_PORT` from `DevToolsActivePort` so the helpers pick it up.
3. **Helper scripts.** Copy `figma_run.py` (single eval) and `figma_batch_run.py` (multi-eval) to `/tmp/`.

## When you receive a Figma URL

1. Parse the file key (after `/design/`, `/file/`, `/proto/`) and the node ID (query param, hyphens become colons).
2. Reconnaissance: use the flat text tree pattern in `references/reading.md` → Flat text tree to get the page structure. Switch to Full node inspection only when you need specific properties.
3. Decide whether to dispatch a worker (see Work decomposition) or run inline.
4. If dispatching: fill in `figma-worker.md` with [Task], [Target Nodes], and [Reference], pass to the Agent tool. Run workers in parallel when their units share no state.
5. Collect results and check each worker's status (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED — `figma-worker.md` defines the emit contract).
6. Summarize back to the user: sections completed, node IDs created/modified, assertions that needed retries, escalations, next steps.

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
| `references/building.md` | Creating or modifying nodes, components, images, effects |
| `references/layout-recipes.md` | Auto Layout patterns for Button, Card, Input, List + constraints decision table |
| `references/copy.md` | Text extraction, updates, font loading patterns |
| `references/execution.md` | Connection setup, eval patterns, batched evals, state persistence, error recovery, performance |
| `references/api-reference.md` | Universal API: `figma` global, find/navigate, lifecycle, events, viewport, base mixins. Start here, then load topical files below |
| `references/api-text.md` | TextNode + range methods + font loading. Load for copy/text work |
| `references/api-layout.md` | FrameNode, shape nodes, Layout / AutoLayout / Grid / Constraint mixins. Load for building screens |
| `references/api-components.md` | Component, ComponentSet, Instance, Variables, Styles. Load for component / variant / design-system work |
| `references/api-styling.md` | Geometry & Blend mixins, Paint, Effect, Prototype types. Load for color / shadow / prototype work |

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
- Preserve existing behavior unless asked.
- Make targeted edits; don't rebuild.
- Follow Figma conventions: components, Auto Layout, consistent naming, proper hierarchy.
