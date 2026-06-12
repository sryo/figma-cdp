#!/usr/bin/env python3
"""Run N Figma Plugin API scripts in one agent-browser invocation.

Each script is base64-encoded and packed into a single `agent-browser batch`
call, eliminating per-eval CLI cold-start (~200ms saved per extra script).
Prefer over multiple figma_run.py calls for >= 3 sequential evals with no
intermediate inspection. Each result is printed under a '== <file> ==' header.

Port: FIGMA_CDP_PORT if set, else the browser's DevToolsActivePort file, else 9222.
"""
import base64, json, os, subprocess, sys

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

if len(sys.argv) < 2:
    print("Usage: python3 figma_batch_run.py <js_file> [<js_file> ...]", file=sys.stderr)
    sys.exit(1)

cmds = []
for path in sys.argv[1:]:
    try:
        with open(path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError:
        print(f'figma_batch_run.py: no such file: {path}', file=sys.stderr)
        sys.exit(1)
    cmds.append(f'eval -b {b64}')

if sum(len(c) for c in cmds) > 200_000:
    print('payload >200KB — use agent-browser batch stdin JSON mode '
          '(see references/execution.md → Batched evals)', file=sys.stderr)
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
    for path, res in zip(sys.argv[1:], results):
        print(f'== {os.path.basename(path)} ==')
        body = res.get('result') if res.get('success') else res.get('error')
        print('' if body is None else body if isinstance(body, str) else json.dumps(body))
else:
    print(r.stdout, end='')

if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
