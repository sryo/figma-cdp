#!/usr/bin/env python3
"""Run Figma Plugin API scripts in the Figma tab through perch.

Runs scripts in the Figma tab, in the order given, and prints their results. Run
it from the skill directory; nothing needs copying.

  python3 figma_run.py [--file <figma-url-or-key>] [--timeout <seconds>] [--lib] [--stop] (<js_file> | - | -e '<js>')...
  python3 figma_run.py [--file <figma-url-or-key>] --screenshot <out.png>
  python3 figma_run.py [--file <figma-url-or-key>] --recover <request-id>
  python3 figma_run.py [--file <figma-url-or-key>] --where

A script is a file, stdin (-, once), or inline (-e / --js). Its result is its
completion value; a script with top-level await or return runs as an async
function body, and its result is what it returns. One script prints its result
as compact JSON. Several run in one call (one perch request: no per-eval cold
start) and share the tab's globals; each result prints under a '== <label> =='
header (the file's basename, 'stdin', or '-e[n]' for the nth inline script) as
{"origin": <the page URL>, "result": <value>}.

perch: eval_js world:"main" from the perch at PERCH_DIR (default ~/.perch, then
~/Documents/perch); FIGMA_BACKEND, if set, must be perch.
Tab: --file (default FIGMA_FILE) names the file; needed when several are open. A room's
tab on the file (perch rooms, `room:<name>:<id>`) wins over a browser's: it runs with the window
minimized or the screen locked. A room on Figma's sign-in page stops the call (signed_out), never
falling back to a browser. FIGMA_PERCH_TAB pins a tab. --where prints the tab a call
would use (it runs only a no-op there).
Await: --timeout <seconds> (or FIGMA_TIMEOUT), 1 to 300, default 100 (under the 120 s a
Bash tool call gets by default, so a timeout comes back as an error with its request id).
--lib: figma_lib.js goes in front of the first script, installing window.__fx once per tab.
--stop: end at the first script that throws, returns nothing, or returns {error}; later
scripts don't run. Use it when a step builds on the one before.
--ns <prefix>: run as that worker (figma-worker.md's NS): the result may carry an fxNote when
it wrote inside another worker's frame, and a script is refused (reason 'stale') when someone
else edited this worker's frame since its last eval.
--recover <request-id>: the result of a script that timed out or whose reply was lost, from
the page's ledger: waits up to --timeout seconds while the script is still running.
"""
import hashlib, json, os, re, subprocess, sys, time, uuid

from figma_backend import Dropped, daemon_exchange, daemon_sock, js_int, require_perch, start_daemon, timeout_seconds

PROG = 'figma_run.py'
USAGE = ("usage: python3 figma_run.py [--file <url-or-key>] [--timeout <seconds>] [--lib] [--stop] [--ns <prefix>] (<js_file> | - | -e '<js>')...\n"
         "       python3 figma_run.py [--file <url-or-key>] --screenshot <out.png>\n"
         "       python3 figma_run.py [--file <url-or-key>] --recover <request-id>\n"
         "       python3 figma_run.py [--file <url-or-key>] --where")

def compact(v):
    """JSON on one line, keys sorted, UTF-8, numbers as JS prints them (1e-7, not 1e-07): every
    result is re-read on each later turn, so indentation is paid for many times over."""
    if isinstance(v, dict):
        return '{' + ','.join(f'{json.dumps(k, ensure_ascii=False)}:{compact(v[k])}' for k in sorted(v)) + '}'
    if isinstance(v, list):
        return '[' + ','.join(compact(x) for x in v) + ']'
    if isinstance(v, float):
        r = repr(v)
        return r[:-2] + r[-1] if len(r) > 3 and r[-4] == 'e' and r[-2] == '0' else r
    return json.dumps(v, ensure_ascii=False)

def perch(req, timeout=100.0, rids=()):
    """Ask figma_perch.mjs (next to this script, symlinks followed) through its daemon, else run it once; its JSON reply.
    rids are the request ids of req's sources, so a timeout can say how to recover its script."""
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
            if req.get('op') != 'eval':
                sys.exit(f'perch: perch_daemon: the daemon dropped the call ({e})')
            # The page's ledger answers a resend without running anything twice.
            try:
                out = daemon_exchange(sock, req, wait)
                if out is None and start_daemon(sock, helper):
                    out = daemon_exchange(sock, req, wait)
            except Dropped as e:
                sys.exit(f'perch: perch_daemon: the daemon dropped the call twice ({e}); check state before retrying')
    if out is None:
        try:
            r = subprocess.run(['node', helper, 'once'], input=json.dumps(req), capture_output=True, text=True)
        except FileNotFoundError:
            sys.exit('node not found; the perch backend needs Node 18+')
        try:
            out = json.loads(r.stdout, parse_int=js_int)
        except ValueError:
            sys.exit(f'perch: no reply from figma_perch.mjs (exit {r.returncode}): {(r.stdout + r.stderr).strip()[:400]}')
    if out.get('fatal'):
        ran = len(out.get('results') or [])
        if ran < len(rids):
            out['fatal'] = timeout_note(out['fatal'], rids[ran])
        if not ran:
            sys.exit(f"perch: {out['fatal']}")
    return out

# Every script runs as this program. It parses the script before running any of
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

# Every script also runs inside this ledger, keyed by a request id the helper picks per script
# and the script's hash. A resend with the same id never runs it twice: it answers from the
# ledger (the value when it finished, the error when it threw, a running marker when it hasn't
# finished), so a reply lost on the way back can be asked for again. `--recover <id>` reads an
# entry without a script. With --ns the script is a worker's: __fx.stale may refuse it before it
# runs, and __fx.presence may add a note to its value after (figma_lib.js).
RUN = r'''(function (rid, h, ns, run) {
  var L = globalThis.__fxRuns || (globalThis.__fxRuns = { ids: [], runs: {} }), e = L.runs[rid];
  if (!run && !e) throw new Error('no request ' + rid + ' in this tab');
  if (run && e && e.h !== h) throw new Error('request ' + rid + ' already ran a different script');
  if (e) {
    if (e.state === 'running') return { __fxRun: rid, state: 'running' };
    if (e.state === 'threw') throw e.err;
    return e.kept ? JSON.parse(e.v) : { __fxRun: rid, state: 'done', kept: false };
  }
  e = L.runs[rid] = { h: h, state: 'running' };
  L.ids.push(rid);
  if (L.ids.length > 50) delete L.runs[L.ids.shift()];
  var fx = ns ? globalThis.__fx : null;
  function done(v) {
    e.state = 'done';
    try { e.v = JSON.stringify(v === undefined ? null : v); e.kept = e.v.length <= 32768; } catch (x) { e.kept = false; }
    if (!e.kept) delete e.v;
    return v;
  }
  function threw(x) { e.state = 'threw'; e.err = x; throw x; }
  try {
    var refused = fx && fx.stale ? fx.stale(ns) : null;
    if (refused) return done(refused);
    return Promise.resolve(run())
      .then(function (v) { return fx && fx.presence ? fx.presence(ns, v) : v; })
      .then(done, threw);
  } catch (x) { threw(x); }
})'''

def program(src, rid, ns=None):
    h = hashlib.sha1(src.encode()).hexdigest()[:12]
    return f'{RUN}({json.dumps(rid)}, {json.dumps(h)}, {json.dumps(ns)}, function () {{ return {AUTO_ASYNC}({json.dumps(src)}); }})'

def recover(rid):
    return f'{RUN}({json.dumps(rid)}, null, null, null)'

def ledger_error(v):
    """The error a ledger marker stands for, or None for an ordinary value."""
    if not isinstance(v, dict) or '__fxRun' not in v:
        return None
    rid = v['__fxRun']
    if v.get('state') == 'running':
        return f'request {rid} is still running in the page; figma_run.py --recover {rid} waits for it and prints its result'
    return f'request {rid} finished, but its result was over 32 KB and was not kept; read the state it left instead'

def timeout_note(error, rid):
    """A timed-out script keeps running in the page: say how to get its result."""
    if not error.startswith('timeout:'):
        return error
    return f'{error}\nIt may still finish: figma_run.py --recover {rid} waits for it and prints its result'

def with_lib(src):
    """figma_lib.js (next to this script) in front of a wrapped script: the library installs
    window.__fx, even when the script then fails to parse, and the script's value stays the result."""
    lib = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'figma_lib.js')
    try:
        with open(lib, encoding='utf-8') as f:
            return f.read() + '\n;' + src
    except OSError:
        sys.exit(f'figma_lib.js not found next to {os.path.basename(__file__)}')

# Plugin API errors name what failed, not what to do about it. Each pattern maps a known message
# to its fix and the references/gotchas.md entry that explains it.
HINTS = [
    (r'unloaded font', 'await figma.loadFontAsync(...) for every font in this same eval before writing text (gotchas #2)'),
    (r'FILL can only be set on children of auto-layout', 'appendChild into the auto-layout parent first, then set layoutSizing* = "FILL" (gotchas #1)'),
    (r'HUG can only be set on auto-layout', 'HUG needs an auto-layout frame or a text node; set layoutMode first (gotchas #1)'),
    (r'Use node\.getMainComponentAsync', 'await inst.getMainComponentAsync() (an async findOne callback can\'t await it: collect the instances, then await each)'),
    (r'instance sublayer or table cell\) with id', 'an id starting with I is an instance sublayer, rebuilt when setProperties or a swap changes the instance: collect what you need before changing properties, or find it again from the instance after each change (gotchas #18)'),
    (r'does not exist|has been removed', 'a node object went stale or was deleted; re-fetch it with await figma.getNodeByIdAsync(id) in this eval (gotchas #15)'),
    (r'documentAccess: dynamic-page|has not been explicitly loaded', 'use await figma.getNodeByIdAsync(id) or await page.loadAsync() instead of the sync API'),
    (r'(inside of |is )an instance|cannot be overridden in an instance', 'instance children are fixed: edit the main component, or set text/property overrides on the instance'),
    (r"Cannot (read|set) propert(y|ies) of null", 'a lookup returned null: the id is on another page, deleted, or mistyped; check it before use'),
    (r'component property definitions of a component set or non-variant', 'a variant: read componentPropertyDefinitions on its set (node.parent)'),
    (r'figma\.(get|create)\w*Variable\w* is not a function', 'the variables API lives under figma.variables.<name> (figma.variables.getVariableByIdAsync, createVariable, ...)'),
    (r'must be in the same page as the parent', 'nodes on two pages: create them with parent: on the target page, or await figma.setCurrentPageAsync(page) first'),
]

def hint(error):
    """The fix for a known Plugin API error message (its first line; a stack follows), as one
    'hint: ...' line, or None."""
    message = (error or '').split('\n', 1)[0]
    for pattern, fix in HINTS:
        if re.search(pattern, message):
            return f'hint: {fix}'
    return None

def journal(rid, file, label, source, ok, out):
    """One eval appended to ~/.figma-cdp/journal/<day>.jsonl for tests/cases/case.py: the script, and its
    result or error. FIGMA_CDP_HOME moves the folder, FIGMA_CDP_JOURNAL=0 turns it off; days older than
    14 are deleted. Never committed, and a failed write never fails the eval."""
    if os.environ.get('FIGMA_CDP_JOURNAL') == '0':
        return
    try:
        d = os.path.join(os.environ.get('FIGMA_CDP_HOME') or os.path.expanduser('~/.figma-cdp'), 'journal')
        os.makedirs(d, mode=0o700, exist_ok=True)
        for name in os.listdir(d):
            if time.time() - os.path.getmtime(os.path.join(d, name)) > 14 * 86400:
                os.remove(os.path.join(d, name))
        text = out if isinstance(out, str) else json.dumps(out, default=str)
        entry = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'rid': rid, 'tool': PROG,
                 'file': file or '', 'label': label, 'sha': hashlib.sha256(source.encode()).hexdigest()[:12],
                 'script': source[:20000], 'ok': ok, 'result' if ok else 'error': text[:4000]}
        if not ok:
            entry['hint'] = hint(text)
        with open(os.path.join(d, time.strftime('%Y-%m-%d') + '.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass

def usage(msg):
    print(f'{PROG}: {msg}\n{USAGE}', file=sys.stderr)
    sys.exit(1)

def parse_args(argv, options, flags=('--lib',)):
    """Option values (FIGMA_FILE the default for --file, each flag True when given) and the scripts
    in command-line order, each ('path', p), ('stdin', None) or ('inline', js)."""
    opts = dict.fromkeys(options)
    opts['--file'] = os.environ.get('FIGMA_FILE')
    opts.update(dict.fromkeys(flags, False))
    scripts = []
    args = iter(argv)
    for arg in args:
        if arg in ('-h', '--help'):
            print(__doc__.strip())
            sys.exit(0)
        name, eq, val = arg.partition('=') if arg.startswith('--') else (arg, '', None)
        if arg in flags:
            opts[arg] = True
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
    return opts, scripts

def load(scripts):
    """(label, source) per script: a file's basename, '-e[n]' for the nth inline one, 'stdin'."""
    if sum(kind == 'stdin' for kind, _ in scripts) > 1:
        usage('- (stdin) can be given once')
    # `-e <file.js>` means the file: as JS the path is only a SyntaxError.
    scripts = [('path', v) if kind == 'inline' and re.fullmatch(r'\S+\.m?js', v) and os.path.isfile(v) else (kind, v)
               for kind, v in scripts]
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


opts, specs = parse_args(sys.argv[1:], ('--file', '--timeout', '--screenshot', '--ns', '--recover'), ('--lib', '--where', '--stop'))
shot, rec = opts['--screenshot'], opts['--recover']
require_perch()
if opts['--where']:
    if specs or shot or rec:
        usage('--where takes no script')
    head = perch({'op': 'eval', 'file': opts['--file'] or '', 'sources': ['null']})['tab']
    room = re.match(r'room:([^:]+):', head['tabId'])
    note = f'room {room[1]}: runs minimized or locked' if room else \
        f"{head.get('app') or 'browser'}: needs its window shown and the screen unlocked"
    print(f"perch {head['tabId']} ({note}) {head['url']}")
    sys.exit(0)
if bool(specs) + bool(shot) + bool(rec) != 1:
    usage('give scripts (<js_file>, - or -e <js>), or --screenshot or --recover alone')
scripts = load(specs)
# The library goes in front of the first script only; later scripts share its tab.
rids = [rec] if rec else [uuid.uuid4().hex[:12] for _ in scripts or [None]]
rid = rids[0]
sources = [recover(rec)] if rec else [program(src, r, opts['--ns']) for (_, src), r in zip(scripts, rids)]
if opts['--lib'] and sources:
    sources[0] = with_lib(sources[0])

def until_finished(ask, running):
    """ask() once; for --recover, again every 2 s while the ledger says the script is still running,
    up to --timeout seconds, so a caller never polls with sleep."""
    deadline = time.time() + timeout_seconds(opts['--timeout'])
    res = ask()
    while rec and running(res) and 'still running' in running(res) and time.time() < deadline:
        time.sleep(min(2.0, max(0.0, deadline - time.time())))
        res = ask()
    return res

def log(ok, out):
    label, src = scripts[0] if scripts else ('--recover', rec)
    journal(rid, opts['--file'], label, src, ok, out)

def fail(error):
    print(f"✗ Evaluation error: {error}", file=sys.stderr)
    if hint(error):
        print(hint(error), file=sys.stderr)
    sys.exit(1)

def stopped(ran):
    return f"--stop: script {ran} of {len(scripts)} failed, returned nothing or returned {{error}}; the rest did not run"

if len(scripts) > 1:
    out = perch({'op': 'eval', 'file': opts['--file'] or '', 'sources': sources, 'stop': opts['--stop']},
                timeout=timeout_seconds(opts['--timeout']), rids=rids)
    # A success is {origin: the page URL, result} with keys sorted and non-ASCII escaped, a
    # failure its error.
    out['results'] = [{'ok': False, 'error': ledger_error(r['value'])} if r['ok'] and ledger_error(r['value']) else r
                      for r in out['results']]
    for (label, src), r_id, res in zip(scripts, rids, out['results']):
        journal(r_id, opts['--file'], label, src, res['ok'], res['value'] if res['ok'] else res['error'])
        print(f'== {label} ==')
        print(json.dumps({'origin': res.get('href') or out['origin'], 'result': res['value']}, sort_keys=True)
              if res['ok'] else f"Evaluation error: {timeout_note(res['error'], r_id)}")
        if not res['ok'] and hint(res['error']):
            print(hint(res['error']))
    if out.get('fatal'):
        sys.exit(f"perch: {out['fatal']} (stopped after {len(out['results'])} of {len(scripts)} scripts)")
    if len(out['results']) < len(scripts):
        sys.exit(stopped(len(out['results'])))
    sys.exit(0 if all(r['ok'] for r in out['results']) else 1)

if shot:
    perch({'op': 'screenshot', 'file': opts['--file'] or '', 'path': os.path.abspath(shot)})
    print(f"✓ Screenshot saved to {shot}")
    sys.exit(0)
ask = lambda: perch({'op': 'eval', 'file': opts['--file'] or '', 'sources': sources},
                    timeout=timeout_seconds(opts['--timeout']), rids=[rid])['results'][0]
res = until_finished(ask, lambda res: res['ok'] and ledger_error(res['value']))
err = timeout_note(res['error'], rid) if not res['ok'] else ledger_error(res['value'])
log(err is None, err or res['value'])
if err:
    fail(err)
print(compact(res['value']))
sys.exit(0)
