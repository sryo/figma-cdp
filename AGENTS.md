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
├── AGENTS.md             # this file — architecture + invariants
├── CLAUDE.md             # pointer to AGENTS.md
├── README.md             # human-facing intro + install
├── references/           # task-shaped reference files (loaded on demand)
└── tests/evals.json      # state-only assertions for hand-verifying behavior
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

**Coordinator vs worker.** The coordinator inspects, decomposes, dispatches, and verifies. Workers execute one self-contained spec and emit a status. Operational thresholds (when to inline vs dispatch, complexity caps per worker, the four statuses) live in `SKILL.md` and `figma-worker.md` — single source of truth.

**Token-cost tiers.** `SKILL.md` is loaded into every conversation that triggers the skill; every line is per-conversation cost. `figma-worker.md` plus its inlined references are loaded into every spawned worker; per-dispatch cost. Other `references/*.md` files load on demand.

**Connection modes.** Mode A is attach to your running Chrome via the `chrome://inspect/#remote-debugging` toggle — preferred, uses the real logged-in Figma session, no profile copy. Mode B is launch a dedicated Chrome Canary with `--remote-debugging-port` and a profile copy — fallback for managed Chrome where the toggle is blocked. Chrome 136+ refuses `--remote-debugging-port` on the default user-data-dir (security hardening), which is what forces Mode B's profile-copy gymnastics. `FIGMA_CDP_PORT` env var binds both helpers to whichever port the chosen mode is using. The setup procedure for both modes lives in `references/connection.md`.

## Reference file organization

- **Always-load with workers:** `conventions.md`, `gotchas.md`.
- **Task-shaped on-demand:** `building.md`, `copy.md`, `reading.md`, `execution.md`, `rest-api.md`.
- **Coordinator-only setup:** `connection.md` (Mode A attach, Mode B Canary launch, troubleshooting) — loaded during setup; workers receive a working connection.
- **API reference split 5 ways** so workers load only what their task touches: `api-reference.md` (universal core), `api-text.md`, `api-layout.md`, `api-components.md`, `api-styling.md`. Per-file "load for" descriptions live in `SKILL.md`'s references table.

Don't add a reference file unless it would otherwise live as a too-large section in another file. Cross-link aggressively before splitting.

## `agent-browser` dependency

`agent-browser` (vercel-labs) is a Rust CLI that wraps Chrome DevTools Protocol. We shell out to it rather than talking CDP ourselves because the binary handles WebSocket lifecycle, base64 input, exit-code propagation, and target routing cleanly. We pay ~200ms cold-start per invocation; `figma_batch_run.py` amortizes that across N sequential evals via the `batch` subcommand.

The only subcommands we depend on:
- `eval -b <base64>` — run a JS script in the page
- `batch --json "<cmd1>" "<cmd2>" ...` — run multiple commands in one CLI invocation, results as a JSON array
- `screenshot <path>` — full-page PNG capture
- `--cdp <port>` — target port (default 9222, overridden by `FIGMA_CDP_PORT`)

If any of these break, that's the integration boundary to fix. The other ~140 agent-browser subcommands are irrelevant to this skill.

## Rules for changes

- **SKILL.md is always-loaded.** Every line is per-conversation token cost. Add only what every coordinator needs.
- **figma-worker.md is per-dispatch.** Every line is per-worker token cost. Compress hedging and meta-narration; preserve imperatives (READ before doing, find before creating, fix only what failed, don't rebuild).
- **References stay task-shaped.** Don't merge files because they're conceptually related. Don't split files because they're long — split only when independent tasks would load disjoint subsets.
- **Source-language framing stays generic.** Don't add per-language mapping tables (SwiftUI / Compose / Flutter / etc.). The `conventions.md` → "Source → Figma primitives" table is the format — name the *kind* of source construct, not the language syntax. The skill should work with any source the user can throw at it.
- **Helpers honor `FIGMA_CDP_PORT`.** New helpers must resolve the port in this order: `FIGMA_CDP_PORT` if set, then the browser's `DevToolsActivePort` file, then 9222. Never hardcode the port in a helper.
- **`gotchas.md` uses WRONG/CORRECT pairs.** Each numbered gotcha earns its slot — only add ones that have actually bitten the skill. Nice-to-have caveats belong in the reference doc they're about, not in gotchas.
- **Worker Loop step descriptions stay explicit.** READ, PLAN, EXECUTE, VERIFY+RETRY, CHECKPOINT, REPORT — each gets a real sentence describing what the worker actually does there. Telegraphic compression loses the imperatives that drive correct behavior.
- **No new references without table updates.** Any new `references/*.md` must land in `SKILL.md`'s references table with a distinct "load for" description. Orphans get pruned.
- **No backwards-compat shims.** If a file's shape changes, update every caller. Don't ship deprecated aliases or "kept for compatibility" sections.
- **`tests/evals.json` assertions are state-only.** Don't add transcript-introspection assertions ("worker reads state before modifying") — the eval framework can't observe agent behavior, only the resulting Figma state.

## Ceiling — what's out of scope

- **Live UI overlays in Figma.** Would need a real Figma plugin, not Plugin API via CDP. The Plugin API runs server-side in Figma's sandbox; it can mutate the document but can't render arbitrary UI in the user's viewport.
- **REST writes other than comments.** No current need; comments are the only POST. Other writes go through the Plugin API.
- **Sub-second design event streams.** Polling `window.__figmaEvents` at 1-2s is the floor — `agent-browser` cold-start makes anything faster wasteful. For real-time observation, write listeners that buffer into a ring and drain on a sensible cadence.
- **Bypassing Chrome 136+'s default-profile restriction.** Mode B's profile-copy dance is the documented workaround; we don't try to defeat the security hardening any further.
- **Port discovery beyond `DevToolsActivePort` in Mode A.** Chrome assigns a new debugging port each launch; the helpers handle that by falling back to the `DevToolsActivePort` file when `FIGMA_CDP_PORT` is unset. Anything past that file — scanning Chrome processes, probing ports — is out of scope; the docs spell out the fallback's limits.
- **A test harness for `tests/evals.json`.** The file is currently a hand-verifiable spec, not an automated test suite. Building a runner is separate work.
