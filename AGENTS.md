# figma-cdp

Architecture and invariants for the figma-cdp Claude Code skill.

figma-cdp drives Figma's Plugin API (`figma.*` global) from outside Figma — code → mockup, the reverse direction of Figma MCP. It reaches a browser tab open on a Figma file through perch (AppleScript, the default on a Mac) or the `agent-browser` CLI over Chrome DevTools Protocol. The current runtime surface is `SKILL.md`; this file is the design doc anyone reads when modifying the skill itself.

## Layout

```
.
├── SKILL.md              # runtime entry — Claude reads this when the skill triggers
├── figma-worker.md       # worker template the coordinator dispatches via the Agent tool
├── figma_run.py          # one eval (-e inline, file or stdin; --lib; --screenshot) → perch or agent-browser eval
├── figma_batch_run.py    # N evals in order in one call → one perch request or one agent-browser batch
├── figma_lib.js          # resident helpers the helpers' --lib prepends: window.__fx (recon, inventory, frame/text/instance/bindFill, audit), once per tab, version-stamped
├── figma_perch.mjs       # perch backend for the helpers and figma_capture.py: list_tabs → eval_js {world:"main"}, no CDP; `serve` keeps it warm behind a unix socket
├── figma_capture.py      # live-URL → Figma: `walk <url>` (own tab → /tmp JSON) and `import <spec>` (Figma tab: reset, assets streamed in pieces, node chunks through figma_importer.js); cdp or perch
├── figma_walker.js       # DOM walker run by `walk` — emits the capture envelope (layout-space geometry, sparse styles, assets)
├── figma_importer.js     # runs once per node chunk in the default session — chunk → Figma nodes
├── figma_source.py       # source files → cited manifest (tokens, colors, scales, copy, variants, states, components) — references/fidelity.md
├── figma_fidelity.py     # manifest + rootId → gap report from one eval through figma_run.py; exit 0 when the check ran, 2 when it couldn't
├── AGENTS.md             # this file — architecture + invariants
├── CLAUDE.md             # pointer to AGENTS.md
├── README.md             # human-facing intro + install
├── references/           # task-shaped reference files (loaded on demand)
└── tests/
    ├── capture_fixture.html  # static page exercising the walker's schema end to end — `walk` it to hand-verify a spec
    ├── figma_stub.js         # stub Plugin API (node tree, components/variants/instances, variables, sandbox ordering rules) shared by the offline tests
    ├── figma_lib_test.js     # `node --test tests/figma_lib_test.js`: every figma_lib.js helper against figma_stub.js, plus its version pin
    ├── importer_stub.js      # `node tests/importer_stub.js <spec.json> [--componentize]` — replays `figma_capture.py import --dry-run` against figma_stub.js, no Figma tab needed
    ├── importer_test.py      # `python3 tests/importer_test.py`: import sizing, constraints and componentize over capture_spec.json (hand-built spec of capture_fixture.html), offline
    ├── walker_live_test.py   # `FIGMA_LIVE=1 python3 tests/walker_live_test.py`: figma_walker.js in a real background tab on svg_paint_fixture.html (SVG paints only the page resolves)
    ├── capture_spec.json     # hand-built capture spec of capture_fixture.html for importer_test.py
    ├── perch_backend_test.py # `python3 tests/perch_backend_test.py`: the helpers, --lib, figma_fidelity.py and figma_capture.py on the perch backend (daemon and one-shot) against perch_stub/, and cdp vs perch output through agent_browser_stub/, offline
    ├── agent_browser_stub/   # stand-in agent-browser CLI (eval -b, batch --json) that runs scripts against perch_stub's `figma`, for the cdp branch offline
    ├── source_test.py        # `python3 tests/source_test.py`: figma_source.py on the eval fixture app and on small generic sources
    ├── fidelity_test.py      # `python3 tests/fidelity_test.py`: figma_fidelity.py on good and bad login builds (fidelity_login.js) through the perch stub
    ├── fidelity_elements_test.py # `python3 tests/fidelity_elements_test.py`: figma_fidelity.py --elements on capture_spec.json built on the stub, with injected faults (move, resize, recolor, retype, remove, extra layer, spacing)
    ├── pixels_test.py        # `python3 tests/pixels_test.py`: figma_fidelity.py --pixels: the stdlib PNG codec and the unexplained-region residual on hand-made images
    ├── api/                  # the Plugin API surface: `figma_api.mjs lookup "<error, CSS property or words>"` ranks typings members ([ro], deprecated, docs link, covered by the skill or not); `coverage <member>`; `diff <old> <new>` between two typings; `runtime <probe-result>` diffs probes/runtime_surface.js's live members against them; `surface` regenerates surface.json from the typings typings.lock pins
    ├── api_test.mjs          # `node --test tests/api_test.mjs`: the typings parser, coverage, lookup, and surface.json against typings.lock
    ├── api/drift.py          # `drift.py check` (offline-safe, for a schedule: is typings.lock the latest @figma/plugin-typings?) and `drift.py bump [<version>]` (diffs it against surface.json and opens a case)
    ├── drift_test.py         # `python3 tests/drift_test.py`: drift.py with a stand-in npm, and figma_api.mjs diff / runtime
    ├── probes/               # live Plugin API probes: `figma_probe.py --file <scratch> [<name>]` runs <name>.js guarded (scratch file only, denied members, __probe* swept before and after, under figma_lock) and checks its verdicts against <name>.json; `--record` writes verdicts/<member>-<date>.json. stub_citations.json: what showed each refusal figma_stub.js models
    ├── probe_test.py         # `python3 tests/probe_test.py`: figma_probe.py through the perch stub (guard, sweep, drift, record), case.py snapshot, and the stub citations
    ├── figma_lock.py         # the one flock every live dev entry point (run.py, probes, case repros) takes on the scratch file
    ├── cases/case.py         # failure cases: `new` (from the run journal), `triage`, `set`, `snapshot` (seed.json), `claim` (worktree + lease), `verify` (gates 1-6), `close` (ledger row), `list`, `stats` — Improving the skill
    ├── cases/snapshot.js, rebuild.js  # a subtree as a seed with ids remapped, and its rebuild on any file (scratch or stub)
    ├── cases_test.py         # `python3 tests/cases_test.py`: case.py and figma_lock.py offline
    ├── sleep/sleep.py        # the sleep pass: `mine` (transcripts + journals → signals), `digest` (clusters, ranked, known vs new vs relapse), `learn`, `replay` (lessons.jsonl), `check` (no-regression gates); AGENTS.md → Sleep pass
    ├── sleep/lessons.jsonl   # what earlier sleeps consolidated, as checks: an error text both helpers must hint, a rule a doc must keep
    ├── sleep_test.py         # `python3 tests/sleep_test.py`: sleep.py on hand-written transcripts, and the repo's lessons replayed
    ├── judge_guard.py        # `judge_guard.py [main..HEAD]`: fails a commit that changes the skill and edits an existing judge (scorers, tasks, lib.js, compare.py, gate.py, noise.json, baseline.json, probe expectations) without a `Judge-Change:` line
    ├── gates_test.py         # `python3 tests/gates_test.py`: compare.py's gate flags, process metrics, affects.json, the judge guard, and `case.py verify` end to end on stand-ins
    ├── snapshot_test.js      # `node --test tests/snapshot_test.js`: snapshot → rebuild → snapshot round-trips on the stub
    ├── ledger/               # one JSON per closed case (class, signature, fix commit, repro); read before fixing a similar signature
    ├── known_losses.json     # capture losses capture.md already documents; case.py refuses them as new cases
    ├── budget_test.py        # `python3 tests/budget_test.py`: byte caps on SKILL.md, figma-worker.md and each per-task reference combo
    ├── bench_backends.py     # read-only timing of cdp vs perch (daemon and one-shot) on one open file
    ├── perch_stub/           # stand-in perch server.js: runs eval_js scripts in Node against a stub `figma` (PERCH_STUB_FIGMA=full: figma_stub.js)
    └── eval/                 # behavior evals: headless sessions on a scratch Figma file, scored on the resulting state
        ├── run.py            # `run.py --file <url> [--skill-dir <worktree>] [--tasks a,b] [--reps N] [--out f]` → per-task medians
        ├── gate.py           # `gate.py [baseline.json] <candidate.json>`: the live-run gate. Both runs in fium's format, then `~/Documents/fium/fium price compare` with noise.json and the Price: trailers since the baseline's rev; compare.py's verdict follows as a reference
        ├── noise.json        # fium noise: abs 1 on failed_tool_calls, unhinted_errors and lost_replies per task (a rise from 0); rel stays fium's 10% until an A/A run
        ├── compare.py        # `compare.py [baseline.json] <candidate.json> [--tasks] [--require t:m>=x] [--gain t:m>=x] [--flaky]` — exit 1 on any regression or unmet rule; `--fium <run>` writes the run in fium's format. The reference for one more live cycle
        ├── affects.json      # which tasks a change to each skill file can move (case.py verify's gate 5)
        ├── session.py        # the headless `claude -p` command pinned to one skill copy; `session.py probe` verifies it offline
        ├── offline_test.py   # `python3 tests/eval/offline_test.py`: seeds, scorers, run.py and compare.py with no Figma and no API
        ├── lib.js            # helpers every seed/scorer/op body runs with (quality metrics, builders)
        ├── tasks/            # <id>.json: prompt ({FILE_URL} {PAGE} {FIXTURE}), seed, score
        ├── seeds/ scorers/ ops/  # Plugin API bodies: seed a page, score it ({metrics, lower, passed}), set up / clean up
        ├── offline/          # hand-built good and bad end states per task, and a fake `claude` for run.py's offline test
        ├── fixtures/app/     # the source app the tasks build from (HTML/CSS tokens + components.jsx)
        └── fixtures/expect.json  # what the fixture renders (copy, token colors, rows, axes), checked against fixtures/app
```

## Architecture

```
Skill triggers on a Figma URL or build request → Claude reads SKILL.md →
coordinator reads the source → figma_source.py manifest → one recon eval
(figma_run.py --lib: __fx.recon + __fx.inventory) → component plan → runs small
work inline or dispatches workers via the Agent tool with figma-worker.md filled
in → each eval is one Bash call (figma_run.py / figma_batch_run.py -e, run from
the skill dir) → perch eval_js or agent-browser over CDP → Figma's Plugin API →
JSON return → final gate: __fx.audit + figma_fidelity.py against the manifest.
```

**Coordinator vs worker.** The coordinator inspects, decomposes, dispatches, and verifies. Workers execute one self-contained spec and emit a status. Operational thresholds (when to inline vs dispatch, complexity caps per worker) live in `SKILL.md`'s Work decomposition section; the four statuses live in `figma-worker.md` — single source of truth for each. One deliberate exception to dedup: `figma-worker.md` carries a cheat sheet (the `__fx` signatures from `references/execution.md` → Resident helper library, the variant recipe from `references/building.md`, five worker-critical gotchas from `references/gotchas.md`) and the verify snippet, so a worker needs no reference read before its first eval. Change those sources and the cheat sheet together.

**Token-cost tiers.** `SKILL.md` is loaded into every conversation that triggers the skill; every line is per-conversation cost. `figma-worker.md` plus the coordinator's filled slots ([Component plan], [Reuse] inventory lines, [Manifest] path) are loaded into every spawned worker; per-dispatch cost. Other `references/*.md` files load on demand, and workers read one only for an API the cheat sheet lacks.

**Helpers run in place.** The coordinator and workers call `python3 <skill-dir>/figma_*.py` from the skill's base directory (pre-allowed as `Bash(python3 *figma_*.py *)`); helpers find their siblings (`figma_perch.mjs`, `figma_lib.js`, `figma_walker.js`, `figma_importer.js`) through their own real path, so nothing is copied to `/tmp`. Scripts go inline with `-e`, so write-and-run is one turn.

**Connection modes.** Mode P (perch) is the default wherever perch is installed; SKILL.md's setup is one perch-first check and every CDP detail lives in `references/connection.md`. Mode A is attach to your running Chrome via the `chrome://inspect/#remote-debugging` toggle — preferred, uses the real logged-in Figma session, no profile copy. Mode B is launch a dedicated Chrome Canary with `--remote-debugging-port` and a profile copy — fallback for managed Chrome where the toggle is blocked. Chrome 136+ refuses `--remote-debugging-port` on the default user-data-dir (security hardening), which is what forces Mode B's profile-copy gymnastics. `FIGMA_CDP_PORT` env var binds both helpers to whichever port the chosen mode is using. Mode P skips CDP: `figma_run.py` / `figma_batch_run.py` hand scripts to `figma_perch.mjs`, which imports perch's `handleCall` and runs them with `eval_js {world:"main", awaitPromise:true}` over AppleScript, so Chrome never shows its remote-debugging prompt. The setup procedure for all three lives in `references/connection.md`.

## Reference file organization

- **Task-shaped on-demand:** `conventions.md` (value precedence, source → Figma tables, design defaults), `gotchas.md`, `building.md` (the one variant recipe), `copy.md`, `reading.md`, `execution.md`, `fidelity.md`, `capture.md`, `rest-api.md`.
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
- `list_tabs {urlContains}` to find the file's tab (a room's tab wins, then a tab its window shows, among duplicates; several files open and no `--file` is an `ambiguous_tab` error)
- `eval_js {world:"main", awaitPromise:true, script, target:{tabId}}`; the script (already in the helpers' parse-first wrapper, `AUTO_ASYNC`, identical on both backends: a program yields its completion value, a script with top-level `await` or `return` runs as an async body) is wrapped as `return await (0, eval)(<source>)`, and a throw is caught in-page and reported as `✗ Evaluation error: ...`. Requests carry the script text (`sources`), never file paths
- `screenshot {target, maxWidth:0, format:"png"}` for `figma_run.py --screenshot` (the tab must be the one its window shows)
- `new_tab {url}`, `wait {target, expression}` (readyState complete off the new tab's initial `about:blank`) and `close_tab {tabId}` for `figma_capture.py walk`
- the `buildKick` export (`buildMainKick` before perch 5725447), which marks a perch new enough to have `world:"main"`; the helpers accept either

Rooms (perch's `room:<name>:<id>` tabs, a Chromium in a VM over its DevTools endpoint) run with the Mac's windows minimized or its screen locked. A background room tab's timers aren't throttled, but it gets no `requestAnimationFrame`, so Figma never renders and `exportAsync` to PNG hangs; `figma_perch.mjs` sends `activate_tab` (CDP `Target.activateTarget` inside the room, no Mac focus) once per request on a room tab. `pickTab` prefers a room's tab on the file over a browser's, a timeout there gets no hidden-tab hint, and `tests/eval/run.py` defaults `--tab` to the file's one room tab. A room tab on Figma's sign-in page (perch's login-path test) stops the call with `signed_out` and the `rooms signin <name> <url>` command: when listing finds no room tab on the file, and when a pinned room tab's page is a sign-in page. It never falls back to a browser tab, so an unattended run fails loudly instead of landing on a window the locked screen stalls. `figma_run.py --where` prints the backend and tab a call uses.

On a `room:` tab, `figma_perch.mjs` checks `typeof figma` before a script. If it is undefined and the snapshot has an exact Tools button or tab, it opens and closes that control once, then checks again. It never runs a plugin or takes the Mac's foreground. If the control is absent, the existing plugin-open hint remains.

**Daemon.** A one-shot run pays node start, the perch import, osascript startup and `list_tabs` on every call (~650 ms). So the Python helpers talk to `node figma_perch.mjs serve <socket>` over a unix socket instead, starting it on first use:
- Socket: `$TMPDIR/figma-perch-<uid>/<hash>.sock`, dir 0700, socket 0600. The hash covers `PERCH_DIR` and the mtime and size of perch's `server.js` and of `figma_perch.mjs`, so an update gets a fresh daemon and the old one idles out. `FIGMA_PERCH_SOCK` overrides the path (tests).
- Start: under a `flock` on `<socket>.lock`, so concurrent first calls start one daemon. A socket nobody answers on is stale and replaced. The daemon's stderr goes to `<socket>.log`.
- Protocol: the daemon greets, the client sends one JSON line, the daemon answers one JSON line (the one-shot reply) and destroys the connection. A client that got no greeting falls back or starts a daemon, since nothing ran. Once a request went out, a lost reply gets one resend of the same request, and the page's ledger keeps a script from running twice: every script runs inside `RUN` (both helpers, identical) under a request id and its hash, and a resend answers from `window.__fxRuns` (the value, the error, or a running marker the helpers turn into a `--recover <id>` message). A second drop is an error. `--ns` makes the same wrapper call `__fx.stale` before the script and `__fx.presence` after it (figma_lib.js; `references/execution.md` → Concurrency safety).
- Tab cache: a call with a file key reuses the tab found for that key. The wrapper checks `location.href` still shows that file before running, and a cached tab that answers `stale_tab` is looked up again. Calls with no file key list tabs every time, so a second open file still gives `ambiguous_tab`.
- Exit: after `FIGMA_PERCH_IDLE` seconds without a call (default 600); `{"op":"stop"}` lets calls in flight finish first. `FIGMA_PERCH_DAEMON=0` turns the daemon off. A daemon that can't start (no node, an unwritable dir, perch failing to load) falls back to the one-shot run.
- The daemon's environment is the first caller's. Per-call settings go in the request (`file`, `FIGMA_PERCH_TAB` as `tab`).

Backend choice: `FIGMA_BACKEND=cdp|perch` wins; else `FIGMA_CDP_PORT` set means CDP; else perch when it is usable; else CDP. Output and exit codes match the CDP path, so callers never branch on the backend: `figma_run.py` prints one compact line of JSON on both (keys sorted, UTF-8, `1e-7`; its CDP branch re-prints agent-browser's indented result, since every result is re-read on each later turn), `figma_batch_run.py` as its CDP branch does (keys sorted, `\u` escapes, `origin` the full page URL), and integers past 2^53 come back as doubles. Errors keep perch's leading code (`timeout`, `stale_tab`, `tab_not_scriptable`, `no_tab`, `ambiguous_tab`, `no_perch`). A Plugin API error whose first line matches the helpers' `HINTS` table gets a `hint:` line with its fix (stderr for `figma_run.py`, under the error for `figma_batch_run.py`); both helpers carry the same table. `figma_batch_run.py --stop` sends perch `stop:true`; on CDP it runs the scripts one at a time to stop at the same point. An awaited eval gets `--timeout` seconds (else `FIGMA_TIMEOUT`, else 120), clamped to 1-300 and passed to perch as `eval_js {timeout}` in ms; a value that isn't a number is refused before anything runs. A perch older than that option (no `AWAIT_MAX_MS` export) gets no `timeout` and awaits its own 30s, and the timeout hint says to update it. The daemon client waits for a reply up to (timeout + 70s) per script plus 30s, above perch's own cap of the await plus reading a long result. The perch path needs no base64 ceiling. The capture fast-path (`figma_capture.py`) picks its backend the same way and carries its own copy of the helpers' daemon client (`tests/perch_backend_test.py` keeps the copies identical): `walk` is one `{op:"page", url, sources, settle}` request, which opens the URL with `new_tab` (a background tab), `wait`s for the load, runs the walker inline (no `eval`, so an eval-banning CSP still works) and `close_tab`s it; `import` is one `eval` request with `stop:true`, so the first failing eval ends the run as on CDP.

## Evals

`tests/eval/run.py` measures the skill end to end on a scratch Figma file that belongs to the evals. Per task rep, under a per-file `flock` in a fixed `/tmp/figma-eval-<uid>/` (never TMPDIR, which differs per session, so every caller queues on the same lock): setup resets the whole file (every page, variable collection and local style) and creates the page `eval/<task>/<n>`; the task's seed through this repo's `figma_run.py`; a headless `claude -p --output-format stream-json` session on the task prompt; the scorer against the page; the rep's pages removed unless `--keep`. The seeds, scorers (`lib.js`, which never uses the skill's own `figma_lib.js`) and `figma_run.py` always come from the repo running `run.py`, so a candidate skill can't move the goalposts.

- **One tab.** `run.py` refuses to start when several tabs show the file and no `--tab` is given: setup and the session could each land on a different tab, one of them out of date. Sessions get `FIGMA_BACKEND=perch` (no `FIGMA_CDP_PORT`) and cannot call `agent-browser`, so a perch failure is an error, never a CDP fallback into another browser's copy of the file or the user's other files.
- **Reparse, don't rerun.** `tests/eval/reparse.py <results.json> <transcripts>` recomputes the session metrics of a run kept with `--transcripts`, for a change to how a transcript is read.

- **Pinning the skill copy.** `session.py` wraps `--skill-dir` in a generated plugin (`figma-eval`, `skills/figma-cdp` → a symlink to the copy) passed with `--plugin-dir`, runs with `--setting-sources project` from an empty temp cwd (so `~/.claude/skills`, where the user's own `figma-cdp` and `figma-text` live, never loads) and `--strict-mcp-config`, and prefixes the prompt with `/figma-eval:figma-cdp` so the skill loads every run. `python3 tests/eval/session.py probe` checks it with the real CLI against a local fake Messages API: the only Figma skill listed is `figma-eval:figma-cdp`, and the skill body sent to the model carries a marker planted in a temp copy, by slash command and by the Skill tool.
- **Unattended.** `--permission-mode dontAsk` with Bash/Read/Write/Edit/Glob/Grep/Agent/Skill allowed; anything else is denied and counts as a failed tool call. Auth is the user's CLI login (or `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY`); env vars a host Claude Code session sets for its children are dropped.
- **Metrics.** Cost: `wall_s`, `tokens_total` and its parts, `cost_usd`, `turns`, `tool_calls`, `failed_tool_calls`, summed over the main session and its subagents (`modelUsage` and every assistant message in the stream: a turn is one model response, a worker's included). A metric a task lists as `saturated` (it scores the same on good and bad output) shows as `info` in `compare.py` and never counts. Quality: each scorer's task metrics (instances of seeded components, duplicates, variant axes, diffs fixed, ids preserved, no mutation...) plus `quality()` in `lib.js` on every build: `autoLayoutShare`, `absoluteStacks`, `sizingShare`, `constrainedAbsShare`, `instanceRatio`, `duplicateComponents`, `detachedLike`, `defaultNames`, and `boundPaintShare` / `hardcodedPaints` when the file has color variables (every seed adds the fixture's tokens as variables). `pass_rate` is the share of reps whose scorer passed.
- **Adding a task.** `tasks/<id>.json` with a prompt a user would type, a seed and a scorer, plus `offline/<id>_good.js` and `_bad.js` end states the scorer must tell apart in `offline_test.py`. A task with `"fixture": "<dir>"` derives its expectations from that fixture's markup and `tokens.css` (`tests/eval/source.py`); the older tasks read `fixtures/expect.json`, kept in step with `fixtures/app`.

## Improving the skill

When the skill fails, or a build doesn't match its source, the question is whether the skill could have done better (an API we didn't know, a wrong doc, a helper bug) or not (a Figma or plan limit, the environment). The loop turns each one into a case and decides that before anything is patched.

1. **Journal.** `figma_run.py` and `figma_batch_run.py` append every eval (script, result or error, hint) to `~/.figma-cdp/journal/<day>.jsonl`: outside the repo, kept 14 days, `FIGMA_CDP_JOURNAL=0` turns it off, `FIGMA_CDP_HOME` moves it. Eval reps keep their session's journal with the run (`--transcripts`), and the harness's own seed and scorer calls aren't journaled.
2. **File.** `python3 tests/cases/case.py new --last` (or `--rid <id>`, or `--symptom "..."` for a mismatch seen by eye, with `--expected "<src path:line>"`). The case lives in `~/.figma-cdp/inbox/<case>/`, since it quotes the user's files; only a minimized, sanitized repro enters the repo. Same signature as an open case or a ledger row → `dup`; a documented capture loss (`tests/known_losses.json`) is refused.
3. **Attribute**, in this order, first fit wins (`case.py triage` proposes from the deterministic signals and prints the rest):
   | Class | Decided by | Fix |
   |---|---|---|
   | `env` | a perch/browser error code, a missing font family, or no repro (deterministic replay; 0 of 3 reps for agent-level failures) | connection.md line or a hint, never a gotcha |
   | `harness` | the scorer disagrees with a manual read of the `--keep` page | scorer + `offline/` states; human review |
   | `source-extract` | `figma_source.py` output wrong or missing for the cited source | source/fidelity + their tests; generic framing |
   | `helper-bug` | a raw Plugin API script on a `__probe` page works where `__fx` or the importer fails | stub repro, offline test, fix |
   | `doc-wrong` | a probe contradicts a reference line or the stub | doc and stub together, citing the probe |
   | `api-unknown` | a member that does it exists (the typings, `references/api-*.md`), the skill doesn't use it, and a probe says it works | reference line; helper if it recurs; stub + test + probe |
   | `api-plan-limited` | the member exists and the scratch file's plan refuses it | "the free plan refuses X" plus a fallback; provisional |
   | `api-limit` | every route fails: the candidate members and the alternates (SVG, vector, image fill, a component swap) | "can't, do X instead"; the stub models it; Ceiling if architectural |
   | `agent-ignored-doc` | the recipe is documented and works, and the miss repeats in 2 of 3 reps | move it to the point of use: a hint, an audit line, a validating helper |
   A new typings release is its own case: `tests/api/drift.py bump` files it with the member diff; its fix regenerates `surface.json` and `typings.lock`, re-runs the probes (`figma_probe.py --record`, `--pin` for a verdict that moved, in a `Judge-Change:` commit) and updates the references a changed member touches.    For the api classes, start from `node tests/api/figma_api.mjs lookup "<error or symptom>"` (triage stores its top hits as `oracle`): a matching member the skill doesn't cover is an `api-unknown` lead, and `[ro]` predicts an ignored write. Probes go through `tests/probes/figma_probe.py` only: it refuses any file but the scratch one, lints the body against file-level and other-node APIs, holds `tests/figma_lock.py`, and sweeps every `__probe*` page, collection and style before and after, so name anything a probe makes `__probe…`. A probe's verdicts (`works`, `ignored`, `readonly`, `refused`, …) live in its `.json`; a stub refusal cites the probe that showed it in `stub_citations.json`. To reproduce a user-file failure on scratch, `case.py snapshot <case> --node <id> --file <url>` keeps the subtree as `seed.json`, and `tests/cases/rebuild.js` rebuilds it. Confirm the class with `case.py set <case> class=<class>`.
4. **Fix test-first.** `case.py claim <case>` makes `.claude/worktrees/case-<case>` on branch `case/<case>` (a 4 h lease; `--steal` after it). Commit the failing test first (offline if it can be, else a probe, else an eval task with good and bad offline states), then the fix. Generalize: no case-specific names, ids or copy in docs. `case.py verify <case> --file <scratch-url>` runs the gates, cheapest first, and stops at the first failure: (1) the offline suites, (2) `budget_test.py`, (3) the judge guard on every commit of the branch, (4) the case's probe, (5) `run.py` at 1 rep on the repro task plus the tasks `tests/eval/affects.json` maps the changed files to, (6) a paired base/candidate run at 3 reps, compared with `--flaky` and, for an eval repro, `--require <task>:pass_rate>=0.67 --gain <task>:pass_rate>=0.34`. Without `--file` it stops after gate 3 (exit 3); `--dry-run` prints the commands. Gates 5-6 spend money and hold the scratch lock for the length of the reps. Main is the installed skill (`~/.claude/skills/figma-cdp` links here), so nothing merges to main before the gates pass.
5. **Close.** `case.py close <case> --status merged --commit <sha> --reason "..."` writes `tests/ledger/<case>.json`; commit it with the fix. A case is `merged` only when the original symptom is gone, not just the minimized repro. `parked` / `wontfix` rows record why, so the next session doesn't retry the same hypothesis.

### Sleep pass

Cases start from one failure someone noticed. The sleep pass starts from everything the sessions since the last pass left behind (`docs/sleep-loop.md` has the design and its first findings). Run it after a working session or a live eval run, offline, never against a Figma tab:

1. `python3 tests/sleep/sleep.py mine` reads the Claude Code transcripts of figma-cdp, perch and avis (main sessions and subagents) and the eval journal since the last pass; `--source <run.py --transcripts dir>` mines one eval run instead.
2. `sleep.py digest --mark` clusters the signals and picks the top clusters by impact plus a few random new ones. `relapse` (a lesson's signature came back after it was learned) ranks first: the consolidated fix isn't working, so move it to the point of use.
3. Each pick goes through the case loop above, or straight to a test-first fix when the cause is plain: an error hint, a helper fix, a doc rule where the agent makes the call, an eval case, or a memory for a user correction. perch findings become proposals in perch's own repo.
4. `sleep.py learn` records each fix in `tests/sleep/lessons.jsonl` with its signature and evidence; `replay` (in the offline suites) keeps every lesson true afterwards, so a trimmed doc or a rewritten helper can't forget it. `learn` refuses a lesson whose fix hasn't landed, and one that only says X doesn't work: say what to do instead, or the claim outlives the fix.
   `sleep.py digest --stale` lists the hint rows and lessons that never fired across every source, with their file and line: candidates to prune, each with a lean live check of the task it serves.
5. `sleep.py check [--candidate <run.json>]` runs the offline suites, budget and replay, and `tests/eval/gate.py` (fium price compare) against the baseline when there is a live run. A change that doesn't pass is dropped, not forced in.

## Rules for changes

- **SKILL.md is always-loaded.** Every line is per-conversation token cost. Add only what every coordinator needs.
- **figma-worker.md is per-dispatch.** Every line is per-worker token cost. Compress hedging and meta-narration; preserve imperatives (READ before doing, find before creating, fix only what failed, don't rebuild).
- **References stay task-shaped.** Don't merge files because they're conceptually related. Don't split files because they're long — split only when independent tasks would load disjoint subsets.
- **Source-language framing stays generic.** Don't add per-language mapping tables (SwiftUI / Compose / Flutter / etc.). The `conventions.md` → "Source layout semantics → auto layout" table is the format — name the *kind* of source construct, not the language syntax. The skill should work with any source the user can throw at it. Carve-out: `references/capture.md`'s CSS→Figma table is the single allowed CSS-property table — computed CSS is the one normalized form every rendered page reduces to regardless of authoring framework, not a source language; the rule still bans per-source-language (SwiftUI/Compose/Flutter) tables.
- **Helpers honor `FIGMA_CDP_PORT`.** New helpers must resolve the port in this order: `FIGMA_CDP_PORT` if set, then the browser's `DevToolsActivePort` file, then 9222. Never hardcode the port in a helper.
- **Eval helpers keep one output shape across backends.** A change to the CDP output of `figma_run.py` / `figma_batch_run.py` lands on the perch path too, with a case in `tests/perch_backend_test.py`.
- **`gotchas.md` uses WRONG/CORRECT pairs.** Each numbered gotcha earns its slot — only add ones that have actually bitten the skill. Nice-to-have caveats belong in the reference doc they're about, not in gotchas.
- **Worker Loop step descriptions stay explicit.** DISCOVER, READ, PLAN, EXECUTE, VERIFY+RETRY, CHECKPOINT, REPORT — each gets a real sentence describing what the worker actually does there. Telegraphic compression loses the imperatives that drive correct behavior.
- **No new references without table updates.** Any new `references/*.md` must land in `SKILL.md`'s references table with a distinct "load for" description. Orphans get pruned.
- **No backwards-compat shims.** If a file's shape changes, update every caller. Don't ship deprecated aliases or "kept for compatibility" sections.
- **Eval scorers are state-only.** A scorer reads the Figma state a session left (and, for read-only tasks, its final answer); don't score transcript introspection ("worker reads state before modifying"). How the skill got there shows up in the cost metrics instead.
- **A skill change is done only when `tests/eval/gate.py <run.json>` (fium price compare, fium RULES K2–K4) shows no worse metric against `tests/eval/baseline.json`.** A `worse?` is a low-rep median past the noise band and still blocks; an accepted cost is a `Price:` trailer quoting the user (K4). Measure the change from a git worktree (`run.py --skill-dir <worktree>`, same file, model and reps as the baseline). Quality metrics may not drop at all; cost metrics (wall time, tokens, turns, tool calls) may not grow past the noise band (`noise.json`, else fium's 10%). When a change improves on the baseline, refresh `baseline.json` from that run in a commit of its own (fium K5). `tests/budget_test.py` caps the always-loaded bytes the same way: lower a cap when a change frees room.

## Ceiling — what's out of scope

- **Live UI overlays in Figma.** Would need a real Figma plugin, not Plugin API via CDP. The Plugin API runs server-side in Figma's sandbox; it can mutate the document but can't render arbitrary UI in the user's viewport.
- **REST writes other than comments.** No current need; comments are the only POST. Other writes go through the Plugin API.
- **Design event streams.** The only listener is figma_lib.js's REMOTE `nodechange` ring behind `__fx.stale`; the skill doesn't stream selection or document events to agents. Same-tab edits are all LOCAL, so workers' and the user's in-tab edits can't be told apart.
- **Bypassing Chrome 136+'s default-profile restriction.** Mode B's profile-copy dance is the documented workaround; we don't try to defeat the security hardening any further.
- **Port discovery beyond `DevToolsActivePort` in Mode A.** Chrome assigns a new debugging port each launch; the helpers handle that by falling back to the `DevToolsActivePort` file when `FIGMA_CDP_PORT` is unset. Anything past that file — scanning Chrome processes, probing ports — is out of scope; the docs spell out the fallback's limits.
- **Recursing into cross-origin iframes during live-page capture.** Would need CDP frame-target routing beyond the agent-browser surface we depend on; cross-origin iframes are captured as named placeholder frames only.
- **Native-fidelity accessibility capture.** The walker emits a semantic layer (`role`/`axName`/`interactable`) computed in-page, which drives layer naming and component instantiation; a native `Accessibility.getFullAXTree` join over the agent-browser CDP surface is the documented accuracy upgrade (`references/capture.md` → Semantic layer), not built in v1.
