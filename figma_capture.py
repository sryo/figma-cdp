#!/usr/bin/env python3
"""Live page → capture spec → Figma nodes, as two subcommands.

  walk <url> [wait_ms] [--timeout <seconds>]
      Opens the URL in a tab of its own, waits wait_ms (default 2000) for it to settle,
      runs figma_walker.js there (an async eval whose envelope comes back whole) and
      persists it to /tmp/figma_capture_<slug>.json. The tab is a new one (perch new_tab) in
      --app, else a perch room that is up, else the frontmost browser, closed after the walk; a
      Mac browser without the user's focus grant stops it (needs_focus).
  import <spec.json> [--components <json-or-path>] [--componentize] [--chunk-bytes N]
         [--file <figma-url-or-key>] [--timeout <seconds>] [--dry-run <dir>]
      Replays the spec into the Figma tab: a reset eval, the assets streamed in
      ≤150 KB pieces, then node chunks (≤150 KB of JSON each, nodes never split) each
      followed by figma_importer.js; the first eval that fails ends the run. Prints the
      final report JSON plus a one-line summary. Every eval goes in one figma_perch.mjs
      request. --componentize
      marks repeated subtrees first (componentize below), so each group imports as one
      COMPONENT plus instances. --dry-run writes every eval to <dir>/NN_<kind>.js
      instead of running it.

perch: eval_js world:"main" from the perch at PERCH_DIR (default ~/.perch, then
~/Documents/perch); FIGMA_BACKEND, if set, must be perch.
Tab: --file (or FIGMA_FILE) names the Figma file; needed when several are open.
Await: --timeout <seconds> (or FIGMA_TIMEOUT) per eval, 1 to 300, default 100.
A walk runs in the user's browser (or a room), with its logins.
"""
import argparse, hashlib, json, os, re, subprocess, sys

from figma_backend import Dropped, daemon_exchange, daemon_sock, js_int, require_perch, start_daemon, timeout_seconds

PIECE_BYTES = 150_000   # asset piece and node chunk budget, measured on the JSON text
EVAL_MAX = 225_000      # node chunk ceiling: one eval's source, importer and envelope included
BATCH_KEYS = ['captureIds', 'captureEdge', 'captureRects', 'captureLayout',
              'captureReport', 'captureFonts', 'captureAssets', 'captureProps']

# ------------------------------------------------- perch client

def perch_call(req, wait):
    """figma_perch.mjs's reply to one request, through its daemon, else a one-shot run."""
    helper = sibling('figma_perch.mjs')
    if not os.path.exists(helper):
        sys.exit('figma_perch.mjs not found next to figma_capture.py')
    req = {**req, 'tab': os.environ.get('FIGMA_PERCH_TAB', '')}
    out = None
    sock = None if os.environ.get('FIGMA_PERCH_DAEMON') == '0' else daemon_sock(helper)
    if sock:
        try:
            out = daemon_exchange(sock, req, wait)
            if out is None and start_daemon(sock, helper):
                out = daemon_exchange(sock, req, wait)
        except Dropped as e:
            sys.exit(f'perch: perch_daemon: the daemon dropped the call ({e}); the script may have run, check before retrying')
    if out is None:
        try:
            r = subprocess.run(['node', helper, 'once'], input=json.dumps(req), capture_output=True, text=True)
        except FileNotFoundError:
            sys.exit('node not found; the perch backend needs Node 18+')
        try:
            out = json.loads(r.stdout, parse_int=js_int)
        except ValueError:
            sys.exit(f'perch: no reply from figma_perch.mjs (exit {r.returncode}): {(r.stdout + r.stderr).strip()[:400]}')
    return out

# ------------------------------------------------------- evals

def read_sibling(name):
    try:
        with open(sibling(name), 'rb') as f:
            return f.read()
    except OSError:
        sys.exit(f'figma_capture.py: {name} not found next to this script')

def sibling(name):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), name)

def js(value):
    # ensure_ascii keeps the output a valid JS literal (U+2028/2029 become \\u escapes)
    return json.dumps(value, separators=(',', ':'))

def checked(result):
    """(result, error) for a value the page returned."""
    if result is None:
        return None, 'eval returned no result'
    if isinstance(result, dict) and 'error' in result:
        return None, str(result['error'])[:400]
    return result, None

def perch_results(out):
    """A figma_perch.mjs reply as [(result, error)], one per script that ran, then
    (None, fatal) when perch stopped the run."""
    rows = [checked(res['value']) if res['ok'] else (None, str(res['error'])[:400])
            for res in out.get('results') or []]
    if out.get('fatal'):
        rows.append((None, str(out['fatal'])[:400]))
    return rows

# ---------------------------------------------------------------- walk

def walk(a):
    timeout = timeout_seconds(a.timeout)
    try:
        settle = max(0, round(float(a.wait_ms)))
    except ValueError:
        sys.exit(f"figma_capture.py: wait_ms is milliseconds; got '{a.wait_ms}'")
    walker = read_sibling('figma_walker.js').decode()
    srcs = [walker]
    if os.environ.get('FIGMA_CAPTURE_PREP'):
        srcs = [open(os.environ['FIGMA_CAPTURE_PREP']).read(), walker]
    req = {'op': 'page', 'url': a.url, 'sources': srcs, 'settle': settle,
           'timeout': round(timeout * 1000), 'show': a.show}
    if a.app:
        req['app'] = a.app
    out = perch_call(req, wait=settle / 1000 + timeout + 130)
    for w in out.get('warnings') or []:
        print(f'figma_capture.py: {w}', file=sys.stderr)
    result, err = perch_results(out)[-1]
    if err and out.get('app'):
        err = f"in {out['app']}: {err}"
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

# -------------------------------------------------------- componentize

REPEAT_MIN = 3   # members a group needs before it becomes a component
SIZE_STEP = 4    # px bucket for a member root's rect when comparing shapes

def layout_mode(st):
    d = st.get('display', 'block')
    if d in ('flex', 'inline-flex'):
        return 'V' if st.get('flexDirection', 'row').startswith('column') else 'H'
    return 'V' if d in ('block', 'flow-root', 'inline-block', 'list-item') else 'N'

def shared_name(group):
    """The group's common axName, else its role, else its tag."""
    names = {n.get('axName') for n in group}
    if len(names) == 1 and next(iter(names)):
        return next(iter(names))
    return group[0].get('role') or group[0]['tag']

def componentize(nodes):
    """Mark each group of REPEAT_MIN+ identical-shape subtrees, siblings or cousins, so the
    importer builds the first as a COMPONENT and the rest as its instances. A subtree's
    shape covers every node's tag, role, layout mode, child count, styles, transform, image
    and whether its text wraps, plus what an instance can't re-derive, rounded to SIZE_STEP:
    the root's rect, a fixed (`sz` px / other) size or a textless leaf's size, and the offset
    of a node in a parent without auto layout or positioned. Text is left out (it becomes a TEXT
    property) unless it carries styled runs, which an override would flatten. Outermost
    groups win and members never overlap. Sets node['rep'] on every node of a chosen group:
      master root    {m: i, name}  name = shared axName, else role, else tag
      master layer   {c: master}, plus prop: <name> on a text that differs across members
      other root     {m: master}
      other layer    {src: the master layer at the same offset, in: this member's root}
    Relies on the spec's DFS preorder: a subtree is the index range [i, i + size).
    """
    by_i = {n['i']: n for n in nodes}
    kids = {i: [] for i in by_i}
    for n in nodes:
        if n['parent'] >= 0:
            kids[n['parent']].append(n['i'])
    step = lambda v: round(v / SIZE_STEP)
    sig, size = {}, {}
    for n in reversed(nodes):
        i, st, r = n['i'], n.get('styles') or {}, n['rect']
        text = bool((n.get('text') or '').strip())
        sz = st.get('sz') or ['auto', 'auto']
        box = [step(v) if sz[a] in ('px', 'other') or not (kids[i] or text) else None
               for a, v in enumerate((r['w'], r['h']))]
        up = by_i.get(n['parent'])
        loose = up is not None and (layout_mode(up.get('styles') or {}) == 'N'
                                    or st.get('position') in ('absolute', 'fixed'))
        at = [step(r['x'] - up['rect']['x']), step(r['y'] - up['rect']['y'])] if loose else None
        own = [n['tag'], n.get('role'), n.get('level'), n.get('interactable'), layout_mode(st), st,
               n.get('xf'), n.get('image'), n.get('iframe'), n.get('origin'), (n.get('lines') or 1) > 1,
               box, at, [r.get('text') for r in n['runs']] if n.get('runs') else None]
        sig[i] = hashlib.sha1(json.dumps([own, [sig[c] for c in kids[i]]], sort_keys=True).encode()).hexdigest()
        size[i] = 1 + sum(size[c] for c in kids[i])

    groups = {}
    for n in nodes:
        i = n['i']
        if i == 0 or not kids[i] or (n.get('text') or '').strip() or n.get('image') or n.get('iframe'):
            continue
        r = n['rect']
        groups.setdefault((sig[i], round(r['w'] / SIZE_STEP), round(r['h'] / SIZE_STEP)), []).append(i)

    covered = set()
    for members in sorted(groups.values(), key=lambda g: (-size[g[0]], g[0])):
        members = [m for m in members if m not in covered]
        if len(members) < REPEAT_MIN:
            continue
        master, props = members[0], set()
        for k in range(size[master]):
            layer = [by_i[m + k] for m in members]
            if k == 0:
                rep = {'m': master, 'name': shared_name(layer)}
            else:
                rep = {'c': master}
                if (layer[0].get('text') or '').strip() and len({n.get('text') for n in layer}) > 1:
                    base = name = shared_name(layer)
                    dup = 1
                    while name in props:
                        dup += 1
                        name = f'{base} {dup}'
                    props.add(name)
                    rep['prop'] = name
            layer[0]['rep'] = rep
            for m, n in zip(members[1:], layer[1:]):
                n['rep'] = {'m': master} if k == 0 else {'src': master + k, 'in': m}
            covered.update(m + k for m in members)

def run_perch(evals, file, timeout):
    sources = [src for _, src in evals]
    out = perch_call({'op': 'eval', 'file': file or '', 'sources': sources, 'timeout': round(timeout * 1000),
                      'stop': True}, wait=(timeout + 70) * len(sources) + 30)
    return perch_results(out)

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

    if a.chunk_bytes < 1:
        sys.exit('figma_capture.py: --chunk-bytes must be a positive byte count')
    if a.componentize:
        componentize(nodes)
    budget = min(a.chunk_bytes, EVAL_MAX - len(importer) - len(js(envelope)) - 64)
    if budget <= 0:
        sys.exit('figma_capture.py: figma_importer.js leaves no room for nodes under the chunk ceiling')

    evals = [('reset', reset_eval())]
    evals += list(asset_evals(spec.get('assets') or {}))
    start = 0
    for chunk in node_chunks(nodes, budget):
        evals.append((f'nodes-{start}-{start + len(chunk) - 1}',
                      'window.__captureSpec = ' + js({'nodes': chunk, **envelope}) + ';\n' + importer))
        start += len(chunk)

    if a.dry_run:
        os.makedirs(a.dry_run, exist_ok=True)
        for n, (kind, src) in enumerate(evals):
            with open(os.path.join(a.dry_run, f'{n:02d}_{kind}.js'), 'w') as f:
                f.write(src)
        print(f'dry-run: {len(evals)} evals written to {a.dry_run}')
        return

    rows = run_perch(evals, a.file, timeout_seconds(a.timeout))
    last = None
    for n, (result, err) in enumerate(rows):
        if err:
            sys.exit(f'figma_capture.py: eval {n} ({evals[n][0]}) failed — {err}')
        last = result
    print(json.dumps(last, indent=1))
    rep = last if isinstance(last, dict) else {}
    print(f'created={rep.get("created", 0)} flagged={len(rep.get("flagged") or [])} '
          f'fontsFallenBack={len(rep.get("fontsFallenBack") or [])} '
          f'components={len(rep.get("components") or [])} '
          f'instantiated={len(rep.get("instantiated") or [])} '
          f'warnings={len(rep.get("warnings") or [])}')

# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(prog='figma_capture.py')
    sub = p.add_subparsers(dest='cmd', required=True)
    w = sub.add_parser('walk', help='walk a live URL into /tmp/figma_capture_<slug>.json')
    w.add_argument('url')
    w.add_argument('wait_ms', nargs='?', default='2000')
    w.add_argument('--app', default=os.environ.get('FIGMA_CAPTURE_APP'),
                   help='browser to open the page tab in (default FIGMA_CAPTURE_APP, else a room that is up, else the frontmost one)')
    w.add_argument('--show', action='store_true',
                   help='Arc only: show the page tab, taking focus; other browsers run it in the background')
    i = sub.add_parser('import', help='replay a spec into the Figma tab')
    i.add_argument('spec')
    i.add_argument('--components', metavar='JSON_OR_PATH', help='{category: componentId} map')
    i.add_argument('--componentize', action='store_true',
                   help='import each group of 3+ identical-shape subtrees as one component plus instances')
    i.add_argument('--chunk-bytes', type=int, default=PIECE_BYTES, metavar='N',
                   help='node chunk budget, bytes of JSON (smaller only to exercise cross-chunk state)')
    i.add_argument('--file', default=os.environ.get('FIGMA_FILE'), help='Figma file URL or key')
    i.add_argument('--dry-run', metavar='DIR', help='write each eval to DIR/NN_<kind>.js instead of running')
    for sp in (w, i):
        sp.add_argument('--timeout', metavar='SECONDS',
                        help='how long an eval may await, 1 to 300 (default FIGMA_TIMEOUT, else 100)')
    args = p.parse_args()
    require_perch()
    walk(args) if args.cmd == 'walk' else import_spec(args)


if __name__ == '__main__':
    main()
