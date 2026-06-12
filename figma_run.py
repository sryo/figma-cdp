#!/usr/bin/env python3
"""Run a Figma Plugin API script via agent-browser.

Reads a .js file, base64-encodes it, and passes to agent-browser eval.
Avoids shell syntax (heredocs, pipes, redirects) that trigger Claude Code warnings.

Port: FIGMA_CDP_PORT if set, else the browser's DevToolsActivePort file, else 9222.
"""
import base64, os, subprocess, sys

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
    print("Usage: python3 figma_run.py <js_file>", file=sys.stderr)
    sys.exit(1)

try:
    with open(sys.argv[1], 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
except OSError:
    print(f'figma_run.py: no such file: {sys.argv[1]}', file=sys.stderr)
    sys.exit(1)

if len(b64) > 200_000:
    print('payload >200KB — use agent-browser batch stdin JSON mode '
          '(see references/execution.md → Batched evals)', file=sys.stderr)
    sys.exit(1)

try:
    r = subprocess.run(
        ['agent-browser', '--cdp', cdp_port(), 'eval', '-b', b64],
        capture_output=True, text=True
    )
except FileNotFoundError:
    print('agent-browser not found — npm i -g agent-browser && agent-browser install',
          file=sys.stderr)
    sys.exit(1)

print(r.stdout, end='')
if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
