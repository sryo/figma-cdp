# figma-cdp

Architecture and invariants for the figma-cdp Claude Code skill.

figma-cdp drives Figma's Plugin API (`figma.*` global) from outside Figma — code → mockup, the reverse direction of Figma MCP. It reaches a browser tab (or a perch room's tab) open on a Figma file through perch, over AppleScript on a Mac. The current runtime surface is `SKILL.md`; this file is the design doc anyone reads when modifying the skill itself.

## Test

```bash
python3 tests/sleep/sleep.py check
```

Every offline suite (`tests/cases/case.py` OFFLINE), the byte budget and the lessons replay, in under two minutes. No browser, perch or Figma: perch is stubbed under `tests/perch_stub`. Each file's docstring has its own usage.

## Architecture

```
Skill triggers on a Figma URL or build request → Claude reads SKILL.md →
coordinator reads the source → figma_source.py manifest → one recon eval
(figma_run.py --lib: __fx.recon + __fx.inventory) → component plan → runs small
work inline or dispatches workers via the Agent tool with figma-worker.md filled
in → each eval is one Bash call (figma_run.py -e, run from
the skill dir) → perch eval_js → Figma's Plugin API →
JSON return → final gate: __fx.audit + figma_fidelity.py against the manifest.
```

**Coordinator vs worker.** The coordinator inspects, decomposes, dispatches, and verifies. Workers execute one self-contained spec and emit a status. Operational thresholds (when to inline vs dispatch, complexity caps per worker) live in `SKILL.md`'s Work decomposition section; the four statuses live in `figma-worker.md` — single source of truth for each. One deliberate exception to dedup: `figma-worker.md` carries a cheat sheet (the `__fx` signatures from `references/execution.md` → Resident helper library, the variant recipe from `references/building.md`, five worker-critical gotchas from `references/gotchas.md`) and the verify snippet, so a worker needs no reference read before its first eval. Change those sources and the cheat sheet together.

**Token-cost tiers.** `SKILL.md` is loaded into every conversation that triggers the skill; every line is per-conversation cost. `figma-worker.md` plus the coordinator's filled slots ([Component plan], [Reuse] inventory lines, [Manifest] path) are loaded into every spawned worker; per-dispatch cost. Other `references/*.md` files load on demand, and workers read one only for an API the cheat sheet lacks.

**Helpers run in place.** The coordinator and workers call `python3 <skill-dir>/figma_*.py` from the skill's base directory (pre-allowed as `Bash(python3 *figma_*.py *)`); helpers find their siblings (`figma_backend.py`, `figma_perch.mjs`, `figma_lib.js`, `figma_walker.js`, `figma_importer.js`) through their own real path, so nothing is copied to `/tmp`. Scripts go inline with `-e`, so write-and-run is one turn.

**Connection.** perch is the only backend: `figma_run.py` hands scripts to `figma_perch.mjs`, which imports perch's `handleCall` and runs them with `eval_js {world:"main", awaitPromise:true}` over AppleScript, so no browser needs a debugging port or shows a remote-debugging prompt. A perch room's tab runs unattended (minimized or locked). The setup lives in `references/connection.md`.

## Reference file organization

- **Task-shaped on-demand:** `conventions.md` (value precedence, source → Figma tables, design defaults), `gotchas.md`, `building.md` (the one variant recipe), `copy.md`, `reading.md`, `execution.md`, `fidelity.md`, `capture.md`, `rest-api.md`.
- **Coordinator-only setup:** `connection.md` (perch, rooms, troubleshooting) — loaded during setup; workers receive a working connection.
- **API reference split 5 ways** so workers load only what their task touches: `api-reference.md` (universal core — including GeometryMixin fills/strokes and the hex helper, so solid color work needs no extra file), `api-text.md`, `api-layout.md`, `api-components.md`, `api-styling.md`. Per-file "load for" descriptions and the per-task combo list live in `SKILL.md`.

Don't add a reference file unless it would otherwise live as a too-large section in another file. Cross-link aggressively before splitting.

## perch

`figma_perch.mjs` imports `server.js` from `PERCH_DIR` (default `~/.perch`, then `~/Documents/perch`) and calls its exported `handleCall` in-process; no MCP session, no CDP. It depends on:
- `list_tabs {urlContains}` to find the file's tab (a room's tab wins, then a tab its window shows, among duplicates; several files open and no `--file` is an `ambiguous_tab` error)
- `eval_js {world:"main", awaitPromise:true, script, target:{tabId}}`; the script (already in the helpers' parse-first wrapper, `AUTO_ASYNC`: a program yields its completion value, a script with top-level `await` or `return` runs as an async body) is wrapped as `return await (0, eval)(<source>)`, and a throw is caught in-page and reported as `✗ Evaluation error: ...`. Requests carry the script text (`sources`), never file paths
- `screenshot {target, maxWidth:0, format:"png"}` for `figma_run.py --screenshot` (the tab must be the one its window shows)
- `new_tab {url}`, `wait {target, expression}` (readyState complete off the new tab's initial `about:blank`) and `close_tab {tabId}` for `figma_capture.py walk`
- the `buildKick` export (`buildMainKick` before perch 5725447), which marks a perch new enough to have `world:"main"`; the helpers accept either

Rooms (perch's `room:<name>:<id>` tabs, a Chromium in a VM over its DevTools endpoint) run with the Mac's windows minimized or its screen locked. A background room tab's timers aren't throttled, but it gets no `requestAnimationFrame`, so Figma never renders and `exportAsync` to PNG hangs; `figma_perch.mjs` sends `activate_tab` (CDP `Target.activateTarget` inside the room, no Mac focus) once per request on a room tab. `pickTab` prefers a room's tab on the file over a browser's, a timeout there gets no hidden-tab hint, and `tests/eval/run.py` defaults `--tab` to the file's one room tab. A room tab on Figma's sign-in page (perch's login-path test) stops the call with `signed_out` and the `rooms signin <name> <url>` command: when listing finds no room tab on the file, and when a pinned room tab's page is a sign-in page. It never falls back to a browser tab, so an unattended run fails loudly instead of landing on a window the locked screen stalls. `figma_run.py --where` prints the tab a call uses.

On a `room:` tab, `figma_perch.mjs` checks `typeof figma` before a script. If it is undefined and the snapshot has an exact Tools button or tab, it opens and closes that control once, then checks again. It never runs a plugin or takes the Mac's foreground. If the control is absent, the existing plugin-open hint remains.

**Daemon.** A one-shot run pays node start, the perch import, osascript startup and `list_tabs` on every call (~650 ms). So the Python helpers talk to `node figma_perch.mjs serve <socket>` over a unix socket instead, starting it on first use:
- Socket: `$TMPDIR/figma-perch-<uid>/<hash>.sock`, dir 0700, socket 0600. The hash covers `PERCH_DIR` and the mtime and size of perch's `server.js` and of `figma_perch.mjs`, so an update gets a fresh daemon and the old one idles out. `FIGMA_PERCH_SOCK` overrides the path (tests).
- Start: under a `flock` on `<socket>.lock`, so concurrent first calls start one daemon. A socket nobody answers on is stale and replaced. The daemon's stderr goes to `<socket>.log`.
- Protocol: the daemon greets, the client sends one JSON line, the daemon answers one JSON line (the one-shot reply) and destroys the connection. A client that got no greeting falls back or starts a daemon, since nothing ran. Once a request went out, a lost reply gets one resend of the same request, and the page's ledger keeps a script from running twice: every script runs inside `RUN` (both helpers, identical) under a request id and its hash, and a resend answers from `window.__fxRuns` (the value, the error, or a running marker the helpers turn into a `--recover <id>` message). A second drop is an error. `--ns` makes the same wrapper call `__fx.stale` before the script and `__fx.presence` after it (figma_lib.js; `references/execution.md` → Concurrency safety).
- Tab cache: a call with a file key reuses the tab found for that key. The wrapper checks `location.href` still shows that file before running, and a cached tab that answers `stale_tab` is looked up again. Calls with no file key list tabs every time, so a second open file still gives `ambiguous_tab`.
- Exit: after `FIGMA_PERCH_IDLE` seconds without a call (default 600); `{"op":"stop"}` lets calls in flight finish first. `FIGMA_PERCH_DAEMON=0` turns the daemon off. A daemon that can't start (no node, an unwritable dir, perch failing to load) falls back to the one-shot run.
- The daemon's environment is the first caller's. Per-call settings go in the request (`file`, `FIGMA_PERCH_TAB` as `tab`).

`FIGMA_BACKEND`, if set, must be `perch`: any other value exits before anything runs, so a caller who asked for CDP isn't moved to perch silently. `figma_run.py` prints one script's result as one compact line of JSON (keys sorted, UTF-8, `1e-7`, since every result is re-read on each later turn), and several scripts' results each under a `== <label> ==` header as `{"origin", "result"}` (keys sorted, `\u` escapes, `origin` the full page URL); integers past 2^53 come back as doubles. Errors keep perch's leading code (`timeout`, `stale_tab`, `tab_not_scriptable`, `no_tab`, `ambiguous_tab`, `no_perch`). A Plugin API error whose first line matches the helpers' `HINTS` table gets a `hint:` line with its fix (stderr for one script, under the error for several). `figma_run.py --stop` sends perch `stop:true`. An awaited eval gets `--timeout` seconds (else `FIGMA_TIMEOUT`, else 100), clamped to 1-300 and passed to perch as `eval_js {timeout}` in ms; a value that isn't a number is refused before anything runs. A perch older than that option (no `AWAIT_MAX_MS` export) gets no `timeout` and awaits its own 30s, and the timeout hint says to update it. The daemon client waits for a reply up to (timeout + 70s) per script plus 30s, above perch's own cap of the await plus reading a long result. The capture fast-path (`figma_capture.py`) talks to the same daemon, both through `figma_backend.py`: `walk` is one `{op:"page", url, sources, settle}` request, which opens the URL with `new_tab` (a background tab), `wait`s for the load, runs the walker inline (no `eval`, so an eval-banning CSP still works) and `close_tab`s it; `import` is one `eval` request with `stop:true`, so the first failing eval ends the run.

## Design sync

A repo's DESIGN.md (Google's format, github.com/google-labs-code/design.md) owns its tokens; code must match it and Figma variables mirror it. Nothing syncs itself: checks report, proposals wait for a person.
- `figma_source.py` reads DESIGN.md's YAML (front matter and ```yaml blocks) with its own parser for the subset the spec uses, so the skill keeps no dependency. Tokens cite `DESIGN.md:<line>`; broken `{group.token}` refs and duplicate keys go in the manifest's `design` entry.
- Themes are a convention on top of the spec, which has none: `themes: [light, dark]` (a list, so Google's linter doesn't flag it as an ignored token map) names them, the first is the base, and a token key ending `-<theme>` overrides its base key there. Free Figma has one mode per collection, so each theme is its own collection `<name>/<theme>` holding every token.
- `figma_source.py --check DESIGN.md <code>` matches code custom properties by name (`--<key>`, `--<group>-<key>`, `--<key>-<prop>`) and by theme (the enclosing block's prelude). The spec's `omitted:` key also lists code names or globs (`--a-*`) left out on purpose, and a token it also covers is reported. DESIGN.md colors keep their alpha (`#rrggbbaa` below opaque), so an alpha-only change is drift. `figma_fidelity.py --variables` diffs the inventory's VARS lines. The runtime doc is `references/fidelity.md` → DESIGN.md; SKILL.md carries one pointer.
- `figma_sync.py propose --to code` pushes only its own `design-sync/<date>` branch (or the open design-sync PR's) from a temporary worktree and runs `gh`; it never pushes the base, merges or force-pushes. `propose --to figma` writes `Proposed <date>` collections and a page, never the live collections, behind `saveVersionHistoryAsync`, plus one REST comment. `tests/sync_test.py` holds both to that with logging `git`/`gh` stand-ins.

## Evals

`tests/eval/run.py` measures the skill end to end on a scratch Figma file that belongs to the evals. Per task rep, under a per-file `flock` in a fixed `/tmp/figma-eval-<uid>/` (never TMPDIR, which differs per session, so every caller queues on the same lock): setup resets the whole file (every page, variable collection and local style) and creates the page `eval/<task>/<n>`; the task's seed through this repo's `figma_run.py`; a headless `claude -p --output-format stream-json` session on the task prompt; the scorer against the page; the rep's pages removed unless `--keep`. The seeds, scorers (`lib.js`, which never uses the skill's own `figma_lib.js`) and `figma_run.py` always come from the repo running `run.py`, so a candidate skill can't move the goalposts.

- **One tab.** `run.py` refuses to start when several tabs show the file and no `--tab` is given: setup and the session could each land on a different tab, one of them out of date. Sessions cannot call `agent-browser` (`--disallowedTools`), which would reach whichever Chrome has a debugging port and the user's own files there.
- **Reparse, don't rerun.** `tests/eval/reparse.py <results.json> <transcripts>` recomputes the session metrics of a run kept with `--transcripts`, for a change to how a transcript is read.
- **Choosing a live run** (fium RULES L1–L4). Live runs cost millions of tokens, so:
  - `run.py` (its CLI is `plan.py`) without `--tasks` runs only what `fium scope <baseline refresh>..HEAD --affects tests/eval/affects.json` says the change can move, and prints the tasks and the expected tokens at baseline medians before it starts (L1). An explicit `--tasks` wins.
  - SKILL.md and figma-worker.md move the trio (recon, effects, fidelity-edit); app-screens runs only when a case targets it. A file no rule matches runs everything.
  - A task's own judge files (its tasks/, scorers/ and seeds/ file and the fixture it reads) move only the tasks that use them, since reparse can't re-score a tree it never kept; a scorer change also refreshes that task's baseline, in its own commit, with a `Judge-Change:` line. Shared eval code (lib.js, source.py, run.py, fixtures/expect.json) moves every task.
  - Other tooling, tests and project docs map to `none` (`bench/inert` lists the files no run reads). Re-judge such a change offline: `reparse.py` on kept transcripts, then `gate.py` on the runs you have. `run.py` refuses to start a run for it.
  - 2 reps, a third only when they disagree; 3 to refresh a baseline (L2). Batch fixes into one run, read kept transcripts first, and give a routing-only change one smoke rep (L3). After 5 runs in a row with no keep, stop or change approach (L4).
  - `tests/token_estimate.py [<rev>]` prices a docs change before any run: always-loaded bytes / 4 x median turns over the mapped tasks.
  - State each run's expected tokens when asking for it, and never in dollars.

- **Pinning the skill copy.** `session.py` wraps `--skill-dir` in a generated plugin (`figma-eval`, `skills/figma-cdp` → a symlink to the copy) passed with `--plugin-dir`, runs with `--setting-sources project` from an empty temp cwd (so `~/.claude/skills`, where the user's own `figma-cdp` and `figma-text` live, never loads) and `--strict-mcp-config`, and prefixes the prompt with `/figma-eval:figma-cdp` so the skill loads every run. `python3 tests/eval/session.py probe` checks it with the real CLI against a local fake Messages API: the only Figma skill listed is `figma-eval:figma-cdp`, and the skill body sent to the model carries a marker planted in a temp copy, by slash command and by the Skill tool.
- **Unattended.** `--permission-mode dontAsk` with Bash/Read/Write/Edit/Glob/Grep/Agent/Skill allowed; anything else is denied and counts as a failed tool call. Auth is the user's CLI login (or `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY`); env vars a host Claude Code session sets for its children are dropped.
- **Metrics.** Cost: `wall_s`, `tokens_total` and its parts, `cost_usd`, `turns`, `tool_calls`, `failed_tool_calls`, summed over the main session and its subagents (`modelUsage` and every assistant message in the stream: a turn is one model response, a worker's included). A metric a task lists as `saturated` (it scores the same on good and bad output) is left out of `gate.py`'s fium export and never counts. Quality: each scorer's task metrics (instances of seeded components, duplicates, variant axes, diffs fixed, ids preserved, no mutation...) plus `quality()` in `lib.js` on every build: `autoLayoutShare`, `absoluteStacks`, `sizingShare`, `constrainedAbsShare`, `instanceRatio`, `duplicateComponents`, `detachedLike`, `defaultNames`, and `boundPaintShare` / `hardcodedPaints` when the file has color variables (every seed adds the fixture's tokens as variables). `pass_rate` is the share of reps whose scorer passed.
- **Adding a task.** `tasks/<id>.json` with a prompt a user would type, a seed and a scorer, plus `offline/<id>_good.js` and `_bad.js` end states the scorer must tell apart in `offline_test.py`. A task with `"fixture": "<dir>"` derives its expectations from that fixture's markup and `tokens.css` (`tests/eval/source.py`); the older tasks read `fixtures/expect.json`, kept in step with `fixtures/app`.

## Improving the skill

When the skill fails, or a build doesn't match its source, the question is whether the skill could have done better (an API we didn't know, a wrong doc, a helper bug) or not (a Figma or plan limit, the environment). The loop turns each one into a case and decides that before anything is patched.

1. **Journal.** `figma_run.py` appends every eval (script, result or error, hint) to `~/.figma-cdp/journal/<day>.jsonl`: outside the repo, kept 14 days, `FIGMA_CDP_JOURNAL=0` turns it off, `FIGMA_CDP_HOME` moves it. Eval reps keep their session's journal with the run (`--transcripts`), and the harness's own seed and scorer calls aren't journaled.
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
4. **Fix test-first.** `case.py claim <case>` makes `.claude/worktrees/case-<case>` on branch `case/<case>` (a 4 h lease; `--steal` after it). Commit the failing test first (offline if it can be, else a probe, else an eval task with good and bad offline states), then the fix. Generalize: no case-specific names, ids or copy in docs. `case.py verify <case> --file <scratch-url>` runs the gates, cheapest first, and stops at the first failure: (1) the offline suites, (2) `budget_test.py`, (3) the judge guard on every commit of the branch, (4) the case's probe, (5) `run.py` at 1 rep on the repro task plus the tasks `tests/eval/affects.json` maps the changed files to, (6) a paired base/candidate run at 3 reps, gated by `gate.py --tasks` and, for an eval repro, `--require <task>:pass_rate>=0.67 --gain <task>:pass_rate>=0.34`. Without `--file` it stops after gate 3 (exit 3); `--dry-run` prints the commands. Gates 5-6 spend tokens and hold the scratch lock for the length of the reps. Main is the installed skill (`~/.claude/skills/figma-cdp` links here), so nothing merges to main before the gates pass.
5. **Close.** `case.py close <case> --status merged --commit <sha> --reason "..."` writes `tests/ledger/<case>.json`; commit it with the fix. A case is `merged` only when the original symptom is gone, not just the minimized repro. `parked` / `wontfix` rows record why, so the next session doesn't retry the same hypothesis.

### Sleep pass

Cases start from one failure someone noticed. The sleep pass starts from everything the sessions since the last pass left behind (fium RULES.md S has the method). Run it after a working session or a live eval run, offline, never against a Figma tab:

1. `python3 tests/sleep/sleep.py mine` reads the Claude Code transcripts of figma-cdp, perch and avis (main sessions and subagents) and the eval journal since the last pass; `--source <run.py --transcripts dir>` mines one eval run instead.
2. `sleep.py digest --mark` clusters the signals and picks the top clusters by impact plus a few random new ones. `relapse` (a lesson's signature came back after it was learned) ranks first: the consolidated fix isn't working, so move it to the point of use.
3. Each pick goes through the case loop above, or straight to a test-first fix when the cause is plain: an error hint, a helper fix, a doc rule where the agent makes the call, an eval case, or a memory for a user correction. perch findings become proposals in perch's own repo.
4. `sleep.py learn` records each fix in `tests/sleep/lessons.jsonl` with its signature and evidence; `replay` (in the offline suites) keeps every lesson true afterwards, so a trimmed doc or a rewritten helper can't forget it. `learn` refuses a lesson whose fix hasn't landed, and one that only says X doesn't work: say what to do instead, or the claim outlives the fix.
   `sleep.py digest --stale` lists the hint rows and lessons that never fired across every source, with their file and line: candidates to prune, each with a lean live check of the task it serves.
5. `sleep.py check [--candidate <run.json>]` runs the offline suites, budget and replay, and `tests/eval/gate.py` (fium compare) against the baseline when there is a live run. A change that doesn't pass is dropped, not forced in.

## Rules for changes

- **SKILL.md is always-loaded.** Every line is per-conversation token cost. Add only what every coordinator needs.
- **figma-worker.md is per-dispatch.** Every line is per-worker token cost. Compress hedging and meta-narration; preserve imperatives (READ before doing, find before creating, fix only what failed, don't rebuild).
- **References stay task-shaped.** Don't merge files because they're conceptually related. Don't split files because they're long — split only when independent tasks would load disjoint subsets.
- **Source-language framing stays generic.** Don't add per-language mapping tables (SwiftUI / Compose / Flutter / etc.). The `conventions.md` → "Source layout semantics → auto layout" table is the format — name the *kind* of source construct, not the language syntax. The skill should work with any source the user can throw at it. Carve-out: `references/capture.md`'s CSS→Figma table is the single allowed CSS-property table — computed CSS is the one normalized form every rendered page reduces to regardless of authoring framework, not a source language; the rule still bans per-source-language (SwiftUI/Compose/Flutter) tables.
- **`gotchas.md` uses WRONG/CORRECT pairs.** Each numbered gotcha earns its slot — only add ones that have actually bitten the skill. Nice-to-have caveats belong in the reference doc they're about, not in gotchas.
- **Worker Loop step descriptions stay explicit.** DISCOVER, READ, PLAN, EXECUTE, VERIFY+RETRY, CHECKPOINT, REPORT — each gets a real sentence describing what the worker actually does there. Telegraphic compression loses the imperatives that drive correct behavior.
- **No new references without table updates.** Any new `references/*.md` must land in `SKILL.md`'s references table with a distinct "load for" description. Orphans get pruned.
- **No backwards-compat shims.** If a file's shape changes, update every caller. Don't ship deprecated aliases or "kept for compatibility" sections.
- **Eval scorers are state-only.** A scorer reads the Figma state a session left (and, for read-only tasks, its final answer); don't score transcript introspection ("worker reads state before modifying"). How the skill got there shows up in the cost metrics instead.
- **A skill change is done only when `tests/eval/gate.py <run.json>` (fium compare, fium RULES K2–K4) shows no worse metric against `tests/eval/baseline.json`.** A `worse?` is a low-rep median past the noise band and still blocks; an accepted cost is a `Price:` trailer quoting the user (K4). Measure the change from a git worktree (`run.py --skill-dir <worktree>`, same file, model and reps as the baseline). Quality metrics may not drop at all; cost metrics (wall time, tokens, turns, tool calls) may not grow past the noise band (`noise.json`, else fium's 10%). When a change improves on the baseline, refresh `baseline.json` from that run in a commit of its own (fium K5). `tests/budget_test.py` caps the always-loaded bytes the same way: lower a cap when a change frees room.

## Ceiling — what's out of scope

- **Live UI overlays in Figma.** Would need a real Figma plugin, not the Plugin API driven from outside. The Plugin API runs server-side in Figma's sandbox; it can mutate the document but can't render arbitrary UI in the user's viewport.
- **REST writes other than comments.** No current need; comments are the only POST. Other writes go through the Plugin API.
- **Design event streams.** The only listener is figma_lib.js's REMOTE `nodechange` ring behind `__fx.stale`; the skill doesn't stream selection or document events to agents. Same-tab edits are all LOCAL, so workers' and the user's in-tab edits can't be told apart.
- **Hosts other than a Mac.** perch drives browsers over AppleScript, so the skill runs on a Mac (a perch room runs in a VM there).
- **Recursing into cross-origin iframes during live-page capture.** Would need DevTools frame-target routing, which perch's AppleScript path lacks; cross-origin iframes are captured as named placeholder frames only.
- **Native-fidelity accessibility capture.** The walker emits a semantic layer (`role`/`axName`/`interactable`) computed in-page, which drives layer naming and component instantiation; a native `Accessibility.getFullAXTree` join over a DevTools connection is the documented accuracy upgrade (`references/capture.md` → Semantic layer), not built in v1.
