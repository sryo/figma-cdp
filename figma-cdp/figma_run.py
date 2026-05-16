#!/usr/bin/env python3
"""Run a Figma Plugin API script via agent-browser.

Reads a .js file, base64-encodes it, and passes to agent-browser eval.
Avoids shell syntax (heredocs, pipes, redirects) that trigger Claude Code warnings.

Usage: python3 figma_run.py <js_file>
   or: python3 /tmp/figma_run.py <js_file>  (if copied to /tmp)
"""
import base64, subprocess, sys

if len(sys.argv) < 2:
    print("Usage: python3 figma_run.py <js_file>", file=sys.stderr)
    sys.exit(1)

with open(sys.argv[1], 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()

r = subprocess.run(
    ['agent-browser', '--cdp', '9222', 'eval', '-b', b64],
    capture_output=True, text=True
)

print(r.stdout, end='')
if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
