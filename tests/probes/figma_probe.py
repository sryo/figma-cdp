#!/usr/bin/env python3
"""Live probes of the Plugin API, guarded so they can only touch what they create on the scratch file.

  python3 tests/probes/figma_probe.py --file <scratch-url-or-key> [--timeout <s>] [--record [--record-dir <dir>]] [<probe> ...]

A probe is tests/probes/<name>.js, a script body that gets `pg` (a fresh `__probe` page, already
current) and four reporters: check(what, want, got), refuses(what, fn, regex),
limit(member, verdict, error?), where verdict is one of VERDICTS, and note(key, value) for data
(--out keeps it). <name>.json, when present, says
whether it needs figma_lib.js ("lib": true) and which verdict it expects per member ("limits").
With no names, every probe here runs; a path runs that file.

The guard:
- --file must be the scratch file baseline.json was measured on, and the document root must be
  named SCRATCH_NAME before anything is created.
- A probe body may not name file-level or other-node APIs (DENY); it works on what it creates.
- Every page, variable collection and style named `__probe*` is removed before and after each
  probe, so one that crashed or timed out last time leaves nothing behind once the next runs. A
  timed-out probe is waited for (figma_run.py --recover) before the sweep, since it keeps running
  in the page.
- figma.skipInvisibleInstanceChildren and the current page are put back afterwards.
- The run holds tests/figma_lock.py's lock on the file, so it never overlaps an eval rep.

Prints one JSON line per probe: {probe, passed, failures, limits, drift}. drift lists members whose
verdict differs from <name>.json. Exits 0 only when every probe passed with no drift. --record
writes each verdict to <record-dir>/<member>-<date>.json (default tests/probes/verdicts/). --pin, after
a typings bump or a plan change, writes the verdicts seen into <name>.json.
"""
import argparse, datetime, glob, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tests'))
from figma_lock import file_lock  # noqa: E402

SCRATCH_NAME = 'figma cdp scratch'
VERDICTS = ['works', 'ignored', 'readonly', 'refused', 'plan-limited', 'needs-async', 'missing', 'throws']
DENY = [
    (r'\bfigma\.root\b', 'figma.root: the runner owns the document and its pages'),
    (r'\bfigma\.currentPage\b', 'figma.currentPage: use pg'),
    (r'\bsaveVersionHistoryAsync\b', 'saveVersionHistoryAsync writes the file history'),
    (r'\bimport\w*ByKeyAsync\b', 'library imports reach outside the file'),
    (r'\bloadAllPagesAsync\b', 'loadAllPagesAsync reaches every page'),
    (r'\bget\w*ById(Async)?\s*\(', 'lookups by id reach nodes the probe did not create'),
    (r'\bgetLocal\w*Async\b', 'file-wide lists reach what the probe did not create'),
    (r'\bfigma\.(on|once|off)\s*\(', 'event handlers outlive the probe'),
    (r'\b(closePlugin|showUI|clientStorage)\b', 'plugin lifecycle and storage'),
]

PROGRAM = r'''const SCRATCH = %(name)s, PROBE = /^__probe/, VERDICTS = %(verdicts)s;
if (figma.root.name !== SCRATCH) return { refused: 'the file is ' + JSON.stringify(figma.root.name) + ', not the scratch file ' + JSON.stringify(SCRATCH) };
const sweep = async () => {
  const gone = { pages: 0, collections: 0, styles: 0 };
  const pages = figma.root.children.filter((p) => PROBE.test(p.name));
  if (pages.includes(figma.currentPage)) await figma.setCurrentPageAsync(figma.root.children.find((p) => !PROBE.test(p.name)));
  for (const p of pages) { p.remove(); gone.pages++; }
  for (const c of await figma.variables.getLocalVariableCollectionsAsync()) if (PROBE.test(c.name)) { c.remove(); gone.collections++; }
  for (const k of ['Paint', 'Text', 'Effect', 'Grid']) {
    const list = figma['getLocal' + k + 'StylesAsync'];
    if (list) for (const s of await list.call(figma)) if (PROBE.test(s.name)) { s.remove(); gone.styles++; }
  }
  return gone;
};
if (%(sweep_only)s) return { swept: await sweep() };
const swept = await sweep();
const home = figma.currentPage, flags = { skipInvisibleInstanceChildren: figma.skipInvisibleInstanceChildren };
const fail = [], limits = {}, notes = {};
const msg = (e) => String((e && e.message) || e);
const check = (what, want, got) => { const w = JSON.stringify(want), g = JSON.stringify(got); if (w !== g) fail.push({ what, want: w, got: g }); };
const refuses = async (what, f, re) => {
  try { await f(); fail.push({ what, want: 'refused', got: 'accepted' }); } catch (e) { if (re && !re.test(msg(e))) fail.push({ what, want: String(re), got: msg(e) }); }
};
const limit = (member, verdict, e) => {
  if (!VERDICTS.includes(verdict)) fail.push({ what: 'limit ' + member, want: VERDICTS.join('|'), got: verdict });
  limits[member] = { verdict, error: e === undefined ? null : msg(e) };
};
const note = (key, value) => { notes[key] = value; };
const pg = figma.createPage();
pg.name = '__probe';
await figma.setCurrentPageAsync(pg);
try {
  await (async (pg, check, refuses, limit, note) => {
%(body)s
  })(pg, check, refuses, limit, note);
} catch (e) {
  fail.push({ what: 'probe threw', want: 'no error', got: String((e && e.stack) || e).split('\n').slice(0, 3).join(' | ') });
} finally {
  if (!home.removed) await figma.setCurrentPageAsync(home);
  for (const k of Object.keys(flags)) if (figma[k] !== flags[k]) figma[k] = flags[k];
  await sweep();
}
return { passed: !fail.length, failures: fail, limits, notes, editorType: figma.editorType, swept };'''


def die(msg, code=2):
    print(f'figma_probe.py: {msg}', file=sys.stderr)
    sys.exit(code)


def scratch_key():
    with open(os.path.join(ROOT, 'tests', 'eval', 'baseline.json')) as f:
        return json.load(f)['meta']['file']


def file_key(arg):
    m = re.search(r'figma\.com/(?:file|design|proto|board)/([A-Za-z0-9]+)', arg or '')
    return m.group(1) if m else arg


def lint(src):
    """Why a probe body may not run: the DENY entries it names."""
    return [why for rx, why in DENY if re.search(rx, src)]


def program(body='', sweep_only=False):
    return PROGRAM % {'name': json.dumps(SCRATCH_NAME), 'verdicts': json.dumps(VERDICTS), 'body': body,
                      'sweep_only': 'true' if sweep_only else 'false'}


def figma_run(args, file, timeout, script=None, lib=False):
    cmd = [sys.executable, os.path.join(ROOT, 'figma_run.py'), '--file', file, '--timeout', str(timeout)]
    cmd += (['--lib'] if lib else []) + (args or ['-'])
    # Probes are harness runs, kept out of the journal as run.py's are.
    p = subprocess.run(cmd, input=script, capture_output=True, text=True, env={**os.environ, 'FIGMA_CDP_JOURNAL': '0'})
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def after_timeout(err, file, timeout, wait):
    """A timed-out probe keeps running in the page: wait for it to finish before sweeping."""
    m = re.search(r'--recover (\S+)', err)
    deadline = time.time() + wait
    while m and time.time() < deadline:
        code, out, e = figma_run(['--recover', m.group(1)], file, timeout)
        if code == 0 or 'still running' not in e:
            break
        time.sleep(10)
    return figma_run(None, file, timeout, program(sweep_only=True))


def probes(names):
    paths = [n if os.path.isfile(n) else os.path.join(HERE, n + '.js') for n in names] if names else sorted(glob.glob(os.path.join(HERE, '*.js')))
    for path in paths:
        if not os.path.isfile(path):
            die(f'no probe {path}')
        spec_path = path[:-3] + '.json'
        spec = {}
        if os.path.isfile(spec_path):
            with open(spec_path) as f:
                spec = json.load(f)
        with open(path, encoding='utf-8') as f:
            yield os.path.basename(path)[:-3], f.read(), dict(spec, _path=spec_path)


def typings_version():
    try:
        with open(os.path.join(ROOT, 'tests', 'api', 'typings.lock')) as f:
            return f.read().strip()
    except OSError:
        return None


def record(out_dir, name, res, plan):
    os.makedirs(out_dir, exist_ok=True)
    day = datetime.date.today().isoformat()
    for member, v in res['limits'].items():
        row = {'member': member, 'verdict': v['verdict'], 'error': v['error'], 'probe': name,
               'typingsVersion': typings_version(), 'date': day, 'editorType': res.get('editorType'),
               'plan': plan if v['verdict'] in ('refused', 'plan-limited') else None}
        with open(os.path.join(out_dir, f'{member}-{day}.json'), 'w') as f:
            json.dump(row, f, indent=1)
            f.write('\n')


def main():
    ap = argparse.ArgumentParser(description='Guarded live probes of the Plugin API on the scratch file.')
    ap.add_argument('--file', required=True, help='the scratch file URL or key')
    ap.add_argument('--timeout', type=int, default=120)
    ap.add_argument('--recover-wait', type=int, default=300, help='seconds to wait for a timed-out probe before sweeping')
    ap.add_argument('--record', action='store_true', help='write a verdict file per member')
    ap.add_argument('--record-dir', default=os.path.join(HERE, 'verdicts'))
    ap.add_argument('--plan', default='free(assumed)', help="the file's plan, stamped on refused verdicts")
    ap.add_argument('--out', help='write each probe\'s full result, notes included, to <out>/<name>.json')
    ap.add_argument('--pin', action='store_true', help="write the verdicts seen into <name>.json's limits (a judge edit: commit it with a Judge-Change line)")
    ap.add_argument('probes', nargs='*')
    a = ap.parse_args()
    key = file_key(a.file)
    if key != scratch_key():
        die(f'probes run only on the scratch file {scratch_key()} (tests/eval/baseline.json), not {key}')
    todo = list(probes(a.probes))
    for name, body, _ in todo:
        bad = lint(body)
        if bad:
            die(f'{name}.js names what a probe may not touch: ' + '; '.join(bad))
    ok = True
    with file_lock(key):
        for name, body, spec in todo:
            code, out, err = figma_run(None, a.file, a.timeout, program(body), spec.get('lib', False))
            if code != 0:
                if err.startswith('timeout') or 'timeout:' in err:
                    after_timeout(err, a.file, a.timeout, a.recover_wait)
                print(json.dumps({'probe': name, 'passed': False, 'error': err or out}))
                ok = False
                continue
            res = json.loads(out)
            if 'refused' in res:
                die(res['refused'])
            want = spec.get('limits', {})
            got = {m: v['verdict'] for m, v in res['limits'].items()}
            drift = {m: {'want': want.get(m), 'got': got.get(m)} for m in sorted(set(want) | set(got)) if want.get(m) != got.get(m)}
            print(json.dumps({'probe': name, 'passed': res['passed'], 'failures': res['failures'], 'limits': res['limits'], 'drift': drift,
                              'notes': sorted(res.get('notes') or {})}))
            if a.out:
                os.makedirs(a.out, exist_ok=True)
                with open(os.path.join(a.out, name + '.json'), 'w') as f:
                    json.dump(res, f, indent=1)
            if a.pin and res['passed'] and got:
                path = spec.pop('_path')
                spec = {**spec, 'limits': dict(sorted(got.items()))}
                with open(path, 'w') as f:
                    json.dump(spec, f, indent=2)
                    f.write('\n')
                drift = {}
            ok = ok and res['passed'] and not drift
            if a.record:
                record(a.record_dir, name, res, a.plan)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
