#!/usr/bin/env python3
"""Run N Figma Plugin API scripts in one agent-browser (or perch) invocation.

Each script is base64-encoded and packed into a single `agent-browser batch`
call, eliminating per-eval CLI cold-start (~200ms saved per extra script).
Prefer over multiple figma_run.py calls for >= 3 sequential evals with no
intermediate inspection. Each result is printed under a '== <file> ==' header.
On the perch backend one figma_perch.mjs run evaluates the scripts in order.

  python3 figma_batch_run.py [--file <figma-url-or-key>] <js_file> [<js_file> ...]

Backend: FIGMA_BACKEND=cdp|perch if set; else cdp when FIGMA_CDP_PORT is set;
else perch when a perch with eval_js world:"main" is at PERCH_DIR (default
~/Documents/perch), which needs no remote debugging; else cdp.
CDP port: FIGMA_CDP_PORT if set, else the browser's DevToolsActivePort file, else 9222.
perch tab: --file (or FIGMA_FILE) names the file; needed when several are open.
"""
import argparse, base64, json, os, subprocess, sys

def cdp_port():
    p = os.environ.get('FIGMA_CDP_PORT')
    if p:
        return p
    for d in ('Library/Application Support/Google/Chrome',
              '.config/google-chrome',
              'Library/Application Support/BraveSoftware/Brave-Browser',
              'Library/Application Support/Google/Chrome Canary'):
        try:
            with open(os.path.expanduser(f'~/{d}/DevToolsActivePort')) as f:
                return str(int(f.readline()))
        except (OSError, ValueError):
            pass
    return '9222'

def perch_ready():
    entry = os.path.join(os.environ.get('PERCH_DIR') or os.path.expanduser('~/Documents/perch'), 'server.js')
    try:
        with open(entry) as f:
            return 'buildMainKick' in f.read()
    except OSError:
        return False

def backend():
    b = os.environ.get('FIGMA_BACKEND', '').lower()
    if b in ('cdp', 'perch'):
        return b
    if b:
        sys.exit(f"FIGMA_BACKEND must be 'cdp' or 'perch', not '{b}'")
    if os.environ.get('FIGMA_CDP_PORT'):
        return 'cdp'
    return 'perch' if perch_ready() else 'cdp'

def perch(op, file, *paths):
    """Run figma_perch.mjs (next to this script) and return its JSON reply."""
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figma_perch.mjs')
    if not os.path.exists(helper):
        sys.exit(f'figma_perch.mjs not found next to {os.path.basename(__file__)}; copy it alongside')
    try:
        r = subprocess.run(['node', helper, op, file or '', *paths], capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit('node not found; the perch backend needs Node 18+')
    try:
        out = json.loads(r.stdout)
    except ValueError:
        sys.exit(f'perch: no reply from figma_perch.mjs (exit {r.returncode}): {(r.stdout + r.stderr).strip()[:400]}')
    if out.get('fatal') and not out.get('results'):
        sys.exit(f"perch: {out['fatal']}")
    return out

ap = argparse.ArgumentParser(prog='figma_batch_run.py')
ap.add_argument('--file', default=os.environ.get('FIGMA_FILE'), help='Figma file URL or key (perch backend)')
ap.add_argument('js_files', nargs='+')
a = ap.parse_args()
for path in a.js_files:
    if not os.path.isfile(path):
        print(f'figma_batch_run.py: no such file: {path}', file=sys.stderr)
        sys.exit(1)

if backend() == 'perch':
    out = perch('eval', a.file, *a.js_files)
    # Same shape as agent-browser batch: a success prints {origin, result}, a failure its error.
    for path, res in zip(a.js_files, out['results']):
        print(f'== {os.path.basename(path)} ==')
        print(json.dumps({'origin': out['origin'], 'result': res['value']}, ensure_ascii=False)
              if res['ok'] else f"Evaluation error: {res['error']}")
    if out.get('fatal'):
        sys.exit(f"perch: {out['fatal']} (stopped after {len(out['results'])} of {len(a.js_files)} scripts)")
    sys.exit(0 if all(r['ok'] for r in out['results']) else 1)

cmds = []
for path in a.js_files:
    with open(path, 'rb') as f:
        cmds.append(f'eval -b {base64.b64encode(f.read()).decode()}')

if sum(len(c) for c in cmds) > 200_000:
    print('payload >200KB — use agent-browser batch stdin JSON mode '
          '(see references/execution.md → Batched evals), or the perch backend', file=sys.stderr)
    sys.exit(1)

try:
    r = subprocess.run(
        ['agent-browser', '--cdp', cdp_port(), 'batch', '--json'] + cmds,
        capture_output=True, text=True
    )
except FileNotFoundError:
    print('agent-browser not found — npm i -g agent-browser && agent-browser install',
          file=sys.stderr)
    sys.exit(1)

try:
    results = json.loads(r.stdout)
except ValueError:
    results = None

if isinstance(results, list):
    for path, res in zip(a.js_files, results):
        print(f'== {os.path.basename(path)} ==')
        body = res.get('result') if res.get('success') else res.get('error')
        print('' if body is None else body if isinstance(body, str) else json.dumps(body))
else:
    print(r.stdout, end='')

if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
