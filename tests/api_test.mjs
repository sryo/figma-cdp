// tests/api/figma_api.mjs offline: the typings parser on a small fixture, coverage with brace
// notation, lookup on the committed surface.json, and that surface.json matches typings.lock.
//
//   node --test tests/api_test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parse, load, inheritors, expand, covered, lookup, line } from './api/figma_api.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLI = path.join(HERE, 'api', 'figma_api.mjs');

const FIXTURE = `
interface ThingAPI {
  /**
   * How it is placed. More text.
   */
  readonly placement: Placement
  /**
   * @deprecated Use setLabelAsync.
   */
  label?: string
  setLabelAsync(label: string): Promise<void>
  find<T>(fn: (n: T) => boolean): T
}
interface BaseMixin
  extends
    ThingAPI,
    Omit<OtherMixin, 'x'> {
  width: number
}
interface OtherMixin {
  x: number
}
interface LeafNode extends BaseMixin {}
type Placement =
  | 'CENTER'
  | 'MANUAL'
declare type Mode = 'A' | 'B'
type Box = {
  readonly type: 'SOLID_BOX' | 'HOLLOW_BOX'
  size: number
} | null
/**
 * @see docs
 */
type Act =
  | {
      readonly type: 'BACK' | 'CLOSE'
    }
  | {
      /** Sets one. */
      readonly type: 'SET_THING'
      thingId: string
    }
interface After {
  y: number
}
`;

test('the parser reads members, extends, unions and literal values', () => {
  const s = parse(FIXTURE);
  assert.deepEqual(s.ThingAPI.members.placement, { kind: 'prop', ro: true, optional: false, deprecated: false, summary: 'How it is placed.' });
  assert.equal(s.ThingAPI.members.label.deprecated, true);
  assert.equal(s.ThingAPI.members.label.optional, true);
  assert.equal(s.ThingAPI.members.setLabelAsync.kind, 'method');
  assert.equal(s.ThingAPI.members.find.kind, 'method');
  assert.deepEqual(s.BaseMixin.extends, ['ThingAPI', 'OtherMixin']);
  assert.deepEqual(Object.keys(s.BaseMixin.members), ['width']);
  assert.deepEqual(s.LeafNode, { extends: ['BaseMixin'], members: {} });
  assert.deepEqual(Object.keys(s.Placement.members), ['CENTER', 'MANUAL']);
  assert.deepEqual(Object.keys(s.Mode.members), ['A', 'B']);
  assert.deepEqual(Object.keys(s.Box.members), ['type', 'SOLID_BOX', 'HOLLOW_BOX', 'size']);
  assert.deepEqual(Object.keys(s.Act.members), ['BACK', 'CLOSE', 'SET_THING']);
  assert.equal(s.Act.members.SET_THING.summary, 'Sets one.');
  assert.deepEqual(Object.keys(s.After.members), ['y']);
});

test('inheritors resolve extends chains, concrete nodes first', () => {
  const s = { interfaces: parse(FIXTURE) };
  assert.deepEqual(inheritors(s, 'OtherMixin'), ['LeafNode', 'BaseMixin', 'OtherMixin']);
});

test('brace notation expands to every name it stands for', () => {
  assert.equal(expand('figma.create{Paint|Text|Effect}Style()'), 'figma.createPaintStyle createTextStyle createEffectStyle()');
  assert.equal(expand('getLocal{Paint,Text}StylesAsync'), 'getLocalPaintStylesAsync getLocalTextStylesAsync');
  assert.equal(expand('{family, style}'), '{family, style}');
});

test('coverage reads the docs and helpers, braces expanded', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'api-'));
  fs.mkdirSync(path.join(root, 'references'));
  fs.writeFileSync(path.join(root, 'references', 'x.md'), 'figma.create{Paint|Grid}Style()');
  fs.writeFileSync(path.join(root, 'figma_lib.js'), 'n.setReactionsAsync(r)');
  const ids = covered(root);
  for (const m of ['createPaintStyle', 'createGridStyle', 'setReactionsAsync']) assert.ok(ids.has(m), m);
  assert.ok(!ids.has('createTextStyle'));
  fs.rmSync(root, { recursive: true });
});

test('surface.json is the typings typings.lock names', () => {
  const s = load();
  assert.equal(s.typings, fs.readFileSync(path.join(HERE, 'api', 'typings.lock'), 'utf8').trim());
  assert.equal(s.extractor, 'regex');
  assert.equal(s.interfaces.PluginAPI.page, 'figma');
  assert.equal(s.interfaces.VariablesAPI.page, 'figma-variables');
  assert.ok(Object.keys(s.interfaces).length > 300);
  for (const [name, def] of Object.entries(s.interfaces)) {
    assert.ok(def.page === null || typeof def.page === 'string', name);
    for (const e of def.extends) assert.ok(typeof e === 'string', name);
  }
});

test('lookup finds the member behind a symptom, with its docs link', () => {
  const s = load();
  const [top] = lookup(s, 'overlay position');
  assert.equal(top.member, 'FramePrototypingMixin.overlayPositionType');
  assert.equal(top.ro, true);
  assert.equal(top.docUrl, 'https://developers.figma.com/docs/plugins/api/FrameNode/#overlaypositiontype');
  assert.match(line(top), /^FramePrototypingMixin\.overlayPositionType \[ro\] prop \(on FrameNode/);
  assert.equal(lookup(s, 'Error: in set_overlayPositionType: Cannot write')[0].member, 'FramePrototypingMixin.overlayPositionType');
  assert.equal(lookup(s, 'You cannot use Set Variable actions in Reactions with your current plan.')[0].member, 'Action.SET_VARIABLE');
  assert.equal(lookup(s, 'in addMode: Limited to 1 modes only')[0].member, 'VariableCollection.addMode');
});

test('lookup marks what the skill already covers', () => {
  const s = load();
  const ids = new Set(['addMode']);
  const [hit] = lookup(s, 'add mode', { ids });
  assert.equal((hit.member, hit.covered), true);
  assert.equal(lookup(s, 'remove mode', { ids }).find((h) => h.member === 'VariableCollection.removeMode').covered, false);
});

test('the CLI prints lines, coverage, and usage', () => {
  assert.match(execFileSync('node', [CLI, 'lookup', 'overlay', 'position']).toString(), /overlayPositionType \[ro\]/);
  assert.equal(execFileSync('node', [CLI, 'coverage', 'createPaintStyle']).toString(), 'createPaintStyle covered\n');
  assert.equal(spawnSync('node', [CLI, 'lookup']).status, 2);
});
