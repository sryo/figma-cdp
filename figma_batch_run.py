#!/usr/bin/env python3
"""Run N Figma Plugin API scripts in one agent-browser invocation.

Each script is base64-encoded and packed into a single `agent-browser batch`
call, eliminating per-eval CLI cold-start (~200ms saved per extra script).
Prefer over multiple figma_run.py calls for >= 3 sequential evals with no
intermediate inspection.

Set FIGMA_CDP_PORT to use a port other than 9222 (e.g. for Mode A attach).
"""
import base64, os, subprocess, sys

if len(sys.argv) < 2:
    print("Usage: python3 figma_batch_run.py <js_file> [<js_file> ...]", file=sys.stderr)
    sys.exit(1)

cmds = []
for path in sys.argv[1:]:
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    cmds.append(f'eval -b {b64}')

port = os.environ.get('FIGMA_CDP_PORT', '9222')
r = subprocess.run(
    ['agent-browser', '--cdp', port, 'batch'] + cmds,
    capture_output=True, text=True
)

print(r.stdout, end='')
if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
