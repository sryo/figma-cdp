#!/usr/bin/env python3
"""Check a Figma subtree against a source manifest from figma_source.py.

  python3 figma_fidelity.py <manifest.json> <rootId> [--file <figma-url-or-key>] [--timeout <s>] [--json] [--scope <screen.html>]

One eval through figma_run.py (next to this script, so CDP or perch as it picks) collects the
subtree's text, resolved solid colors, fonts, auto-layout spacing, radii and the component
sets behind it. The report lists, per kind, what differs from the manifest:
  missing copy / invented copy      source strings no text layer shows; text layers no source string has
  off-manifest colors, spacing, radii, font sizes, weights, fonts
  unbound                           a raw value equal to a source token while a local variable scoped for the field holds it
  missing variants / missing states for components the subtree uses (sets reached through instances too)
  missing components                a source component used 2+ times with no component in the subtree, or
                                    behind its instances, whose name (or a /-segment of it) holds all its words
                                    and no longer source component's
  stretched usages hug              a manifest fillAcross usage built as a HUG instance in a column whose name (or
                                    its slot's instance) holds a word of the source parent's classes
A boolean variant or a state counts as present on a component whose instances override it per use
(a nested instance's variant or a hidden layer that differs from the main component).
--scope <file> checks one screen: missing copy, missing components and stretched usages only from that
markup file (the manifest's src and files), while every source string still vouches for a layer.
A kind the manifest has no entries for is not checked. The first line counts the gaps; exit 0
when the check ran, gaps or not, 2 when it could not run.

  python3 figma_fidelity.py --elements <capture-spec.json> <rootId> [--waive tests/known_losses.json] [--json]

Per element instead, against a figma_capture.py walk of the source page: each captured element
is paired with the Figma node the importer named [cap:i] (several with the same index: the
closest), or, when most nodes carry no such name, greedily by text (bigram Dice >= 0.5) and then
by geometry (|dx|+|dy|+|dw|+|dh|). Each pair gives one row per property that differs:
position (> 2 px against the parent, so a moved frame is one row, not one per descendant; every
child of one element shifted alike is one spacing row on that element: its padding or gap), size
(> 2 px), color (fill or text color, CIEDE2000 > 2.3), font-size, font-weight, font-family,
line-height, letter-spacing (> 0.5 px), text (Dice < 1), radius, opacity, visibility. An
element with no node is missing-node (once, at the top of a missing subtree, weighted by its
share of the root's area); a node with no element is extra-node. --waive drops rows under an
element the walker flagged for a loss known_losses.json lists (grid, transform) and counts them.
Rows are {kind, source:{i, css_prop, value}, figma:{id, name, prop, value}}.

  ... --elements <spec> <rootId> --pixels <page.png> [--crops <dir>]

Adds what the rows don't explain: the subtree exported as PNG, compared with a screenshot of the
page (full page, as walked) on an 8 px grid, text masked out. Differing cells join into regions;
a region that overlaps no row's element is listed as unexplained (with a source and a Figma crop
in --crops), which is where to look for a loss no property check knows about (a blend mode, a
gradient, a mask). Informational: it never decides a pass.
"""
import argparse, json, os, re, subprocess, sys, tempfile

COLLECT = r'''
(async function (ROOT_ID) {
  var root = await figma.getNodeByIdAsync(ROOT_ID);
  if (!root) throw new Error('figma_fidelity: no node ' + ROOT_ID);
  if (root.type === 'PAGE' && root.loadAsync) await root.loadAsync();
  var WEIGHT = { thin: 100, hairline: 100, extralight: 200, ultralight: 200, light: 300, regular: 400, normal: 400,
    book: 400, medium: 500, semibold: 600, demibold: 600, bold: 700, extrabold: 800, ultrabold: 800, black: 900, heavy: 900 };
  function hex(c) { function h(v) { var s = Math.round(v * 255).toString(16); return s.length < 2 ? '0' + s : s; } return '#' + h(c.r) + h(c.g) + h(c.b); }
  var cache = {};
  async function resolve(id, depth) {
    if (id in cache) return cache[id];
    var v = await figma.variables.getVariableByIdAsync(id);
    if (!v) return (cache[id] = null);
    var col = figma.variables.getVariableCollectionByIdAsync ? await figma.variables.getVariableCollectionByIdAsync(v.variableCollectionId) : null;
    var mode = col && v.valuesByMode[col.defaultModeId] !== undefined ? col.defaultModeId : Object.keys(v.valuesByMode)[0];
    var val = v.valuesByMode[mode];
    if (val && val.type === 'VARIABLE_ALIAS') { var r = depth < 5 ? await resolve(val.id, depth + 1) : null; val = r ? r.value : null; }
    return (cache[id] = { name: v.name, value: val });
  }
  function hidden(n) { for (var p = n; p && p !== root.parent; p = p.parent) if (p.visible === false) return true; return false; }
  function inDef(n) { for (var p = n.parent; p; p = p.parent) if (p.type === 'COMPONENT' || p.type === 'COMPONENT_SET') return true; return false; }
  var out = { root: { id: root.id, name: root.name, type: root.type }, texts: [], colors: {}, nums: { spacing: {}, radius: {}, fontSize: {}, fontWeight: {} },
    families: {}, comps: [], names: {}, vars: { color: {}, float: {} }, cols: [] };
  // An instance the build placed (not one inside another instance, except per-use slot content).
  function placed(n) {
    for (var p = n.parent; p && p !== root.parent; p = p.parent) { if (p.type === 'SLOT') return true; if (p.type === 'INSTANCE') return false; }
    return true;
  }
  function pathOf(n) { var names = []; for (var p = n; p && p !== root.parent; p = p.parent) names.unshift(p.name); return names.join(' / '); }
  function add(map, key, id, bound, extra) {
    var e = map[key] || (map[key] = { n: 0, ids: [], unbound: [], u: 0 });
    e.n++;
    if (e.ids.indexOf(id) === -1 && e.ids.length < 5) e.ids.push(id);
    if (!bound) { e.u++; if (e.unbound.indexOf(id) === -1 && e.unbound.length < 5) e.unbound.push(id); }
    if (extra) for (var k in extra) e[k] = e[k] || extra[k];
  }
  async function paints(n, list, styled) {
    if (!list || list === figma.mixed) return;
    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      if (p.type !== 'SOLID' || p.visible === false) continue;
      var h = hex(p.color), bound = styled;
      if (p.boundVariables && p.boundVariables.color) {
        var r = await resolve(p.boundVariables.color.id, 0);
        if (r && r.value && r.value.r !== undefined) { h = hex(r.value); bound = true; }
      }
      add(out.colors, h, n.id, bound);
    }
  }
  function overrideSig(n) {
    var sig = [];
    (n.findAll ? n.findAll() : []).forEach(function (d) {
      if (d.visible === false) sig.push('hidden ' + d.name);
      else if (d.type === 'INSTANCE') { var vp = d.variantProperties || {}; Object.keys(vp).forEach(function (k) { sig.push(vp[k]); }); }
    });
    return sig;
  }
  var nodes = [root].concat(root.findAll ? root.findAll() : []);
  var mains = {};
  for (var i = 0; i < nodes.length; i++) {
    var n = nodes[i];
    if (hidden(n)) continue;
    out.names[String(n.name).toLowerCase()] = 1;
    var bv = n.boundVariables || {};
    if (n.type === 'TEXT') {
      out.texts.push({ id: n.id, t: n.characters, def: inDef(n) });
      var segs = (n.fills === figma.mixed || n.fontSize === figma.mixed || n.fontName === figma.mixed) && n.getStyledTextSegments
        ? n.getStyledTextSegments(['fills', 'fillStyleId', 'fontSize', 'fontName'])
        : [{ fills: n.fills, fillStyleId: n.fillStyleId, fontSize: n.fontSize, fontName: n.fontName }];
      for (var s = 0; s < segs.length; s++) {
        var seg = segs[s];
        await paints(n, seg.fills, !!(seg.fillStyleId && typeof seg.fillStyleId === 'string'));
        if (typeof seg.fontSize === 'number') add(out.nums.fontSize, seg.fontSize, n.id, !!bv.fontSize);
        if (seg.fontName && seg.fontName !== figma.mixed) {
          add(out.families, seg.fontName.family, n.id, true);
          var w = typeof n.fontWeight === 'number' && segs.length === 1 ? n.fontWeight : WEIGHT[String(seg.fontName.style).toLowerCase().replace(/[^a-z]/g, '').replace(/italic$/, '') || 'regular'];
          if (w) add(out.nums.fontWeight, w, n.id, true);
        }
      }
    } else {
      await paints(n, n.fills, !!(n.fillStyleId && typeof n.fillStyleId === 'string'));
    }
    await paints(n, n.strokes, !!(n.strokeStyleId && typeof n.strokeStyleId === 'string'));
    if (n.layoutMode && n.layoutMode !== 'NONE') {
      ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'].forEach(function (k) { if (n[k] > 0) add(out.nums.spacing, n[k], n.id, !!bv[k], { field: k }); });
      var flow = (n.children || []).filter(function (c) { return c.visible !== false && c.layoutPositioning !== 'ABSOLUTE'; });
      if (flow.length > 1 && n.primaryAxisAlignItems !== 'SPACE_BETWEEN' && n.itemSpacing > 0) add(out.nums.spacing, n.itemSpacing, n.id, !!bv.itemSpacing);
      if (n.layoutWrap === 'WRAP' && n.counterAxisSpacing > 0) add(out.nums.spacing, n.counterAxisSpacing, n.id, !!bv.counterAxisSpacing);
    }
    // A component set's own frame is Figma's dashed variant container: its radius is not the source's.
    var setFrame = n.type === 'COMPONENT_SET';
    if (!setFrame && typeof n.cornerRadius === 'number' && n.cornerRadius > 0) {
      add(out.nums.radius, n.cornerRadius, n.id, !!(bv.topLeftRadius || bv.cornerRadius), { pill: n.cornerRadius >= Math.min(n.width, n.height) / 2 });
    } else if (!setFrame && n.cornerRadius === figma.mixed) {
      ['topLeftRadius', 'topRightRadius', 'bottomLeftRadius', 'bottomRightRadius'].forEach(function (k) { if (n[k] > 0) add(out.nums.radius, n[k], n.id, !!bv[k]); });
    }
    var owner = null, main = null;
    if (n.type === 'COMPONENT_SET') owner = n;
    else if (n.type === 'COMPONENT') owner = n.parent && n.parent.type === 'COMPONENT_SET' ? n.parent : n;
    else if (n.type === 'INSTANCE') {
      main = await n.getMainComponentAsync();
      if (main) owner = main.parent && main.parent.type === 'COMPONENT_SET' ? main.parent : main;
    }
    if (owner && !mains[owner.id]) {
      var words = [];
      var defs = {};
      try { defs = owner.componentPropertyDefinitions || {}; } catch (e) { /* a set with errors throws; its child names still count */ }
      Object.keys(defs).forEach(function (k) { words.push(k.split('#')[0]); (defs[k].variantOptions || []).forEach(function (o) { words.push(o); }); });
      if (owner.type === 'COMPONENT_SET') owner.children.forEach(function (c) { words.push(c.name); });
      mains[owner.id] = { id: owner.id, name: owner.name, words: words };
      out.comps.push(mains[owner.id]);
    }
    // An instance placed in a column: its width sizing and the names around it, for the source's stretched usages.
    var col = n.parent;
    if (main && owner && !inDef(n) && placed(n) && col && col.layoutMode === 'VERTICAL' && n.layoutPositioning !== 'ABSOLUTE' && out.cols.length < 300) {
      var ctx = [col.name];
      if (col.type === 'SLOT') for (var q = col.parent; q; q = q.parent) if (q.type === 'INSTANCE') {
        var qm = await q.getMainComponentAsync();
        ctx.push(q.name);
        if (qm) ctx.push(qm.parent && qm.parent.type === 'COMPONENT_SET' ? qm.parent.name : qm.name);
        break;
      }
      out.cols.push({ id: n.id, comp: owner.name, sizing: n.layoutSizingHorizontal, path: pathOf(n), ctx: ctx });
    }
    // A per-use state set through overrides: the instance's nested variants or hidden layers differ from its main's.
    if (main && !inDef(n)) {
      var mine = overrideSig(n), theirs = overrideSig(main);
      if (mine.join('|') !== theirs.join('|')) {
        var seen = mains[owner.id].overrides || (mains[owner.id].overrides = []);
        mine.forEach(function (w) { if (seen.indexOf(w) === -1) seen.push(w); });
      }
    }
  }
  var vs = await figma.variables.getLocalVariablesAsync();
  for (var j = 0; j < vs.length; j++) {
    var r = await resolve(vs[j].id, 0);
    if (!r || r.value === null || r.value === undefined) continue;
    var into = vs[j].resolvedType === 'COLOR' && r.value.r !== undefined ? out.vars.color[hex(r.value)] || (out.vars.color[hex(r.value)] = [])
      : vs[j].resolvedType === 'FLOAT' && typeof r.value === 'number' ? out.vars.float[r.value] || (out.vars.float[r.value] = []) : null;
    if (into) into.push({ name: r.name, scopes: vs[j].scopes && vs[j].scopes.length ? vs[j].scopes.slice() : ['ALL_SCOPES'] });
  }
  out.names = Object.keys(out.names);
  return out;
})(%s)
'''

KINDS = ['missing copy', 'invented copy', 'off-manifest colors', 'off-manifest spacing', 'off-manifest radii',
         'off-manifest font sizes', 'off-manifest weights', 'off-manifest fonts', 'unbound', 'missing variants',
         'missing states', 'missing components', 'stretched usages hug']
NUM_KINDS = [('spacing', 'spacing', 'off-manifest spacing'), ('radius', 'radii', 'off-manifest radii'),
             ('fontSize', 'fontSizes', 'off-manifest font sizes'), ('fontWeight', 'fontWeights', 'off-manifest weights')]


def fail(msg):
    print(f'figma_fidelity.py: {msg}', file=sys.stderr)
    sys.exit(2)


def norm(s):
    return re.sub(r'\s+', ' ', str(s)).strip().casefold()


def rgb(h):
    n = int(h[1:7], 16)
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def near(a, b):
    return all(abs(x - y) <= 3 for x, y in zip(rgb(a), rgb(b)))


def num_key(v):
    v = float(v)
    return int(v) if v == int(v) else round(v, 2)


def flat(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower())


# The variable scopes that let a variable stand in for each field the check reads.
SCOPES = {'color': {'ALL_SCOPES', 'ALL_FILLS', 'FRAME_FILL', 'SHAPE_FILL', 'TEXT_FILL', 'STROKE_COLOR'},
          'spacing': {'ALL_SCOPES', 'GAP'}, 'radius': {'ALL_SCOPES', 'CORNER_RADIUS'}}


def variable(candidates, kind):
    return next((v['name'] for v in candidates if SCOPES[kind] & set(v['scopes'])), None)


def name_words(name):
    return re.findall(r'[a-z0-9]+', re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', str(name)).lower())


def pattern(source):
    """A source string as a regex over normalized text: each {expression} matches any filled-in value."""
    parts = re.split(r'\{[^{}]*\}', norm(source))
    return re.compile(r'.+?'.join(re.escape(p) for p in parts)) if len(parts) > 1 else None


def lines(text):
    return [norm(l) for l in str(text).split('\n') if norm(l)]


def within(a, b):
    """a occurs in b on word boundaries."""
    return re.search(r'(?<!\w)' + re.escape(a) + r'(?!\w)', b) is not None


def shows(source, texts):
    s, p = norm(source), pattern(source)
    for t in texts:
        if p and p.fullmatch(t['full']) or any(p and p.fullmatch(l) for l in t['lines']):
            return True
        if t['full'] == s or s in t['lines'] or (len(s) >= 12 and s in t['full']):
            return True
    return False


def vouched(text, copy):
    """A text layer some source string accounts for: equal, a fragment of it, or containing it."""
    n = norm(text)
    for s, p in copy:
        if p and (p.fullmatch(n) or p.search(n)):
            return True
        if n == s or within(n, s) or within(s, n):
            return True
    return False


def in_scope(src, scopes):
    f = str(src).rsplit(':', 1)[0] if re.search(r':\d+$', str(src)) else str(src)
    return any(f == s or f.endswith('/' + s) or s.endswith('/' + f) for s in scopes)


def scoped(m, scopes):
    """The manifest as one screen's: its copy, the components its markup uses (or that say no files),
    and their stretched usages there. Value lists (colors, spacing, fonts) stay whole."""
    scopes = [s.strip().lstrip('./') for s in scopes if s.strip()]
    out = dict(m, copy=[e for e in m.get('copy', []) if in_scope(e['src'], scopes)])
    comps = []
    for e in m.get('components', []):
        if e.get('files') and not any(in_scope(f, scopes) for f in e['files']):
            continue
        if e.get('fillAcross') or e.get('fill'):
            e = dict(e, fillAcross=[u for u in e.get('fillAcross') or e.get('fill') if in_scope(u.split(' in ', 1)[0], scopes)])
            e.pop('fill', None)
        comps.append(e)
    out['components'] = comps
    return out


def diff(m, c, vouch=None):
    gaps = {k: [] for k in KINDS}
    texts = [{'full': norm(t['t']), 'lines': lines(t['t'])} for t in c['texts']]
    copy = [(norm(e['text']), pattern(e['text'])) for e in (vouch or m).get('copy', [])]
    if copy:
        gaps['missing copy'] = [{'text': e['text'], 'src': e['src']} for e in m['copy'] if not shows(e['text'], texts)]
        seen = set()
        for t in c['texts']:
            n = norm(t['t'])
            if t['def'] or not re.search(r'\w', n) or n in seen:
                continue
            if not vouched(t['t'], copy):
                seen.add(n)
                gaps['invented copy'].append({'text': t['t'], 'ids': [t['id']]})

    tokens = {t['name']: t for t in m.get('tokens', [])}
    palette = m.get('colors', [])
    for h, e in sorted(c['colors'].items()):
        hit = next((p for p in palette if near(h, p['value'])), None)
        if palette and not hit:
            gaps['off-manifest colors'].append({'value': h, 'n': e['n'], 'ids': e['ids']})
        elif hit and hit.get('token') and e['unbound']:
            var = next((v for vh, vs in sorted(c['vars']['color'].items()) if near(vh, h) for v in [variable(vs, 'color')] if v), None)
            if var:
                gaps['unbound'].append({'value': h, 'n': e['u'], 'ids': e['unbound'], 'token': hit['token'], 'variable': var})

    for kind, key, label in NUM_KINDS:
        allowed = [e for e in m.get(key, [])]
        pill = kind == 'radius' and any(e['value'] >= 999 for e in allowed)
        for v, e in sorted(c['nums'][kind].items(), key=lambda kv: float(kv[0])):
            value = num_key(v)
            hit = next((a for a in allowed if abs(a['value'] - value) <= 0.5), None)
            if allowed and not hit and not (pill and e.get('pill')):
                gaps[label].append({'value': value, 'n': e['n'], 'ids': e['ids']})
            elif hit and hit.get('token') and e['unbound'] and kind in ('spacing', 'radius'):
                var = next((v for fv, vs in c['vars']['float'].items() if abs(float(fv) - value) <= 0.01
                            for v in [variable(vs, kind)] if v), None)
                if var:
                    gaps['unbound'].append({'value': value, 'n': e['u'], 'ids': e['unbound'], 'token': hit['token'], 'variable': var})

    fams = {e['value'].casefold() for e in m.get('fontFamilies', [])}
    if fams:
        for fam, e in sorted(c['families'].items()):
            if fam.casefold() not in fams:
                gaps['off-manifest fonts'].append({'value': fam, 'n': e['n'], 'ids': e['ids']})

    def matching(component):
        a = flat(component)
        out = []
        for k in c['comps']:
            b = flat(k['name'].split('/')[-1])
            if a and b and (a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a))):
                out.append(k)
        return out

    def vocab(comps):
        words = set()
        for k in comps:
            for w in k['words'] + k.get('overrides', []) + [k['name']]:
                words.update(re.findall(r'[a-z0-9]+', str(w).lower()))
                words.add(flat(w))
        return words

    unchecked = []
    for g in m.get('variants', []):
        comps = matching(g['component'])
        if not comps:
            unchecked.append(g['component'])
            continue
        words = vocab(comps)
        if sorted(g['values']) == ['false', 'true']:
            missing = [] if flat(g['prop']) in words or any(k.get('overrides') for k in comps) else [g['prop']]
        else:
            missing = [v for v in g['values'] if flat(v) not in words]
        if missing:
            gaps['missing variants'].append({'component': g['component'], 'prop': g.get('prop'), 'values': missing, 'src': g['src']})
    done = set()
    for s in m.get('states', []):
        key = (s['component'], s['state'])
        if key in done:
            continue
        done.add(key)
        comps = matching(s['component'])
        if not comps:
            unchecked.append(s['component'])
            continue
        stem = flat(s['state'])[:5]
        if not any(w.startswith(stem) for w in vocab(comps)):
            gaps['missing states'].append({'component': s['component'], 'state': s['state'], 'src': s['src']})
    entries = [set(name_words(e['component'])) for e in m.get('components', [])]

    def covers(seg, want):
        # Every source word is in the name ("Product card" is a card), unless a longer source
        # name in it claims it ("Stat card" is a StatCard when the source has one).
        have = set(seg)
        return want <= have and not any(want < w <= have for w in entries)

    segs = [name_words(seg) for k in c['comps'] for seg in k['name'].split('/')]
    for e, want in zip(m.get('components', []), entries):
        if e['uses'] >= 2 and want and not any(covers(seg, want) for seg in segs):
            gaps['missing components'].append({'component': e['component'], 'uses': e['uses'], 'src': e['src']})
    # A usage the source's column parent stretches (the manifest's fillAcross; `fill` before the
    # rename) built as a hugging instance in a column whose names hold a word of that parent's classes.
    flagged = set()
    for e in m.get('components', []):
        for u in e.get('fillAcross') or e.get('fill') or []:
            if ' in ' not in u:
                continue
            words = set(name_words(u.split(' in ', 1)[1].replace('.', ' ')))
            for k in c.get('cols', []):
                b = flat(k['comp'].split('/')[-1])
                if k['sizing'] != 'HUG' or k['id'] in flagged or b != flat(e['component']):
                    continue
                if words & {w for name in k['ctx'] for w in name_words(name)}:
                    flagged.add(k['id'])
                    gaps['stretched usages hug'].append({'component': e['component'], 'usage': u, 'ids': [k['id']], 'path': k['path']})
    return {'root': c['root'], 'count': sum(len(v) for v in gaps.values()), 'gaps': gaps,
            'unchecked': list(dict.fromkeys(unchecked))}


def ids(e):
    shown = ', '.join(e['ids'][:3])
    return f"({shown}{', +' + str(e['n'] - 3) if e.get('n', 0) > 3 else ''})"


def item(kind, e):
    if kind == 'missing copy':
        return f"{json.dumps(e['text'], ensure_ascii=False)} {e['src']}"
    if kind == 'invented copy':
        return f"{json.dumps(e['text'], ensure_ascii=False)} {e['ids'][0]}"
    if kind == 'unbound':
        return f"{e['value']} ×{e['n']} → {e['variable']} {ids(e)}"
    if kind == 'missing variants':
        return f"{e['component']}: {', '.join(e['values'])} ({e['src']})"
    if kind == 'missing components':
        return f"{e['component']} ×{e['uses']} ({e['src']})"
    if kind == 'stretched usages hug':
        return f"{e['component']} {e['usage']}: {e['path']} ({e['ids'][0]}) → layoutSizingHorizontal = 'FILL'"
    if kind == 'missing states':
        return f"{e['component']}: {e['state']} ({e['src']})"
    return f"{e['value']} ×{e['n']} {ids(e)}"


def render(rep):
    r = rep['root']
    lines = [f"fidelity {r['id']} {json.dumps(r['name'], ensure_ascii=False)}: {rep['count']} gaps"]
    for kind in KINDS:
        items = rep['gaps'][kind]
        if items:
            lines.append(f"{kind} ({len(items)}): " + ' · '.join(item(kind, e) for e in items))
    if rep['unchecked']:
        lines.append('not checked (no component in the subtree): ' + ', '.join(rep['unchecked']))
    return '\n'.join(lines)


def collect(root, a):
    run = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figma_run.py')
    if not os.path.exists(run):
        fail(f'figma_run.py not found next to {os.path.basename(__file__)}; copy it alongside')
    fd, path = tempfile.mkstemp(prefix='figma_fidelity_', suffix='.js')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(COLLECT % json.dumps(root))
        cmd = [sys.executable, run, *(['--file', a.file] if a.file else []), *(['--timeout', a.timeout] if a.timeout else []), path]
        r = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(path)
    if r.returncode != 0:
        fail((r.stderr or r.stdout).strip()[:600])
    try:
        out = json.loads(r.stdout)
    except ValueError:
        fail(f'unreadable eval output: {r.stdout.strip()[:300]}')
    if not isinstance(out, dict) or 'texts' not in out:
        fail(f'unexpected eval output: {r.stdout.strip()[:300]}')
    return out


# ---- --elements: per element, against a capture spec ----------------------------------------

ELEMENTS = r"""
(async function (ROOT_ID) {
  var root = await figma.getNodeByIdAsync(ROOT_ID);
  if (!root) throw new Error('figma_fidelity: no node ' + ROOT_ID);
  function hex(c) { function h(v) { var s = Math.round(v * 255).toString(16); return s.length < 2 ? '0' + s : s; } return '#' + h(c.r) + h(c.g) + h(c.b); }
  function paint(list) {
    if (!list || list === figma.mixed) return null;
    for (var i = 0; i < list.length; i++) if (list[i].type === 'SOLID' && list[i].visible !== false) return { hex: hex(list[i].color), a: list[i].opacity === undefined ? 1 : list[i].opacity };
    return null;
  }
  function num(v) { return typeof v === 'number' ? v : null; }
  var out = [], base = root.absoluteBoundingBox;
  function walk(n, parent, ox, oy) {
    var bb = n.absoluteBoundingBox, x, y;
    if (bb && base) { x = bb.x - base.x; y = bb.y - base.y; }
    else { x = n === root ? 0 : ox + n.x; y = n === root ? 0 : oy + n.y; }
    var e = { id: n.id, name: n.name, type: n.type, parent: parent, x: x, y: y, w: n.width, h: n.height,
      visible: n.visible !== false, opacity: num(n.opacity), fill: paint(n.fills), radius: num(n.cornerRadius) };
    if (n.type === 'TEXT') {
      e.text = n.characters;
      e.family = n.fontName === figma.mixed ? null : n.fontName.family;
      e.style = n.fontName === figma.mixed ? null : n.fontName.style;
      e.size = num(n.fontSize);
      e.lineHeight = n.lineHeight && n.lineHeight.unit === 'PIXELS' ? n.lineHeight.value : null;
      e.letterSpacing = n.letterSpacing && n.letterSpacing.unit === 'PIXELS' ? n.letterSpacing.value : null;
    }
    var me = out.length;
    out.push(e);
    // A group's children sit in the group's parent's coordinates.
    var cx = n.type === 'GROUP' ? ox : x, cy = n.type === 'GROUP' ? oy : y;
    if (n.children) for (var i = 0; i < n.children.length; i++) walk(n.children[i], me, cx, cy);
  }
  walk(root, -1, 0, 0);
  return { root: { id: root.id, name: root.name }, nodes: out };
})
"""

STYLE_WEIGHT = {'thin': 100, 'hairline': 100, 'extralight': 200, 'ultralight': 200, 'light': 300, 'regular': 400,
                'normal': 400, 'book': 400, 'medium': 500, 'semibold': 600, 'demibold': 600, 'bold': 700,
                'extrabold': 800, 'ultrabold': 800, 'black': 900, 'heavy': 900}
GENERIC_FAMILIES = {'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-sans-serif', 'ui-serif',
                    'ui-monospace', 'ui-rounded', '-apple-system', 'blinkmacsystemfont'}
CAP = re.compile(r'^\[cap:(\d+)\]')
WAIVE_FLAGS = {'grid': 'grid-display', 'transform': 'transform-3d'}


def lab(h):
    """sRGB hex → CIELAB (D65)."""
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v / 255) for v in rgb(h))
    x, y, z = ((r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047, r * 0.2126 + g * 0.7152 + b * 0.0722,
               (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883)
    f = lambda t: t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(h1, h2):
    """CIEDE2000 between two hex colors."""
    import math
    L1, a1, b1 = lab(h1)
    L2, a2, b2 = lab(h2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    G = 0.5 * (1 - math.sqrt(((C1 + C2) / 2) ** 7 / (((C1 + C2) / 2) ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dL, dC = L2 - L1, C2p - C1p
    dh = 0 if C1p * C2p == 0 else (h2p - h1p if abs(h2p - h1p) <= 180 else h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360)
    dH = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2))
    Lm, Cm = (L1 + L2) / 2, (C1p + C2p) / 2
    hm = h1p + h2p if C1p * C2p == 0 else ((h1p + h2p) / 2 if abs(h1p - h2p) <= 180 else (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2)
    T = 1 - 0.17 * math.cos(math.radians(hm - 30)) + 0.24 * math.cos(math.radians(2 * hm)) + 0.32 * math.cos(math.radians(3 * hm + 6)) \
        - 0.2 * math.cos(math.radians(4 * hm - 63))
    SL = 1 + 0.015 * (Lm - 50) ** 2 / math.sqrt(20 + (Lm - 50) ** 2)
    SC, SH = 1 + 0.045 * Cm, 1 + 0.015 * Cm * T
    RT = -2 * math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-((hm - 275) / 25) ** 2)))
    return math.sqrt((dL / SL) ** 2 + (dC / SC) ** 2 + (dH / SH) ** 2 + RT * (dC / SC) * (dH / SH))


def dice(a, b):
    a, b = ' '.join((a or '').split()), ' '.join((b or '').split())
    if a == b:
        return 1.0
    grams = lambda s: [s[i:i + 2] for i in range(len(s) - 1)]
    ga, gb = grams(a.lower()), grams(b.lower())
    if not ga or not gb:
        return 0.0
    rest, hit = list(gb), 0
    for g in ga:
        if g in rest:
            rest.remove(g)
            hit += 1
    return 2 * hit / (len(ga) + len(gb))


def chex(c):
    return hex_of(c) if c and c.get('a', 1) > 0 else None


def hex_of(c):
    return '#' + ''.join(f'{round(c[k] * 255):02x}' for k in 'rgb')


def pair(spec, fig):
    """{source i: {'frame': figma node or None, 'text': figma TEXT node or None}} and the pairing used."""
    nodes, src = fig['nodes'], spec['nodes']
    origin = src[0]['rect']
    box = lambda n: (n['rect']['x'] - origin['x'], n['rect']['y'] - origin['y'], n['rect']['w'], n['rect']['h'])
    gamma = lambda s, f: sum(abs(a - b) for a, b in zip(box(s), (f['x'], f['y'], f['w'], f['h'])))
    capped = [f for f in nodes if CAP.match(f['name'])]
    out = {s['i']: {'frame': None, 'text': None} for s in src}
    if len(capped) * 2 >= len(nodes):
        for f in capped:
            i = int(CAP.match(f['name']).group(1))
            if i not in out:
                continue
            slot = 'text' if f['type'] == 'TEXT' else 'frame'
            if out[i][slot] is None or gamma(src[i], f) < gamma(src[i], out[i][slot]):
                out[i][slot] = f
        return out, 'cap'
    used = set()
    for s in src:
        if not s.get('text'):
            continue
        best = max((f for f in nodes if f['type'] == 'TEXT' and f['id'] not in used),
                   key=lambda f: (dice(s['text'], f.get('text')), -gamma(s, f)), default=None)
        if best and dice(s['text'], best.get('text')) >= 0.5:
            out[s['i']]['text'] = best
            used.add(best['id'])
    for s in src:
        x, y, w, h = box(s)
        cands = [f for f in nodes if f['type'] != 'TEXT' and f['id'] not in used]
        best = min(cands, key=lambda f: gamma(s, f), default=None)
        if best and gamma(s, best) <= max(8, 0.1 * (w + h)):
            out[s['i']]['frame'] = best
            used.add(best['id'])
    return out, 'geometry'


def element_rows(spec, fig, waive=None):
    src, nodes = spec['nodes'], fig['nodes']
    pairs, how = pair(spec, fig)
    origin = src[0]['rect']
    byid = {f['id']: f for f in nodes}
    paired_ids = {p[k]['id'] for p in pairs.values() for k in ('frame', 'text') if p[k]}
    flagged = {f['i']: f['reason'] for f in spec.get('flagged', [])}

    def flag_of(i):
        while i >= 0:
            if i in flagged:
                return flagged[i]
            i = src[i]['parent']
        return None

    rows = []

    def row(kind, s, css, sv, f, prop, fv, **extra):
        rows.append({'kind': kind, 'source': {'i': s['i'], 'css_prop': css, 'value': sv},
                     'figma': {'id': f['id'], 'name': f['name'], 'prop': prop, 'value': fv} if f else None, **extra})

    def anchor(i):
        """The nearest paired ancestor's source rect and Figma node, for positions against the parent."""
        p = src[i]['parent']
        while p >= 0 and not (pairs[p]['frame'] or pairs[p]['text']):
            p = src[p]['parent']
        return (src[p]['rect'], pairs[p]['frame'] or pairs[p]['text']) if p >= 0 else (origin, None)

    root_area = max(origin['w'] * origin['h'], 1)
    for s in src:
        p, st = pairs[s['i']], s.get('styles') or {}
        f, t = p['frame'] or p['text'], p['text']
        if not f:
            up = s['parent']
            if up < 0 or pairs[up]['frame'] or pairs[up]['text']:
                row('missing-node', s, None, [s['rect'][k] for k in 'xywh'], None, None, None,
                    weight=round(s['rect']['w'] * s['rect']['h'] / root_area, 4))
            continue
        r = s['rect']
        if s['parent'] >= 0:
            prect, pf = anchor(s['i'])
            sx, sy = r['x'] - prect['x'], r['y'] - prect['y']
            fx, fy = (f['x'] - pf['x'], f['y'] - pf['y']) if pf else (f['x'], f['y'])
            if abs(sx - fx) > 2 or abs(sy - fy) > 2:
                row('position', s, 'left/top', [round(sx, 2), round(sy, 2)], f, 'x/y', [round(fx, 2), round(fy, 2)])
        if abs(r['w'] - f['w']) > 2 or abs(r['h'] - f['h']) > 2:
            row('size', s, 'width/height', [r['w'], r['h']], f, 'width/height', [round(f['w'], 2), round(f['h'], 2)])
        if not f['visible']:
            row('visibility', s, 'visibility', 'visible', f, 'visible', False)
        frame = p['frame']
        bg = chex(st.get('bg'))
        got = frame and frame['fill'] and frame['fill']['a'] > 0 and frame['fill']['hex']
        if frame and (bg or got) and not (bg and got and delta_e(bg, got) <= 2.3):
            row('color', s, 'background-color', bg, frame, 'fills', got or None)
        if frame and 'radius' in st and frame['radius'] is not None and abs(st['radius'] - frame['radius']) > 0.5:
            row('radius', s, 'border-radius', st['radius'], frame, 'cornerRadius', frame['radius'])
        if frame and abs(st.get('opacity', 1) - (frame['opacity'] if frame['opacity'] is not None else 1)) > 0.02:
            row('opacity', s, 'opacity', st.get('opacity', 1), frame, 'opacity', frame['opacity'])
        if s.get('text') and t:
            if dice(s['text'], t.get('text')) < 1:
                row('text', s, 'content', s['text'], t, 'characters', t.get('text'))
            c, tc = chex(st.get('color')), t['fill'] and t['fill']['hex']
            if c and (not tc or delta_e(c, tc) > 2.3):
                row('color', s, 'color', c, t, 'fills', tc)
            if t.get('size') is not None and abs(st.get('fontSize', 16) - t['size']) > 0.5:
                row('font-size', s, 'font-size', st.get('fontSize', 16), t, 'fontSize', t['size'])
            w = STYLE_WEIGHT.get(re.sub(r'[\s_-]|italic|oblique', '', (t.get('style') or '').lower()) or 'regular')
            if w and w != st.get('fontWeight', 400):
                row('font-weight', s, 'font-weight', st.get('fontWeight', 400), t, 'fontName.style', t.get('style'))
            fam = (st.get('fontFamily') or '').strip()
            if fam and fam.lower() not in GENERIC_FAMILIES and t.get('family') and fam.lower() != t['family'].lower():
                row('font-family', s, 'font-family', fam, t, 'fontName.family', t['family'])
            if st.get('lineHeight') and t.get('lineHeight') is not None and abs(st['lineHeight'] - t['lineHeight']) > 0.5:
                row('line-height', s, 'line-height', st['lineHeight'], t, 'lineHeight', t['lineHeight'])
            if abs(st.get('letterSpacing', 0) - (t.get('letterSpacing') or 0)) > 0.5:
                row('letter-spacing', s, 'letter-spacing', st.get('letterSpacing', 0), t, 'letterSpacing', t.get('letterSpacing'))
    # Every paired child of one element off by the same amount: its padding or gap, one row on it.
    kids = {}
    for s in src:
        if s['parent'] >= 0 and (pairs[s['i']]['frame'] or pairs[s['i']]['text']):
            kids.setdefault(s['parent'], []).append(s['i'])
    moved = {r['source']['i']: r for r in rows if r['kind'] == 'position'}
    for parent, ks in kids.items():
        if len(ks) < 2 or not all(k in moved for k in ks):
            continue
        shifts = {(round(moved[k]['figma']['value'][0] - moved[k]['source']['value'][0]),
                   round(moved[k]['figma']['value'][1] - moved[k]['source']['value'][1])) for k in ks}
        if len(shifts) == 1:
            dx, dy = shifts.pop()
            rows = [r for r in rows if not (r['kind'] == 'position' and r['source']['i'] in ks)]
            pf = pairs[parent]['frame'] or pairs[parent]['text']
            rows.append({'kind': 'spacing', 'source': {'i': parent, 'css_prop': 'padding/gap', 'value': [0, 0]},
                         'figma': {'id': pf['id'] if pf else None, 'name': pf['name'] if pf else None, 'prop': 'padding/itemSpacing',
                                   'value': [dx, dy]}})
    for f in nodes:
        if f['id'] in paired_ids or not f['visible'] or f['name'] == 'spacer' or f['parent'] < 0:
            continue
        up = nodes[f['parent']]
        if up['id'] in paired_ids or up['parent'] < 0:
            rows.append({'kind': 'extra-node', 'source': None, 'figma': {'id': f['id'], 'name': f['name'], 'prop': None, 'value': None},
                         'weight': round(f['w'] * f['h'] / root_area, 4), 'rect': [f['x'], f['y'], f['w'], f['h']]})
    waived = {}
    if waive:
        listed = {l['id'] for l in waive}
        kept = []
        for r in rows:
            loss = WAIVE_FLAGS.get(flag_of(r['source']['i'])) if r['source'] else None
            if loss in listed:
                waived[loss] = waived.get(loss, 0) + 1
            else:
                kept.append(r)
        rows = kept
    paired = sum(1 for p in pairs.values() if p['frame'] or p['text'])
    return {'root': fig['root'], 'pairing': how, 'paired': paired, 'elements': len(src), 'rows': rows, 'waived': waived}


def render_elements(rep):
    by = {}
    for r in rep['rows']:
        by[r['kind']] = by.get(r['kind'], 0) + 1
    n = len(rep['rows'])
    head = (f"elements {rep['root']['id']} {json.dumps(rep['root']['name'], ensure_ascii=False)}: {n} gap{'' if n == 1 else 's'}"
            + (' (' + ', '.join(f'{k} {v}' for k, v in sorted(by.items())) + ')' if by else '')
            + f", {rep['paired']} of {rep['elements']} paired by {rep['pairing']}"
            + (', waived ' + ', '.join(f'{k} {v}' for k, v in rep['waived'].items()) if rep['waived'] else ''))
    lines = [head]
    for r in rep['rows']:
        s, f = r['source'], r['figma']
        where = f"[cap:{s['i']}]" if s else f"{f['id']} {json.dumps(f['name'], ensure_ascii=False)}"
        val = '' if r['kind'] in ('missing-node', 'extra-node') else f": {s['css_prop']} {json.dumps(s['value'], ensure_ascii=False)} → {f['prop']} {json.dumps(f['value'], ensure_ascii=False)}"
        lines.append(f"{r['kind']} {where}{' ' + f['id'] if s and f else ''}{val}")
    for g in rep.get('unexplained', []):
        lines.append(f"unexplained {g['rect']} ({g['cells']} cells)" + (': ' + ' '.join(g['crops']) if g.get('crops') else ''))
    return '\n'.join(lines)


# ---- --pixels: what the rows don't explain ----------------------------------------------------

def png_read(data):
    """(width, height, RGB bytes) of an 8-bit, non-interlaced PNG; alpha is composited on white."""
    import struct, zlib
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    pos, idat, w = 8, [], None
    while pos < len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b'IHDR':
            w, h, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', body)
            if depth != 8 or ctype not in (0, 2, 4, 6) or interlace:
                raise ValueError(f'unsupported PNG (depth {depth}, color type {ctype}, interlace {interlace})')
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
        pos += n + 12
    bpp = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw, stride = zlib.decompress(b''.join(idat)), w * bpp
    out, prev = bytearray(w * h * 3), bytearray(stride)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b, c = prev[x], prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        for x in range(w):
            px = line[x * bpp:(x + 1) * bpp]
            rgb = (px[0], px[0], px[0]) if ctype in (0, 4) else (px[0], px[1], px[2])
            alpha = px[-1] if ctype in (4, 6) else 255
            o = (y * w + x) * 3
            for k in range(3):
                out[o + k] = (rgb[k] * alpha + 255 * (255 - alpha)) // 255
        prev = line
    return w, h, out


def png_write(path, w, h, rgb):
    import struct, zlib
    chunk = lambda kind, body: struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    raw = b''.join(b'\x00' + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def crop(img, scale, box):
    w, h, px = img
    x0, y0 = int(box[0] * scale), int(box[1] * scale)
    x1, y1 = min(w, int((box[0] + box[2]) * scale)), min(h, int((box[1] + box[3]) * scale))
    out = bytearray()
    for y in range(y0, y1):
        out += px[(y * w + x0) * 3:(y * w + x1) * 3]
    return max(x1 - x0, 0), max(y1 - y0, 0), out


def residual(spec, rep, src, fig, cell=8, tol=24, crops=None):
    """Regions where the screenshot and the export differ that no row of rep accounts for."""
    origin = spec['nodes'][0]['rect']
    W, H = origin['w'], origin['h']
    viewport = (spec.get('meta') or {}).get('viewport', {}).get('w') or W
    ss, fs = src[0] / viewport, fig[0] / W

    def mean(img, scale, off, x, y):
        """The mean color of one cell, sampling every other pixel; off is where the root sits in img."""
        w, h, px = img
        x0, y0 = int((x + off[0]) * scale), int((y + off[1]) * scale)
        n, acc = 0, [0, 0, 0]
        for yy in range(y0, min(h, y0 + max(1, int(cell * scale))), 2):
            for xx in range(x0, min(w, x0 + max(1, int(cell * scale))), 2):
                o = (yy * w + xx) * 3
                acc[0] += px[o]; acc[1] += px[o + 1]; acc[2] += px[o + 2]
                n += 1
        return [v / n for v in acc] if n else None

    box = lambda r: (r['x'] - origin['x'], r['y'] - origin['y'], r['w'], r['h'])
    texts = [box(n['rect']) for n in spec['nodes'] if (n.get('text') or '').strip()]
    hit = lambda a, b: a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
    cols, rows_n = int(W // cell) + 1, int(H // cell) + 1
    bad = set()
    for cy in range(rows_n):
        for cx in range(cols):
            c = (cx * cell, cy * cell, cell, cell)
            if any(hit(c, t) for t in texts):
                continue
            a, b = mean(src, ss, (origin['x'], origin['y']), c[0], c[1]), mean(fig, fs, (0, 0), c[0], c[1])
            if a and b and max(abs(p - q) for p, q in zip(a, b)) > tol:
                bad.add((cx, cy))
    regions, seen = [], set()
    for start in sorted(bad):
        if start in seen:
            continue
        stack, cells = [start], []
        seen.add(start)
        while stack:
            cx, cy = stack.pop()
            cells.append((cx, cy))
            for n in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if n in bad and n not in seen:
                    seen.add(n)
                    stack.append(n)
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        regions.append({'rect': [min(xs) * cell, min(ys) * cell, (max(xs) - min(xs) + 1) * cell, (max(ys) - min(ys) + 1) * cell], 'cells': len(cells)})
    explaining = []
    for r in rep['rows']:
        if r['source']:
            explaining.append(box(spec['nodes'][r['source']['i']]['rect']))
        elif r.get('rect'):
            explaining.append(tuple(r['rect']))
    out = [g for g in regions if not any(hit(g['rect'], e) for e in explaining)]
    if crops:
        os.makedirs(crops, exist_ok=True)
        for k, g in enumerate(out, 1):
            x, y, w, h = g['rect']
            g['crops'] = []
            for side, img, scale, off in (('source', src, ss, (origin['x'], origin['y'])), ('figma', fig, fs, (0, 0))):
                cw, ch, px = crop(img, scale, (x + off[0], y + off[1], w, h))
                path = os.path.join(crops, f'unexplained-{k}-{side}.png')
                if cw and ch:
                    png_write(path, cw, ch, px)
                    g['crops'].append(path)
    return out


EXPORT = r"""
(async function (ROOT_ID) {
  var root = await figma.getNodeByIdAsync(ROOT_ID);
  if (!root) throw new Error('figma_fidelity: no node ' + ROOT_ID);
  var bytes = await root.exportAsync({ format: 'PNG', constraint: { type: 'SCALE', value: 1 } });
  return figma.base64Encode(bytes);
})
"""


def run_collect(script, a):
    run = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figma_run.py')
    if not os.path.exists(run):
        fail(f'figma_run.py not found next to {os.path.basename(__file__)}; copy it alongside')
    fd, path = tempfile.mkstemp(prefix='figma_fidelity_', suffix='.js')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(script)
        cmd = [sys.executable, run, *(['--file', a.file] if a.file else []), *(['--timeout', a.timeout] if a.timeout else []), path]
        r = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(path)
    if r.returncode != 0:
        fail((r.stderr or r.stdout).strip()[:600])
    try:
        return json.loads(r.stdout)
    except ValueError:
        fail(f'unreadable eval output: {r.stdout.strip()[:300]}')


def main():
    ap = argparse.ArgumentParser(prog='figma_fidelity.py', description='Diff a Figma subtree against a figma_source.py manifest')
    ap.add_argument('manifest')
    ap.add_argument('root', help='node id of the subtree, e.g. 12:34')
    ap.add_argument('--file', default=os.environ.get('FIGMA_FILE'), help='Figma file URL or key (perch backend)')
    ap.add_argument('--timeout', help='seconds the eval may await (passed to figma_run.py)')
    ap.add_argument('--json', action='store_true', help='print the full report as JSON')
    ap.add_argument('--scope', action='append', default=[], help="one screen's markup file (repeat or comma-separate): only its copy, components and stretched usages count as missing")
    ap.add_argument('--elements', action='store_true', help='per element: the first argument is a figma_capture.py walk spec')
    ap.add_argument('--waive', help='with --elements: known_losses.json; rows under an element flagged for a listed loss are counted, not listed')
    ap.add_argument('--pixels', help='with --elements: a full-page screenshot of the walked page; adds the regions no row explains')
    ap.add_argument('--figma-png', help='with --pixels: the subtree exported at scale 1 already (skips the export)')
    ap.add_argument('--crops', help='with --pixels: write a source and a Figma crop of each unexplained region here')
    a = ap.parse_args()
    if a.elements:
        try:
            with open(a.manifest) as f:
                spec = json.load(f)
            waive = None
            if a.waive:
                with open(a.waive) as f:
                    waive = json.load(f)['losses']
        except (OSError, ValueError, KeyError) as e:
            fail(f'cannot read {a.manifest if not a.waive else a.manifest + " or " + a.waive}: {e}')
        if not spec.get('nodes'):
            fail(f'{a.manifest} has no nodes; pass a figma_capture.py walk spec')
        fig = run_collect(ELEMENTS + f'({json.dumps(a.root)})', a)
        if not isinstance(fig, dict) or 'nodes' not in fig:
            fail(f'unexpected eval output: {str(fig)[:300]}')
        rep = element_rows(spec, fig, waive)
        if a.pixels:
            import base64
            try:
                with open(a.pixels, 'rb') as f:
                    src = png_read(f.read())
                if a.figma_png:
                    with open(a.figma_png, 'rb') as f:
                        exported = f.read()
                else:
                    exported = base64.b64decode(run_collect(EXPORT + f'({json.dumps(a.root)})', a))
                rep['unexplained'] = residual(spec, rep, src, png_read(exported), crops=a.crops)
            except (OSError, ValueError) as e:
                fail(f'--pixels: {e}')
        print(json.dumps(rep, indent=1, ensure_ascii=False) if a.json else render_elements(rep))
        sys.exit(0)
    try:
        with open(a.manifest) as f:
            m = json.load(f)
    except (OSError, ValueError) as e:
        fail(f'cannot read manifest {a.manifest}: {e}')
    scopes = [s for v in a.scope for s in v.split(',')]
    rep = diff(scoped(m, scopes), collect(a.root, a), vouch=m) if scopes else diff(m, collect(a.root, a))
    print(json.dumps(rep, indent=1, ensure_ascii=False) if a.json else render(rep))
    # Gaps are the report: exit 0 whenever the check ran, so a shell doesn't read them as a failed call.
    sys.exit(0)


if __name__ == '__main__':
    main()
