// perch backend for figma_run.py / figma_batch_run.py / figma_capture.py: runs Figma Plugin API
// scripts in the page's main world through perch's eval_js {world:"main"}
// (AppleScript, no CDP, no "allow remote debugging" prompt). Called by the
// Python helpers, which format the output; not meant to be run by hand.
//
//   node figma_perch.mjs once                 one request as a JSON line on stdin
//   node figma_perch.mjs serve <socket-path>
//
// A request is {op:"eval", file, sources:[<js>...], tab, timeout, stop},
// {op:"screenshot", file, path:<out.png>, tab} or {op:"page", url, sources, settle,
// timeout, app, show}; file is a Figma URL, a file key or "". The reply is one JSON object:
//   {tab:{tabId,url,title,app}, origin, results:[{ok:true,value,href} | {ok:false,error,figma,href}]}
//   {tab, origin, path}                 (screenshot)
//   {fatal:"<code>: <message>"}          (no perch, no tab, perch call failed)
//
//   stop: true     (eval) the first script that fails, returns nothing or returns an
//                  object with an `error` key ends the run (figma_capture.py's failures)
//   op "page"      opens url in a new background tab, waits for it to load and
//                  `settle` ms more, runs each source there, closes the tab. Each source
//                  is one expression (awaited); it runs inline, not through eval, so a
//                  page whose CSP bans eval still runs it. `app` names the browser (else
//                  perch's frontmost one); the reply adds {app, warnings}. Arc runs page JS
//                  only in the tab its window shows, so an Arc tab is refused unless
//                  `show` (activate_tab, which takes focus); other browsers never need it,
//                  and `show` is ignored there. Both come from the request, never this
//                  process's environment: a daemon outlives the call that started it.
//
// serve keeps perch loaded (its osascript daemons warm, the file's tab
// remembered) and answers the same requests over a unix socket, so a call costs
// one socket round trip instead of a node start, a perch import and a tab
// lookup. Protocol, one exchange per connection: the daemon greets with a JSON
// line, the client sends the request as a JSON line, the daemon
// answers with the object above as one line and closes. A client that got no
// greeting knows nothing ran. Clients read the reply line, not to EOF, and the
// daemon closes with destroy() once the line is written, not end(): under load
// a socket's end() could leave its shutdown pending forever, the client waiting
// on an EOF that never came and the connection holding the daemon open. The daemon exits after FIGMA_PERCH_IDLE seconds (default 600)
// without a call.
//
// PERCH_DIR: the perch checkout to import (default ~/.perch, then ~/Documents/perch).
// A request's `tab` is a perch tabId to use as is, skipping tab lookup; its
// `timeout` is how long eval_js awaits a script, 1000 to 300000 ms (default 100000).
import { chmodSync, existsSync, readFileSync, realpathSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { createConnection, createServer } from "node:net";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// perch reports through MCP on stdout when run as a server; keep any stray log
// off the one JSON line the Python side parses.
console.log = console.info = console.error;

const FIGMA_PATH = /figma\.com\/(?:design|file|proto)\/([A-Za-z0-9]+)/;
export const TIMEOUT_MS = { def: 100000, min: 1000, max: 300000 };
// Set by loadPerch: a perch that takes eval_js {timeout} exports AWAIT_MAX_MS; an
// older one awaits 30s whatever it is asked.
let takesTimeout = false;

export function timeoutMs(v) {
  const n = Number(v);
  if (v == null || v === "" || !Number.isFinite(n)) return TIMEOUT_MS.def;
  return Math.round(Math.min(TIMEOUT_MS.max, Math.max(TIMEOUT_MS.min, n)));
}

function timeoutHint(ms, src) {
  const waited = takesTimeout ? `The script ran past the ${ms / 1000}s it was given (--timeout or FIGMA_TIMEOUT, in seconds, up to 300)`
    : "This perch awaits at most 30s; update perch to wait longer with --timeout";
  let lib = "";
  try { lib = readFileSync(new URL("figma_lib.js", import.meta.url), "utf8"); } catch { /* no lib to strip */ }
  const own = lib && src.startsWith(lib) ? src.slice(lib.length) : src;
  return /loadAllPagesAsync/.test(own) ? `${waited}. In a background tab figma.loadAllPagesAsync() on a many-page file can stall; read figma.currentPage or getNodeByIdAsync instead, or show the tab in its window` : waited;
}
const UNDEFINED_HINT ="figma is undefined in this tab: ask the user to open and close any Figma plugin once (it takes their click in the Figma window; don't script it), then retry";

function finish(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n", () => process.exit(0));
}

async function loadPerch() {
  const dir = process.env.PERCH_DIR || [join(homedir(), ".perch"), join(homedir(), "Documents", "perch")]
    .find((d) => existsSync(join(d, "server.js"))) || join(homedir(), ".perch");
  const entry = join(dir, "server.js");
  if (!existsSync(entry)) throw new Error(`no_perch: no perch at ${dir} (set PERCH_DIR to a perch checkout)`);
  const mod = await import(pathToFileURL(entry).href);
  if (typeof mod.handleCall !== "function") throw new Error(`no_perch: ${entry} exports no handleCall`);
  // buildKick marks eval_js world:"main" from perch 5725447 on; buildMainKick, the perch before it.
  if (typeof mod.buildKick !== "function" && typeof mod.buildMainKick !== "function") throw new Error(`no_perch: perch at ${dir} has no eval_js world:"main"; update perch`);
  takesTimeout = typeof mod.AWAIT_MAX_MS === "number";
  return mod;
}

// handleCall answers MCP-shaped results; a failed call is one text item "error: <code>: ...".
async function call(handleCall, name, args) {
  const r = await handleCall(name, args);
  const text = (r.content || []).filter((c) => c.type === "text").map((c) => c.text).join("\n");
  if (r.isError) throw new Error(text.replace(/^error: /, ""));
  return { r, text };
}

export function fileKey(file) {
  if (!file) return null;
  const m = FIGMA_PATH.exec(file);
  return m ? m[1] : /^[A-Za-z0-9]+$/.test(file) ? file : null;
}

// perch's own test for a room tab that landed on a sign-in page.
const LOGIN_PATH = /(^|\/)(login|log-in|signin|sign-in|sign_in|auth|session\/new)([\/?#]|$)/i;
const roomOf = (tabId) => /^room:([^:]+):/.exec(String(tabId))?.[1] || null;
function signedOut(url) {
  try { const u = new URL(url); return /(^|\.)figma\.com$/.test(u.hostname) && LOGIN_PATH.test(u.pathname + u.search); } catch { return false; }
}
const signedOutError = (room, url) => `signed_out: room ${room} is signed out of Figma (its tab shows ${url}); ` +
  `run rooms view ${room} --signin https://www.figma.com/login, sign in, then retry; nothing ran`;

// One tab per call: the pinned tabId as is, else the Figma tabs of the named file
// (or of the only Figma file open), preferring a room's (it runs minimized or locked),
// then the one its window shows. A room on Figma's sign-in page with no tab on the
// file stops the call rather than falling back to a browser tab.
export function pickTab(tabs, file) {
  const out = tabs.find((t) => roomOf(t.tabId) && signedOut(t.url));
  const figma = tabs.filter((t) => FIGMA_PATH.test(t.url));
  const key = fileKey(file);
  if (file && !key) throw new Error(`bad_file: '${file}' is neither a Figma file URL nor a file key`);
  let pool = figma;
  if (key) pool = figma.filter((t) => FIGMA_PATH.exec(t.url)[1] === key);
  else {
    const keys = [...new Set(figma.map((t) => FIGMA_PATH.exec(t.url)[1]))];
    if (keys.length > 1) {
      const names = keys.map((k) => `${k} (${figma.find((t) => FIGMA_PATH.exec(t.url)[1] === k).title})`);
      throw new Error(`ambiguous_tab: ${keys.length} Figma files are open; pass --file <url-or-key>, one of: ${names.join(", ")}`);
    }
  }
  if (out && !pool.some((t) => roomOf(t.tabId))) throw new Error(signedOutError(roomOf(out.tabId), out.url));
  if (!pool.length) throw new Error(`no_tab: no open Figma tab${key ? ` for file ${key}` : ""}; open the file in Chrome first`);
  return pool.find((t) => roomOf(t.tabId)) || pool.find((t) => t.active) || pool[0];
}

// `cache` (serve only) maps a file key to its tab. A cached tab is checked on
// use: the eval wrapper refuses to run in a page that no longer shows the file,
// and a stale_tab from it means the eval never started; either drops the entry.
// Calls without a file key always list tabs, so a second open file still turns
// into ambiguous_tab.
async function resolveTab(handleCall, file, pinned, cache) {
  if (pinned) return { tabId: pinned, url: "https://www.figma.com/", title: "", app: roomOf(pinned) ? `room:${roomOf(pinned)}` : "", key: null, cached: false };
  const want = fileKey(file);
  if (cache && want && cache.has(want)) return { ...cache.get(want), cached: true };
  const { text } = await call(handleCall, "list_tabs", { urlContains: "figma.com/", limit: 500 });
  const t = pickTab(JSON.parse(text).tabs || [], file);
  const tab = { tabId: t.tabId, url: t.url, title: t.title, app: t.app || "", key: FIGMA_PATH.exec(t.url)[1] };
  if (cache && want) cache.set(want, tab);
  return { ...tab, cached: false };
}

// Runs the script the way a CDP Runtime.evaluate does: a program whose
// completion value is the result, awaited when it's a promise. Indirect eval
// gives exactly that in the page's global scope; Figma's CSP allows it.
// With a file key, a page showing another file answers {miss} without running it.
export function wrap(src, key) {
  return `var __h = String(location.href);\n` +
    (key ? `var __m = ${FIGMA_PATH}.exec(__h); if (!__m || __m[1] !== ${JSON.stringify(key)}) return { miss: __h };\n` : "") +
    `var __src = ${JSON.stringify(src)};\n` +
    `var __figma = typeof figma !== "undefined";\n` +
    `try { var __v = await (0, eval)(__src); return { v: __v === undefined ? null : __v, h: __h }; }\n` +
    `catch (e) { var s = e && typeof e.stack === "string" && e.stack.indexOf(String(e.message)) >= 0 ? e.stack : String(e && e.name ? e.name + ": " + e.message : e);\n` +
    `  return { e: s, figma: __figma, h: __h }; }`;
}

// The page op's form of wrap: the script is one expression, placed in the body as is.
export function wrapExpr(src) {
  return `var __h = String(location.href);\n` +
    `try { var __v = await (\n${src.replace(/[\s;]+$/, "")}\n); return { v: __v === undefined ? null : __v, h: __h }; }\n` +
    `catch (e) { var s = e && typeof e.stack === "string" && e.stack.indexOf(String(e.message)) >= 0 ? e.stack : String(e && e.name ? e.name + ": " + e.message : e);\n` +
    `  return { e: s, h: __h }; }`;
}

async function runEval(handleCall, tab, src, ms, page = false) {
  const args = { target: { tabId: tab.tabId }, world: "main", awaitPromise: true, script: page ? wrapExpr(src) : wrap(src, tab.key) };
  if (takesTimeout) args.timeout = ms;
  const { text } = await call(handleCall, "eval_js", args);
  let out;
  try { out = JSON.parse(text); } catch { out = null; }
  if (!out || typeof out !== "object") return { ok: false, error: `unexpected eval_js reply: ${text.slice(0, 300)}` };
  if (roomOf(tab.tabId) && signedOut(out.miss ?? out.h)) throw new Error(signedOutError(roomOf(tab.tabId), out.miss ?? out.h));
  if ("miss" in out) return { miss: String(out.miss) };
  if ("e" in out) return { ok: false, error: page || out.figma ? out.e : `${out.e}\n${UNDEFINED_HINT}`, figma: !!out.figma, href: out.h };
  return { ok: true, value: out.v === undefined ? null : out.v, href: out.h };
}

// Some room loads have no Plugin API until Figma's Tools panel has opened once.
// Use only an exact accessible control in that room tab; a missing or changed
// control leaves the normal undefined-figma error and its user-facing hint.
export async function wakeFigma(handleCall, tab) {
  if (!String(tab.tabId).startsWith("room:")) return false;
  const target = { tabId: tab.tabId };
  const probe = await call(handleCall, "eval_js", { target, world: "main", script: "return typeof figma" });
  if (probe.text.trim() !== "undefined") return false;
  const snap = async () => (await call(handleCall, "accessibility_snapshot", { target, max: 500 })).text;
  const before = await snap();
  const tools = /^(\d+) (button|tab) "Tools"[^\n]*/m.exec(before);
  if (!tools || /\bselected\b/.test(tools[0])) return false;
  const previous = /^(\d+) tab "[^"]+" selected(?:\s|$)/m.exec(before);
  const clickRef = async (ref) => {
    const { text } = await call(handleCall, "click", { target, ref });
    return JSON.parse(text).ok === true;
  };
  if (!await clickRef(tools[1])) return false;
  const after = await snap();
  const close = tools[2] === "button" ? /^(\d+) button "Tools"(?:\s|$)/m.exec(after)
    : previous ? [...after.matchAll(/^(\d+) tab "([^"]+)"(?:\s|$)/gm)].find((m) => m[2] === previous[0].split('"')[1]) : null;
  if (!close || !await clickRef(close[1])) return false;
  const again = await call(handleCall, "eval_js", { target, world: "main", script: "return typeof figma" });
  return again.text.trim() !== "undefined";
}

// A timeout in a hidden tab is usually Chrome throttling its timers, not a slow script: say so.
const HIDDEN_HINT = "The tab is hidden (document.visibilityState is hidden), and Chrome throttles a hidden tab's timers, so awaits in the page crawl: show the tab in its window, then --recover";
async function tabHidden(handleCall, tab) {
  const args = { target: { tabId: tab.tabId }, world: "main", awaitPromise: true,
    script: 'return typeof document === "object" && document ? String(document.visibilityState) : ""' };
  if (takesTimeout) args.timeout = 3000;
  try { return /hidden/.test((await call(handleCall, "eval_js", args)).text); } catch { return false; }
}

const perchFatal = (e, ms, src = "") => /^timeout: /.test(e.message) ? `${e.message}. ${timeoutHint(ms, src)}` : e.message;

// The page op: a tab of its own, shown only when Arc needs it and the caller asked, closed whatever the scripts do.
const ARC = /^arc$/i;
async function page(handleCall, { url, sources: srcs, settle, app, show }, ms) {
  let tabId, opened;
  const warnings = [];
  try {
    const { text } = await call(handleCall, "new_tab", app ? { url, app } : { url });
    opened = JSON.parse(text.split("\n")[0]);
    tabId = opened.tabId;
    if (opened.warning) warnings.push(opened.warning);
  } catch (e) {
    return { fatal: e.message };
  }
  const where = opened.app || app || "the browser";
  if (tabId && ARC.test(where) && !show) {
    try { await call(handleCall, "close_tab", { tabId }); } catch {}
    return { app: where, warnings, fatal: "tab_not_visible: the page tab opened in Arc, which runs page JS only in the tab its window shows; "
      + "name a Chrome-family browser or Safari (--app or FIGMA_CAPTURE_APP), which run it in the background, or pass --show (takes focus)" };
  }
  if (tabId && show) {
    if (!ARC.test(where)) warnings.push(`show ignored: ${where} runs page JS in a background tab`);
    else {
      try { await call(handleCall, "activate_tab", { target: { tabId } }); warnings.push("show: brought Arc to the front"); } catch {}
    }
  }
  if (!tabId) return { app: where, warnings, fatal: `no_tab: perch opened ${url} in ${where}, in a tab it can't address; retry, or use another browser` };
  const tab = { tabId, url, title: "", key: null };
  const results = [];
  try {
    // A new tab shows an initial about:blank, already complete, until the URL commits.
    // A page that never settles to complete is still walked, as a CDP open's timeout would leave it.
    const loaded = url === "about:blank" ? { readyState: "complete" }
      : { expression: 'document.readyState === "complete" && location.href !== "about:blank"' };
    try { await call(handleCall, "wait", { target: { tabId }, ...loaded, timeout: 30000 }); } catch {}
    const rest = Math.max(0, Number(settle) || 0);
    if (rest) await new Promise((r) => setTimeout(r, rest));
    for (const src of srcs) {
      try {
        results.push(await runEval(handleCall, tab, src, ms, true));
      } catch (e) {
        return { ...headOf(tab), app: where, warnings, results, fatal: perchFatal(e, ms) };
      }
    }
    return { ...headOf(tab), app: where, warnings, results };
  } finally {
    try { await call(handleCall, "close_tab", { tabId }); } catch {}
  }
}

function headOf(tab) {
  const origin = (() => { try { return new URL(tab.url).origin; } catch { return null; } })();
  return { tab: { tabId: tab.tabId, url: tab.url, title: tab.title, app: tab.app || "" }, origin };
}

// One request, one reply object (the shape documented at the top). Never throws.
export async function handle(handleCall, req, cache = null) {
  const { op, file = "", sources = [], path = "", tab: pinned = "", stop = false } = req || {};
  const ms = timeoutMs(req && req.timeout);
  const scripts = Array.isArray(sources) && sources.length && sources.every((s) => typeof s === "string");
  const ok = op === "eval" ? scripts : op === "page" ? scripts && typeof req.url === "string" && req.url
    : op === "screenshot" && typeof path === "string" && path;
  if (!ok) return { fatal: 'bad_request: expected {op:"eval", sources:[<js>...]}, {op:"page", url, sources} or {op:"screenshot", path}' };
  if (op === "page") return page(handleCall, req, ms);
  const want = fileKey(file);
  let tab;
  try {
    tab = await resolveTab(handleCall, file, pinned, op === "eval" ? cache : null);
  } catch (e) {
    return { fatal: e.message };
  }

  if (op === "screenshot") {
    try {
      const { r } = await call(handleCall, "screenshot", { target: { tabId: tab.tabId }, maxWidth: 0, format: "png" });
      const img = (r.content || []).find((c) => c.type === "image");
      if (!img) throw new Error("screenshot: perch returned no image");
      writeFileSync(path, Buffer.from(img.data, "base64"));
      return { ...headOf(tab), path };
    } catch (e) {
      return { fatal: e.message };
    }
  }

  const results = [];
  let retried = false;
  if (String(tab.tabId).startsWith("room:")) {
    try { await wakeFigma(handleCall, tab); } catch { /* the ordinary eval reports the missing API */ }
  }
  for (let i = 0; i < sources.length; i++) {
    let res;
    try {
      res = await runEval(handleCall, tab, sources[i], ms);
    } catch (e) {
      if (i === 0 && !retried && tab.cached && /^stale_tab: /.test(e.message)) res = { miss: null };
      // A perch-level failure (stale tab, timeout, browser gone) would fail every
      // later script the same way, so it ends the run.
      else {
        // A room's background tab reads hidden but is not throttled.
        const hidden = /^timeout: /.test(e.message) && !roomOf(tab.tabId) && await tabHidden(handleCall, tab);
        return { ...headOf(tab), results, fatal: perchFatal(e, ms, sources[i]) + (hidden ? `. ${HIDDEN_HINT}` : "") };
      }
    }
    if ("miss" in res) {
      if (cache && want) cache.delete(want);
      if (i > 0 || retried) {
        return { ...headOf(tab), results, fatal: `stale_tab: tab ${tab.tabId} no longer shows file ${tab.key}${res.miss ? ` (now ${res.miss})` : ""}; this script and the rest did not run` };
      }
      retried = true;
      try { tab = await resolveTab(handleCall, file, pinned, cache); } catch (e) { return { fatal: e.message }; }
      i--;
      continue;
    }
    results.push(res);
    if (stop && !(res.ok && res.value != null && !(typeof res.value === "object" && "error" in res.value))) break;
  }
  return { ...headOf(tab), results };
}

function listen(server, sock) {
  return new Promise((resolve, reject) => {
    const attempt = (again) => {
      const onError = (e) => {
        if (e.code !== "EADDRINUSE" || again) return reject(e);
        const probe = createConnection(sock);
        probe.once("connect", () => { probe.destroy(); reject(Object.assign(new Error(`a daemon already serves ${sock}`), { code: "ELIVE" })); });
        probe.once("error", () => { try { unlinkSync(sock); } catch {} attempt(true); });
      };
      server.once("error", onError);
      server.listen(sock, () => { server.removeListener("error", onError); resolve(); });
    };
    attempt(false);
  });
}

async function serve(sock) {
  const idleMs = Math.max(0.05, Number(process.env.FIGMA_PERCH_IDLE || 600)) * 1000;
  const mod = await loadPerch();
  const daemons = Object.values(mod.DAEMONS || {});
  const cache = new Map();
  let open = 0, timer = null, ino = null, stopping = false, seq = 0;
  const debug = process.env.FIGMA_PERCH_DEBUG ? (...a) => console.error(new Date().toISOString(), ...a) : () => {};

  const shutdown = (code = 0) => {
    try { if (ino !== null && statSync(sock).ino === ino) unlinkSync(sock); } catch {}
    for (const d of daemons) { try { d.kill(); } catch {} }
    process.exit(code);
  };
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { if (open === 0) shutdown(0); }, idleMs);
  };

  const reply = (conn, obj) => conn.write(JSON.stringify(obj) + "\n", () => conn.destroy());

  const server = createServer((conn) => {
    const id = ++seq;
    open++;
    debug(id, "accept open", open);
    clearTimeout(timer);
    let buf = "", taken = false, closed = false;
    const done = () => {
      if (closed) return;
      closed = true;
      open--;
      if (open === 0) stopping ? shutdown(0) : arm();
    };
    conn.on("close", () => { debug(id, "close"); done(); });
    conn.on("error", () => {});
    conn.setEncoding("utf8");
    conn.write(JSON.stringify({ perch_daemon: 1, pid: process.pid }) + "\n");
    conn.on("data", (d) => {
      if (taken) return;
      buf += d;
      const nl = buf.indexOf("\n");
      if (nl < 0) return;
      taken = true;
      debug(id, "request", buf.slice(0, Math.min(nl, 200)));
      let req;
      try { req = JSON.parse(buf.slice(0, nl)); } catch { return reply(conn, { fatal: "perch_daemon: bad request" }); }
      if (req.op === "ping") return reply(conn, { ok: true, pid: process.pid });
      // stop lets calls in flight finish: no new connections, exit once the last one closes.
      if (req.op === "stop") {
        stopping = true;
        try { if (statSync(sock).ino === ino) unlinkSync(sock); } catch {}
        ino = null;
        server.close();
        return reply(conn, { ok: true, pid: process.pid });
      }
      handle(mod.handleCall, req, cache)
        .catch((e) => ({ fatal: `perch_daemon: ${e && e.message}` }))
        .then((out) => { debug(id, "reply", out.fatal || ""); reply(conn, out); });
    });
  });

  const old = process.umask(0o077);
  try {
    await listen(server, sock);
  } catch (e) {
    process.exit(e.code === "ELIVE" ? 0 : 1);
  } finally {
    process.umask(old);
  }
  chmodSync(sock, 0o600);
  ino = statSync(sock).ino;
  for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) process.on(sig, () => shutdown(0));
  arm();
  // Pays the osascript bridge startup now instead of on the first call.
  for (const d of daemons) { try { d.warm(); } catch {} }
}

async function main() {
  const [op, ...rest] = process.argv.slice(2);
  if (op === "serve" && rest[0]) return serve(rest[0]).catch((e) => { console.error(e && e.message); process.exit(1); });
  if (op !== "once") return finish({ fatal: "usage: node figma_perch.mjs once < request.json | serve <socket-path>" });
  let req;
  try { req = JSON.parse(readFileSync(0, "utf8")); } catch { return finish({ fatal: "bad_request: stdin is not one JSON request" }); }
  let mod;
  try {
    mod = await loadPerch();
  } catch (e) {
    return finish({ fatal: e.message });
  }
  finish(await handle(mod.handleCall, req));
}

// Node runs the main module from its real path, so a copy reached through a symlink compares that.
if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href) main();
