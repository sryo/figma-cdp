#!/usr/bin/env python3
"""Walk a live public page into a Figma capture spec (the importer runs separately).

Binds an isolated `--session capture` to the CDP port (per phase-5 spike: connect,
don't rely on --cdp retargeting a live session), opens the URL there, runs
figma_walker.js, and persists the JSON the walker returns over the WebSocket to
/tmp/figma_capture_<slug>.json. Prints that path plus a node/flagged-subtree summary.

Port: FIGMA_CDP_PORT if set, else the browser's DevToolsActivePort file, else 9222.
Public/unauthenticated pages only (isolated session has no Chrome login).
"""
import base64, json, os, re, subprocess, sys

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

def ab(*args):
    try:
        return subprocess.run(['agent-browser', '--session', 'capture', *args],
                              capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit('agent-browser not found — npm i -g agent-browser && agent-browser install')

if len(sys.argv) < 2:
    sys.exit('Usage: python3 figma_capture.py <url> [wait_ms]')
url = sys.argv[1]
wait_ms = sys.argv[2] if len(sys.argv) > 2 else '2000'
here = os.path.dirname(os.path.abspath(__file__))
try:
    with open(os.path.join(here, 'figma_walker.js'), 'rb') as f:
        walker_b64 = base64.b64encode(f.read()).decode()
except OSError:
    sys.exit('figma_capture.py: figma_walker.js not found next to this script')

if ab('connect', cdp_port()).returncode != 0:
    sys.exit(f'figma_capture.py: could not connect capture session to CDP {cdp_port()}')
if ab('open', url).returncode != 0:
    sys.exit(f'figma_capture.py: could not open {url} in capture session')
ab('wait', wait_ms)

r = ab('eval', '-b', walker_b64, '--json')
try:
    result = json.loads(r.stdout)['data']['result']
except (ValueError, KeyError, TypeError):
    sys.exit(f'figma_capture.py: walker returned no parseable result — {r.stdout[:200]}{r.stderr[:200]}')
if not isinstance(result, dict) or 'nodes' not in result:
    sys.exit(f'figma_capture.py: walker result missing nodes — {str(result)[:200]}')

slug = re.sub(r'[^a-z0-9]+', '-', re.sub(r'^https?://', '', url).lower()).strip('-')[:60] or 'page'
out = f'/tmp/figma_capture_{slug}.json'
with open(out, 'w') as f:
    json.dump(result, f)
print(f'spec: {out}')
print(f'nodes: {result["meta"]["nodeCount"]}  flagged-subtrees: {len(result.get("flagged", []))}')
