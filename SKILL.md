---
name: figma-cdp
description: "Code → Figma mockups. The reverse of Figma MCP, which goes design → code. Use this to build screens in Figma, edit copy and layouts, or convert HTML into a Figma file. Drives the Plugin API via the agent-browser CLI over Chrome DevTools Protocol. Triggers on Figma URLs, building or editing UI in Figma, HTML-to-Figma conversion, copy work, and design system tasks."
allowed-tools: Bash(agent-browser:*)
---

# Figma design automation

Code → Figma. The reverse of Figma MCP. Drives Figma's Plugin API via `agent-browser` in a read → modify → verify loop.

Plugin API (`agent-browser --cdp 9222 eval`) for everything. REST is only for image rendering and comments.

You are a coordinator, not a builder. You inspect the page, decompose the work, write specs with verifiable assertions, and hand each spec to a worker subagent. The workers do the actual Plugin API calls. You orchestrate and verify.

## Setup

Test the connection: `agent-browser --cdp 9222 eval "typeof figma"` should return `"object"`. If not, see `references/execution.md` → Connection for how to launch Chrome.

The helper `figma_run.py` ships with the repo. Copy it to `/tmp/` if that's where your worker scripts live.

## When you receive a Figma URL

1. Parse the file key (after `/design/`, `/file/`, `/proto/`) and the node ID (query param, hyphens become colons).
2. Reconnaissance: use the flat text tree pattern in `references/reading.md` to get the page structure. Switch to Full node inspection only when you need specific properties.
3. Decompose the work into independent units.
4. Fill in `figma-worker.md` with [Task], [Target Nodes], and [Reference], then pass it to the Agent tool. Run workers in parallel when their units share no state.
5. Collect results and check each worker's status (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED).
6. Summarize back to the user:
   - Sections completed (with worker status for each)
   - Node IDs created or modified
   - Any assertions that needed retries (and why)
   - Anything that escalated to NEEDS_CONTEXT or BLOCKED
   - Suggested next steps if the work isn't finished

## Work decomposition

One worker when units overlap, run sequentially, or stay under 20 operations. Parallel workers for independent areas (different pages or frames) that share no state. Never parallelize the same nodes, or chains where one worker depends on another's output.

If a worker's task list exceeds 20 operations or its assertion block exceeds 25 items, split it. This is a hard rule. Don't override it because "it's all related".

### Task boundaries

Each worker gets explicit, self-contained instructions: real node IDs like `1:23 (TextNode "Hero Heading")` instead of "the heading", an exact end state instead of "make it better", verifiable assertions to run after building, and no TBDs. Everything the worker needs goes in the prompt.

### Structured spec with assertions

The coordinator provides verifiable assertions, not just prose. Workers check against them after building. This is what stops requirements from getting lost in long documents.

```
## Task
Build a login screen.

## Assertions (worker verifies ALL after building)
- node ROOT: type=FRAME, childCount=8, name="Screens/Login"
- child 0: type=INSTANCE, name contains "Avatar"
- child 1: type=TEXT, characters="Welcome back", fontSize=28
- child 2: type=TEXT, characters="Sign in to your account"
- child 3: type=INSTANCE, name contains "Input"
- child 4: type=INSTANCE, name contains "Input"
- child 5: type=INSTANCE, name contains "Button"
- child 6: type=INSTANCE, name contains "Text Link"
- child 7: type=INSTANCE, name contains "Text Link"
```

Workers run assertions programmatically, fix failures (max 3 retries), then report DONE or BLOCKED.

### Large documents: section checkpointing

For large tasks (e.g., converting an HTML site to Figma), break into sections:

```
## Sections
1. Component library (atoms + molecules) — assertions: [...]
2. Screen: Login — assertions: [...]
3. Screen: Dashboard — assertions: [...]
```

Workers complete and verify one section at a time, checkpoint progress in `window.__batchState.checkpoint`, and resume from the last completed section if re-launched. See `figma-worker.md` for the checkpoint pattern.

### Worker status protocol

- **DONE** — completed and verified. Collect result.
- **DONE_WITH_CONCERNS** — completed but unexpected. Review before accepting.
- **NEEDS_CONTEXT** — can't proceed. Provide missing info, re-launch.
- **BLOCKED** — unrecoverable. Reassess the task.

## Files

Worker template (the coordinator fills it in and passes it to the Agent tool):

- `figma-worker.md`: spec-driven worker prompt with a verification loop

References, loaded on demand:

| File | Load for |
|------|----------|
| `references/conventions.md` | Atomic design, naming, spacing, colors, typography. Always include for workers |
| `references/gotchas.md` | WRONG/CORRECT examples for common API pitfalls. Always include for workers |
| `references/reading.md` | Understanding design before modifying (also contains the REST API reference) |
| `references/building.md` | Creating or modifying nodes, components, images, effects |
| `references/copy.md` | Text extraction, updates, font loading patterns |
| `references/execution.md` | Connection setup, eval patterns, state persistence, error recovery, performance |
| `references/api-reference.md` | Plugin API methods, types, properties |

## Pre-dispatch checklist

Before spawning a worker, verify every box:

- [ ] Target nodes named with exact IDs, not descriptions
- [ ] Each target ID verified to exist (`getNodeByIdAsync` returns a node, not null) before dispatch
- [ ] End state is exact (no "make it better")
- [ ] Assertions list every verifiable check
- [ ] Worker template filled in: [Task], [Target Nodes], [Reference]
- [ ] References loaded: `gotchas.md` and `conventions.md` always; topic-specific files as needed
- [ ] Task fits under the complexity budget (20 ops, 25 assertions)

## Rules

- Explain in plain English what you're about to do.
- Never use Chrome MCP tools (`mcp__claude-in-chrome__*`). Always use `agent-browser`.
- Read state before writing. Inspect the Plugin API before mutating anything.
- Preserve existing behavior unless asked to change it.
- Make targeted edits. Don't rebuild from scratch.
- Follow Figma conventions: components, Auto Layout, consistent naming, proper hierarchy.

## Anti-patterns (what NOT to do)

- **Don't spawn a worker without a spec.** "Build a nice login screen" goes wrong every time. The spec with assertions is the contract.
- **Don't bundle unrelated work into one worker.** A copy edit and a layout change in the same worker means neither gets verified properly.
- **Don't parallelize on the same nodes.** Two workers writing to `1:23` race each other and silently overwrite.
- **Don't skip the read step.** Inspecting the current Plugin API state takes one eval and saves three re-do cycles.
- **Don't retry failed evals blindly.** Read state first, then retry the specific failure (see `references/execution.md` → Error Recovery).
- **Don't rebuild from scratch.** Figma designers iterate on real artifacts. Clobbering their work breaks trust.
