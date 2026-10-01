# figma-cdp

Architecture and invariants for the figma-cdp Claude Code skill.

figma-cdp drives Figma's Plugin API (`figma.*` global) from outside Figma — code → mockup, the reverse direction of Figma MCP. It shells out to the `agent-browser` CLI, which talks Chrome DevTools Protocol to a Chrome tab open on a Figma file. The current runtime surface is `SKILL.md`; this file is the design doc anyone reads when modifying the skill itself.

## Layout

```
.
├── SKILL.md              # runtime entry — Claude reads this when the skill triggers
├── figma-worker.md       # worker template the coordinator dispatches via the Agent tool
├── figma_run.py          # single-eval helper — base64 → agent-browser eval
├── figma_batch_run.py    # multi-eval helper — base64 N scripts → one agent-browser batch
├── figma_perch.mjs       # perch backend for both helpers: list_tabs → eval_js {world:"main"}, no CDP
├── figma_capture.py      # live-URL → Figma: `walk <url>` (--session capture → /tmp JSON) and `import <spec>` (default session: reset, assets streamed in pieces, node chunks through figma_importer.js)
├── figma_walker.js       # DOM walker run by `walk` — emits the capture envelope (layout-space geometry, sparse styles, assets)
├── figma_importer.js     # runs once per node chunk in the default session — chunk → Figma nodes
├── AGENTS.md             # this file — architecture + invariants
├── CLAUDE.md             # pointer to AGENTS.md
├── README.md             # human-facing intro + install
├── references/           # task-shaped reference files (loaded on demand)
└── tests/
    ├── capture_fixture.html  # static page exercising the walker's schema end to end — `walk` it to hand-verify a spec
    ├── importer_stub.js      # `node tests/importer_stub.js <spec.json>` — runs the importer against a stub Plugin API, no Figma tab needed
    ├── perch_backend_test.py # `python3 tests/perch_backend_test.py`: both helpers on the perch backend against perch_stub/, offline
    ├── perch_stub/           # stand-in perch server.js: runs eval_js scripts in Node against a stub `figma`
    └── evals.json            # state-only assertions for hand-verifying behavior
```

## Architecture

```
Skill triggers on a Figma URL or build request → Claude reads SKILL.md →
coordinator parses URL, recons via references/reading.md → Flat text tree →
decomposes work → dispatches workers via the Agent tool with figma-worker.md
filled in → workers Write .js files → shell out via figma_run.py /
figma_batch_run.py → agent-browser CLI → CDP WebSocket → Figma's Plugin API
(QuickJS sandbox) → JSON return.
```

**Coordinator vs worker.** The coordinator inspects, decomposes, dispatches, and verifies. Workers execute one self-contained spec and emit a status. Operational thresholds (when to inline vs dispatch, complexity caps per worker) live in `SKILL.md`'s Work decomposition section; the four statuses live in `figma-worker.md` — single source of truth for each. One deliberate exception to dedup: `figma-worker.md` inlines the property-check and assertion-verification skeletons from `references/execution.md` as dispatch-cost duplication (saves every worker a reference load; the copies carry keep-in-sync comments and are maintained manually).

**Token-cost tiers.** `SKILL.md` is loaded into every conversation that triggers the skill; every line is per-conversation cost. `figma-worker.md` plus its inlined references are loaded into every spawned worker; per-dispatch cost. Other `references/*.md` files load on demand.

**Connection modes.** Mode A is attach to your running Chrome via the `chrome://inspect/#remote-debugging` toggle — preferred, uses the real logged-in Figma session, no profile copy. Mode B is launch a dedicated Chrome Canary with `--remote-debugging-port` and a profile copy — fallback for managed Chrome where the toggle is blocked. Chrome 136+ refuses `--remote-debugging-port` on the default user-data-dir (security hardening), which is what forces Mode B's profile-copy gymnastics. `FIGMA_CDP_PORT` env var binds both helpers to whichever port the chosen mode is using. Mode P skips CDP: `figma_run.py` / `figma_batch_run.py` hand scripts to `figma_perch.mjs`, which imports perch's `handleCall` and runs them with `eval_js {world:"main", awaitPromise:true}` over AppleScript, so Chrome never shows its remote-debugging prompt. The setup procedure for all three lives in `references/connection.md`.

## Reference file organization

- **Always-load with workers:** `conventions.md`, `gotchas.md`.
- **Task-shaped on-demand:** `building.md`, `copy.md`, `reading.md`, `execution.md`, `rest-api.md`.
- **Coordinator-only setup:** `connection.md` (Mode A attach, Mode B Canary launch, troubleshooting) — loaded during setup; workers receive a working connection.
- **API reference split 5 ways** so workers load only what their task touches: `api-reference.md` (universal core — including GeometryMixin fills/strokes and the hex helper, so solid color work needs no extra file), `api-text.md`, `api-layout.md`, `api-components.md`, `api-styling.md`. Per-file "load for" descriptions and the per-task combo list live in `SKILL.md`.

Don't add a reference file unless it would otherwise live as a too-large section in another file. Cross-link aggressively before splitting.

## `agent-browser` dependency

`agent-browser` (vercel-labs) is a Rust CLI that wraps Chrome DevTools Protocol. We shell out to it rather than talking CDP ourselves because the binary handles WebSocket lifecycle, base64 input, exit-code propagation, and target routing cleanly. We pay ~200ms cold-start per invocation; `figma_batch_run.py` amortizes that across N sequential evals via the `batch` subcommand.

The only subcommands we depend on:
- `eval -b <base64>` — run a JS script in the page
- `batch --json "<cmd1>" "<cmd2>" ...` — run multiple commands in one CLI invocation, results as a JSON array
- `screenshot <path>` — full-page PNG capture
- `open <url>` — navigate a tab (verified subcommand name; not `navigate`/`goto`)
- `connect <port>` — bind a session to a CDP port (capture fast-path binds explicitly; a later bare `--cdp` does NOT retarget a bound session)
- `--cdp <port>` — target port (default 9222, overridden by `FIGMA_CDP_PORT`)
- `--session <name>` — per-worker browser tab/session isolation; the spike verified named sessions are isolated tab sets (the capture fast-path binds its own `--session capture`). `references/execution.md` → "When to use sessions vs shared state" prescribes it for parallel workers on *different* Figma files (same-file workers share one tab via namespaced `window.__batchState`)

If any of these break, that's the integration boundary to fix. The other ~140 agent-browser subcommands are irrelevant to this skill.

## perch backend

`figma_perch.mjs` imports `server.js` from `PERCH_DIR` (default `~/Documents/perch`) and calls its exported `handleCall` in-process; no MCP session, no CDP. It depends on:
- `list_tabs {urlContains}` to find the file's tab (a tab its window shows wins among duplicates; several files open and no `--file` is an `ambiguous_tab` error)
- `eval_js {world:"main", awaitPromise:true, script, target:{tabId}}`; the script is wrapped as `return await (0, eval)(<source>)` so a program's completion value comes back as CDP's `Runtime.evaluate` returns it, and a throw is caught in-page and reported as `✗ Evaluation error: ...`
- `screenshot {target, maxWidth:0, format:"png"}` for `figma_run.py --screenshot` (the tab must be the one its window shows)
- the `buildMainKick` export, which marks a perch new enough to have `world:"main"`

Backend choice: `FIGMA_BACKEND=cdp|perch` wins; else `FIGMA_CDP_PORT` set means CDP; else perch when it is usable; else CDP. Output and exit codes match the CDP path, so callers never branch on the backend. Errors keep perch's leading code (`timeout`, `stale_tab`, `tab_not_scriptable`, `no_tab`, `ambiguous_tab`, `no_perch`). perch caps an awaited eval at 30s and needs no base64 ceiling. The capture fast-path (`figma_capture.py`) stays CDP-only: `walk` opens the URL in its own agent-browser session.

## Rules for changes

- **SKILL.md is always-loaded.** Every line is per-conversation token cost. Add only what every coordinator needs.
- **figma-worker.md is per-dispatch.** Every line is per-worker token cost. Compress hedging and meta-narration; preserve imperatives (READ before doing, find before creating, fix only what failed, don't rebuild).
- **References stay task-shaped.** Don't merge files because they're conceptually related. Don't split files because they're long — split only when independent tasks would load disjoint subsets.
- **Source-language framing stays generic.** Don't add per-language mapping tables (SwiftUI / Compose / Flutter / etc.). The `conventions.md` → "Source → Figma primitives" table is the format — name the *kind* of source construct, not the language syntax. The skill should work with any source the user can throw at it. Carve-out: `references/capture.md`'s CSS→Figma table is the single allowed CSS-property table — computed CSS is the one normalized form every rendered page reduces to regardless of authoring framework, not a source language; the rule still bans per-source-language (SwiftUI/Compose/Flutter) tables.
- **Helpers honor `FIGMA_CDP_PORT`.** New helpers must resolve the port in this order: `FIGMA_CDP_PORT` if set, then the browser's `DevToolsActivePort` file, then 9222. Never hardcode the port in a helper.
- **Eval helpers keep one output shape across backends.** A change to the CDP output of `figma_run.py` / `figma_batch_run.py` lands on the perch path too, with a case in `tests/perch_backend_test.py`.
- **`gotchas.md` uses WRONG/CORRECT pairs.** Each numbered gotcha earns its slot — only add ones that have actually bitten the skill. Nice-to-have caveats belong in the reference doc they're about, not in gotchas.
- **Worker Loop step descriptions stay explicit.** DISCOVER, READ, PLAN, EXECUTE, VERIFY+RETRY, CHECKPOINT, REPORT — each gets a real sentence describing what the worker actually does there. Telegraphic compression loses the imperatives that drive correct behavior.
- **No new references without table updates.** Any new `references/*.md` must land in `SKILL.md`'s references table with a distinct "load for" description. Orphans get pruned.
- **No backwards-compat shims.** If a file's shape changes, update every caller. Don't ship deprecated aliases or "kept for compatibility" sections.
- **`tests/evals.json` assertions are state-only.** Don't add transcript-introspection assertions ("worker reads state before modifying") — the eval framework can't observe agent behavior, only the resulting Figma state.

## Ceiling — what's out of scope

- **Live UI overlays in Figma.** Would need a real Figma plugin, not Plugin API via CDP. The Plugin API runs server-side in Figma's sandbox; it can mutate the document but can't render arbitrary UI in the user's viewport.
- **REST writes other than comments.** No current need; comments are the only POST. Other writes go through the Plugin API.
- **Sub-second design event streams.** Polling `window.__figmaEvents` at 1-2s is the floor — `agent-browser` cold-start makes anything faster wasteful. For real-time observation, the injected listeners buffer into a ring that consumers read non-destructively via per-consumer cursors (never drained — see `references/execution.md`).
- **Bypassing Chrome 136+'s default-profile restriction.** Mode B's profile-copy dance is the documented workaround; we don't try to defeat the security hardening any further.
- **Port discovery beyond `DevToolsActivePort` in Mode A.** Chrome assigns a new debugging port each launch; the helpers handle that by falling back to the `DevToolsActivePort` file when `FIGMA_CDP_PORT` is unset. Anything past that file — scanning Chrome processes, probing ports — is out of scope; the docs spell out the fallback's limits.
- **A test harness for `tests/evals.json`.** The file is currently a hand-verifiable spec, not an automated test suite. Building a runner is separate work.
- **Recursing into cross-origin iframes during live-page capture.** Would need CDP frame-target routing beyond the agent-browser surface we depend on; cross-origin iframes are captured as named placeholder frames only.
- **Native-fidelity accessibility capture.** The walker emits a semantic layer (`role`/`axName`/`interactable`) computed in-page, which drives layer naming and component instantiation; a native `Accessibility.getFullAXTree` join over the agent-browser CDP surface is the documented accuracy upgrade (`references/capture.md` → Semantic layer), not built in v1.
