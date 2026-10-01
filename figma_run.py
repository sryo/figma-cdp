#!/usr/bin/env python3
"""Run a Figma Plugin API script via agent-browser (CDP) or perch.

Reads a .js file and runs it in the Figma tab. Avoids shell syntax (heredocs,
pipes, redirects) that trigger Claude Code warnings.

  python3 figma_run.py [--file <figma-url-or-key>] [--timeout <seconds>] <js_file>
  python3 figma_run.py [--file <figma-url-or-key>] --screenshot <out.png>

Backend: FIGMA_BACKEND=cdp|perch if set; else cdp when FIGMA_CDP_PORT is set;
else perch when a perch with eval_js world:"main" is at PERCH_DIR (default
~/Documents/perch), which needs no remote debugging; else cdp.
CDP port: FIGMA_CDP_PORT if set, else the browser's DevToolsActivePort file, else 9222.
perch tab: --file (or FIGMA_FILE) names the file; needed when several are open.
perch await: --timeout <seconds> (or FIGMA_TIMEOUT), 1 to 300, default 120.
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

def pretty(v, ind=''):
    """JSON as agent-browser prints an eval result: keys sorted, 2-space indent, UTF-8, 1e-7 not 1e-07."""
    inner = ind + '  '
    if isinstance(v, dict):
        if not v:
            return '{}'
        rows = (f'{inner}{json.dumps(k, ensure_ascii=False)}: {pretty(v[k], inner)}' for k in sorted(v))
        return '{\n' + ',\n'.join(rows) + '\n' + ind + '}'
    if isinstance(v, list):
        if not v:
            return '[]'
        return '[\n' + ',\n'.join(inner + pretty(x, inner) for x in v) + '\n' + ind + ']'
    if isinstance(v, float):
        r = repr(v)
        return r[:-2] + r[-1] if len(r) > 3 and r[-4] == 'e' and r[-2] == '0' else r
    return json.dumps(v, ensure_ascii=False)

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

def perch(op, file, *paths, timeout=120.0):
    """Ask figma_perch.mjs (next to this script) through its daemon, else run it once; its JSON reply."""
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figma_perch.mjs')
    if not os.path.exists(helper):
        sys.exit(f'figma_perch.mjs not found next to {os.path.basename(__file__)}; copy it alongside')
    ms = round(timeout * 1000)
    req = {'op': op, 'file': file or '', 'paths': [os.path.abspath(p) for p in paths], 'timeout': ms,
           'tab': os.environ.get('FIGMA_PERCH_TAB', '')}
    out = None
    sock = None if os.environ.get('FIGMA_PERCH_DAEMON') == '0' else daemon_sock(helper)
    if sock:
        # perch's own cap per script: the await, plus reading a long result back.
        wait = (timeout + 70) * len(paths) + 30
        try:
            out = daemon_exchange(sock, req, wait)
            if out is None and start_daemon(sock, helper):
                out = daemon_exchange(sock, req, wait)
        except Dropped as e:
            sys.exit(f'perch: perch_daemon: the daemon dropped the call ({e}); the script may have run, check before retrying')
    if out is None:
        try:
            r = subprocess.run(['node', helper, op, file or '', *req['paths']], capture_output=True, text=True,
                               env={**os.environ, 'FIGMA_TIMEOUT_MS': str(ms)})
        except FileNotFoundError:
            sys.exit('node not found; the perch backend needs Node 18+')
        try:
            out = json.loads(r.stdout, parse_int=js_int)
        except ValueError:
            sys.exit(f'perch: no reply from figma_perch.mjs (exit {r.returncode}): {(r.stdout + r.stderr).strip()[:400]}')
    if out.get('fatal') and not out.get('results'):
        sys.exit(f"perch: {out['fatal']}")
    return out

ap = argparse.ArgumentParser(prog='figma_run.py')
ap.add_argument('--file', default=os.environ.get('FIGMA_FILE'), help='Figma file URL or key (perch backend)')
ap.add_argument('--timeout', metavar='SECONDS',
                help='how long a script may await, 1 to 300 (perch backend; default FIGMA_TIMEOUT, else 120)')
ap.add_argument('--screenshot', metavar='PNG', help='capture the Figma tab instead of running a script')
ap.add_argument('js_file', nargs='?')
a = ap.parse_args()
if not a.screenshot and not a.js_file:
    print('Usage: python3 figma_run.py [--file <url-or-key>] <js_file> | --screenshot <out.png>', file=sys.stderr)
    sys.exit(1)
if a.js_file and not os.path.isfile(a.js_file):
    print(f'figma_run.py: no such file: {a.js_file}', file=sys.stderr)
    sys.exit(1)

if backend() == 'perch':
    if a.screenshot:
        perch('screenshot', a.file, a.screenshot)
        print(f"✓ Screenshot saved to {a.screenshot}")
        sys.exit(0)
    res = perch('eval', a.file, a.js_file, timeout=timeout_seconds(a.timeout))['results'][0]
    if not res['ok']:
        print(f"✗ Evaluation error: {res['error']}", file=sys.stderr)
        sys.exit(1)
    print(pretty(res['value']))
    sys.exit(0)

if a.screenshot:
    cmd = ['screenshot', a.screenshot]
else:
    with open(a.js_file, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    if len(b64) > 200_000:
        print('payload >200KB — use agent-browser batch stdin JSON mode '
              '(see references/execution.md → Batched evals), or the perch backend', file=sys.stderr)
        sys.exit(1)
    cmd = ['eval', '-b', b64]

try:
    r = subprocess.run(['agent-browser', '--cdp', cdp_port(), *cmd], capture_output=True, text=True)
except FileNotFoundError:
    print('agent-browser not found — npm i -g agent-browser && agent-browser install',
          file=sys.stderr)
    sys.exit(1)

print(r.stdout, end='')
if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
