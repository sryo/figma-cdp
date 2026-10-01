#!/usr/bin/env python3
"""Time figma_run.py / figma_batch_run.py on the cdp and perch backends against one open file.

Every script is read-only: no node creation, edits, selection or page changes.

  python3 tests/bench_backends.py --file <url-or-key> --small <nodeId> --large <nodeId> \
      [--runs 10] [--out DIR] [--only op,op]

The cdp backend needs a live agent-browser connection (FIGMA_CDP_PORT or
DevToolsActivePort); perch needs eval_js world:"main". Runs are interleaved
cdp/perch per op so drift hits both alike. Writes DIR/results.json (every
sample) and prints a median/p90 table. Cold start is each backend's first call
in this process (a 1+1), timed before any warm-up.
"""
import argparse, hashlib, json, os, statistics, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == 'tests' else os.environ.get('FIGMA_CDP_DIR', HERE)
RUN = os.path.join(ROOT, 'figma_run.py')
BATCH = os.path.join(ROOT, 'figma_batch_run.py')

def scripts(small, large):
    return {
        'trivial': '1+1',
        'typeof': 'typeof figma',
        'pages': '(async () => { await figma.loadAllPagesAsync();\n'
                 '  return figma.root.children.map(p => ({ id: p.id, name: p.name, children: p.children.length })); })()',
        'pages_noload': 'figma.root.children.map(p => ({ id: p.id, name: p.name }))',
        'components': '(async () => {\n'
                      '  const p = figma.currentPage;\n'
                      '  const comps = p.findAllWithCriteria({ types: ["COMPONENT", "COMPONENT_SET"] })\n'
                      '    .map(n => ({ id: n.id, name: n.name, type: n.type, parent: n.parent && n.parent.type === "COMPONENT_SET" ? n.parent.id : null }));\n'
                      '  const uses = {};\n'
                      '  for (const i of p.findAllWithCriteria({ types: ["INSTANCE"] })) {\n'
                      '    const m = await i.getMainComponentAsync(); const k = m ? m.id : "missing"; uses[k] = (uses[k] || 0) + 1; }\n'
                      '  return { page: p.name, components: comps, instances: uses }; })()',
        'export_small': f'(async () => {{ const n = await figma.getNodeByIdAsync({json.dumps(small)});\n'
                        f'  const b = await n.exportAsync({{ format: "PNG" }});\n'
                        f'  return {{ id: n.id, w: n.width, h: n.height, bytes: b.length, png: figma.base64Encode(b) }}; }})()',
        'export_large': f'(async () => {{ const n = await figma.getNodeByIdAsync({json.dumps(large)});\n'
                        f'  const b = await n.exportAsync({{ format: "PNG", constraint: {{ type: "SCALE", value: 2 }} }});\n'
                        f'  return {{ id: n.id, w: n.width, h: n.height, bytes: b.length, png: figma.base64Encode(b) }}; }})()',
    }

BATCH_OPS = ['typeof', 'pages_noload', 'components', 'export_small']

def parse_single(out):
    try:
        return json.loads(out)
    except ValueError:
        return out.strip()

def parse_batch(out):
    """Both backends print {origin, result} per script; origin differs by design, so keep result."""
    vals = []
    for line in out.splitlines():
        if line.startswith('== ') and line.endswith(' =='):
            continue
        try:
            vals.append(json.loads(line)['result'])
        except (ValueError, KeyError, TypeError):
            vals.append(line)
    return vals

def digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

def call(backend, argv):
    env = dict(os.environ, FIGMA_BACKEND=backend)
    t = time.perf_counter()
    r = subprocess.run(argv, capture_output=True, text=True, env=env)
    dt = (time.perf_counter() - t) * 1000
    return dt, r

def pct(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--small', required=True)
    ap.add_argument('--large', required=True)
    ap.add_argument('--runs', type=int, default=10)
    ap.add_argument('--out', default='.')
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    sdir = os.path.join(a.out, 'scripts')
    os.makedirs(sdir, exist_ok=True)
    paths = {}
    for k, src in scripts(a.small, a.large).items():
        paths[k] = os.path.join(sdir, k + '.js')
        with open(paths[k], 'w') as f:
            f.write(src + '\n')

    def argv(op):
        if op == 'batch4':
            return [sys.executable, BATCH, '--file', a.file, *[paths[o] for o in BATCH_OPS]]
        return [sys.executable, RUN, '--file', a.file, paths[op]]

    backends = ['cdp', 'perch']
    res = {'meta': {'file': a.file, 'small': a.small, 'large': a.large, 'runs': a.runs,
                    'started': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'loadavg_start': os.getloadavg()}, 'cold': {}, 'ops': {}}
    for b in backends:
        dt, r = call(b, argv('trivial'))
        res['cold'][b] = {'ms': dt, 'rc': r.returncode, 'out': r.stdout.strip()[:80]}
        print(f'cold {b}: {dt:.0f} ms rc={r.returncode}', file=sys.stderr)

    ops = ['trivial', 'typeof', 'pages', 'components', 'export_small', 'export_large', 'batch4']
    if a.only:
        ops = [o for o in ops if o in a.only.split(',')]
    for op in ops:
        rec = {b: {'ms': [], 'bytes': None, 'digest': None, 'errors': [], 'first_ms': None} for b in backends}
        for b in backends:
            dt, r = call(b, argv(op))
            rec[b]['first_ms'] = dt
        for i in range(a.runs):
            for b in (backends if i % 2 == 0 else backends[::-1]):
                dt, r = call(b, argv(op))
                if r.returncode != 0:
                    rec[b]['errors'].append((r.stderr or r.stdout).strip()[:300])
                    continue
                rec[b]['ms'].append(dt)
                v = parse_batch(r.stdout) if op == 'batch4' else parse_single(r.stdout)
                d = digest(v)
                rec[b]['bytes'] = len(r.stdout.encode())
                if rec[b]['digest'] not in (None, d):
                    rec[b]['errors'].append(f'output changed between runs: {rec[b]["digest"]} -> {d}')
                rec[b]['digest'] = d
                if i == 0:
                    with open(os.path.join(a.out, f'{op}.{b}.out'), 'w') as f:
                        f.write(r.stdout)
        for b in backends:
            xs = rec[b]['ms']
            rec[b]['median'] = statistics.median(xs) if xs else None
            rec[b]['p90'] = pct(xs, 0.9) if xs else None
        rec['identical'] = rec['cdp']['digest'] is not None and rec['cdp']['digest'] == rec['perch']['digest']
        res['ops'][op] = rec
        c, p = rec['cdp'], rec['perch']
        print(f"{op:13s} cdp {c['median'] or 0:7.0f}/{c['p90'] or 0:7.0f}  perch {p['median'] or 0:7.0f}/{p['p90'] or 0:7.0f}"
              f"  x{(p['median'] or 0) / (c['median'] or 1):.2f}  bytes {c['bytes']}/{p['bytes']}  same={rec['identical']}"
              f"  err {len(c['errors'])}/{len(p['errors'])}", file=sys.stderr)
    res['meta']['loadavg_end'] = os.getloadavg()
    with open(os.path.join(a.out, 'results.json'), 'w') as f:
        json.dump(res, f, indent=2)

if __name__ == '__main__':
    main()
