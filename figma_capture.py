#!/usr/bin/env python3
"""Live page → capture spec → Figma nodes, as two subcommands.

  walk <url> [wait_ms] [--timeout <seconds>]
      Opens the URL in a tab of its own, waits wait_ms (default 2000) for it to settle,
      runs figma_walker.js there (an async eval whose envelope comes back whole) and
      persists it to /tmp/figma_capture_<slug>.json.
      cdp: binds an isolated `--session capture` to the CDP port (connect explicitly —
      a bare --cdp does not retarget a bound session) and `open`s the URL in it.
      perch: a new unselected tab (perch new_tab; the browser may come forward), closed after the walk.
  import <spec.json> [--components <json-or-path>] [--file <figma-url-or-key>]
         [--timeout <seconds>] [--dry-run <dir>]
      Replays the spec into the Figma tab: a reset eval, the assets streamed in
      ≤150 KB pieces, then node chunks (≤150 KB of JSON each, nodes never split) each
      followed by figma_importer.js; the first eval that fails ends the run. Prints the
      final report JSON plus a one-line summary. cdp: the DEFAULT session's tab, one
      eval per call. perch: every eval in one figma_perch.mjs request. --dry-run writes
      every eval to <dir>/NN_<kind>.js instead of running it.

Backend: FIGMA_BACKEND=cdp|perch if set; else cdp when FIGMA_CDP_PORT is set;
else perch when a perch with eval_js world:"main" is at PERCH_DIR (default
~/Documents/perch); else cdp.
CDP port: FIGMA_CDP_PORT if set, else the browser's DevToolsActivePort file, else 9222.
perch tab: --file (or FIGMA_FILE) names the Figma file; needed when several are open.
perch await: --timeout <seconds> (or FIGMA_TIMEOUT) per eval, 1 to 300, default 120.
cdp walks public/unauthenticated pages only (the capture session has no Chrome login);
a perch walk runs in the user's browser, with its logins.
"""
import argparse, base64, fcntl, hashlib, json, os, re, socket, stat, subprocess, sys, tempfile, time

PIECE_BYTES = 150_000   # asset piece and node chunk budget, measured on the JSON text
EVAL_B64_MAX = 300_000  # per-eval base64 ceiling on cdp (ARG_MAX headroom)
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

# ------------------------------------------------- perch client
# perch_dir through timeout_seconds are figma_batch_run.py's own, kept identical
# (tests/perch_backend_test.py compares them).

def perch_dir():
    return os.environ.get('PERCH_DIR') or os.path.expanduser('~/Documents/perch')

def perch_ready():
    try:
        with open(os.path.join(perch_dir(), 'server.js')) as f:
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

def js_int(s):
    """JSON from the page is JS numbers: an integer past 2^53 is a double, as agent-browser prints it."""
    n = int(s)
    return n if -2**53 <= n <= 2**53 else float(s)

class Dropped(Exception):
    pass

def daemon_sock(helper):
    """The figma_perch.mjs daemon's socket: per user, per perch checkout and helper version."""
    if os.environ.get('FIGMA_PERCH_SOCK'):
        return os.environ['FIGMA_PERCH_SOCK']
    try:
        st = [os.stat(p) for p in (os.path.join(perch_dir(), 'server.js'), helper)]
    except OSError:
        return None
    tag = '\0'.join([os.path.realpath(perch_dir()), os.path.realpath(helper)] +
                    [f'{x.st_mtime_ns}:{x.st_size}' for x in st])
    name = hashlib.sha1(tag.encode()).hexdigest()[:16] + '.sock'
    for base in (os.environ.get('TMPDIR') or '/tmp', '/tmp'):
        d = os.path.join(base, f'figma-perch-{os.getuid()}')
        if len(os.path.join(d, name).encode()) < 100:
            break
    else:
        return None
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        st = os.lstat(d)
        if st.st_uid != os.getuid() or not stat.S_ISDIR(st.st_mode):
            return None
        if st.st_mode & 0o077:
            os.chmod(d, 0o700)
    except OSError:
        return None
    return os.path.join(d, name)

def daemon_exchange(sock, req, wait=5):
    """The daemon's reply line; None when no daemon greeted, so nothing ran; Dropped once the
    request went out. `wait` bounds the reply: perch caps a main-world eval near 95s."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    f = None
    try:
        s.settimeout(5)
        s.connect(sock)
        f = s.makefile('rb')
        if not f.readline().startswith(b'{"perch_daemon"'):
            f.close()
            s.close()
            return None
    except OSError:
        if f:
            f.close()
        s.close()
        return None
    try:
        s.settimeout(wait)
        s.sendall(json.dumps(req).encode() + b'\n')
        data = f.readline()
    except socket.timeout:
        raise Dropped(f'no reply in {wait:.0f}s')
    except OSError as e:
        raise Dropped(str(e))
    finally:
        f.close()
        s.close()
    try:
        return json.loads(data, parse_int=js_int)
    except ValueError:
        raise Dropped('no reply')

def start_daemon(sock, helper):
    """Start figma_perch.mjs serve on sock unless one answers; True once it does."""
    try:
        lock = open(sock + '.lock', 'a')
    except OSError:
        return False
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if daemon_exchange(sock, {'op': 'ping'}):
                return True
        except Dropped:
            pass
        try:
            os.unlink(sock)
        except FileNotFoundError:
            pass
        except OSError:
            return False
        try:
            with open(sock + '.log', 'wb') as log:
                p = subprocess.Popen(['node', helper, 'serve', sock], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
        except OSError:
            return False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if os.path.exists(sock):
                try:
                    if daemon_exchange(sock, {'op': 'ping'}):
                        return True
                except Dropped:
                    pass
            if p.poll() is not None and not os.path.exists(sock):
                return False
            time.sleep(0.005)
        p.kill()
        return False

def timeout_seconds(flag):
    """--timeout, else FIGMA_TIMEOUT, else 120: seconds a perch eval may await, clamped to 1-300."""
    raw = flag if flag is not None else os.environ.get('FIGMA_TIMEOUT')
    if raw is None or str(raw).strip() == '':
        return 120.0
    try:
        v = float(raw)
    except ValueError:
        v = float('nan')
    if v != v or v in (float('inf'), float('-inf')):
        sys.exit(f"--timeout / FIGMA_TIMEOUT is seconds, 1 to 300; got '{raw}'")
    return min(300.0, max(1.0, v))


def perch_call(req, wait):
    """figma_perch.mjs's reply to one request, through its daemon, else a one-shot run."""
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figma_perch.mjs')
    if not os.path.exists(helper):
        sys.exit('figma_perch.mjs not found next to figma_capture.py; copy it alongside')
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
            r = subprocess.run(['node', helper, 'call', json.dumps(req)], capture_output=True, text=True)
        except FileNotFoundError:
            sys.exit('node not found; the perch backend needs Node 18+')
        try:
            out = json.loads(r.stdout, parse_int=js_int)
        except ValueError:
            sys.exit(f'perch: no reply from figma_perch.mjs (exit {r.returncode}): {(r.stdout + r.stderr).strip()[:400]}')
    return out

# ------------------------------------------------------- evals

def agent_browser(args, session=None):
    target = ['--session', session] if session else ['--cdp', cdp_port()]
    try:
        return subprocess.run(['agent-browser', *target, *args], capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit('agent-browser not found — npm i -g agent-browser && agent-browser install')

def read_sibling(name):
    try:
        with open(sibling(name), 'rb') as f:
            return f.read()
    except OSError:
        sys.exit(f'figma_capture.py: {name} not found next to this script')

def sibling(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)

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

def eval_result(r):
    """Unwrap `agent-browser eval --json` output into (result, error)."""
    try:
        out = json.loads(r.stdout)
    except ValueError:
        return None, (r.stdout + r.stderr).strip()[:400] or f'exit {r.returncode}'
    if r.returncode != 0 or not out.get('success') or out.get('error'):
        return None, str(out.get('error') or r.stderr.strip() or f'exit {r.returncode}')[:400]
    return checked((out.get('data') or {}).get('result'))

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
    if backend() == 'perch':
        timeout = timeout_seconds(a.timeout)
        try:
            settle = max(0, round(float(a.wait_ms)))
        except ValueError:
            sys.exit(f"figma_capture.py: wait_ms is milliseconds; got '{a.wait_ms}'")
        read_sibling('figma_walker.js')
        out = perch_call({'op': 'page', 'url': a.url, 'paths': [sibling('figma_walker.js')], 'settle': settle,
                          'timeout': round(timeout * 1000)}, wait=settle / 1000 + timeout + 130)
        result, err = perch_results(out)[0]
    else:
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

def run_cdp(evals):
    """Each eval's (result, error) in order, stopping after the first error."""
    for n, (kind, src) in enumerate(evals):
        b64 = base64.b64encode(src.encode()).decode()
        if len(b64) >= EVAL_B64_MAX:
            sys.exit(f'figma_capture.py: eval {n} ({kind}) base64 is {len(b64)} ≥ {EVAL_B64_MAX} — '
                     'a single node or asset piece exceeds the eval ceiling')
        row = eval_result(agent_browser(['eval', '-b', b64, '--json']))
        yield row
        if row[1]:
            return

def run_perch(evals, file, timeout):
    with tempfile.TemporaryDirectory(prefix='figma_capture_') as d:
        paths = []
        for n, (kind, src) in enumerate(evals):
            paths.append(os.path.join(d, f'{n:02d}_{kind}.js'))
            with open(paths[-1], 'w') as f:
                f.write(src)
        out = perch_call({'op': 'eval', 'file': file or '', 'paths': paths, 'timeout': round(timeout * 1000),
                          'stop': True}, wait=(timeout + 70) * len(paths) + 30)
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
        for n, (kind, src) in enumerate(evals):
            with open(os.path.join(a.dry_run, f'{n:02d}_{kind}.js'), 'w') as f:
                f.write(src)
        print(f'dry-run: {len(evals)} evals written to {a.dry_run}')
        return

    rows = run_perch(evals, a.file, timeout_seconds(a.timeout)) if backend() == 'perch' else run_cdp(evals)
    last = None
    for n, (result, err) in enumerate(rows):
        if err:
            sys.exit(f'figma_capture.py: eval {n} ({evals[n][0]}) failed — {err}')
        last = result
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
i = sub.add_parser('import', help='replay a spec into the Figma tab')
i.add_argument('spec')
i.add_argument('--components', metavar='JSON_OR_PATH', help='{category: componentId} map')
i.add_argument('--file', default=os.environ.get('FIGMA_FILE'), help='Figma file URL or key (perch backend)')
i.add_argument('--dry-run', metavar='DIR', help='write each eval to DIR/NN_<kind>.js instead of running')
for sp in (w, i):
    sp.add_argument('--timeout', metavar='SECONDS',
                    help='how long an eval may await, 1 to 300 (perch backend; default FIGMA_TIMEOUT, else 120)')
args = p.parse_args()
walk(args) if args.cmd == 'walk' else import_spec(args)
