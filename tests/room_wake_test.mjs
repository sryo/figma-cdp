import test from "node:test";
import assert from "node:assert/strict";
import { handle, wakeFigma } from "../figma_perch.mjs";

const reply = (text) => ({ content: [{ type: "text", text }] });
function fake({ tools = true } = {}) {
  let open = false, figma = false;
  const calls = [];
  const handleCall = async (name, args) => {
    calls.push({ name, args });
    if (name === "eval_js") return reply(args.script === "return typeof figma"
      ? figma ? "object" : "undefined"
      : JSON.stringify({ v: figma ? "ready" : null, h: "https://www.figma.com/design/AAA111/File" }));
    if (name === "accessibility_snapshot") return reply(`# {"count":2}\n1 button "Move tools"\n${tools ? `${open ? 3 : 2} button "Tools"` : ""}`);
    if (name === "click") { assert.equal(args.ref, open ? "3" : "2"); open = !open; if (open) figma = true; return reply('{"ok":true}'); }
    throw new Error(`unexpected ${name}`);
  };
  return { handleCall, calls, get open() { return open; } };
}

test("a room with an exact Tools button opens and closes it before the script runs", async () => {
  const f = fake();
  const r = await handle(f.handleCall, { op: "eval", tab: "room:main:T1", sources: ["figma.currentPage.name"] });
  assert.equal(r.results[0].value, "ready");
  assert.equal(f.open, false);
  assert.deepEqual(f.calls.filter((c) => c.name === "click").map((c) => c.args.ref), ["2", "3"]);
  assert.ok(f.calls.findIndex((c) => c.name === "click") < f.calls.findLastIndex((c) => c.name === "eval_js"));
});

test("a similar Tools name does not get clicked, and ordinary tabs are untouched", async () => {
  const f = fake({ tools: false });
  assert.equal(await wakeFigma(f.handleCall, { tabId: "room:main:T1" }), false);
  assert.equal(f.calls.some((c) => c.name === "click"), false);
  const g = fake();
  assert.equal(await wakeFigma(g.handleCall, { tabId: "chrome:T1" }), false);
  assert.equal(g.calls.length, 0);
});

test("a Tools tab returns to the previously selected tab", async () => {
  let open = false, figma = false;
  const clicks = [];
  const handleCall = async (name, args) => {
    if (name === "eval_js") return reply(figma ? "object" : "undefined");
    if (name === "accessibility_snapshot") return reply(open
      ? '# {"count":2}\n3 tab "Layers"\n4 tab "Tools" selected'
      : '# {"count":2}\n1 tab "Layers" selected\n2 tab "Tools"');
    if (name === "click") { clicks.push(args.ref); open = args.ref === "2"; if (open) figma = true; return reply('{"ok":true}'); }
    throw new Error(name);
  };
  assert.equal(await wakeFigma(handleCall, { tabId: "room:main:T1" }), true);
  assert.deepEqual(clicks, ["2", "3"]);
  assert.equal(open, false);
});

test("an already selected Tools tab is left alone", async () => {
  const calls = [];
  const handleCall = async (name) => {
    calls.push(name);
    if (name === "eval_js") return reply("undefined");
    if (name === "accessibility_snapshot") return reply('# {"count":1}\n1 tab "Tools" selected');
    throw new Error(`unexpected ${name}`);
  };
  assert.equal(await wakeFigma(handleCall, { tabId: "room:main:T1" }), false);
  assert.deepEqual(calls, ["eval_js", "accessibility_snapshot"]);
});
