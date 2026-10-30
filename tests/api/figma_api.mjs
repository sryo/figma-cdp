#!/usr/bin/env node
// What the Plugin API offers, against what the skill already uses: the offline half of "could the
// API have done it?" (AGENTS.md → Improving the skill).
//
//   node tests/api/figma_api.mjs lookup "<error text, CSS property or words>" [--limit n] [--json]
//   node tests/api/figma_api.mjs coverage <member> [...]       # covered or not, by name
//   node tests/api/figma_api.mjs surface <plugin-api.d.ts> [--check-docs] > tests/api/surface.json
//
// surface.json (committed) is the typings named in typings.lock, read with regexes rather than the
// TypeScript compiler: interfaces and object types with their own members (readonly, optional,
// deprecated, the doc summary), the `type:` variants of unions such as Action and Trigger, and the
// values of string-literal unions. `extends` is kept per interface and resolved here; generic
// wrappers (Omit<X, …>) resolve to X, so a member an Omit drops can still show up. --check-docs
// asks developers.figma.com which interfaces have a page, so each member gets a link that resolves.
// Regenerate it on a typings bump:
//
//   npm pack @figma/plugin-typings@$(cat tests/api/typings.lock)   # in an empty scratch dir
//   tar xzf figma-plugin-typings-*.tgz
//   node tests/api/figma_api.mjs surface package/plugin-api.d.ts --check-docs > tests/api/surface.json
//
// Coverage is every identifier in the skill's docs and helpers, with brace notation expanded
// (create{Paint|Text}Style → createPaintStyle, createTextStyle).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const DOCS = 'https://developers.figma.com/docs/plugins/api/';
const SURFACE = path.join(HERE, 'surface.json');
const COVERED_FILES = ['SKILL.md', 'figma-worker.md', 'figma_lib.js', 'figma_importer.js', 'figma_walker.js'];
const STOP = new Set(['the', 'a', 'an', 'of', 'to', 'in', 'is', 'on', 'for', 'with', 'and', 'or', 'not', 'at', 'by', 'from',
  'error', 'cannot', 'can', 'be', 'it', 'this', 'that', 'was', 'are', 'no', 'node', 'figma', 'use', 'your', 'only']);
// Too common in member names to say much: they count, but less.
const WEAK = new Set(['set', 'get', 'async', 'type', 'id']);

const summary = (doc) => {
  const text = doc.map((l) => l.replace(/^\s*\/?\*+\/?\s?/, '').replace(/\*\/\s*$/, '')).filter((l) => !/^@/.test(l.trim())).join(' ')
    .replace(/\s+/g, ' ').trim();
  const first = text.match(/^(.+?[.!?])(\s|$)/);
  return (first ? first[1] : text).slice(0, 200);
};

// The typings as {name: {extends, members}}; see the header for what is read.
export function parse(text) {
  const lines = text.split('\n'), out = {};
  let cur = null, union = false, doc = [], header = null;
  const open = (name, ext) => { cur = out[name] = out[name] || { extends: [], members: {} }; cur.extends.push(...ext); doc = []; };
  const bases = (s) => (s || '').split(/,(?![^<]*>)/).map((x) => (x.match(/^\s*(?:Omit|Pick|Partial|Readonly)?<?\s*(\w+)/) || [])[1]).filter(Boolean);
  for (const line of lines) {
    let m;
    if (cur && union === 'pending') union = /^\s*\|?\s*'/.test(line) ? 'values' : 'variants';
    // A string-literal union ends at its first line that isn't one of its values.
    if (cur && union === 'values' && !/^\s*\|?\s*'/.test(line)) { cur = null; union = false; }
    // A declaration that ends without a closing brace (a union of objects) ends at the next one.
    if (cur && /^\S/.test(line) && !/^\}/.test(line)) { cur = null; union = false; }
    if (header) {
      header.text += ' ' + line;
      if (/\{/.test(line)) {
        open(header.name, bases(header.text.replace(/^.*?\bextends\b/, '').replace(/\{.*$/, '')));
        if (/\{\s*\}/.test(line)) cur = null;
        header = null;
      }
      continue;
    }
    if (!cur && (m = line.match(/^(?:declare )?(?:export )?interface (\w+)(?:<[^>]*>)?(.*)$/))) {
      if (/\{/.test(m[2])) {
        open(m[1], /\bextends\b/.test(m[2]) ? bases(m[2].replace(/^.*?\bextends\b/, '').replace(/\{.*$/, '')) : []);
        union = false;
        if (/\{\s*\}/.test(m[2])) cur = null;
      } else header = { name: m[1], text: m[2] };
      continue;
    }
    if (!cur && (m = line.match(/^(?:declare )?(?:export )?type (\w+)(?:<[^>]*>)?\s*=\s*(.*)$/))) {
      const rest = m[2].trim();
      if (rest === '') { open(m[1], []); union = 'pending'; continue; }
      if (/^\|?\s*'/.test(rest)) {
        // A string-literal union, on this line or the next ones.
        open(m[1], []);
        union = 'values';
        for (const v of rest.match(/'([^']+)'/g) || []) cur.members[v.slice(1, -1)] = { kind: 'value' };
        if (rest && !/\|\s*$/.test(rest) && !/^\|/.test(rest)) { cur = null; union = false; }
        continue;
      }
      if (/^\{|^\|?\s*\{/.test(rest)) { open(m[1], []); union = rest.startsWith('{') ? false : 'variants'; continue; }
      continue;
    }
    if (!cur) continue;
    if (union === 'values') {
      for (const v of line.match(/'([^']+)'/g)) cur.members[v.slice(1, -1)] = { kind: 'value' };
      continue;
    }
    if (/^\}/.test(line)) { if (!/^\}\s*\|\s*\{/.test(line)) { cur = null; union = false; } continue; }
    if (/^\s*\/\*\*/.test(line)) doc = [];
    if (/^\s*\/?\*/.test(line)) { doc.push(line); continue; }
    if (union === 'variants') {
      // A union of object types (Action, Trigger): each object's `type:` values are its variants.
      if ((m = line.match(/^\s+(?:readonly )?type\??:\s*((?:'[^']+'\s*\|?\s*)+)/))) {
        for (const v of m[1].match(/'([^']+)'/g)) cur.members[v.slice(1, -1)] = { kind: 'variant', summary: summary(doc) };
        doc = [];
      }
      continue;
    }
    if ((m = line.match(/^  (readonly )?(\w+)(\?)?\s*(\(|:|<)/))) {
      cur.members[m[2]] = { kind: m[4] === ':' ? 'prop' : 'method', ro: !!m[1], optional: !!m[3], deprecated: /@deprecated/.test(doc.join('\n')), summary: summary(doc) };
      // An object type tagged by a literal `type` (BlurEffect: 'LAYER_BLUR' | 'BACKGROUND_BLUR') gets those as variants.
      if (m[2] === 'type' && (m = line.match(/:\s*((?:'[^']+'\s*\|?\s*)+)$/))) {
        for (const v of m[1].match(/'([^']+)'/g)) cur.members[v.slice(1, -1)] = { kind: 'variant', summary: '' };
      }
      doc = [];
    }
  }
  for (const v of Object.values(out)) v.extends = [...new Set(v.extends)];
  return out;
}

export function load(file = SURFACE) { return JSON.parse(fs.readFileSync(file, 'utf8')); }

// Interfaces that inherit name (itself included), concrete nodes first.
export function inheritors(surface, name) {
  const all = surface.interfaces, memo = {};
  const has = (i, seen = new Set()) => {
    if (i === name) return true;
    if (i in memo) return memo[i];
    if (seen.has(i) || !all[i]) return false;
    seen.add(i);
    return (memo[i] = all[i].extends.some((e) => has(e, seen)));
  };
  const rank = (i) => (/Node$/.test(i) ? 0 : /Mixin$/.test(i) ? 2 : 1);
  return Object.keys(all).filter((i) => has(i)).sort((a, b) => rank(a) - rank(b) || (a === 'FrameNode' ? -1 : b === 'FrameNode' ? 1 : a.localeCompare(b)));
}

export function docUrl(surface, iface, member) {
  const page = surface.interfaces[iface] && surface.interfaces[iface].page;
  if (!page) return null;
  const m = surface.interfaces[iface].members[member];
  return DOCS + page + '/' + (m && (m.kind === 'prop' || m.kind === 'method') ? '#' + member.toLowerCase() : '');
}

// Brace notation: create{Paint|Text}Style, getLocal{Paint,Text}StylesAsync.
export function expand(text) {
  return text.replace(/(\w*)\{([\w|, ]+)\}(\w*)/g, (all, pre, alts, post) =>
    (pre || post) && /[|,]/.test(alts) ? alts.split(/[|,]/).map((a) => pre + a.trim() + post).join(' ') : all);
}

export function covered(root = ROOT) {
  const files = COVERED_FILES.map((f) => path.join(root, f));
  const refs = path.join(root, 'references');
  if (fs.existsSync(refs)) for (const f of fs.readdirSync(refs)) if (f.endsWith('.md')) files.push(path.join(refs, f));
  const ids = new Set();
  for (const f of files) {
    if (!fs.existsSync(f)) continue;
    for (const id of expand(fs.readFileSync(f, 'utf8')).match(/[A-Za-z_]\w*/g) || []) ids.add(id);
  }
  return ids;
}

const stem = (w) => (w.length > 4 && w.endsWith('s') && !w.endsWith('ss') ? w.slice(0, -1) : w);
const words = (s) => (s || '').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2').toLowerCase()
  .split(/[^a-z0-9]+/).filter(Boolean).map(stem);

export function lookup(surface, query, { limit = 8, ids = covered() } = {}) {
  const q = new Set(words(query).filter((w) => !STOP.has(w)));
  const exact = new Set((query.match(/[A-Za-z_]\w*/g) || []).filter((w) => /[a-z][A-Z]|^[A-Z_]{4,}$/.test(w)));
  const hits = [];
  for (const [iface, def] of Object.entries(surface.interfaces)) {
    const it = new Set(words(iface));
    for (const [name, m] of Object.entries(def.members)) {
      const nt = words(name);
      const hit = nt.filter((w) => q.has(w)), strong = hit.filter((w) => !WEAK.has(w)).length;
      const isExact = exact.has(name);
      if (!strong && !isExact) continue;
      let score = 3 * strong + (hit.length - strong) + (isExact ? 10 : 0) + (hit.length === nt.length ? 2 : 0) - 0.5 * (nt.length - hit.length);
      score += [...it].filter((w) => q.has(w)).length;
      score += 0.5 * new Set(words(m.summary).filter((w) => q.has(w))).size;
      if (m.deprecated) score -= 1;
      hits.push({ score, iface, member: name, ...m });
    }
  }
  hits.sort((a, b) => b.score - a.score || a.member.localeCompare(b.member));
  const seen = new Set();
  return hits.filter((h) => { const k = h.iface + '.' + h.member; return !seen.has(k) && seen.add(k); }).slice(0, limit).map((h) => ({
    member: h.iface + '.' + h.member, kind: h.kind, ro: !!h.ro, deprecated: !!h.deprecated, covered: ids.has(h.member),
    on: inheritors(surface, h.iface).filter((i) => /Node$|API$/.test(i)).slice(0, 4), summary: h.summary || '', docUrl: docUrl(surface, h.iface, h.member),
  }));
}

export function line(h) {
  const flags = [h.ro && 'ro', h.deprecated && 'deprecated'].filter(Boolean).map((f) => `[${f}]`).join(' ');
  const on = h.on.length && !h.on.includes(h.member.split('.')[0]) ? ` (on ${h.on.join(', ')})` : '';
  return `${h.member}${flags ? ' ' + flags : ''} ${h.kind}${on} — ${h.covered ? 'covered' : 'uncovered'}${h.summary ? ' — ' + h.summary : ''}${h.docUrl ? ' ' + h.docUrl : ''}`;
}

async function pages(interfaces) {
  // An interface's own page, else the page of a figma.<name> namespace it is the type of
  // (VariablesAPI → figma-variables), else its first concrete inheritor's.
  const alias = { PluginAPI: 'figma' };
  for (const [name, m] of Object.entries(interfaces.PluginAPI ? interfaces.PluginAPI.members : {})) {
    if (m.kind === 'prop' && m.ro) alias[name] = name;
  }
  const typeOf = {};
  const src = surfaceSource;
  for (const [, prop, type] of src.matchAll(/^  readonly (\w+): (\w+API)$/gm)) typeOf[type] = 'figma-' + prop;
  const ok = {};
  const names = Object.keys(interfaces);
  const check = async (p) => {
    if (p in ok) return ok[p];
    try { ok[p] = (await fetch(DOCS + p + '/', { method: 'HEAD', redirect: 'follow' })).ok; } catch (e) { ok[p] = false; }
    return ok[p];
  };
  for (let i = 0; i < names.length; i += 16) {
    await Promise.all(names.slice(i, i + 16).map((n) => check(n === 'PluginAPI' ? 'figma' : typeOf[n] || n)));
  }
  const s = { interfaces };
  for (const n of names) {
    const own = n === 'PluginAPI' ? 'figma' : typeOf[n] || n;
    if (ok[own]) { interfaces[n].page = own; continue; }
    const heir = inheritors(s, n).find((h) => h !== n && ok[h]);
    interfaces[n].page = heir || null;
  }
}
let surfaceSource = '';

async function main(argv) {
  const [cmd, ...rest] = argv;
  const flag = (f) => { const i = rest.indexOf(f); if (i === -1) return null; const v = rest[i + 1]; rest.splice(i, 2); return v; };
  if (cmd === 'surface') {
    const check = rest.includes('--check-docs');
    const file = rest.find((a) => !a.startsWith('--'));
    surfaceSource = fs.readFileSync(file, 'utf8');
    const interfaces = parse(surfaceSource);
    if (check) await pages(interfaces);
    const lock = fs.readFileSync(path.join(HERE, 'typings.lock'), 'utf8').trim();
    const sorted = {};
    for (const k of Object.keys(interfaces).sort()) sorted[k] = interfaces[k];
    process.stdout.write(JSON.stringify({ typings: lock, extractor: 'regex', interfaces: sorted }, null, 0).replace(/\},"(?=[A-Z])/g, '},\n"') + '\n');
  } else if (cmd === 'lookup') {
    const limit = Number(flag('--limit') || 8);
    const json = rest.includes('--json');
    const query = rest.filter((a) => a !== '--json').join(' ');
    if (!query) return usage();
    const hits = lookup(load(), query, { limit });
    if (json) console.log(JSON.stringify(hits, null, 1));
    else console.log(hits.length ? hits.map(line).join('\n') : 'no member matches; try other words, or the CSS property / error text');
  } else if (cmd === 'coverage') {
    if (!rest.length) return usage();
    const ids = covered();
    for (const m of rest) console.log(`${m} ${ids.has(m.split('.').pop()) ? 'covered' : 'uncovered'}`);
  } else usage();
}

function usage() {
  console.error('usage: figma_api.mjs lookup "<text>" [--limit n] [--json] | coverage <member> ... | surface <plugin-api.d.ts> [--check-docs]');
  process.exitCode = 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main(process.argv.slice(2));
