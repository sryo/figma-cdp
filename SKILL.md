---
name: figma-cdp
description: "Code → Figma mockups. The reverse of Figma MCP, which goes design → code. Use this to build screens in Figma, edit copy and layouts, or convert UI code into a Figma file. Drives the Plugin API through perch (AppleScript) or agent-browser (CDP). Triggers on Figma URLs, building or editing UI in Figma, code-to-Figma conversion, copy work, and design system tasks."
allowed-tools: Bash(agent-browser:*), Bash(python3 *figma_*.py *)
---

# Figma design automation

You coordinate: read the source and the file, plan, run small work inline, dispatch the rest to workers (`figma-worker.md`), gate the result. Plugin API for everything; REST only for renders and comments.

## Setup

`<skill-dir>` is the folder holding this SKILL.md. Run every helper from there. Check: `python3 <skill-dir>/figma_run.py --file <figma-url> -e 'typeof figma'` → `"object"`. Failure or CDP setup: `references/connection.md`; if it still fails, stop and report the error. Never work around it with browser MCP tools, clicks, screenshots or exported code. Pass `--file` (or export `FIGMA_FILE`) on every helper call. Split outputs in one Bash call with `echo ---` (zsh runs `====` as a command).

## Flow

1. Parse the file key (after `/design/`, `/file/`, `/proto/`) and `node-id` (`-` → `:`).
2. **Source.** Find it (`~/Documents/<name>`, a path, a GitHub or live URL) and read the real UI. No UI (CLI, library): ask what to design; never invent from a name. Manifest, once: `python3 <skill-dir>/figma_source.py <files> -o /tmp/figma_source_<slug>.json` (`references/fidelity.md`); then read the manifest (copy, tokens, each component's CSS rules), not the source files, except a screen's markup. A component's `fill` lists the usages its column parent stretches: the brief says FILL across for those, never hug. A live URL goes through capture instead: `figma_capture.py walk <url>`, then `import <spec> --componentize --components <json>` (`references/capture.md`); workers only fix after.
3. **Recon, one call:** `python3 <skill-dir>/figma_run.py --lib --file <url> -e 'await figma.saveVersionHistoryAsync("pre <task>"); return [await __fx.recon({nodeId: "<id>"}), (await __fx.inventory()).text]'`: pages, text tree, one line per component set, component, style, variable and repeated pattern.
4. **An edit or "make it match"** on an existing frame: read the target in step 3's call with `recon({nodeId: "<id>", props: true})` (layout, paints, effects per line); diff (`figma_fidelity.py`), patch the existing nodes in place, never replace or remove one, swap it for an instance or add components unless asked; skip to 8.
5. **Component plan** (builds): every manifest `components` entry and unit repeating 2+ times, existing screens too (a shared header). Inventory first (`__fx.inventory({match: 'card'})`); a match is REUSE `<id>` as is, per-use differences (state, text) as instance overrides, never renamed, given variants or made a set unless asked; else NEW. Prop/state enums: VARIANT axes; varying text: TEXT; optional parts: BOOLEAN; swappable icons: INSTANCE_SWAP. A container with per-use content (card, panel) is still a component: a header with those props, or a slot (`createSlot`); a wrapper of repeated items (tabs, list) holds exposed item instances. A repeated PATTERN the task touches becomes a component first. Recipe: `references/building.md` → Repeated patterns.
6. **Inline or dispatch** (below). Dispatch: pre-create target frames, fill every `figma-worker.md` slot ([Reuse]: only the lines the task needs), hand it to a subagent.
7. **Statuses.** DONE_WITH_CONCERNS: verify its concerns; an `fxNote` means workers' areas overlapped: fix the split. NEEDS_CONTEXT: get it, re-dispatch. BLOCKED: from failures and `createdNodeIds`, re-split, roll back (`references/execution.md` → Rollback) or ask.
8. **Final gate:** `figma_run.py --lib --file <url> -e 'return (await __fx.audit("<rootId>")).text'` empty on what you built (an edit reports the lines it found) and `figma_fidelity.py /tmp/figma_source_<slug>.json <rootId> --file <url>` 0 gaps. Fix gaps with targeted edits; report any left on purpose.
9. **Summarize:** changes, node ids, retries, every worker assumption verbatim, gaps left, next steps.

## Work decomposition

Run inline up to one frame or ~20 operations, following `figma-worker.md`'s cheat sheet and Loop. Group small related units into one worker's Sections, never one worker each. Parallel workers only for independent areas (other frames or pages); never shared nodes or dependent chains. Split a worker past ~40 operations or 25 assertions.

Specs are self-contained: verified ids, exact end state, assertions, no TBDs; [Reuse] and [Manifest] filled.

## References (load on demand)

| File | Load for |
|------|----------|
| `references/capture.md` | Live URL → Figma import |
| `references/conventions.md` | Value precedence, source → Figma mapping, design defaults, naming |
| `references/gotchas.md` | API pitfalls as WRONG/CORRECT |
| `references/reading.md` | Recon, inventory, deep reads |
| `references/building.md` | Creating nodes, variant recipe, layout recipes |
| `references/copy.md` | Text edits, fonts |
| `references/connection.md` | Setup, perch/CDP modes, troubleshooting |
| `references/execution.md` | Helpers, `__fx`, batching, state, verification, rollback |
| `references/fidelity.md` | Source manifest and fidelity check |
| `references/rest-api.md` | REST renders and comments |
| `references/api-reference.md` | `figma` global, base mixins, fills |
| `references/api-text.md` | TextNode |
| `references/api-layout.md` | Frames, auto layout, constraints |
| `references/api-components.md` | Components, variables, styles |
| `references/api-styling.md` | Effects, gradients, prototype types |
| `references/prototyping.md` | Reactions, overlays, flows, interactive components, plan limits |

Per-task reference combos (a worker reads these only for calls its cheat sheet lacks):
- Build screens: conventions + building + api-layout
- Copy/text edit: copy + api-text
- Component/variant/design-system: building + api-components
- Color/effects/prototype: conventions + api-styling (+ prototyping for interactions)

## Rules

- Say plainly what you will do.
- Read before writing; make targeted edits; don't rebuild; preserve behavior unless asked.
