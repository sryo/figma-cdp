#!/usr/bin/env python3
"""Run a Figma Plugin API script via agent-browser (CDP) or perch.

Reads a .js file and runs it in the Figma tab. Avoids shell syntax (heredocs,
pipes, redirects) that trigger Claude Code warnings.

  python3 figma_run.py [--file <figma-url-or-key>] <js_file>
  python3 figma_run.py [--file <figma-url-or-key>] --screenshot <out.png>

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

ap = argparse.ArgumentParser(prog='figma_run.py')
ap.add_argument('--file', default=os.environ.get('FIGMA_FILE'), help='Figma file URL or key (perch backend)')
ap.add_argument('--screenshot', metavar='PNG', help='capture the Figma tab instead of running a script')
ap.add_argument('js_file', nargs='?')
a = ap.parse_args()
if not a.screenshot and not a.js_file:
    print('Usage: python3 figma_run.py [--file <url-or-key>] <js_file> | --screenshot <out.png>', file=sys.stderr)
    sys.exit(1)
if a.js_file and not os.path.isfile(a.js_file):
    print(f'figma_run.py: no such file: {a.js_file}', file=sys.stderr)
    sys.exit(1)

if backend() == 'perch':
    if a.screenshot:
        print(f"✓ Screenshot saved to {perch('screenshot', a.file, a.screenshot)['path']}")
        sys.exit(0)
    res = perch('eval', a.file, a.js_file)['results'][0]
    if not res['ok']:
        print(f"✗ Evaluation error: {res['error']}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(res['value'], indent=2, ensure_ascii=False))
    sys.exit(0)

if a.screenshot:
    cmd = ['screenshot', a.screenshot]
else:
    with open(a.js_file, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    if len(b64) > 200_000:
        print('payload >200KB — use agent-browser batch stdin JSON mode '
              '(see references/execution.md → Batched evals), or the perch backend', file=sys.stderr)
        sys.exit(1)
    cmd = ['eval', '-b', b64]

try:
    r = subprocess.run(['agent-browser', '--cdp', cdp_port(), *cmd], capture_output=True, text=True)
except FileNotFoundError:
    print('agent-browser not found — npm i -g agent-browser && agent-browser install',
          file=sys.stderr)
    sys.exit(1)

print(r.stdout, end='')
if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
