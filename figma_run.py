#!/usr/bin/env python3
"""Run a Figma Plugin API script via agent-browser.

Reads a .js file, base64-encodes it, and passes to agent-browser eval.
Avoids shell syntax (heredocs, pipes, redirects) that trigger Claude Code warnings.

Set FIGMA_CDP_PORT to use a port other than 9222 (e.g. for Mode A attach).
"""
import base64, os, subprocess, sys

if len(sys.argv) < 2:
    print("Usage: python3 figma_run.py <js_file>", file=sys.stderr)
    sys.exit(1)

with open(sys.argv[1], 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()

port = os.environ.get('FIGMA_CDP_PORT', '9222')
r = subprocess.run(
    ['agent-browser', '--cdp', port, 'eval', '-b', b64],
    capture_output=True, text=True
)

print(r.stdout, end='')
if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
