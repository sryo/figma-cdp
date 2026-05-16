---
name: figma-cdp
description: "Turns code, copy, and intent into Figma mockups — the reverse of Figma MCP (design → code). Builds screens, components, and design tokens; edits text and layouts; applies styles and effects. Drives Figma's Plugin API via Chrome DevTools Protocol (agent-browser CLI). Trigger on Figma URLs, building or modifying UI in Figma, converting HTML/code to mockups, extracting or updating copy, and design system work."
allowed-tools: Bash(agent-browser:*)
---

# Figma Design Automation

Code → Figma. The reverse of Figma MCP. Drives Figma's Plugin API via `agent-browser` through iterative read → modify → verify loops.

Plugin API (`agent-browser --cdp 9222 eval`) for everything. REST API only for image rendering and comments.

## Setup

1. **Connect** — `agent-browser --cdp 9222 eval "typeof figma"` → `"object"`. If not, see `references/execution.md` → Connection.
2. **Helper** — ensure `figma_run.py` exists (or copy to `/tmp/`). See `references/execution.md` → Connection.

## When You Receive a Figma URL

1. **Parse** — file key (after `/design/`, `/file/`, `/proto/`), node ID (query param, hyphens → colons).
2. **Recon** — run reconnaissance from `references/reading.md` to get page structure.
3. **Decompose** — break into independent work units.
4. **Launch workers** — read `figma-worker.md` (root-level template), fill in [Task], [Target Nodes], and [Reference], pass to Agent tool. Parallel when independent.
5. **Collect results** — check worker status (DONE/DONE_WITH_CONCERNS/NEEDS_CONTEXT/BLOCKED).
6. **Report** — summarize to user.

## Work Decomposition

**Single worker** — overlapping nodes, sequential work, or scope < 20 operations.

**Parallel workers** — independent areas (different pages/frames), no shared state.

**Never parallelize** — same nodes, or one depends on the other's output.

### Task Boundaries

Each worker receives explicit, self-contained instructions:
- **Exact node IDs** — `node 1:23 (TextNode "Hero Heading")`, not "the heading"
- **Complete spec** — exact end state, not "make it better"
- **Assertions** — verifiable checks the worker runs after building (see below)
- **No TBDs** — everything the worker needs is in the prompt

### Structured Spec with Assertions

The coordinator provides **verifiable assertions** — not just prose. Workers verify against these after building. This is how you prevent stuff getting lost in large documents.

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

### Large Documents: Section Checkpointing

For large tasks (e.g., converting an HTML site to Figma), break into sections:

```
## Sections
1. Component library (atoms + molecules) — assertions: [...]
2. Screen: Login — assertions: [...]
3. Screen: Dashboard — assertions: [...]
```

Workers complete and verify one section at a time, checkpoint progress in `window.__batchState.checkpoint`, and resume from the last completed section if re-launched. See `figma-worker.md` for the checkpoint pattern.

### Worker Status Protocol

- **DONE** — completed and verified. Collect result.
- **DONE_WITH_CONCERNS** — completed but unexpected. Review before accepting.
- **NEEDS_CONTEXT** — can't proceed. Provide missing info, re-launch.
- **BLOCKED** — unrecoverable. Reassess the task.

## Files

**Worker template (not a reference — coordinator fills it in and passes to Agent tool):**
- `figma-worker.md` — spec-driven worker prompt with verification loop

**References:**

| File | Load for |
|------|----------|
| `references/conventions.md` | Atomic design, naming, spacing, colors, typography — always include for workers |
| `references/gotchas.md` | WRONG/CORRECT examples for common API pitfalls — always include for workers |
| `references/reading.md` | Understanding design before modifying (also contains REST API reference) |
| `references/building.md` | Creating/modifying nodes, components, images, effects |
| `references/copy.md` | Text extraction, updates, font loading patterns |
| `references/execution.md` | Connection setup, eval patterns, state persistence, error recovery, performance |
| `references/api-reference.md` | Plugin API methods, types, properties lookup |

## Rules of Engagement

- Explain in plain English what you are about to do.
- **NEVER use Chrome MCP tools** (`mcp__claude-in-chrome__*`). Always use `agent-browser`.
- **Read before writing.** Inspect Plugin API state before mutations.
- **Preserve existing behavior** unless explicitly asked to change.
- **Targeted edits only.** Never rebuild from scratch.
- **Figma best practices:** Components, Auto Layout, consistent naming, proper hierarchy.
