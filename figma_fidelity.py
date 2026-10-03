#!/usr/bin/env python3
"""Check a Figma subtree against a source manifest from figma_source.py.

  python3 figma_fidelity.py <manifest.json> <rootId> [--file <figma-url-or-key>] [--timeout <s>] [--json]

One eval through figma_run.py (next to this script, so CDP or perch as it picks) collects the
subtree's text, resolved solid colors, fonts, auto-layout spacing, radii and the component
sets behind it. The report lists, per kind, what differs from the manifest:
  missing copy / invented copy      source strings no text layer shows; text layers no source string has
  off-manifest colors, spacing, radii, font sizes, weights, fonts
  unbound                           a raw value equal to a source token while a local variable scoped for the field holds it
  missing variants / missing states for components the subtree uses (sets reached through instances too)
  missing components                a source component used 2+ times with no component in the subtree, or
                                    behind its instances, whose name (or a /-segment of it) starts with its words
A kind the manifest has no entries for is not checked. The first line counts the gaps; exit 0
when the check ran, gaps or not, 2 when it could not run.
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
    families: {}, comps: [], names: {}, vars: { color: {}, float: {} } };
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
    var owner = null;
    if (n.type === 'COMPONENT_SET') owner = n;
    else if (n.type === 'COMPONENT') owner = n.parent && n.parent.type === 'COMPONENT_SET' ? n.parent : n;
    else if (n.type === 'INSTANCE') {
      var main = await n.getMainComponentAsync();
      if (main) owner = main.parent && main.parent.type === 'COMPONENT_SET' ? main.parent : main;
    }
    if (owner && !mains[owner.id]) {
      mains[owner.id] = 1;
      var words = [];
      var defs = {};
      try { defs = owner.componentPropertyDefinitions || {}; } catch (e) { /* a set with errors throws; its child names still count */ }
      Object.keys(defs).forEach(function (k) { words.push(k.split('#')[0]); (defs[k].variantOptions || []).forEach(function (o) { words.push(o); }); });
      if (owner.type === 'COMPONENT_SET') owner.children.forEach(function (c) { words.push(c.name); });
      out.comps.push({ id: owner.id, name: owner.name, words: words });
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
         'missing states', 'missing components']
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


def diff(m, c):
    gaps = {k: [] for k in KINDS}
    texts = [{'full': norm(t['t']), 'lines': lines(t['t'])} for t in c['texts']]
    copy = [(norm(e['text']), pattern(e['text'])) for e in m.get('copy', [])]
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
            for w in k['words'] + [k['name']]:
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
            missing = [] if flat(g['prop']) in words else [g['prop']]
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
    for e in m.get('components', []):
        want = name_words(e['component'])
        if e['uses'] >= 2 and want and not any(name_words(seg)[:len(want)] == want for k in c['comps'] for seg in k['name'].split('/')):
            gaps['missing components'].append({'component': e['component'], 'uses': e['uses'], 'src': e['src']})
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


def main():
    ap = argparse.ArgumentParser(prog='figma_fidelity.py', description='Diff a Figma subtree against a figma_source.py manifest')
    ap.add_argument('manifest')
    ap.add_argument('root', help='node id of the subtree, e.g. 12:34')
    ap.add_argument('--file', default=os.environ.get('FIGMA_FILE'), help='Figma file URL or key (perch backend)')
    ap.add_argument('--timeout', help='seconds the eval may await (passed to figma_run.py)')
    ap.add_argument('--json', action='store_true', help='print the full report as JSON')
    a = ap.parse_args()
    try:
        with open(a.manifest) as f:
            m = json.load(f)
    except (OSError, ValueError) as e:
        fail(f'cannot read manifest {a.manifest}: {e}')
    rep = diff(m, collect(a.root, a))
    print(json.dumps(rep, indent=1, ensure_ascii=False) if a.json else render(rep))
    # Gaps are the report: exit 0 whenever the check ran, so a shell doesn't read them as a failed call.
    sys.exit(0)


if __name__ == '__main__':
    main()
