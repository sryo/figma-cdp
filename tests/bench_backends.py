#!/usr/bin/env python3
"""Time figma_run.py / figma_batch_run.py on the cdp and perch backends against one open file.

Every script is read-only: no node creation, edits, selection or page changes.

  python3 tests/bench_backends.py --file <url-or-key> --small <nodeId> --large <nodeId> \
      [--runs 10] [--out DIR] [--only op,op]

The cdp backend needs a live agent-browser connection (FIGMA_CDP_PORT or
DevToolsActivePort); perch needs eval_js world:"main". Three columns: cdp,
perch (through the figma_perch.mjs daemon) and perch1 (FIGMA_PERCH_DAEMON=0,
a node run per call). Runs are interleaved per op so drift hits all alike.
Writes DIR/results.json (every sample) and prints a median/p90 table.
Cold start is each backend's first call in this process (a 1+1) with no perch
daemon running; --cold N repeats the perch one N times, stopping the daemon
before each. A cold cdp connection is not timed: it waits on Chrome's
"Allow debugging?" prompt. agent-browser evaluates in its session's current tab,
not by file: when that tab shows another file, cdp is timed on 1+1 only and
results.json says which page it was on.
"""
import argparse, hashlib, json, os, socket, statistics, subprocess, sys, time

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
    """Both backends print {origin, result} per script; compare the results."""
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

BACKENDS = ['cdp', 'perch', 'perch1']

def stop_perch_daemons():
    """Stop every figma_perch.mjs daemon of this user; returns how many answered."""
    d = os.path.join(os.environ.get('TMPDIR') or '/tmp', f'figma-perch-{os.getuid()}')
    n = 0
    for name in (os.listdir(d) if os.path.isdir(d) else []):
        if not name.endswith('.sock'):
            continue
        path = os.path.join(d, name)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(5)
            s.connect(path)
            f = s.makefile('rb')
            f.readline()
            s.sendall(b'{"op":"stop"}\n')
            f.read()
            n += 1
        except OSError:
            pass
        finally:
            s.close()
        deadline = time.monotonic() + 5
        while os.path.exists(path) and time.monotonic() < deadline:
            time.sleep(0.01)
    time.sleep(0.2)
    return n

def call(backend, argv):
    env = dict(os.environ, FIGMA_BACKEND=backend.rstrip('1'))
    if backend == 'perch1':
        env['FIGMA_PERCH_DAEMON'] = '0'
    else:
        env.pop('FIGMA_PERCH_DAEMON', None)
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
    ap.add_argument('--cold', type=int, default=0, help='extra perch cold starts, daemon stopped before each')
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

    backends = BACKENDS
    res = {'meta': {'file': a.file, 'small': a.small, 'large': a.large, 'runs': a.runs,
                    'started': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'loadavg_start': os.getloadavg()}, 'cold': {}, 'ops': {}}
    probe = os.path.join(sdir, 'href.js')
    with open(probe, 'w') as f:
        f.write('location.href\n')
    _, r = call('cdp', [sys.executable, RUN, '--file', a.file, probe])
    href = parse_single(r.stdout) if r.returncode == 0 else None
    key = a.file.split('/design/')[-1].split('/')[0]
    cdp_on_file = isinstance(href, str) and f'/{key}' in href
    res['meta']['cdp_page'] = href if r.returncode == 0 else (r.stderr or r.stdout).strip()[:200]
    if not cdp_on_file:
        print(f'cdp is not on {key} ({res["meta"]["cdp_page"]}); timing cdp on 1+1 only', file=sys.stderr)
    stop_perch_daemons()
    for b in backends:
        dt, r = call(b, argv('trivial'))
        res['cold'][b] = {'ms': dt, 'rc': r.returncode, 'out': r.stdout.strip()[:80]}
        print(f'cold {b}: {dt:.0f} ms rc={r.returncode}', file=sys.stderr)
    if a.cold:
        xs = []
        for _ in range(a.cold):
            stop_perch_daemons()
            dt, r = call('perch', argv('trivial'))
            if r.returncode == 0:
                xs.append(dt)
        res['cold']['perch_samples'] = xs
        print(f'cold perch x{len(xs)}: median {statistics.median(xs):.0f} ms, p90 {pct(xs, 0.9):.0f} ms', file=sys.stderr)

    ops = ['trivial', 'typeof', 'pages', 'components', 'export_small', 'export_large', 'batch4']
    if a.only:
        ops = [o for o in ops if o in a.only.split(',')]
    for op in ops:
        rec = {b: {'ms': [], 'bytes': None, 'digest': None, 'errors': [], 'first_ms': None} for b in BACKENDS}
        backends = BACKENDS if cdp_on_file or op == 'trivial' else [b for b in BACKENDS if b != 'cdp']
        for b in backends:
            dt, r = call(b, argv(op))
            rec[b]['first_ms'] = dt
        for i in range(a.runs):
            for b in backends[i % len(backends):] + backends[:i % len(backends)]:
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
        for b in BACKENDS:
            xs = rec[b]['ms']
            rec[b]['median'] = statistics.median(xs) if xs else None
            rec[b]['p90'] = pct(xs, 0.9) if xs else None
        rec['identical'] = len({rec[b]['digest'] for b in backends}) == 1 and rec[backends[0]]['digest'] is not None
        res['ops'][op] = rec
        c, p, q = rec['cdp'], rec['perch'], rec['perch1']
        print(f"{op:13s} cdp {c['median'] or 0:6.0f}/{c['p90'] or 0:6.0f}  perch {p['median'] or 0:6.0f}/{p['p90'] or 0:6.0f}"
              f"  perch1 {q['median'] or 0:6.0f}/{q['p90'] or 0:6.0f}"
              f"  perch/cdp {'x%.2f' % (p['median'] / c['median']) if c['median'] and p['median'] else 'n/a'}"
              f"  bytes {c['bytes']}/{p['bytes']}/{q['bytes']}  same={rec['identical']}"
              f"  err {len(c['errors'])}/{len(p['errors'])}/{len(q['errors'])}", file=sys.stderr)
    res['meta']['loadavg_end'] = os.getloadavg()
    with open(os.path.join(a.out, 'results.json'), 'w') as f:
        json.dump(res, f, indent=2)

if __name__ == '__main__':
    main()
