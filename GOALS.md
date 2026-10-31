# figma-cdp: goals

## What figma-cdp is for
You point your agent at your app's code, some HTML or a description, and it builds the screen in the Figma file you have open. The mockup uses your real copy, colors and spacing, reuses the components already in the file, and is checked against the source before the agent says it's done.

## Never traded
- **Your file, your tab.** It works only in the Figma file and tab you gave it. It never touches your other files, never takes your foreground, and never falls back into another browser's copy.
- **True to the source.** It never invents copy, colors or spacing the source doesn't have.
- **Reversible.** It edits through the Plugin API, so everything it does can be undone in Figma.

## Goals, in priority order
1. **Matches the source.** The build has the source's copy, tokens and layout, and the agent checks that before it reports.
2. **A file a designer would keep.** It uses components with variants, auto layout and variables, and it reuses what's already there instead of duplicating it.
3. **Few tokens and turns.** The agent reads only what the task needs, and the always-loaded skill stays small.
4. **Reliable.** Calls succeed the first time, and every error tells the agent what to do next.
5. **Fast.** A screen is built in as little wall time as the steps above allow.

## How we know
| Goal | Metric | Where |
|---|---|---|
| 1 | each task's scorer: diffs fixed, copy kept, `inventedCopy`, `hardcodedPaints`, `boundPaintShare`; `pass_rate` | `tests/eval/gate.py` |
| 2 | `quality()`: `autoLayoutShare`, `instanceRatio`, `duplicateComponents`, `detachedLike`, `defaultNames`, `absoluteStacks` | `tests/eval/gate.py` |
| 3 | tokens and their parts, turns, tool calls; always-loaded bytes | `tests/eval/gate.py`, `tests/budget_test.py` |
| 4 | failed tool calls, retries, lost replies, unhinted errors | `tests/eval/gate.py` |
| 5 | `wall_s` | `tests/eval/gate.py` |

Caps: `q3 k2 n2 b2 t1` (how firm each kind of number is: 3 never grows, 2 needs the owner's price, 1 may grow 10%, 0 only reported; fium RULES.md K6)

## Non-goals
- Live UI overlays in Figma, design event streams, and REST writes other than comments (AGENTS.md, Ceiling).
- Per-language source tables: the skill names kinds of source constructs so it works with any source.
