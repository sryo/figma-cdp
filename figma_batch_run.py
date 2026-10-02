#!/usr/bin/env python3
"""Run N Figma Plugin API scripts in one agent-browser (or perch) invocation.

Each script is base64-encoded and packed into a single `agent-browser batch`
call, eliminating per-eval CLI cold-start (~200ms saved per extra script).
Prefer over multiple figma_run.py calls for >= 3 sequential evals with no
intermediate inspection. On the perch backend one figma_perch.mjs request
evaluates the scripts in order. Run it from the skill directory; nothing needs
copying.

  python3 figma_batch_run.py [--file <figma-url-or-key>] [--timeout <seconds>] [--lib] <script> [<script> ...]

A script is a <js_file>, - (stdin, once) or -e '<js>' (or --js), run in the
order given. Each result is printed under a '== <label> ==' header: the file's
basename, 'stdin', or '-e[n]' for the nth inline script. A script's result is
its completion value; one with top-level await or return runs as an async
function body, and its result is what it returns.

Backend: FIGMA_BACKEND=cdp|perch if set; else cdp when FIGMA_CDP_PORT is set;
else perch when a perch with eval_js world:"main" is at PERCH_DIR (default
~/Documents/perch), which needs no remote debugging; else cdp.
CDP port: FIGMA_CDP_PORT if set, else the browser's DevToolsActivePort file, else 9222.
perch tab: --file (default FIGMA_FILE) names the file; needed when several are open.
perch await: --timeout <seconds> (or FIGMA_TIMEOUT), 1 to 300, default 120.
--lib: figma_lib.js goes in front of the first script, installing window.__fx once per tab.
"""
import base64, fcntl, hashlib, json, os, socket, stat, subprocess, sys, time

PROG = 'figma_batch_run.py'
USAGE = "usage: python3 figma_batch_run.py [--file <url-or-key>] [--timeout <seconds>] [--lib] (<js_file> | - | -e '<js>')..."

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


def perch(req, timeout=120.0):
    """Ask figma_perch.mjs (next to this script, symlinks followed) through its daemon, else run it once; its JSON reply."""
    helper = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'figma_perch.mjs')
    if not os.path.exists(helper):
        sys.exit(f'figma_perch.mjs not found next to {os.path.realpath(__file__)}')
    req = {**req, 'timeout': round(timeout * 1000), 'tab': os.environ.get('FIGMA_PERCH_TAB', '')}
    out = None
    sock = None if os.environ.get('FIGMA_PERCH_DAEMON') == '0' else daemon_sock(helper)
    if sock:
        # perch's own cap per script: the await, plus reading a long result back.
        wait = (timeout + 70) * len(req.get('sources') or [None]) + 30
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
    if out.get('fatal') and not out.get('results'):
        sys.exit(f"perch: {out['fatal']}")
    return out

# Every script runs as this program on both backends. It parses the script before running any of
# it. A script that parses as a program runs as one: its value is its completion value, as CDP's
# Runtime.evaluate gives it (awaited when a promise), and indirect eval keeps its let/const to
# itself. A script that parses only as an async function body (top-level await or return) runs as
# one; its value is what it returns. So does a program with `await` as an identifier at its top
# level, as in `await (p)`: a class static block, where that is an error, finds it. The parse
# probes run in a function scope (direct eval behind a throw), so they declare nothing global.
# Nothing runs twice.
AUTO_ASYNC = r'''(function (src) {
  function syntaxError(parse) {
    try { parse(); } catch (e) { if (e instanceof SyntaxError) return e; if (e !== "figma-parse-probe") throw e; }
    return null;
  }
  var body = null;
  var asScript = syntaxError(function () { eval('throw "figma-parse-probe";\n' + src); });
  var asBody = syntaxError(function () { body = new (Object.getPrototypeOf(async function () {}).constructor)(src); });
  var awaitAtTop = body && /\bawait\b/.test(src) && /await|reserved/i.test(
    (syntaxError(function () { Function('(class { static {\n' + src + '\n} })'); }) || {}).message);
  if (!asScript && !awaitAtTop) return (0, eval)(src);
  if (body) return body();
  throw /return|await/i.test(asScript.message) ? asBody : asScript;
})'''

def program(src):
    return f'{AUTO_ASYNC}({json.dumps(src)})'

def with_lib(src):
    """figma_lib.js (next to this script) in front of a wrapped script: the library installs
    window.__fx, even when the script then fails to parse, and the script's value stays the result."""
    lib = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'figma_lib.js')
    try:
        with open(lib, encoding='utf-8') as f:
            return f.read() + '\n;' + src
    except OSError:
        sys.exit(f'figma_lib.js not found next to {os.path.basename(__file__)}')

def usage(msg):
    print(f'{PROG}: {msg}\n{USAGE}', file=sys.stderr)
    sys.exit(1)

def parse_args(argv, options):
    """Option values (FIGMA_FILE the default for --file, --lib True when given) and the scripts in
    command-line order, each ('path', p), ('stdin', None) or ('inline', js)."""
    opts = dict.fromkeys(options)
    opts['--file'] = os.environ.get('FIGMA_FILE')
    lib = False
    scripts = []
    args = iter(argv)
    for arg in args:
        if arg in ('-h', '--help'):
            print(__doc__.strip())
            sys.exit(0)
        name, eq, val = arg.partition('=') if arg.startswith('--') else (arg, '', None)
        if arg == '--lib':
            lib = True
        elif name in opts or name in ('-e', '--js'):
            if not eq:
                val = next(args, None)
                if val is None:
                    usage(f'{name} needs a value')
            if name in opts:
                opts[name] = val
            else:
                scripts.append(('inline', val))
        elif arg == '-':
            scripts.append(('stdin', None))
        elif arg.startswith('-'):
            usage(f'unknown option {arg}')
        else:
            scripts.append(('path', arg))
    opts['--lib'] = lib
    return opts, scripts

def load(scripts):
    """(label, source) per script: a file's basename, '-e[n]' for the nth inline one, 'stdin'."""
    if sum(kind == 'stdin' for kind, _ in scripts) > 1:
        usage('- (stdin) can be given once')
    for kind, v in scripts:
        if kind == 'path' and not os.path.isfile(v):
            print(f'{PROG}: no such file: {v}', file=sys.stderr)
            sys.exit(1)
    out, inline = [], 0
    for kind, v in scripts:
        if kind == 'inline':
            inline += 1
            out.append((f'-e[{inline}]', v))
        elif kind == 'stdin':
            out.append(('stdin', sys.stdin.buffer.read().decode('utf-8')))
        else:
            with open(v, encoding='utf-8') as f:
                out.append((os.path.basename(v), f.read()))
    return out

opts, specs = parse_args(sys.argv[1:], ('--file', '--timeout'))
if not specs:
    usage('give at least one script')
scripts = load(specs)
# The library goes in front of the first script only; later scripts in a batch share its tab.
sources = [program(src) for _, src in scripts]
if opts['--lib'] and sources:
    sources[0] = with_lib(sources[0])

if backend() == 'perch':
    out = perch({'op': 'eval', 'file': opts['--file'] or '', 'sources': sources},
                timeout=timeout_seconds(opts['--timeout']))
    # As agent-browser batch prints: a success is {origin: the page URL, result} with keys
    # sorted and non-ASCII escaped, a failure its error.
    for (label, _), res in zip(scripts, out['results']):
        print(f'== {label} ==')
        print(json.dumps({'origin': res.get('href') or out['origin'], 'result': res['value']}, sort_keys=True)
              if res['ok'] else f"Evaluation error: {res['error']}")
    if out.get('fatal'):
        sys.exit(f"perch: {out['fatal']} (stopped after {len(out['results'])} of {len(scripts)} scripts)")
    sys.exit(0 if all(r['ok'] for r in out['results']) else 1)

cmds = [f'eval -b {base64.b64encode(src.encode()).decode()}' for src in sources]

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
    for (label, _), res in zip(scripts, results):
        print(f'== {label} ==')
        body = res.get('result') if res.get('success') else res.get('error')
        print('' if body is None else body if isinstance(body, str) else json.dumps(body))
else:
    print(r.stdout, end='')

if r.stderr:
    print(r.stderr, end='', file=sys.stderr)
sys.exit(r.returncode)
