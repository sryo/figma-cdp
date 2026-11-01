# Connection

Coordinator-facing setup: how the helpers reach Figma's Plugin API through [perch](https://github.com/sryo/perch), in a browser tab or a perch room. Workers receive a working connection and never run these steps. The helpers run in place from the skill directory (`<skill-dir>`); nothing is copied.

## Quick start

1. **Test existing connection**: skip the rest if this prints `"object"`:
   ```bash
   python3 <skill-dir>/figma_run.py --file "FIGMA_URL_HERE" -e 'typeof figma'
   ```

2. **Connect.** The helpers run scripts in your open Figma tab through perch's `eval_js {world:"main"}` over AppleScript (macOS): no debugging toggle, no port, no "Allow debugging?" prompt.

   1. Have perch at `~/.perch` (its installer's spot) or `~/Documents/perch` (or set `PERCH_DIR`), on a version with `eval_js` `world:"main"`, and its one-time setup done (Chrome: View > Developer > Allow JavaScript from Apple Events).
   2. Have Node 18+; it runs `figma_perch.mjs`, which sits next to the helpers.
   3. Test with the command in step 1. Expected `"object"`.

   The first call starts a small background helper (`figma_perch.mjs serve`) that keeps perch loaded, so later calls skip its start-up. It exits after 10 idle minutes (`FIGMA_PERCH_IDLE`, in seconds); `FIGMA_PERCH_DAEMON=0` runs every call on its own instead.

   `--file` takes the file URL or key (or set `FIGMA_FILE`); it is required when several Figma files are open, which fails with `ambiguous_tab` and lists them. The tab can stay in the background, except in Arc, where it must be the tab its window shows. Run scripts with `figma_run.py -e`. `figma_run.py --screenshot <png>` needs the tab to be the one its window shows. The capture fast-path (`figma_capture.py`) is in `references/capture.md`.

   ### A perch room (unattended runs)

   A perch room is a Chromium on its own profile in a VM, driven over its DevTools endpoint, with no window of yours involved. Its tab runs with your windows minimized or the screen locked, so prefer it for unattended runs. The helpers show the tab inside the room before each call (no focus taken on the Mac): a background room tab's timers run, but it gets no animation frames, so Figma's PNG `exportAsync` would never settle. The user signs the room in to Figma once (`rooms signin <name> https://www.figma.com/login`); then open the file there: `new_tab {app:"room:<name>", url}` in perch, or `rooms` CLI.

   - Tabs are `room:<name>:<id>` (`list_tabs {app:"room"}`). With `--file`, a room's tab on the file wins over a browser's; `FIGMA_PERCH_TAB=room:<name>:<id>` pins one, and `tests/eval/run.py` takes the file's one room tab by default.
   - Which tab ran: `python3 <skill-dir>/figma_run.py --file <url> --where` prints `perch room:main:<id> (room main: runs minimized or locked) <url>`, or the browser tab and that it needs its window shown and the screen unlocked.
   - A room tab on Figma's sign-in page stops the call with `signed_out` and the `rooms signin` command, and nothing runs. It never falls back to a browser tab. `no_browser: room '<name>' is not up` means `rooms up <name>`.

## Troubleshooting

If `typeof figma` returns `"undefined"`:
1. Ensure user has **edit permissions** (or create a branch).
2. Wait for page to fully load, retry.
3. Have user **open and close any plugin** to initialize the Plugin API, retry. (`window.figma` is a guarded getter that returns undefined until a plugin run populates its backing store. The plugin can be anything: first available in the menu is fine.)

If text set in a local system font (SF Pro, a font installed on the Mac) measures 0 wide and the node reports `hasMissingFont`, though `listAvailableFontsAsync` lists the font and `loadFontAsync` resolves: the browser hasn't granted figma.com its local-fonts permission. Have the user allow Local fonts in the site settings for figma.com, then reload the tab (a second reload may be needed). Check with one text node: `width > 0` and `hasMissingFont === false`.

If a call fails, the error keeps perch's code:
- `no_perch`: no `server.js` at `PERCH_DIR`, or a perch without `eval_js` `world:"main"`; update perch.
- `no_tab` / `ambiguous_tab`: open the file in Chrome, or pass `--file`.
- `timeout`: an awaited eval runs at most 100s by default; pass `--timeout <seconds>` to either helper (or set `FIGMA_TIMEOUT`), up to 300. A perch older than this awaits 30s whatever you ask; update it. In a background tab, `figma.loadAllPagesAsync()` on a many-page file can stall; read `figma.currentPage` or `getNodeByIdAsync`, or show the tab in its window.
- `tab_not_visible` (screenshot only): the tab isn't the one its window shows.
- `signed_out` / `no_browser: room`: the room needs the user; nothing ran.
- `figma is undefined in this tab`: on a room tab the helper first tries an exact Tools control once; if that control is unavailable, open and close any plugin once, as above.
- `stale_tab: ... no longer shows file`: the tab moved to another file mid-batch; the rest of the batch didn't run.
- `perch_daemon: the daemon dropped the call`: the background helper died or went silent after taking the call, so the script may have run; check the file before running it again. Its log is next to its socket in `$TMPDIR/figma-perch-<uid>/`.
