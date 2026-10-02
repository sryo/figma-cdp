---
name: figma-cdp
description: "Code → Figma mockups. The reverse of Figma MCP, which goes design → code. Use this to build screens in Figma, edit copy and layouts, or convert UI code into a Figma file. Drives the Plugin API through perch (AppleScript) or the agent-browser CLI (Chrome DevTools Protocol). Triggers on Figma URLs, building or editing UI in Figma, code-to-Figma conversion, copy work, and design system tasks."
allowed-tools: Bash(agent-browser:*), Bash(python3 *figma_*.py *)
---

# Figma design automation

You coordinate: read the source and the file, plan components, run small work inline, dispatch the rest to workers (`figma-worker.md`), and gate the result. Plugin API for everything; REST only for image renders and comments.

## Setup

`<skill-dir>` is this skill's base directory. Run every helper from there; nothing is copied. Check: `python3 <skill-dir>/figma_run.py --file <figma-url> -e 'typeof figma'` → `"object"`. It uses perch when present (macOS, no debugging prompt), else CDP through `agent-browser`. Any failure or CDP setup: `references/connection.md`. Pass `--file` (or export `FIGMA_FILE`) on every helper call.

## Flow

1. Parse the file key (after `/design/`, `/file/`, `/proto/`) and node id (`node-id`, `-` → `:`).
2. **Source.** Code → Figma means the source exists: find it (`~/Documents/<name>`, a path, a GitHub URL, a live URL) and read the real UI. An app with no UI (CLI, library): ask what to design; never invent from a name. Write the manifest once: `python3 <skill-dir>/figma_source.py <files> -o /tmp/figma_source_<slug>.json` (`references/fidelity.md`). A live URL goes through capture instead: `figma_capture.py walk <url>`, then `import <spec> --componentize --components <json>` (`references/capture.md`); workers only fix after.
3. **Recon, one call:** `python3 <skill-dir>/figma_run.py --lib --file <url> -e 'await figma.saveVersionHistoryAsync("pre <task>"); return [await __fx.recon({nodeId: "<id>"}), (await __fx.inventory()).text]'`: page list and text tree, plus one line per reusable set, component, library component, style, variable and repeated raw pattern (`references/reading.md`).
4. **Component plan.** Search the inventory first (`__fx.inventory({match: 'button|card'})`); a match is REUSE `<id>`. A unit with no match becomes NEW when it repeats 2+ times or has prop/state enums. Enums and states become VARIANT axes of a component set; text that varies becomes a TEXT property, optional parts BOOLEAN, swappable icons INSTANCE_SWAP. A repeated PATTERN the task touches becomes a component first. Recipe: `references/building.md` → Component variants.
5. **Inline or dispatch** (below). Dispatch: pre-create target frames, fill every `figma-worker.md` slot ([Reuse] gets only the inventory lines the task needs) and pass it to the Agent tool.
6. **Statuses.** DONE: collect ids. DONE_WITH_CONCERNS: check its concerns and assumptions yourself. NEEDS_CONTEXT: get it, re-dispatch the same spec. BLOCKED: read the failures and `createdNodeIds`, then re-split, clean up (`references/execution.md` → Rollback) or ask the user.
7. **Final gate** before summarizing: `__fx.audit(rootId)` counts at 0 and `python3 <skill-dir>/figma_fidelity.py /tmp/figma_source_<slug>.json <rootId> --file <url>` exit 0. Fix gaps with targeted edits; report any left on purpose.
8. **Summarize:** what changed, node ids, retries, every worker assumption verbatim, gaps left, next steps.

## Work decomposition

Run inline up to one frame or ~20 operations. Group small related units into one worker with Sections, never one worker each. Parallel workers only for independent large areas (different frames or pages); never the same nodes or dependent chains. Split a worker past ~40 operations or 25 assertions.

Specs are self-contained: real ids (`1:23 (TEXT "Hero Heading")`), an exact end state, assertions, no TBDs.

## Before dispatch

- [ ] Target ids verified to exist
- [ ] Component plan covers every source unit; [Reuse] and [Manifest] filled
- [ ] End state exact; assertions cover it; under the size limits

## References (load on demand)

| File | Load for |
|------|----------|
| `references/capture.md` | Live URL → Figma import |
| `references/conventions.md` | Value precedence, source → Figma mapping, design defaults, naming |
| `references/gotchas.md` | API pitfalls as WRONG/CORRECT |
| `references/reading.md` | Recon, inventory, deep reads |
| `references/building.md` | Creating nodes, variant recipe, layout recipes |
| `references/copy.md` | Text edits, fonts |
| `references/connection.md` | Setup, perch and CDP modes, troubleshooting |
| `references/execution.md` | Helpers, `__fx`, batching, state, verification, rollback |
| `references/fidelity.md` | Source manifest and fidelity check |
| `references/rest-api.md` | REST renders and comments |
| `references/api-reference.md` | `figma` global, base mixins, fills |
| `references/api-text.md` | TextNode |
| `references/api-layout.md` | Frames, auto layout, constraints |
| `references/api-components.md` | Components, variables, styles |
| `references/api-styling.md` | Effects, gradients, prototyping |

Per-task reference combos (a worker reads these only for calls its cheat sheet lacks):
- Build screens: conventions + building + api-layout
- Copy/text edit: copy + api-text
- Component/variant/design-system: building + api-components
- Color/effects/prototype: conventions + api-styling

## Rules

- Say in plain English what you'll do.
- Never use Chrome MCP tools; always the helpers.
- Read state before writing; make targeted edits; don't rebuild; preserve behavior unless asked.
