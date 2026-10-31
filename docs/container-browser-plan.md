# Container browser: analysis and plan

Status: analysis only, nothing implemented. §0 records the user's answers and supersedes the recommendations in §2-§5. 2026-10-31, Apple M4 MacBook Air, macOS 27.2 (26B123).

The question: would a Chrome inside an Apple `container` VM, seeded with the user's local session, let figma-cdp and perch keep working while the Mac is locked or the browser is minimized?

## 0. Revision after the user's answers (2026-10-31): supersedes the recommendations in §2, §3 and §5

**The user's answers:**
1. Keep one server. A sibling with the same tools is waste. The current goals are liked, but negotiable.
2. All accounts, the main ones: Figma, and trabagitos's many sites, which are already signed in on the primary profile.
3. It must reach the user's files (Instagram story uploads, a CV for job applications).
4. Two modes only: unlocked and in use, with no focus taken; or locked, plugged in, lid open.

**What this rules out.** Every route that uses a separate profile (rung 1's agent Chrome, rung 2's container):
- they would need a fresh sign-in on every site;
- the container can't see the user's files without mounting them;
- they need either a second server or a second browser kind with its own sign-ins.

Copying the primary profile's cookies into such a browser is also out (§4, §9). They stay below as considered options, not the plan.

**New recommendation: drive the user's own Canary profile, and add CDP as a second transport into the same browser.**
- **Rung 0** stays first. It is the three anti-throttling flags, which fix the timer stall.
- **New rung 1** is Chrome's consent-gated remote debugging on the running browser, which works on the default profile:
  - The user turns it on once at `chrome://inspect/#remote-debugging`, on Chrome 144 or later. Chrome then writes `DevToolsActivePort` in the user's own data dir. A client reads it and connects. Chrome asks the user "Allow?" for the connection and shows an "automated test software" banner while it lasts. Sources:
    - chrome-devtools-mcp `docs/configuration.md:67-68` and `docs/advanced-usage.md:92` ("connect to the default profile ... access to all open windows");
    - `src/BrowserManager.ts:384-405` (reads `<userDataDir>/DevToolsActivePort` and connects to `ws://127.0.0.1:<port><path>`);
    - https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session (M144, the per-connection dialog and the banner). All [H], ChromeDevTools/chrome-devtools-mcp@8d009e8.
  - The Chrome 136 block covers only the `--remote-debugging-port/-pipe` *switches* on the default data dir (https://developer.chrome.com/blog/remote-debugging-port). The consent toggle is the sanctioned route around it.
  - **figma-cdp already documents this as Mode A** (`references/connection.md:27-47`).
  - On this Mac, Canary is 159.0.8133.0, and `~/Library/Application Support/Google/Chrome Canary/DevToolsActivePort` exists (mtime 2026-10-30 16:11). So the toggle appears to be on already. I only checked that the file exists; I didn't read it and didn't connect.
- **Why this fits all four answers:**
  - **Same profile:** every account and the files are there.
  - **Same server:** CDP becomes a perch transport behind the existing tools, at 0 schema bytes.
  - **Same tab:** a per-action fallback is honest now. §5's objection was that a container tab is a different page; here it is the same page. A host action that's refused (trusted click while locked, screenshot while minimized) can be retried over CDP on that same target.
  - **No focus taken:** CDP `Input.*` events go to the renderer, not through the WindowServer, so the cursor doesn't move and no app activates [4 §2, H]. `Page.bringToFront` and `Target.activateTarget` must be refused.
- **Unverified, and the reason the experiments below exist [L]:**
  - Do CDP input and `Page.captureScreenshot` work on a minimized, locked or display-asleep Canary window? Commands that need a frame can stall in backgrounded pages. Rung 0's `--disable-backgrounding-occluded-windows` keeps the page visible, which may be what makes them work.
  - Does the "Allow?" dialog take focus?
  - Does the toggle survive a Canary relaunch?
  - Is the dialog per connection or per tab? `connection.md:45` says "Accept once per tab".

**The goal change this needs, and only this one.** In `GOALS.md:14`, "no debug port" becomes: *"perch may use the remote debugging the user turned on in their own browser (chrome://inspect, consent per connection). perch never opens a port, never relaunches, and never reads cookies or storage over CDP."*
- "The user's own browser, as it is", "no extension", "no relaunch" and "no separate profile" all stay.
- The only relaunch is the user's own, once, for the rung 0 flags, and only if those prove necessary.

**Costs and risks of new rung 1:**

| Cost / risk | Mitigation |
|---|---|
| A connection needs the user to click Allow. If perch restarts, or the connection drops while the user is away and locked, CDP is gone until they return | perch connects once while the user is present and keeps one long-lived socket. If there's no CDP, it falls back to today's AppleScript path and today's error codes, plus a hint |
| While connected, perch's process can do anything in every signed-in account, including reading HttpOnly cookies (`Network.getAllCookies`) | perch's CDP client allows only a fixed list of methods (Runtime, Input, Page.captureScreenshot, Target attach and lookup, DOM.setFileInputFiles). It denies Network/Storage cookie methods and `Page.bringToFront`, and never exposes raw CDP as a tool. This keeps "credentials are never read" (perch `AGENTS.md:114`) |
| Any local process that wins an Allow click gets the same power | The per-connection dialog is the defence. Never click Allow for a prompt you didn't expect |
| A banner sits in the window while connected | Cosmetic. Report it in the experiment |
| macOS TCC can block reading `DevToolsActivePort` (EPERM) | Grant the host app Files & Folders access to Chrome (chrome-devtools-mcp `docs/troubleshooting.md:65-69`) |
| Only Chromium-family browsers have this; Safari has no equivalent | Neutral errors stay as they are for Safari. Helium and Arc are Chromium, but whether they ship the toggle is unknown |
| Mapping a perch tab to a CDP target | Write a nonce with `eval_js`, find the target whose `Runtime.evaluate` reads it back, and cache the pairing. Re-pair on `stale_tab` |

**Experiments added to the rung 0 slot.** Each needs the user present for the Allow click. They use a scratch tab on the user's Canary through a minimal CDP client that sends only Runtime, Input and Page commands, with no cookie calls.
- **X2.** With the flags on: perch's existing trusted click into the scratch window while locked. The lock alone blocked it before because the page reported hidden (`perch-next-research.md`, "Locked, display awake"); the flags may change that.
- **X3.** CDP `Input.dispatchMouseEvent` into the scratch page across 6b.E's four states and the locked state. Pass: the page records `isTrusted:true` clicks, and the foreground and cursor are unchanged.
- **X4.** `Page.captureScreenshot` in the same states. Is the frame live (the probe's counter advances between two shots), stale, or does it hang?
- **X5.** Housekeeping: does the Allow dialog take focus? Is it per connection or per tab? Does the toggle survive 6b.B's relaunch?

**The phased plan changes to:**
- P0/P1 (rung 0, as written).
- P2: X2-X5.
- P3: a CDP transport inside perch, behind the method allowlist, TDD'd against a fake CDP world, with perch's lock scenarios as the oracle (§5).
- P4: the locked live checks.

The old P3-P6 (agent Chrome, container) are dropped unless P2 fails.

## Sources

Six research lenses ran in parallel. Each wrote a findings file with file:line or URL citations and a confidence tag per claim (H = read in code or primary docs, M = inferred or secondary, L = unverified). In the shared notes folder `~/Library/Application Support/Claude/side-session-notes/local_27aad4d7-3306-4627-b870-efad73d43203/container-browser/`:

| # | File | Lens |
|---|---|---|
| 1 | `1-apple-containers.md` | Apple `container` / Containerization; Docker, OrbStack, Lima, tart and host headless compared |
| 2 | `2-session-continuity.md` | Cookie storage and encryption, Figma auth, security |
| 3 | `3-figma-cdp-fit.md` | figma-cdp's CDP path, eval harness, Chromium throttling source |
| 4 | `4-perch-fit.md` | perch dispatch, budgets, per-tool CDP mapping, tests |
| 5 | `5-petri.md` | petri |
| 6 | `6-claw-sandboxes.md` | OpenClaw and other "claw" agents' browser sandboxes |

Citations below are shortened to `[n §section]` for these files. Repo paths are given as `file:line`. Chromium paths are `chromium/chromium` main at `3904780230c2`. Apple source is `apple/container@af7c439` and `apple/containerization@fd4a84a`.

Experiments run: none touched a browser. `container`, `docker`, `orb` and `limactl` are not installed on this Mac (`which`, 2026-10-31). The host WebGL probe could not run: the puppeteer Chrome cache is a broken stub, and downloading Chrome for Testing needs the user's OK [1 §Q1]. The probe page is ready at `/private/tmp/claude-501/-Users-mateoyadarola-Documents-figma-cdp/86b91623-abe6-496d-8e05-040de1773171/scratchpad/hlexp/probe.html`.

---

## 1. Verdict

**Partly. A container would fix the lock stall, but it is the most expensive of three fixes and the slowest at running Figma. Try the cheapest fix first: a flag change on the host Canary.**

1. **What figma-cdp actually suffers from is timer throttling, not missing input or pixels.** The r3 eval had a 10-node build that ran 9 minutes in the page while synchronous recon answered in 0.2 s. It had zero stalls with Canary in front (`figma-cdp-cost-ledger.md:101-116`, [3 §4]). On macOS, a locked screen, a sleeping display and a minimized or covered window all reach the page as `OCCLUDED`:
   - `window_occlusion_checker_mac.mm:305-313` and `:578-589` set this for display sleep and for occlusion state;
   - minimized windows go through the same check (`:537-544`);
   - `web_contents_view_cocoa.mm:542-553` maps all of these to `kOccluded`.

   Hidden pages then get 1 s and later 1 min timer throttling (`frame_scheduler_impl.cc:1086-1110`, `page_scheduler_impl.h:51-56`) [3 §6, H].
2. **Three launch flags on the host Canary very likely remove that throttling, keeping the user's own browser, profile and perch path** [3 §6, M-H, untested]:
   - `--disable-backgrounding-occluded-windows` rewrites `OCCLUDED` as `VISIBLE` (`web_contents_impl.cc:12764-12772`);
   - `--disable-background-timer-throttling` turns off both background and intensive timer throttling at one gate (`runtime_features.cc:339-340`, `frame_scheduler_impl.cc:1104-1110`), and this one also works for hidden tabs;
   - `--disable-renderer-backgrounding` stops OS priority demotion (`render_process_host_impl.cc:1449-1462`).

   These need no debug port, so the Chrome 136 rule doesn't apply [3 §6]. If they work, figma-cdp needs no container at all.
3. **A browser in a VM or a headless browser does avoid every host limit, including trusted input and live screenshots.** The cost is the user's browser itself: it becomes a different browser with a separate profile that has to be signed in once.
   - A headless or VM browser has no NSWindow, so there is nothing to occlude (`native_widget_mac_ns_window_host.mm:1223-1225`) [3 §6, M].
   - CDP `Input.dispatchMouseEvent` produces `isTrusted` events with no window server involved [4 §2, H].
4. **Among separate browsers, a second headless Chrome on the host beats Apple `container` on every axis except isolation** (section 3):
   - **WebGL:** the host browser keeps Metal; the container runs CPU-only SwiftShader [1 §Q1, H].
   - **Lock and sleep:** both behave the same.
   - **Setup:** the host browser has no VM or image to manage.
5. **Nothing survives system sleep.** That includes the VM, host headless Chrome and Canary [1 §Q4, H]. On this MacBook Air, closing the lid forces sleep [1 §Q4, M]. "Works while the Mac sleeps" is impossible, so the realistic goal is "works while locked with the display off", plus `caffeinate -i`.
6. **Copying the session from the host profile is neither needed nor advisable** (section 4). Sign in once inside the agent's profile.
7. **petri is not the right host.** It runs disposable Tart macOS VMs and forbids persistent state in the guest (petri `AGENTS.md:67-68`) [5]. A small dedicated launcher is less work.

---

## 2. Recommended architecture

The plan runs as a ladder. Climb a rung only when the one below fails a measured test.

```
Rung 0  Host Canary + 3 anti-throttling flags         figma-cdp via perch, unchanged
        (user's profile, no debug port)               perch, unchanged
            │ fails the locked-eval test?
            ▼
Rung 1  "Agent Chrome": Chrome for Testing,           figma-cdp: FIGMA_BACKEND=cdp
        headless=new on the host, own profile,        FIGMA_CDP_PORT=<port>
        CDP on 127.0.0.1, signed in once, Metal       perch: a `container:`/`agent:` backend
            │ need isolation from host files/keys?    (or sibling server), choice up front
            ▼
Rung 2  Same agent profile inside Apple `container`   same CDP contract, published on
        (headful Chromium on Xvfb, SwiftShader,       127.0.0.1 through an in-guest socat
        socat relay, noVNC for the one-time login)    relay; slower canvas
```

### Rung 0: flags on the host Canary
- The user relaunches Canary once with the three flags. perch never relaunches the browser (perch `GOALS.md:14`). Nothing else changes.
- Residual risks [3 §6, L]:
  - rAF and frames may still stop while the display sleeps. Plugin API awaits don't need frames, but `exportAsync` and screenshot timing are unmeasured.
  - App Nap and Chrome Energy Saver.
  - A background tab in a window is `kHidden`, not `kOccluded`. Timers stay unthrottled by the second flag, but rAF stops.
- This rung doesn't fix perch's trusted input under lock. The lock alone blocks trusted click and press, whatever the throttling (`perch-next-research.md`, "Locked, display awake"). figma-cdp only needs trusted input to wake `figma`, and an untrusted DOM click on a plugin row does that ([3 §1]; `memory/project_live_eval_pitfalls.md`).

### Rung 1: the "agent Chrome" on the host (recommended if rung 0 isn't enough)
- **Bundle.** Use Chrome for Testing (bundle id `com.google.chrome.for.testing`) or Chromium, never a second Canary or Chrome instance. A twin of the same bundle makes perch drop its bounded execute and refuse trusted input with `window_ambiguous` (perch `server.js:797-803`, `:160`, `:930`; `test/twin-instance.test.mjs`) [4 §4, H]. perch's `procs()` ignores bundles that aren't in `BROWSERS` (`server.js:157-159`).
- **Launch.** A host LaunchAgent starts:

  ```
  --headless=new
  --user-data-dir=~/Library/Application Support/agent-chrome
  --remote-debugging-port=<p>
  --remote-allow-origins=http://127.0.0.1:<p>
  ```

  plus the three throttling flags as a safety margin. The Chrome 136 rule needs the non-default data dir (developer.chrome.com/blog/remote-debugging-port) [1 §Q2, 2 §2, H].
- **One profile, forever.** The user's reason for "no separate profile" was that every new profile started signed out. So the agent profile has these rules:
  - **One fixed path, a constant in the launcher, never a parameter.** It is created only by an explicit `agent-chrome init`, which launches headful so the user can sign in, and never by a normal start. No temp dirs and no per-run copies; consumers (figma-cdp, perch) never pass `--user-data-dir`.
  - **Refuse rather than recreate.** On start:
    - if the directory is missing, the launcher exits with `profile_missing: run agent-chrome init`;
    - if a signed-in probe fails, it exits with `signed_out: <site>; run agent-chrome login <site>`.

    The probe checks, for each site the user registered at init, that the site's own page is logged in; for Figma, it opens `figma.com/files` and checks it doesn't redirect to `/login`. Chrome would otherwise create a fresh profile silently at any path it is given.
  - **Lock it to one process.** Chrome's singleton lock already rejects a second process on the same path. The launcher reports that as `profile_in_use`, never by falling back to another path.
  - **Back it up, don't regenerate it.** Rung 2 keeps the same rules for its named volume, which is never `--rm` or recreated by an image rebuild.
- **GPU.** The browser keeps Metal through ANGLE, and Chromium disables App Nap (`NSAppSleepDisabled`, `content/app/mac_init.mm`) [1 §Q6, M].
- **figma-cdp.** No code change: `FIGMA_BACKEND=cdp FIGMA_CDP_PORT=<p>` (`figma_run.py:36-49`, `:66-74`) [3 §1, H]. Two caveats:
  - The eval harness forces perch (`tests/eval/run.py:123-131`) and needs a `--backend cdp` option.
  - The CDP path evaluates in agent-browser's current tab, not by file (`tests/bench_backends.py:17-19`). Keep exactly one page target, or select by URL [3 §1, §5].
- **perch.** Either a backend behind the same API or a sibling server (section 5).
- **Viewing.** For the human, run a CDP screencast (`Page.startScreencast`) to a local page, or do the one-time sign-in headful. Headless has no window.

### Rung 2: Apple `container` (only if isolation is required)
- **Image.** linux/arm64 with Chromium, or Google Chrome for arm64 Linux, which shipped in 2026 [1 §Q1, M]. Run it headful under Xvfb rather than headless, because headless sets `navigator.webdriver` and a HeadlessChrome UA (`runtime_features.cc:342-343`) [3 §6]. Install `fonts-inter` so walked fixtures match; Figma itself serves Inter [3 §3].
- **Graphics.** `--use-angle=swiftshader-webgl --enable-unsafe-swiftshader`, needed since M139. There is no virtual GPU device (`VZVirtualMachineInstance.swift:416-582`, `kernel/config-arm64:2597`, apple/container#57) [1 §Q1, H].
- **CDP.** Chrome binds guest loopback only (`remote_debugging_server.cc:89-151`). Run `socat TCP-LISTEN:9223,fork,bind=0.0.0.0 TCP:127.0.0.1:9222` inside the guest, then `container run -p 127.0.0.1:<p>:9223` (`docs/networking.md:86-95`) [1 §Q2, 3 §1].
- **Resources.** Allow 4 GB or more of memory and `--shm-size 1g` (`docs/command-reference.md:76`). Freed guest memory isn't returned to the host, so restart the container periodically (`docs/technical-overview.md:55-59`) [1 §Q3, H].
- **Support.** `container` supports macOS 26+ (`README.md:20`). Watch the open macOS 27 bug #2275, where every command hangs on pfd [1 §Q5, M].
- **Fixtures.** Mount `tests/eval/fixtures` read-only at the same absolute path, so `file://` walks resolve [3 §2].

### petri's role
**None in rungs 0-2.** petri is one 243-line bash script plus a skill. It copies a golden Tart macOS VM into a scratch VM for each run, shares the project folder, and runs commands through Tart's guest agent (petri `README.md:3-5`, `bin/petri:46-140`). It has no Linux guests, port forwarding or tests, and its rule forbids persisting anything in the guest (`AGENTS.md:67-79`) [5, H].
- **What's reusable:** about 40 lines for an optional rung 2b, a **macOS guest with real paravirtualized Metal**. These are the Tart helpers (`bin/petri:19-36`), the background boot (`55-62`), the readiness check (`46-53`) and VNC for the one-time sign-in [5].
- **Why rung 2b is unattractive:** the image is tens of GB, the license caps it at 2 macOS VMs, the image's default login is admin/admin, and the guest's own lock and occlusion rules apply inside it [1 §Q6; 5].
- **If the user wants petri to grow into this anyway:** add a `petri keep <name>` persistent-VM mode with an encrypted data volume, a `--publish` port relay, and a LaunchAgent health loop. Those are new features against petri's stated goals [5].

---

## 3. Head to head: host headless "agent Chrome" vs Apple `container`

| | Host headless Chrome (rung 1) | Apple `container` (rung 2) |
|---|---|---|
| **WebGL / Figma canvas** | Metal through ANGLE, the same GPU path as Canary [1 §Q6, M] | CPU SwiftShader only: no GPU device, no virtio-gpu, passthrough unsupported (apple/container#57, #1511) [1 §Q1, H]. Speed unmeasured; a 5-50x slower canvas is an estimate [L]. Plugin API mutations don't need frames, but `exportAsync` rasterizes [3 §4] |
| **Screen lock** | Keeps running. No NSWindow, so no occlusion (`native_widget_mac_ns_window_host.mm:1223-1225`) [3 §6, M]. Unverified on 27.2 | Keeps running. The services are launchd agents in `gui/<uid>`, which survive lock and die at logout (`ServiceManager.swift:160-171`, `SystemStart.swift:115-121`) [1 §Q4, H] |
| **Display sleep** | Keeps running [M]. Screenshots render offscreen | Keeps running [H] |
| **System sleep / lid close** | Frozen; sockets may drop | Frozen; `TimeSyncer` fixes the clock every 30 s (`TimeSyncer.swift:31`) [1 §Q4, H] |
| **Setup** | Download Chrome for Testing (~150 MB), one LaunchAgent, sign in once. No VM | Install `container` (brew 1.6.1, macOS 26+), build an image (Chromium, Xvfb, fonts, socat, noVNC), sign in through noVNC. 2-4 GB RAM per VM. macOS 27 pf hang risk (#2275) |
| **Startup** | ~1-2 s Chrome cold start | Under 1 s VM (`containerization/README.md:27`) plus Chrome |
| **Fonts** | Host fonts, including SF Pro and licensed families | Linux fonts only. Install Inter; Mac-local families are gone for real work [3 §3] |
| **Security: isolation** | None from the host. The agent's browser runs as the user and can read host files through `file://` and downloads | VM boundary. The agent browser can't read host files except mounts [M] |
| **Security: secrets at rest** | Cookies encrypted with a Keychain item on the host, presumably Chrome for Testing's own Safe Storage (same `v10` scheme [2 §1, M]; item name unverified) | Linux Chrome with `--password-store=basic` stores the `v10` "peanuts" key, which is effectively plaintext in the volume [2 §1, H]. Encrypt the volume |
| **Security: CDP exposure** | `127.0.0.1:<p>`, no auth. Any local process running as any user can drive it, and CDP is full account control [2 §5, H]. `--remote-debugging-pipe` avoids the port if the launcher owns the pipe | Same once published on `127.0.0.1`. Never publish on `0.0.0.0` |
| **Coexists with perch** | Yes, when it's a different bundle (see the twin-instance gotcha) [4 §4, H] | Yes. perch can't see it at all |

**Recommendation: rung 1 (host headless Chrome for Testing).** Move to `container` only if the user wants the agent's browser isolated from their files, for example for unattended agents on untrusted sites. Plan for its slower canvas.

---

## 4. Session continuity design

### Recommendation: don't copy. Sign in once inside the agent profile, and keep the two sessions independent.
- **Why not copy the cookie DB.** Host cookies are `v10`: AES-128-CBC, with a key from PBKDF2-SHA1 (`saltysalt`, 1003 iterations) over the "Chrome Canary Safe Storage" Keychain secret [2 §1, H scheme / M constants]. Since cookie DB v24 the plaintext is also prefixed with `SHA256(domain)` (`sqlite_persistent_cookie_store.cc`) [2 §1, H].
  - Copying means decrypting on the host and re-encrypting for the target, which is brittle.
  - It is also exactly what infostealers do. Reading the Keychain item triggers an access prompt, and this plan should never do it.
- **Why not CDP export.** `Network.getAllCookies` would read HttpOnly cookies, but only from a host browser running a debug port. Chrome 136+ refuses that on the default profile, and a non-default profile is logged out anyway (developer.chrome.com/blog/remote-debugging-port) [2 §2, H].
  - perch's `eval_js` sees only `document.cookie`, so it can't read an HttpOnly auth cookie [2 §2, H].
  - Public sources point to `__Host-figma.authn` as Figma's auth cookie [2 §3, M]. Whether it is HttpOnly is unverified [L].
- **Why not sync both ways.** Two live copies of one session risk refresh-token rotation logging out one side [2 §4, M]. Figma has no self-service "sign out other devices"; ending a session takes a support request (forum.figma.com/t/.../53044) [2 §3, M].
- **The flow:**
  1. The launcher starts the agent profile headful once. On rung 2, the user opens noVNC.
  2. The user types their own password or SSO and completes 2FA. Claude never enters it.
  3. The profile directory persists: a host dir on rung 1, an encrypted volume on rung 2.
  4. Figma sees a normal second device.

### Risks to the user's accounts
| Risk | Mitigation |
|---|---|
| CDP port = full control of every account signed into the agent profile [2 §5, H] | Bind to 127.0.0.1 only, or use `--remote-debugging-pipe` owned by the launcher. Sign the profile into Figma only, never email or a password manager |
| Agent profile stolen from disk | Rung 1: Keychain-encrypted like any Chrome profile. Rung 2: encrypt the volume, since Linux `basic` storage is plaintext [2 §1] |
| Figma flags automated use; the ToS restricts scraping and reverse engineering [2 §3, M via third-party trackers; verify figma.com/tos] | Prefer a dedicated or limited Figma account in the agent profile [2 §5]. Keep automation to the Plugin API on the user's own files |
| Concurrent sessions detected as replay | No public evidence of IP or device binding [2 §3, L]. Independent sign-in avoids replay entirely |
| SSO or 2FA re-prompts end unattended runs | The health check reports `signed_out` and stops the run. It never retries the login |

---

## 5. perch: backend or sibling server, and what the goal change costs

The user is willing to change perch's goals. **The debug port is not the only blocker: "no separate profile" has to be reworded too.** The new wording is "one persistent agent profile, signed in once, never recreated", which keeps the goal's purpose (the user never lands in a signed-out profile). A separate profile is unavoidable for any of these routes, for two reasons:
1. **Chrome 136+ ignores `--remote-debugging-port` on the default user-data-dir**, so a debuggable browser is a non-default profile by definition (developer.chrome.com/blog/remote-debugging-port) [2 §2, H].
2. **Two processes can't share one profile directory.** Chrome holds a singleton lock on the user-data-dir (`chrome/browser/process_singleton_posix.cc`) [M], so the agent browser can't run on Canary's profile while Canary is open.

"No relaunch" stays intact, because the user's Canary is never touched. "No extension" stays intact as well.

What changing the two goals costs the user:
| Goal changed | Cost |
|---|---|
| "no debug port" | A local port (or pipe) that gives full control of the agent profile to any local process. perch gains a CDP client. Node's global WebSocket means no new dependency [4 §4]. perch's Apple-Event perf metric (`test/perf-budget.test.mjs`) doesn't cover the CDP half, so a CDP round-trip budget is needed |
| "no separate profile" → "one persistent agent profile, signed in once" | The goal's purpose (never land in a signed-out profile) is kept by the rules in rung 1: one fixed path, created only by `init`, and a start that refuses with `profile_missing`/`signed_out` instead of creating a fresh profile. What remains:<br>• The agent's tabs aren't in the user's own browser, so the user sees them only through a viewer.<br>• The agent profile has only the sign-ins the user made there.<br>• Each site's sign-in is a one-time step, repeated when the site expires it.<br>• It is a second credential store to protect.<br>• Agents choose the agent browser up front. |

**Backend inside perch: feasible, behind the same tool API** [4 §1-2, H]:
- **Plug point.** Fork in `handleCallCore` (`server.js:10381`) on a `container:` (or `agent:`) handle prefix. `rt()` already routes the `safari:` prefix in Node (`:4220-4235`), and handles are opaque `<key>:<raw>` (`:49-67`). Keep the key out of `BROWSERS`/`BY_KEY`, so it never reaches JXA. The backend can't be a new `kind` row, because kinds are AppleScript dictionary shapes inside the JXA runtime (`:17-27`, `:39-43`).
- **Code reuse.** perch's page scripts are exported strings (`PAGE_PRELUDE`, `PAGE_SCRIPTS`, `pageScript`, `buildEvalWrapper`; `:4442`, `:4847`, `:7314`, `:9133`) that run unchanged through `Runtime.evaluate`. The JXA orchestration (polls, trusted aiming, dialogs) must be rewritten, an estimated 1.5-3k lines [4 §4, low-med].
- **Mapping.** Most tools map 1:1, and many are better than on the host: trusted input, awaited eval, dialogs, drag, hover, offscreen screenshots.
  - `file_upload` needs the file reachable from the browser. That's trivial on rung 1 (the browser runs on the host); rung 2 needs a mount.
  - `activate_tab` has nothing to act on.
  - `notify` stays a host action.
  - The screenshot `window` and screen coordinates become viewport coordinates [4 §2].
- **Budget.** The schema is at 9589 of 9600 bytes, and `INSTRUCTIONS` at 1197 of 1200 [4 §1, measured]. `new_tab {app:"agent"}` costs 0 bytes, because `app` is a free string (`server.js:10086-10089`). The explanation goes in SKILL.md, plus a hint on locked failures (`:10336-10346`).
- **Routing.** The agent browser is never a silent fallback and never the untargeted default [4 §3, H]:
  - A tab's state lives in one browser, so retrying a refused host click "in the container" would act on a different page and report a false `ok`.
  - Locked or asleep host failures may append a hint naming the agent browser.
  - URL-only handoff is the caller's explicit choice.

**Recommendation:** if the user amends `GOALS.md:13-15`, put the backend in perch behind a `container:`/`agent:` prefix. Agents then keep one server and one skill. Otherwise, build a sibling server that imports perch's page scripts and mirrors its contract.
- Either way, test against a fake CDP world and use perch's 115 lock scenarios as the conformance oracle (`test/lock/`) [4 §5].
- Middle option: perch recognises the prefix and forwards those calls to the sibling over stdio (`scripts/mcp-client.mjs`) [4 §4].
- In all three cases the agent browser is a different bundle, to avoid the twin-instance gotcha.

---

## 6. Prior art: OpenClaw and other "claw" agents

Repos were read only, from shallow clones under the session scratchpad `claws/`. Citations are [6 §n] with file:line from those repos.

**Only two projects put a browser in a container and hand CDP to the host** [6 §Bottom line, H]:

| | OpenClaw (MIT) | Moltis (MIT) |
|---|---|---|
| Sandbox | Docker or Podman, not Apple `container`. The image-contract and config-hash labels decide when to recreate it [6 §1.1, 1.6] | **Apple `container` first on macOS**, then Podman, then Docker (`crates/browser/src/container.rs:864-901`) |
| Chrome | Headful Chromium under `Xvfb :1` (`entrypoint.sh:93-99`), Debian trixie with CJK/emoji fonts (`Dockerfile.browser:3-36`). **WebGL off by default** (`--disable-3d-apis --disable-gpu`, `entrypoint.sh:131-138`); `OPENCLAW_BROWSER_DISABLE_GRAPHICS_FLAGS=0` falls back to SwiftShader | Headless Browserless image. `--tmpfs /dev/shm`, because Apple `container` has no `--shm-size` (`container.rs:821-823`) |
| CDP to host | Chrome on 127.0.0.1 in the guest. A ~130-line Python relay on 0.0.0.0 requires a Basic/Bearer token (`hmac.compare_digest`) and an optional CIDR allowlist, and **does not start without a token** (`entrypoint.sh:182-314`). Published to host loopback only (`browser.ts:392-395`) | Browserless serves on 0.0.0.0:3000. **Published without a `127.0.0.1` bind and with no auth** (`container.rs:749,820`), so it's an anti-pattern |
| Viewer | x11vnc + noVNC, one-time 60 s tokens (`novnc-auth.ts:15-68`) | None |
| Login | **Ephemeral** profile on tmpfs (`entrypoint.sh:107-147`). No cookie import; the docs say to sign in manually (`docs/tools/browser-login.md`) | Persistent bind-mounted profile with a singleton-lock cleanup (`container.rs:260-288`). The docs admit Browserless v2 doesn't reliably restore cookies (`docs/src/browser-automation.md:434-437`) |
| Lock and sleep | Nothing in the browser path. The macOS app reads `CGSSessionScreenIsLocked` and holds IOPM assertions for computer use (`MacDesktopAvailabilityPlatform.swift:23-110`) | Nothing |

- **The others** [6 §3-9]:
  - NanoClaw and PicoClaw run the whole agent in a container with `agent-browser` inside, and expose no CDP. NanoClaw's Apple `container` support exists only on a frozen opt-in branch.
  - ZeroClaw and nanobot use the host browser.
  - IronClaw has no browser; NullClaw has no CDP.
  - Moltworker proxies Cloudflare's hosted browser, with its secret in the query string. That's an anti-pattern.
- **No project sets the anti-throttling flags.** OpenClaw's managed host Chrome adds only `--disable-background-networking` (`extensions/browser/src/browser/chrome.ts:748-770`) [6 §1.5]. None measures Figma-class WebGL under software GL, and none handles host sleep [6 §10].
- **OpenClaw's Chrome extension relay** is the strongest prior art for driving the user's *real* signed-in Chrome without a debug port:
  - an MV3 `chrome.debugger` extension;
  - native-messaging pairing with a 16-byte nonce and an origin check;
  - HMAC proofs that never send the key;
  - an "OpenClaw" tab group as the consent boundary (`docs/tools/chrome-extension.md:12-14, 317-379, 610-691`) [6 §1.4, H].

  It conflicts with perch's "no extension" constraint (`GOALS.md:14`). It is still worth knowing: it removes the need for a separate profile, but it shares the host browser's throttling and lock limits, so it doesn't solve this problem.

**What to reuse (all permissive; keep the notices: MIT, or Apache-2.0 for moltworker) [6 §10]:**
- **For rung 2:** OpenClaw's `scripts/sandbox-browser-entrypoint.sh`:
  - its Xvfb, Chromium and relay supervisor;
  - the fail-closed token relay, which replaces bare `socat` and fixes the "any local process" CDP exposure;
  - noVNC with one-time tokens, for the one-time sign-in;
  - the `/json/version` readiness probe.

  Also Moltis's Apple `container` launcher pieces: the backend detection order, the `--tmpfs /dev/shm` workaround, and the profile-lock cleanup. Add a `127.0.0.1:` bind and keep the profile volume persistent, which inverts OpenClaw's tmpfs choice.
- **For rung 1:** the same token-relay idea applies on the host. Put a small authenticated relay in front of a `--remote-debugging-pipe` Chrome, so the agent profile has no open, unauthenticated port.
- **For perch:** OpenClaw's lock and keep-awake code matches what perch already ships (`IOConsoleUsers` lock read; `perch-next-research.md`, lock-screen update). There's nothing new to take.

---

## 6b. Rung 0 runbook (approved by the user: "Yes, try it")

**Runner.** `container-browser/rung0/runner.mjs` (in the notes folder) runs this runbook unit by unit:
- **Resume and report.** Each finished unit appends one JSON line to `results.jsonl`, and a rerun skips the units that already have one. `report` lists every unit; missing ones show as "not run".
- **Interrupts.** Ctrl-C or SIGTERM undoes that unit's window state (unminimize, unhide, wake, give the foreground back) and loses only that unit. After a SIGKILL, the next `run`, or `restore`, does the same from `state.json`.
- **Order.**
  1. Unattended: A-minimized (control, flags off), B-relaunch (verified with `ps`; writes `figma-tab.json`), F-figma-ready, then E-visible (the baseline: on screen, Canary not frontmost), E-minimized, and E-hidden (app hidden through System Events).
  2. Last, only with `--attended`: E-covered, E-display-asleep, L-locked, X5-connect and X34-<state>.
- **CDP allowlist.** Target.getTargets/attachToTarget, Runtime.evaluate, Input.dispatchMouseEvent and Page.captureScreenshot only.
- **Tests.** `node --test test.mjs`, 5 tests against a fake world, all pass. Nothing has run against a browser yet.
- **Command:**
  ```bash
  node runner.mjs run --file <key>
  ```

Run it in a slot the manager session gives, after figma-cdp's next live run, with `caffeinate -i` held. No eval may be running against Canary during it. Probe files are in the notes folder at `container-browser/rung0/`:
- `probe.html`: a chained 10 ms `setTimeout`, a rAF counter and a visibility log, read through `__probe.summary()`;
- `figma-loop.js`: 50 chained 10 ms timers plus a 10-rectangle Plugin API build and removal. It leaves nothing in the file.

Both scripts were syntax-checked offline. Neither has run in a browser.

### A. Control (normal Canary, before the relaunch, ~8 min)
1. With perch, `new_tab` a `file://` URL of `probe.html` **in its own window** (so it is the shown tab of that window, not `kHidden` behind another tab). Keep the Figma scratch tab as the shown tab of its own window.
2. `eval_js {target, code:"__probe.mark('C front')"}`. After 1 min, minimize the probe window: `osascript -e 'tell application "Google Chrome Canary" to set minimized of (first window whose title contains "rung0 probe") to true'`.

   Then `__probe.mark('C minimized')`, and hold for 6 min. Intensive throttling starts after 5 min hidden (`third_party/blink/renderer/platform/scheduler/common/features.h:40-41` [3 §6]).
3. Read `eval_js {code:"JSON.stringify(__probe.summary())"}`. **The control is valid only if `C minimized` shows ≤ 2 timers/s and a max gap ≥ 900 ms.** Otherwise the probe can't detect throttling; stop and report.

### B. Quit and relaunch with the flags
1. Save the tab list as a fallback: perch `list_tabs` → `container-browser/rung0/tabs-before.json` (URLs and titles only).
2. Quit cleanly, which writes the session file: `osascript -e 'tell application "Google Chrome Canary" to quit'`. Wait until `pgrep -x "Google Chrome Canary"` prints nothing. A leave-page prompt would block the quit; perch's `dialog_open` handling or the user clears it.
3. Relaunch in the background (`open -g` doesn't take the foreground) with session restore forced. This profile's Preferences have no `session.restore_on_startup` set (read 2026-10-31), so a plain launch would open the new-tab page:
   ```bash
   open -g -a "Google Chrome Canary" --args --restore-last-session --disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
   ```
   `open --args` reaches the app only when it isn't already running; that's why step 2 waits.
4. If restore misses a tab, reopen it from `tabs-before.json` with perch `new_tab`. Figma autosaves, so the scratch file reloads intact.

### C. Verify the flags took effect
- **Primary (scriptable).** Run:
  ```bash
  ps -ww -o command= -p "$(pgrep -x 'Google Chrome Canary')"
  ```
  The output must contain all three flags.
- **Secondary (by eye, for the user).** `chrome://version` → "Command Line". perch can't script `chrome://` pages (`tab_not_scriptable`), so don't use perch for this.
- **Behavioural.** In state S2 or S3 below, the probe's `visibility` stays `visible` (flag 2), and timers stay near the front rate (flag 1).

### D. Re-acquire the Figma tab
1. Tab ids change on relaunch, so perch answers `stale_tab` for the old one. Run `list_tabs {urlContains:"<file key>"}` and take the new tabId.
2. Pass it as `tests/eval/run.py --tab <new id>` (sets `FIGMA_PERCH_TAB`, `run.py:82,130,242`). Update any cached `FIGMA_PERCH_TAB` in the caller's env.
3. `figma` is undefined again after the reload. Wake it with one plugin run: an untrusted DOM click on Actions → "Plugins & widgets" → any plugin row (`memory/project_live_eval_pitfalls.md`, `references/connection.md:99,108`).
4. Check that `python3 figma_run.py --file <key> -e 'typeof figma'` prints `object`.

### E. Measure four states (screen not locked)
1. Open a fresh probe tab in its own window, with the Figma tab in its own window, as in A.1.
2. For each state:
   - `__probe.mark('<state>')`;
   - run `python3 figma_run.py --file <key> --timeout 300 container-browser/rung0/figma-loop.js` at minute 1 and at minute 6 of the hold;
   - read `__probe.summary()` at the end.

   Apply each state to **both** windows.

| State | How | Hold | Takes focus? |
|---|---|---|---|
| S1 front | Both windows visible side by side, Canary frontmost | 2 min | Yes; do it when the user is present or the manager allows it |
| S2 covered | Another app's window fully covers both (e.g. a maximized Finder or TextEdit window) | 6 min | Yes, the covering app comes forward; same condition |
| S3 minimized | `set minimized of window … to true` for both, via AppleScript as in A.2 | 6 min | No |
| S4 display asleep | `pmset displaysleepnow`; wake later with `caffeinate -u -t 2` | 6 min | No. **But if "require password after screen saver/display off" is immediate, display sleep also locks the screen.** Then S4 becomes the locked run, and the user has to unlock |

### F. Locked run (the user locks by hand, while present)
Same as E with one state, `L locked`, held 6 min, with the figma loop at minutes 1 and 6. Trusted click and press still fail while locked; that's expected and not a rung 0 failure, because figma-cdp doesn't need them (section 2, rung 0).

### G. Pass and fail thresholds
Measured on the probe over each state's last 60 s. S1's figma-loop values are the baseline.

| Result | Condition |
|---|---|
| **Pass** (per state S2-S4 and L) | Probe ≥ 50 timers/s and max gap ≤ 250 ms. figma-loop `timers50Ms` ≤ 2× S1 and `build10Ms` ≤ 2× S1, at minute 6 too |
| **Fail** (per state) | Probe ≤ 2 timers/s, or max gap ≥ 900 ms, or a figma-loop call times out (300 s) |
| In between | Partial throttling: record it and report. Don't proceed to P1 for that state |
| Record only | `rafPerS`; expected near 0 when minimized or asleep, and not required by the Plugin API. `visibility` |

If S3, S4 and L pass, run P1 (the locked eval, section 7) in the manager's next slot. If any of them fails, rung 0 doesn't cover that state; go to rung 1 for it.

### H. Restore normal Canary (on fail, or when the user wants it back)
1. Quit as in B.2.
2. Relaunch without the flags: `open -g -a "Google Chrome Canary" --args --restore-last-session`.
3. Check that `ps` shows none of the three flags.
4. Re-acquire the tab and wake `figma` as in D.

A plain launch from the Dock later also starts Canary without the flags; they don't persist anywhere.

---

## 7. Phased plan (TDD-able milestones)

Each phase states the test that decides whether to continue.

| Phase | Work | Test (what it proves) |
|---|---|---|
| **P0: flag probe** (no code; approved) | Runbook 6b on Canary itself: control A, relaunch B-D, states E, locked F | The thresholds in 6b.G. **Proves** whether the flags stop throttling in each state, and that the probe detects throttling (control). No Chrome for Testing download needed |
| **P1: rung 0 live** (needs the user's OK and a Canary slot from the manager session) | User relaunches Canary with the 3 flags. `tests/eval/run.py --tasks recon,effects --reps 1` with the screen locked the whole time (after the current live eval ends) | 0 page-side stalls and no lost replies, against r3's 13 stalls. **Proves** whether figma-cdp needs anything more. If it passes, stop here for figma-cdp |
| **P2: harness `--backend cdp`** (offline TDD) [3 §5] | `session_env` branching; `cdp_tabs()` preflight against a fake `/json/list` (0, 1 or 2 matching pages, plus another page, which must be refused); `typeof figma` preflight; `meta.backend` in results; optional `FIGMA_CDP_URL` in the 3 helpers, with `perch_backend_test.py` stubs | Unit tests: no `FIGMA_CDP_PORT` leak on perch, no `FIGMA_PERCH_TAB` on cdp, a ws URL passed unchanged. **Proves** the harness can target any CDP browser |
| **P3: agent Chrome launcher** (rung 1) | LaunchAgent plus a script: CfT headless, the one fixed profile, 127.0.0.1 port, health check (`/json/version`, signed-in probe), `caffeinate -i` while running; `init` and `login <site>` run headful for the user | Tests against a fake Chrome binary:<br>• arguments, and the port bound only to loopback;<br>• the profile path is the constant whatever the env or args;<br>• a missing dir exits with `profile_missing` and **creates nothing**;<br>• a failed probe exits with `signed_out`;<br>• a held singleton lock gives `profile_in_use`;<br>• restart on crash reuses the same dir.<br>Live: `figma_run.py -e 'typeof figma'` returns `"object"` after the plugin wake via CDP |
| **P4: rung 1 live eval** | `run.py --backend cdp`, recon/effects, then app-screens ×3, locked | Match or beat r8/r9 host numbers (wall time, page timeouts, lost replies); `exportAsync` timing recorded. **Proves** the agent Chrome works unattended under lock |
| **P5: perch backend** (only after the GOALS decision) | `test/fakes/cdp-world.mjs` (happy-dom per target, isolated world, Input to hit test, dialog events, a method log); `CDP_HANDLERS`; `container:`/`agent:` routing | Lock scenarios diffed against `golden.json` minus a documented allowlist. A CDP round-trip budget test. Live: trusted click, fill and screenshot while locked with the display asleep, foreground unchanged. **Proves** "same tool API" for real |
| **P6: rung 2 container** (optional) | Image (Chromium, Xvfb, Inter, socat, noVNC), `container run -p 127.0.0.1:<p>:9223 --shm-size 1g -m 4g`, encrypted profile volume | Same P4 suite against the container. Recorded alongside: canvas fps, CPU, and `exportAsync` against rung 1. **Proves** whether isolation is worth the SwiftShader cost |

---

## 8. Open questions for the user

**Still open after §0:**
- **A.** ~~OK to reword `GOALS.md:14`?~~ **Approved on a condition.** The user's words: "if this allows it to work while minimized or locked, without stealing focus, then yes, reword it".
  - **The gate:** X3 (CDP input) and X4 (live screenshots) must pass in the minimized and locked states, and X5 must show that neither the Allow dialog nor any call takes focus.
  - **If the gate passes,** apply this edit in perch, as its own commit:
    - `GOALS.md:14` changes from `no extension, no debug port, no relaunch,` to `no extension, no relaunch,`;
    - after `GOALS.md:15`, add `- No debug port of perch's own. perch may use the remote debugging the user turned on in their own browser (chrome://inspect, consent per connection); it never opens a port, never relaunches, and never reads cookies or storage over CDP.`;
    - `AGENTS.md:5` ("No extension, no debug port") needs the same wording.
  - **If the gate fails,** the goal stays as it is and rung 1 is dropped.
- **B.** Is Canary's chrome://inspect remote-debugging toggle on deliberately (from figma-cdp Mode A)? `DevToolsActivePort` exists.
- **C.** For X2-X5 you need to be present once, to click Allow and to lock the screen.

The questions below are the original list. Q2, Q4 and Q5 are answered.

1. **Chrome for Testing download.** Needed only for rung 1 and the WebGL probe (~150 MB, from Google's official CfT endpoints into a scratch folder). OK when we get there?
2. ~~Relaunch Canary with the 3 flags?~~ Approved ("Yes, try it"). Runbook 6b runs in a slot from the manager session.
3. **perch goals.** Amend `GOALS.md:13-15` to allow "one persistent agent browser profile, signed in once and never recreated, with a loopback debug port, chosen explicitly, never a fallback"? Or keep perch pure and build a sibling server?
4. ~~Which Figma account goes in the agent profile?~~ Answered: all main accounts, so no agent profile (§0). Original question: your main one or a dedicated one? Any SSO or 2FA that would force periodic re-login?
5. **Isolation.** Do unattended agents need a VM boundary from your files (rung 2, with a slower canvas), or is a host process enough (rung 1)?
6. **Sleep.** Is "locked with the display off, plugged in, lid open" enough? Lid-closed or battery sleep can't be covered by any option.
7. **petri.** Leave it as the disposable-VM tool (recommended)? Or grow a persistent-VM mode for a rung 2b macOS guest with Metal?

---

## 9. Does OpenAI copy local sessions into its cloud browser? (researched 2026-10-31)

**Not according to anything public.** ChatGPT's cloud browser moved to OpenAI's machines in the August 2026 update. It keeps its *own* cookies:
- You sign in through a secure form in the remote browser, and the model never sees the credentials.
- The browser keeps cookies, not passwords.
- Settings → Cloud browser lists those cookies per site.
- It is described as walled off from the local browser's "open tabs, cookies, browsing history, passwords".

Sources: https://www.macstories.net/stories/hands-on-with-chatgpt-works-new-cloud-browser-feature/ (hands-on, ~2026-08-26); https://go9x.com/blog/chatgpt-browser (sessions are "held in a cookie" created by that sign-in); OpenAI's help article "Using cloud browser in ChatGPT" (https://help.openai.com/en/articles/20001280, which returned 403 to my fetch, so I read it through search snippets only) [M].

**What did copy: Atlas, locally.**
- OpenAI's Mac browser Atlas (retired 2026-08-09) added "Site Data" import from Chrome, cookies included, on 2026-01-15. Source: the Atlas release notes, https://help.openai.com/en/articles/12591856, via search snippet [M].
- Its import flow asks you to "allow Keychain Access" (https://help.openai.com/en/articles/12628461) [M].
- The likely mechanism, inferred and consistent with §4:
  1. Read Chrome's `Cookies` SQLite.
  2. Get the "Chrome Safe Storage" secret from the Keychain; that is the prompt.
  3. Derive the AES-128-CBC key: PBKDF2-SHA1, salt `saltysalt`, 1003 iterations.
  4. Decrypt the `v10` values, and strip the `SHA256(domain)` prefix on cookie DB v24 and later.
  5. Re-encrypt with Atlas's own Safe Storage key.

  This is local to local, with no cloud upload. Chromium's own importers work the same way.

**Third parties that do copy local to cloud** [M]:
- **Browserbase "cookie sync"** needs "a Chromium-based browser with remote debugging enabled". So it attaches to the *running* Chrome, almost certainly through the chrome://inspect consent route above, reads cookies over CDP, filters them by domain, and uploads them to a cloud "context" (https://docs.browserbase.com/integrations/skills/cookie-sync).
- **Browser Use** syncs "your real Chrome profile to the cloud with a single terminal command" (`profile.sh`; https://browser-use.com/posts/web-agent-authentication). The mechanism is undocumented; the script wasn't retrievable.
- rtrvr.ai and agent-cookie-sync are similar.

**How it can be done in general** (the three routes from §4, then injection):
1. **CDP on the running browser.** Use `Storage.getCookies`, which includes HttpOnly cookies. The browser needs debugging consent, because Chrome 136+ refuses the switches on the default profile.
2. **Keychain decrypt of the `Cookies` DB.** This raises a Keychain prompt, and it is the same thing infostealers do.
3. **An extension with the `cookies` permission.**

Then inject with `Network.setCookies` or a Playwright `storageState`. Browserbase itself notes that a site may still reject the copied session. The copy is a second live session for each site, with the refresh-token rotation, device-check and ToS risks in §4.

**Relevance here.** These tools solve "a *cloud* browser needs my logins". The user's needs (all accounts, local files, one server, no focus taken) are met better by driving the real profile over its own consent-gated CDP (§0). That needs no copy, so there's no second session to rotate or leak.
