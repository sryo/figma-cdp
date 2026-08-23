#!/usr/bin/env python3
"""Live page → capture spec → Figma nodes, as two subcommands.

  walk <url> [wait_ms]
      Binds an isolated `--session capture` to the CDP port (connect explicitly —
      a bare --cdp does not retarget a bound session), opens the URL, runs
      figma_walker.js (an async eval; the envelope returns over the WebSocket) and
      persists it to /tmp/figma_capture_<slug>.json.
  import <spec.json> [--components <json-or-path>] [--dry-run <dir>]
      Replays the spec into the DEFAULT session's Figma tab: a reset eval, the
      assets streamed in ≤150 KB pieces, then node chunks (≤150 KB of JSON each,
      nodes never split) each followed by figma_importer.js. Prints the final
      report JSON plus a one-line summary. --dry-run writes every eval to
      <dir>/NN_<kind>.js instead of running it.

Port: FIGMA_CDP_PORT if set, else the browser's DevToolsActivePort file, else 9222.
Public/unauthenticated pages only (the capture session has no Chrome login).
"""
import argparse, base64, json, os, re, subprocess, sys

PIECE_BYTES = 150_000   # asset piece and node chunk budget, measured on the JSON text
EVAL_B64_MAX = 300_000  # per-eval base64 ceiling (ARG_MAX headroom)
BATCH_KEYS = ['captureIds', 'captureRects', 'captureLayout',
              'captureReport', 'captureFonts', 'captureAssets']

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

def agent_browser(args, session=None):
    target = ['--session', session] if session else ['--cdp', cdp_port()]
    try:
        return subprocess.run(['agent-browser', *target, *args], capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit('agent-browser not found — npm i -g agent-browser && agent-browser install')

def read_sibling(name):
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, name), 'rb') as f:
            return f.read()
    except OSError:
        sys.exit(f'figma_capture.py: {name} not found next to this script')

def js(value):
    # ensure_ascii keeps the output a valid JS literal (U+2028/2029 become \\u escapes)
    return json.dumps(value, separators=(',', ':'))

def eval_result(r):
    """Unwrap `agent-browser eval --json` output into (result, error)."""
    try:
        out = json.loads(r.stdout)
    except ValueError:
        return None, (r.stdout + r.stderr).strip()[:400] or f'exit {r.returncode}'
    if r.returncode != 0 or not out.get('success') or out.get('error'):
        return None, str(out.get('error') or r.stderr.strip() or f'exit {r.returncode}')[:400]
    result = (out.get('data') or {}).get('result')
    if result is None:
        return None, 'eval returned no result'
    if isinstance(result, dict) and 'error' in result:
        return None, str(result['error'])[:400]
    return result, None

# ---------------------------------------------------------------- walk

def walk(a):
    walker_b64 = base64.b64encode(read_sibling('figma_walker.js')).decode()
    cap = lambda *args: agent_browser(list(args), session='capture')
    if cap('connect', cdp_port()).returncode != 0:
        sys.exit(f'figma_capture.py: could not connect capture session to CDP {cdp_port()}')
    if cap('open', a.url).returncode != 0:
        sys.exit(f'figma_capture.py: could not open {a.url} in capture session')
    cap('wait', a.wait_ms)

    result, err = eval_result(cap('eval', '-b', walker_b64, '--json'))
    if err:
        sys.exit(f'figma_capture.py: walker failed — {err}')
    if not isinstance(result, dict) or 'nodes' not in result:
        sys.exit(f'figma_capture.py: walker result missing nodes — {str(result)[:200]}')

    slug = re.sub(r'[^a-z0-9]+', '-', re.sub(r'^https?://', '', a.url).lower()).strip('-')[:60] or 'page'
    out = f'/tmp/figma_capture_{slug}.json'
    with open(out, 'w') as f:
        json.dump(result, f)
    print(f'spec: {out}')
    print(f'nodes: {result["meta"]["nodeCount"]}  flagged: {len(result.get("flagged", []))}  '
          f'assets: {len(result.get("assets", {}))}')

# -------------------------------------------------------------- import

def load_components(arg):
    if not arg:
        return {}
    try:
        text = arg if arg.lstrip().startswith('{') else open(arg).read()
        m = json.loads(text)
    except (OSError, ValueError) as e:
        sys.exit(f'figma_capture.py: --components is neither a JSON object nor a readable file — {e}')
    if not isinstance(m, dict):
        sys.exit('figma_capture.py: --components must be a JSON object {category: componentId}')
    return m

def pieces(s):
    """Split s so each piece's JSON body (without quotes) stays within PIECE_BYTES."""
    out, start = [], 0
    while start < len(s):
        n = min(PIECE_BYTES, len(s) - start)
        while len(js(s[start:start + n])) - 2 > PIECE_BYTES:
            n = n * 3 // 4
        out.append(s[start:start + n])
        start += n
    return out

def reset_eval():
    return ('(function(){ var s = window.__batchState = window.__batchState || {};\n'
            f'  {js(BATCH_KEYS)}.forEach(function(k){{ delete s[k]; }});\n'
            '  s.captureAssets = {}; return "reset"; })()')

def asset_evals(assets):
    for key, asset in assets.items():
        meta = {k: v for k, v in asset.items() if k not in ('b64', 'svg')}
        yield (f'asset-{key}-meta',
               f'(function(){{ window.__batchState.captureAssets[{js(key)}] = {js(meta)}; return {js(key)}; }})()')
        field = 'b64' if 'b64' in asset else 'svg' if 'svg' in asset else None
        if not field:
            continue
        for n, piece in enumerate(pieces(asset[field]), 1):
            yield (f'asset-{key}-{n}',
                   f'(function(a){{ a.{field} = (a.{field} || "") + {js(piece)}; return a.{field}.length; }})'
                   f'(window.__batchState.captureAssets[{js(key)}])')

def node_chunks(nodes, budget):
    chunk, size = [], 0
    for node in nodes:
        n = len(js(node)) + 1
        if chunk and size + n > budget:
            yield chunk
            chunk, size = [], 0
        chunk.append(node)
        size += n
    if chunk:
        yield chunk

def import_spec(a):
    importer = read_sibling('figma_importer.js').decode()
    try:
        with open(a.spec) as f:
            spec = json.load(f)
    except (OSError, ValueError) as e:
        sys.exit(f'figma_capture.py: cannot read spec {a.spec} — {e}')
    nodes = spec.get('nodes') or []
    if not nodes:
        sys.exit('figma_capture.py: spec has no nodes')
    envelope = {'flagged': spec.get('flagged', []), 'components': load_components(a.components),
                'meta': spec.get('meta', {})}

    budget = min(PIECE_BYTES, EVAL_B64_MAX * 3 // 4 - len(importer) - len(js(envelope)) - 64)
    if budget <= 0:
        sys.exit('figma_capture.py: figma_importer.js leaves no room for nodes under the eval ceiling')

    evals = [('reset', reset_eval())]
    evals += list(asset_evals(spec.get('assets') or {}))
    start = 0
    for chunk in node_chunks(nodes, budget):
        evals.append((f'nodes-{start}-{start + len(chunk) - 1}',
                      'window.__captureSpec = ' + js({'nodes': chunk, **envelope}) + ';\n' + importer))
        start += len(chunk)

    if a.dry_run:
        os.makedirs(a.dry_run, exist_ok=True)
    last = None
    for n, (kind, src) in enumerate(evals):
        b64 = base64.b64encode(src.encode()).decode()
        if len(b64) >= EVAL_B64_MAX:
            sys.exit(f'figma_capture.py: eval {n} ({kind}) base64 is {len(b64)} ≥ {EVAL_B64_MAX} — '
                     'a single node or asset piece exceeds the eval ceiling')
        if a.dry_run:
            with open(os.path.join(a.dry_run, f'{n:02d}_{kind}.js'), 'w') as f:
                f.write(src)
            continue
        last, err = eval_result(agent_browser(['eval', '-b', b64, '--json']))
        if err:
            sys.exit(f'figma_capture.py: eval {n} ({kind}) failed — {err}')

    if a.dry_run:
        print(f'dry-run: {len(evals)} evals written to {a.dry_run}')
        return
    print(json.dumps(last, indent=1))
    rep = last if isinstance(last, dict) else {}
    print(f'created={rep.get("created", 0)} flagged={len(rep.get("flagged") or [])} '
          f'fontsFallenBack={len(rep.get("fontsFallenBack") or [])} '
          f'instantiated={len(rep.get("instantiated") or [])} '
          f'warnings={len(rep.get("warnings") or [])}')

# ---------------------------------------------------------------- main

p = argparse.ArgumentParser(prog='figma_capture.py')
sub = p.add_subparsers(dest='cmd', required=True)
w = sub.add_parser('walk', help='walk a live URL into /tmp/figma_capture_<slug>.json')
w.add_argument('url')
w.add_argument('wait_ms', nargs='?', default='2000')
i = sub.add_parser('import', help='replay a spec into the default session\'s Figma tab')
i.add_argument('spec')
i.add_argument('--components', metavar='JSON_OR_PATH', help='{category: componentId} map')
i.add_argument('--dry-run', metavar='DIR', help='write each eval to DIR/NN_<kind>.js instead of running')
args = p.parse_args()
walk(args) if args.cmd == 'walk' else import_spec(args)
