#!/usr/bin/env python3
"""Run N Figma Plugin API scripts in one agent-browser (or perch) invocation.

Each script is base64-encoded and packed into a single `agent-browser batch`
call, eliminating per-eval CLI cold-start (~200ms saved per extra script).
Prefer over multiple figma_run.py calls for >= 3 sequential evals with no
intermediate inspection. Each result is printed under a '== <file> ==' header.
On the perch backend one figma_perch.mjs run evaluates the scripts in order.

  python3 figma_batch_run.py [--file <figma-url-or-key>] <js_file> [<js_file> ...]

Backend: FIGMA_BACKEND=cdp|perch if set; else cdp when FIGMA_CDP_PORT is set;
else perch when a perch with eval_js world:"main" is at PERCH_DIR (default
~/Documents/perch), which needs no remote debugging; else cdp.
CDP port: FIGMA_CDP_PORT if set, else the browser's DevToolsActivePort file, else 9222.
perch tab: --file (or FIGMA_FILE) names the file; needed when several are open.
"""
import argparse, base64, fcntl, hashlib, json, os, socket, stat, subprocess, sys, time

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

def perch(op, file, *paths):
    """Ask figma_perch.mjs (next to this script) through its daemon, else run it once; its JSON reply."""
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figma_perch.mjs')
    if not os.path.exists(helper):
        sys.exit(f'figma_perch.mjs not found next to {os.path.basename(__file__)}; copy it alongside')
    req = {'op': op, 'file': file or '', 'paths': [os.path.abspath(p) for p in paths],
           'tab': os.environ.get('FIGMA_PERCH_TAB', '')}
    out = None
    sock = None if os.environ.get('FIGMA_PERCH_DAEMON') == '0' else daemon_sock(helper)
    if sock:
        wait = 120 * len(paths) + 30
        try:
            out = daemon_exchange(sock, req, wait)
            if out is None and start_daemon(sock, helper):
                out = daemon_exchange(sock, req, wait)
        except Dropped as e:
            sys.exit(f'perch: perch_daemon: the daemon dropped the call ({e}); the script may have run, check before retrying')
    if out is None:
        try:
            r = subprocess.run(['node', helper, op, file or '', *req['paths']], capture_output=True, text=True)
        except FileNotFoundError:
            sys.exit('node not found; the perch backend needs Node 18+')
        try:
            out = json.loads(r.stdout, parse_int=js_int)
        except ValueError:
            sys.exit(f'perch: no reply from figma_perch.mjs (exit {r.returncode}): {(r.stdout + r.stderr).strip()[:400]}')
    if out.get('fatal') and not out.get('results'):
        sys.exit(f"perch: {out['fatal']}")
    return out

ap = argparse.ArgumentParser(prog='figma_batch_run.py')
ap.add_argument('--file', default=os.environ.get('FIGMA_FILE'), help='Figma file URL or key (perch backend)')
ap.add_argument('js_files', nargs='+')
a = ap.parse_args()
for path in a.js_files:
    if not os.path.isfile(path):
        print(f'figma_batch_run.py: no such file: {path}', file=sys.stderr)
        sys.exit(1)

if backend() == 'perch':
    out = perch('eval', a.file, *a.js_files)
    # As agent-browser batch prints: a success is {origin: the page URL, result} with keys
    # sorted and non-ASCII escaped, a failure its error.
    for path, res in zip(a.js_files, out['results']):
        print(f'== {os.path.basename(path)} ==')
        print(json.dumps({'origin': res.get('href') or out['origin'], 'result': res['value']}, sort_keys=True)
              if res['ok'] else f"Evaluation error: {res['error']}")
    if out.get('fatal'):
        sys.exit(f"perch: {out['fatal']} (stopped after {len(out['results'])} of {len(a.js_files)} scripts)")
    sys.exit(0 if all(r['ok'] for r in out['results']) else 1)

cmds = []
for path in a.js_files:
    with open(path, 'rb') as f:
        cmds.append(f'eval -b {base64.b64encode(f.read()).decode()}')

if sum(len(c) for c in cmds) > 200_000:
    print('payload >200KB — use agent-browser batch stdin JSON mode '
          '(see references/execution.md → Batched evals), or the perch backend', file=sys.stderr)
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
    for path, res in zip(a.js_files, results):
        print(f'== {os.path.basename(path)} ==')
        body = res.get('result') if res.get('success') else res.get('error')
        print('' if body is None else body if isinstance(body, str) else json.dumps(body))
else:
    print(r.stdout, end='')

if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
