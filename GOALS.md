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
| Goal | Metric | Where | Run |
|---|---|---|---|
| 1 | each task's scorer: diffs fixed, copy kept, `inventedCopy`, `hardcodedPaints`, `boundPaintShare`; `pass_rate` | `tests/eval/gate.py` | costly: `out=$(mktemp -d)/results.json && python3 tests/eval/run.py --file "${EVAL_FILE:?set EVAL_FILE to the scratch Figma file}" --tasks "${EVAL_TASKS:?set EVAL_TASKS to the tasks plan.py scopes}" --reps "${EVAL_REPS:-2}" --out "$out" >&2 && python3 tests/eval/gate.py --fium "$out" > "$out.fium.json" && echo "$out.fium.json"` |
| 2 | `quality()`: `autoLayoutShare`, `instanceRatio`, `duplicateComponents`, `detachedLike`, `defaultNames`, `absoluteStacks` | `tests/eval/gate.py`: `<task>.autoLayoutShare`, `<task>.instanceRatio`, `<task>.duplicateComponents`, `<task>.detachedLike`, `<task>.defaultNames`, `<task>.absoluteStacks` | costly: `out=$(mktemp -d)/results.json && python3 tests/eval/run.py --file "${EVAL_FILE:?set EVAL_FILE to the scratch Figma file}" --tasks "${EVAL_TASKS:?set EVAL_TASKS to the tasks plan.py scopes}" --reps "${EVAL_REPS:-2}" --out "$out" >&2 && python3 tests/eval/gate.py --fium "$out" > "$out.fium.json" && echo "$out.fium.json"` |
| 3 | tokens and their parts, turns, tool calls | `tests/eval/gate.py`: `<task>.tokens_total`, `<task>.<part>tokens`, `<task>.turns`, `<task>.tool_calls` | costly: `out=$(mktemp -d)/results.json && python3 tests/eval/run.py --file "${EVAL_FILE:?set EVAL_FILE to the scratch Figma file}" --tasks "${EVAL_TASKS:?set EVAL_TASKS to the tasks plan.py scopes}" --reps "${EVAL_REPS:-2}" --out "$out" >&2 && python3 tests/eval/gate.py --fium "$out" > "$out.fium.json" && echo "$out.fium.json"` |
| 3 | always-loaded bytes (SKILL.md + figma-worker.md) | `tests/budget_test.py` | `python3 tests/budget_test.py && cat SKILL.md figma-worker.md \| wc -c` |
| 4 | failed tool calls, retries, lost replies, unhinted errors | `tests/eval/gate.py`: `<task>.failed_tool_calls`, `<task>.retries`, `<task>.lost_replies`, `<task>.unhinted_errors`, `<task>.recover_uses` | costly: `out=$(mktemp -d)/results.json && python3 tests/eval/run.py --file "${EVAL_FILE:?set EVAL_FILE to the scratch Figma file}" --tasks "${EVAL_TASKS:?set EVAL_TASKS to the tasks plan.py scopes}" --reps "${EVAL_REPS:-2}" --out "$out" >&2 && python3 tests/eval/gate.py --fium "$out" > "$out.fium.json" && echo "$out.fium.json"` |
| 4 | offline suites and lessons replay pass | `tests/cases/case.py offline` | `python3 tests/cases/case.py offline` |
| 5 | `wall_s` | `tests/eval/gate.py`: `<task>.wall_s` | costly: `out=$(mktemp -d)/results.json && python3 tests/eval/run.py --file "${EVAL_FILE:?set EVAL_FILE to the scratch Figma file}" --tasks "${EVAL_TASKS:?set EVAL_TASKS to the tasks plan.py scopes}" --reps "${EVAL_REPS:-2}" --out "$out" >&2 && python3 tests/eval/gate.py --fium "$out" > "$out.fium.json" && echo "$out.fium.json"` |

Caps: `all=ask quality=hard time=ask+10%`

## Non-goals
- Live UI overlays in Figma, design event streams, and REST writes other than comments (AGENTS.md, Ceiling).
- Per-language source tables: the skill names kinds of source constructs so it works with any source.
