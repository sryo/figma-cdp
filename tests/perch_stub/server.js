// Stand-in for perch's server.js, imported by figma_perch.mjs when
// PERCH_DIR points here. eval_js runs the script in this Node process against a
// stub `figma` global, so the real wrapper (indirect eval, error capture) is
// exercised end to end. Every call is appended to $PERCH_STUB_LOG as a JSON line.
//
//   PERCH_STUB_TABS   JSON array of list_tabs rows (default: one Figma tab)
//   PERCH_STUB_FIGMA  "0" leaves `figma` undefined; "full" is tests/figma_stub.js's Plugin API,
//                     whose document lives as long as this process (the daemon keeps it)
//   PERCH_STUB_ERROR  a perch error ("timeout: ...") every eval_js call fails with
//   PERCH_STUB_TABS_FILE  a file holding the list_tabs rows, re-read on every call
//                     (tabs that navigate or close); eval_js on a tab not in it is stale_tab
//   PERCH_STUB_DELAY  ms each eval_js waits before running (concurrency tests)
//   PERCH_STUB_OLD    "1" plays a perch from before eval_js {timeout} (no AWAIT_MAX_MS)
//   PERCH_STUB_HIDDEN "1" gives scripts a `document` whose visibilityState is "hidden"
//   PERCH_STUB_FRONT  the browser new_tab opens in when the call names none (default Google Chrome)
//   PERCH_STUB_NO_FOCUS  no focus grant: new_tab in a Mac browser other than Safari and activate_tab on a
//                     browser tab answer needs_focus; rooms are exempt
// eval_js {timeout} is checked and enforced as perch does: 1000 to 300000 ms.
// new_tab adds a tab (http(s), file or about:blank, as perch takes) that wait, eval_js and
// close_tab address until it closes; it lives as long as this process. Like a browser's,
// it shows its initial about:blank (readyState complete) until a wait {expression} poll
// finds that falsy, and then the URL has loaded.
// Scripts see `location` as the target tab's URL. Each log line carries this process's pid.
import { appendFileSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";

const DEFAULT_TABS = process.env.PERCH_STUB_TABS ? JSON.parse(process.env.PERCH_STUB_TABS) : [
  { app: "Google Chrome", tabId: "chrome:1", url: "https://www.figma.com/design/AAA111/Stub?node-id=0-1", title: "Stub – Figma" },
];
const opened = [];
let openSeq = 100;
const tabs = () => (process.env.PERCH_STUB_TABS_FILE ? JSON.parse(readFileSync(process.env.PERCH_STUB_TABS_FILE, "utf8")) : DEFAULT_TABS).concat(opened);

if (process.env.PERCH_STUB_FIGMA === "full") {
  globalThis.figma = createRequire(import.meta.url)("../figma_stub.js").createFigma();
} else if (process.env.PERCH_STUB_FIGMA !== "0") {
  globalThis.figma = {
    currentPage: { name: "Page 1" },
    root: { children: [{ name: "Page 1", children: [{ type: "FRAME" }] }, { name: "Page 2", children: [] }] },
    loadAllPagesAsync: async () => {},
  };
}
globalThis.window = globalThis;

// Current perch marks eval_js world:"main" with buildKick; perch before 5725447 with buildMainKick.
export function buildKick() {}
export const AWAIT_MAX_MS = process.env.PERCH_STUB_OLD === "1" ? undefined : 300000;

const text = (t) => ({ content: [{ type: "text", text: t }] });
const fail = (msg) => ({ content: [{ type: "text", text: `error: ${msg}` }], isError: true });

export async function handleCall(name, args = {}) {
  if (process.env.PERCH_STUB_LOG) appendFileSync(process.env.PERCH_STUB_LOG, JSON.stringify({ name, args, pid: process.pid }) + "\n");
  if (name === "list_tabs") {
    const q = String(args.urlContains || "").toLowerCase();
    const want = args.app ? String(args.app) : null;
    const rows = tabs().filter((t) => t.url.toLowerCase().includes(q) &&
      (!want || t.app === want || (want === "room" && /^room:/.test(t.app || ""))));
    if (want === "room" && !rows.length) return fail("no_browser: no room is up; rooms up <name>");
    return text(JSON.stringify({ tabs: rows, total: rows.length }));
  }
  if (name === "eval_js") {
    if (process.env.PERCH_STUB_ERROR) return fail(process.env.PERCH_STUB_ERROR);
    if (args.world !== "main" || !args.awaitPromise) return fail("stub: expected world main + awaitPromise");
    const tab = tabs().find((t) => t.tabId === (args.target || {}).tabId);
    if (!tab && process.env.PERCH_STUB_TABS_FILE) return fail(`stale_tab: tab ${args.target.tabId} is gone; re-run list_tabs`);
    if (process.env.PERCH_STUB_DELAY) await new Promise((r) => setTimeout(r, Number(process.env.PERCH_STUB_DELAY)));
    if (args.timeout != null && (typeof args.timeout !== "number" || args.timeout < 1000 || args.timeout > 300000)) {
      return fail(`bad_args: eval_js timeout is in milliseconds (1000 to 300000); got ${args.timeout}`);
    }
    const ms = args.timeout ?? 30000;
    globalThis.location = new URL(tab ? tab.url : DEFAULT_TABS[0].url);
    if (process.env.PERCH_STUB_HIDDEN === "1") globalThis.document = { visibilityState: "hidden" };
    try {
      const run = new (Object.getPrototypeOf(async function () {}).constructor)(args.script)();
      const LATE = {};
      let timer;
      const v = await Promise.race([run, new Promise((r) => { timer = setTimeout(() => r(LATE), ms); })]);
      clearTimeout(timer);
      if (v === LATE) return fail(`timeout: eval_js (world main) timed out after ${ms}ms`);
      return text(typeof v === "string" ? v : JSON.stringify(v));
    } catch (e) {
      return fail(`stub: wrapper threw ${e}`);
    }
  }
  if (name === "new_tab") {
    const url = args.url == null ? "about:blank" : String(args.url);
    if (!/^(https?:|file:|about:blank$)/i.test(url)) return fail(`bad_url: new_tab takes http(s), file or about:blank URLs; got ${url}`);
    const app = args.app || process.env.PERCH_STUB_FRONT || "Google Chrome";
    // perch 955a79b: a new tab in a Mac browser other than Safari takes focus, so it needs the grant.
    if (process.env.PERCH_STUB_NO_FOCUS && !/^room:/.test(app) && app !== "Safari") return fail("needs_focus: new_tab would bring the browser to the front, and the user has not allowed perch to take focus; nothing was sent");
    const tab = { app, tabId: `${app.split(" ").pop().toLowerCase()}:${++openSeq}`, url: "about:blank", title: "", loads: url };
    opened.push(tab);
    return text(JSON.stringify({ app: tab.app, tabId: tab.tabId }));
  }
  if (name === "activate_tab") {
    const tab = tabs().find((t) => t.tabId === (args.target || {}).tabId);
    if (!tab) return fail(`stale_tab: tab ${(args.target || {}).tabId} is gone; re-run list_tabs`);
    // perch takes focus only under the user's grant; PERCH_STUB_NO_FOCUS: there is none.
    if (process.env.PERCH_STUB_NO_FOCUS && !/^room:/.test(tab.tabId)) return fail("needs_focus: activate_tab would bring the browser to the front, and the user has not allowed perch to take focus; nothing was sent");
    return text(JSON.stringify({ ok: true }));
  }
  if (name === "wait") {
    const tab = tabs().find((t) => t.tabId === (args.target || {}).tabId);
    if (!tab) return fail(`stale_tab: tab ${(args.target || {}).tabId} is gone; re-run list_tabs`);
    if (args.expression == null) return text(JSON.stringify({ ok: true, waited: false }));
    const holds = () => new Function("location", "document", `return (${args.expression})`)(new URL(tab.url), { readyState: "complete" });
    if (!holds() && tab.loads) { tab.url = tab.loads; delete tab.loads; }
    if (!holds()) return fail(`timeout: wait timed out after ${args.timeout}ms`);
    return text(JSON.stringify({ ok: true, waited: true, value: true }));
  }
  if (name === "close_tab") {
    const i = opened.findIndex((t) => t.tabId === args.tabId);
    if (i < 0) return fail(`stale_tab: tab ${args.tabId} is gone; re-run list_tabs`);
    opened.splice(i, 1);
    return text(JSON.stringify({ ok: true, closed: args.tabId }));
  }
  if (name === "screenshot") {
    const png = Buffer.from("89504e470d0a1a0a0000000d49484452", "hex").toString("base64");
    return { content: [{ type: "image", data: png, mimeType: "image/png" }, { type: "text", text: "{}" }] };
  }
  return fail(`unknown tool: ${name}`);
}
