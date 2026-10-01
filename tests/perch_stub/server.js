// Stand-in for perch's server.js, imported by figma_perch.mjs when
// PERCH_DIR points here. eval_js runs the script in this Node process against a
// stub `figma` global, so the real wrapper (indirect eval, error capture) is
// exercised end to end. Every call is appended to $PERCH_STUB_LOG as a JSON line.
//
//   PERCH_STUB_TABS   JSON array of list_tabs rows (default: one Figma tab)
//   PERCH_STUB_FIGMA  "0" leaves `figma` undefined
//   PERCH_STUB_ERROR  a perch error ("timeout: ...") every eval_js call fails with
import { appendFileSync } from "node:fs";

const TABS = process.env.PERCH_STUB_TABS ? JSON.parse(process.env.PERCH_STUB_TABS) : [
  { app: "Google Chrome", tabId: "chrome:1", url: "https://www.figma.com/design/AAA111/Stub?node-id=0-1", title: "Stub – Figma" },
];

if (process.env.PERCH_STUB_FIGMA !== "0") {
  globalThis.figma = {
    currentPage: { name: "Page 1" },
    root: { children: [{ name: "Page 1", children: [{ type: "FRAME" }] }, { name: "Page 2", children: [] }] },
    loadAllPagesAsync: async () => {},
  };
}
globalThis.window = globalThis;

export function buildMainKick() {}

const text = (t) => ({ content: [{ type: "text", text: t }] });
const fail = (msg) => ({ content: [{ type: "text", text: `error: ${msg}` }], isError: true });

export async function handleCall(name, args = {}) {
  if (process.env.PERCH_STUB_LOG) appendFileSync(process.env.PERCH_STUB_LOG, JSON.stringify({ name, args }) + "\n");
  if (name === "list_tabs") {
    const q = String(args.urlContains || "").toLowerCase();
    const tabs = TABS.filter((t) => t.url.toLowerCase().includes(q));
    return text(JSON.stringify({ tabs, total: tabs.length }));
  }
  if (name === "eval_js") {
    if (process.env.PERCH_STUB_ERROR) return fail(process.env.PERCH_STUB_ERROR);
    if (args.world !== "main" || !args.awaitPromise) return fail("stub: expected world main + awaitPromise");
    try {
      const v = await new (Object.getPrototypeOf(async function () {}).constructor)(args.script)();
      return text(typeof v === "string" ? v : JSON.stringify(v));
    } catch (e) {
      return fail(`stub: wrapper threw ${e}`);
    }
  }
  if (name === "screenshot") {
    const png = Buffer.from("89504e470d0a1a0a0000000d49484452", "hex").toString("base64");
    return { content: [{ type: "image", data: png, mimeType: "image/png" }, { type: "text", text: "{}" }] };
  }
  return fail(`unknown tool: ${name}`);
}
