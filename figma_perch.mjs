// perch backend for figma_run.py / figma_batch_run.py: runs Figma Plugin API
// scripts in the page's main world through perch's eval_js {world:"main"}
// (AppleScript, no CDP, no "allow remote debugging" prompt). Called by the
// Python helpers, which format the output; not meant to be run by hand.
//
//   node figma_perch.mjs eval <file-url-key-or-''> <js_file> [<js_file> ...]
//   node figma_perch.mjs screenshot <file-url-key-or-''> <out.png>
//
// Prints one JSON object on stdout:
//   {tab:{tabId,url,title}, origin, results:[{ok:true,value} | {ok:false,error,figma}]}
//   {tab, origin, path}                 (screenshot)
//   {fatal:"<code>: <message>"}          (no perch, no tab, perch call failed)
//
// PERCH_DIR: the perch checkout to import (default ~/Documents/perch).
// FIGMA_PERCH_TAB: a perch tabId to use as is, skipping tab lookup.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// perch reports through MCP on stdout when run as a server; keep any stray log
// off the one JSON line the Python side parses.
console.log = console.info = console.error;

const FIGMA_PATH = /figma\.com\/(?:design|file|proto)\/([A-Za-z0-9]+)/;
const TIMEOUT_HINT = "perch caps an eval at 30s, and in a background tab figma.loadAllPagesAsync() on a many-page file can stall; read figma.currentPage or getNodeByIdAsync instead, or show the tab in its window";
const UNDEFINED_HINT ="figma is undefined in this tab: open and close any Figma plugin once to load the Plugin API, then retry";

function finish(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n", () => process.exit(0));
}

function fatal(msg) {
  finish({ fatal: msg });
}

async function loadPerch() {
  const dir = process.env.PERCH_DIR || join(homedir(), "Documents", "perch");
  const entry = join(dir, "server.js");
  if (!existsSync(entry)) throw new Error(`no_perch: no perch at ${dir} (set PERCH_DIR to a perch checkout)`);
  const mod = await import(pathToFileURL(entry).href);
  if (typeof mod.handleCall !== "function") throw new Error(`no_perch: ${entry} exports no handleCall`);
  if (typeof mod.buildMainKick !== "function") throw new Error(`no_perch: perch at ${dir} has no eval_js world:"main"; update perch`);
  return mod.handleCall;
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

// One tab per call: FIGMA_PERCH_TAB as is, else the Figma tabs of the named file
// (or of the only Figma file open), preferring the one its window shows.
export function pickTab(tabs, file) {
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
  if (!pool.length) throw new Error(`no_tab: no open Figma tab${key ? ` for file ${key}` : ""}; open the file in Chrome first`);
  return pool.find((t) => t.active) || pool[0];
}

async function resolveTab(handleCall, file) {
  const pinned = process.env.FIGMA_PERCH_TAB;
  if (pinned) return { tabId: pinned, url: "https://www.figma.com/", title: "" };
  const key = fileKey(file);
  const { text } = await call(handleCall, "list_tabs", { urlContains: key ? key : "figma.com/", limit: 500 });
  return pickTab(JSON.parse(text).tabs || [], file);
}

// Runs the script the way a CDP Runtime.evaluate does: a program whose
// completion value is the result, awaited when it's a promise. Indirect eval
// gives exactly that in the page's global scope; Figma's CSP allows it.
export function wrap(src) {
  return `var __src = ${JSON.stringify(src)};\n` +
    `var __figma = typeof figma !== "undefined";\n` +
    `try { var __v = await (0, eval)(__src); return { v: __v === undefined ? null : __v }; }\n` +
    `catch (e) { var s = e && typeof e.stack === "string" && e.stack.indexOf(String(e.message)) >= 0 ? e.stack : String(e && e.name ? e.name + ": " + e.message : e);\n` +
    `  return { e: s, figma: __figma }; }`;
}

async function runEval(handleCall, target, src) {
  const { text } = await call(handleCall, "eval_js", { target, world: "main", awaitPromise: true, script: wrap(src) });
  let out;
  try { out = JSON.parse(text); } catch { out = null; }
  if (!out || typeof out !== "object") return { ok: false, error: `unexpected eval_js reply: ${text.slice(0, 300)}` };
  if ("e" in out) return { ok: false, error: out.figma ? out.e : `${out.e}\n${UNDEFINED_HINT}`, figma: !!out.figma };
  return { ok: true, value: out.v === undefined ? null : out.v };
}

async function main() {
  const [op, file, ...rest] = process.argv.slice(2);
  if (!["eval", "screenshot"].includes(op) || !rest.length) {
    return fatal("usage: node figma_perch.mjs eval <file> <js_file>... | screenshot <file> <out.png>");
  }
  let handleCall, tab;
  try {
    handleCall = await loadPerch();
    tab = await resolveTab(handleCall, file);
  } catch (e) {
    return fatal(e.message);
  }
  const target = { tabId: tab.tabId };
  const origin = (() => { try { return new URL(tab.url).origin; } catch { return null; } })();
  const head = { tab: { tabId: tab.tabId, url: tab.url, title: tab.title }, origin };

  if (op === "screenshot") {
    try {
      const { r } = await call(handleCall, "screenshot", { target, maxWidth: 0, format: "png" });
      const img = (r.content || []).find((c) => c.type === "image");
      if (!img) throw new Error("screenshot: perch returned no image");
      writeFileSync(rest[0], Buffer.from(img.data, "base64"));
      return finish({ ...head, path: rest[0] });
    } catch (e) {
      return fatal(e.message);
    }
  }

  const results = [];
  for (const path of rest) {
    let src;
    try { src = readFileSync(path, "utf8"); } catch { results.push({ ok: false, error: `no such file: ${path}` }); continue; }
    try {
      results.push(await runEval(handleCall, target, src));
    } catch (e) {
      // A perch-level failure (stale tab, timeout, browser gone) would fail every
      // later script the same way, so it ends the run.
      return finish({ ...head, results, fatal: /^timeout: /.test(e.message) ? `${e.message}. ${TIMEOUT_HINT}` : e.message });
    }
  }
  finish({ ...head, results });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
