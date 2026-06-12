# Connection

Coordinator-facing setup: how to connect to Figma's Plugin API via `agent-browser`. Workers receive a working connection and never run these steps.

## Quick start

1. **Test existing connection**: skip the rest if `typeof figma` returns `"object"`:
   ```bash
   agent-browser --cdp "${FIGMA_CDP_PORT:-9222}" eval "typeof figma" 2>/dev/null && echo "connected"
   ```

2. **Connect to Chrome.** Two paths — try Mode A first.

   ### Mode A — Attach to your running Chrome (recommended)

   No relaunch, no profile copy, no flags. Works with your already-logged-in Figma session.

   1. In your normal Chrome window, open `chrome://inspect/#remote-debugging` once and enable "Discover network targets". Chrome now exposes CDP on a local port for the lifetime of the browser session.
   2. Find the port (Chrome writes it on launch):
      ```bash
      cat "$HOME/Library/Application Support/Google/Chrome/DevToolsActivePort" | head -1
      # Linux:   ~/.config/google-chrome/DevToolsActivePort
      # Brave:   ~/Library/Application Support/BraveSoftware/Brave-Browser/DevToolsActivePort
      # Canary:  ~/Library/Application Support/Google/Chrome Canary/DevToolsActivePort
      ```
   3. Use that port in place of 9222 — e.g. if it printed `54321`, run `agent-browser --cdp 54321 eval "typeof figma"`.
   4. Optionally export the port for the helper scripts:
      ```bash
      export FIGMA_CDP_PORT=54321
      ```
      Both `figma_run.py` and `figma_batch_run.py` read `FIGMA_CDP_PORT` when set; when unset they fall back to reading `DevToolsActivePort` themselves (then 9222). So the export is optional for the helpers — but raw `agent-browser` one-liners don't do the fallback, so they still need the env var (or an explicit `--cdp <port>`).
   5. The first time the agent touches a tab, Chrome may show an "Allow debugging?" prompt. Accept once per tab.

   Trade-offs: requires the one-time toggle; the port changes between Chrome restarts (the helpers re-read `DevToolsActivePort` on their own; raw `agent-browser` one-liners need the new port re-read and re-exported). If you can't enable the toggle (managed Chrome, etc.), use Mode B.

   ### Mode B — Launch a dedicated Chrome Canary (fallback)

   Chrome 136+ refuses `--remote-debugging-port` on the default user-data-dir (security hardening; stops malicious pages from connecting to a logged-in session), so you must pass `--user-data-dir`. To preserve your Figma login, copy your default Canary profile right before launching:
   ```bash
   rm -rf /tmp/canary-cdp && \
     cp -R "$HOME/Library/Application Support/Google/Chrome Canary" /tmp/canary-cdp
   ```
   Launch against the copy:
   ```bash
   /Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary \
     --remote-debugging-port=9222 \
     --user-data-dir=/tmp/canary-cdp \
     '--remote-allow-origins=*' \
     "FIGMA_URL_HERE" &
   ```
   Wait for CDP to be ready before the first eval (Chrome opens the port before it's actually answering):
   ```bash
   for i in $(seq 1 60); do
     curl -sf http://127.0.0.1:9222/json/version > /dev/null && break
     sleep 0.5
   done
   curl -sf http://127.0.0.1:9222/json/version > /dev/null \
     || { echo "CDP never came up on 9222" >&2; exit 1; }
   ```
   Without the post-loop check, a 30s timeout exits cleanly and the next `agent-browser` call fails with an opaque CDP error.
   Why these flags:
   - `--user-data-dir`: Chrome 136+ won't expose CDP on the default profile path.
   - `--remote-allow-origins=*`: Chrome 111+ silently rejects CDP requests without this; the rejection presents as a 404 on `/json/version` even though the port is listening. Quote the flag to stop the shell from globbing the `*`.
   - Profile copy: preserves your Figma cookies so you don't have to re-log-in.

   Re-copy each session. The copy is ~640M and goes stale over time (Chrome appears to rotate keys in the live profile, after which the copy stops being accepted). Stale-copy symptoms: `agent-browser --cdp 9222` reports "EOF while parsing" and `curl http://localhost:9222/json/version` returns an empty body / 404. Fix: kill Canary, re-copy, relaunch.

   No saved Figma login? Use a fresh profile dir and log in once:
   ```bash
   rm -rf /tmp/canary-fresh
   /Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary \
     --remote-debugging-port=9222 \
     --user-data-dir=/tmp/canary-fresh \
     --no-first-run --no-default-browser-check \
     '--remote-allow-origins=*' \
     "https://www.figma.com" &
   ```

3. **Copy the helpers to `/tmp/`**: `figma_run.py` (single eval) and `figma_batch_run.py` (multiple evals in one CLI invocation). Both read `FIGMA_CDP_PORT` (default 9222), base64-encode the JS, and shell out to `agent-browser eval -b` / `agent-browser batch`.

   Install `agent-browser` once: `npm i -g agent-browser && agent-browser install`.

## Troubleshooting

If `typeof figma` returns `"undefined"`:
1. Ensure user has **edit permissions** (or create a branch).
2. Wait for page to fully load, retry.
3. Have user **open and close any plugin** to initialize the Plugin API, retry. (`window.figma` is a guarded getter that returns undefined until a plugin run populates its backing store. The plugin can be anything: first available in the menu is fine.)

If `agent-browser --cdp 9222` fails to connect (Mode B):
1. Check that CDP responds: `curl -s http://localhost:9222/json/version | head -2`. Expected: JSON starting with `"Browser": "Chrome/..."`. An empty body / 404 means Chrome's listening but disallowing CDP routes — usually a stale profile copy or a missing `--remote-allow-origins=*` flag. Re-copy the profile and relaunch.
2. Close other Chrome instances holding port 9222.
3. Prefer Chrome Canary to avoid conflicts with your regular Chrome.

If Mode A attach fails:
1. Confirm the toggle is enabled at `chrome://inspect/#remote-debugging`.
2. Re-read `DevToolsActivePort` — the port changes on every Chrome restart.
3. If the "Allow debugging?" modal didn't appear, try clicking the Figma tab to bring it foreground, then retry.
