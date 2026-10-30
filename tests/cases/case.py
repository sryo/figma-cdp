#!/usr/bin/env python3
"""Failure cases for improving figma-cdp: file one when the skill fails or a build doesn't match its
source, sort out why, fix it test-first on its own branch, and record the outcome.

  python3 tests/cases/case.py new [--last | --rid <id>] [--symptom "<what went wrong>"] [--expected "<src path:line or value>"]
  python3 tests/cases/case.py triage <case>          # proposes a class from the evidence; prints the checks left
  python3 tests/cases/case.py set <case> class=<class> [status=<status>] [key=value ...]
  python3 tests/cases/case.py snapshot <case> --node <id> --file <url> [--max <n>]  # seed.json: the subtree, rebuildable anywhere
  python3 tests/cases/case.py claim <case> [--steal] # a worktree .claude/worktrees/case-<case> on branch case/<case>
  python3 tests/cases/case.py close <case> --status merged|wontfix|parked|out-of-scope --reason "<why>" [--commit <sha>]
  python3 tests/cases/case.py list | stats

Cases live in ~/.figma-cdp/inbox/<case>/ (FIGMA_CDP_HOME moves it), outside the repo, since they
quote the user's own files: case.json (fields) and notes.md (expected, actual, oracle, routes).
--last / --rid pull the eval from the journal figma_run.py and figma_batch_run.py keep in
~/.figma-cdp/journal/. A closed case leaves one file in tests/ledger/<case>.json, committed with
its fix; read the ledger before proposing a fix for a similar signature. AGENTS.md → Improving the
skill has the loop, the classes and when each is decided.
"""
import argparse, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('FIGMA_CDP_REPO') or os.path.dirname(os.path.dirname(HERE))
HOME = os.environ.get('FIGMA_CDP_HOME') or os.path.expanduser('~/.figma-cdp')
INBOX, JOURNAL = os.path.join(HOME, 'inbox'), os.path.join(HOME, 'journal')
LEDGER = os.path.join(REPO, 'tests', 'ledger')
LOSSES = os.path.join(REPO, 'tests', 'known_losses.json')
LEASE_S = 4 * 3600

# In the order triage decides them; the first that fits wins. AGENTS.md → Improving the skill.
CLASSES = ['env', 'harness', 'source-extract', 'helper-bug', 'doc-wrong', 'api-unknown', 'api-plan-limited',
           'api-limit', 'agent-ignored-doc']
STATUSES = ['open', 'claimed', 'parked', 'merged', 'wontfix', 'out-of-scope', 'dup']
ENV = re.compile(r"^(perch: )?(timeout|stale_tab|tab_not_visible|tab_not_scriptable|no_tab|ambiguous_tab|no_perch|perch_daemon|no_browser"
                 r"|window_offscreen|dialog_open)\b|figma is undefined|agent-browser not found|node not found", re.M)
PLAN = re.compile(r'paid plan|with your current plan|limited to \d+ modes? only|requires? an? (paid|professional|organization|enterprise)|upgrade (your|to)|not available on (your|the) plan', re.I)


def die(msg, code=1):
    print(f'case.py: {msg}', file=sys.stderr)
    sys.exit(code)


def signature(text):
    """What makes two failures the same: the first line, lowercased, with node ids, quoted text and
    numbers blanked."""
    line = (text or '').strip().split('\n', 1)[0].lower()
    line = re.sub(r'^(✗ )?evaluation error: ', '', line)
    line = re.sub(r'\bi?\d+:\d+(;\d+:\d+)*\b', '<id>', line)
    line = re.sub(r'"[^"]*"|\'[^\']*\'|`[^`]*`', '<s>', line)
    return re.sub(r'\d+(\.\d+)?', '#', line)[:160]


def journal_entries():
    if not os.path.isdir(JOURNAL):
        return []
    out = []
    for name in sorted(os.listdir(JOURNAL)):
        with open(os.path.join(JOURNAL, name), encoding='utf-8') as f:
            out += [json.loads(l) for l in f if l.strip()]
    return out


def read(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def case_dir(cid):
    d = os.path.join(INBOX, cid)
    if not os.path.isfile(os.path.join(d, 'case.json')):
        die(f'no case {cid} in {INBOX}')
    return d


def load(cid):
    return read(os.path.join(case_dir(cid), 'case.json'))


def save(case):
    path = os.path.join(INBOX, case['id'], 'case.json')
    with open(path + '.tmp', 'w') as f:
        json.dump(case, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(path + '.tmp', path)


def cases():
    if not os.path.isdir(INBOX):
        return []
    return [read(os.path.join(INBOX, d, 'case.json')) for d in sorted(os.listdir(INBOX))
            if os.path.isfile(os.path.join(INBOX, d, 'case.json'))]


def ledger():
    if not os.path.isdir(LEDGER):
        return []
    return [read(os.path.join(LEDGER, f)) for f in sorted(os.listdir(LEDGER)) if f.endswith('.json')]


def skill_rev():
    try:
        rev = subprocess.run(['git', '-C', REPO, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(['git', '-C', REPO, 'status', '--porcelain'], capture_output=True, text=True).stdout.strip()
        return rev + ('-dirty' if dirty else '')
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def known_loss(text):
    try:
        losses = read(LOSSES)['losses']
    except (OSError, ValueError, KeyError):
        return None
    return next((l for l in losses if re.search(l['pattern'], text or '', re.I)), None)


def slug(text):
    words = re.findall(r'[a-z0-9]+', (text or 'case').lower())[:6]
    return '-'.join(words) or 'case'


def cmd_new(a):
    entry, context = None, []
    if a.last or a.rid:
        entries = journal_entries()
        idx = [i for i, e in enumerate(entries) if (e['rid'] == a.rid if a.rid else not e['ok'])]
        if not idx:
            die(f'no journal entry {a.rid}' if a.rid else f'no failed eval in {JOURNAL}')
        i = idx[-1]
        entry = entries[i]
        context = [e for e in entries[max(0, i - 5):i] if e.get('file') == entry.get('file')]
    error = entry.get('error') if entry else None
    symptom = a.symptom or (error or '').split('\n', 1)[0]
    if not symptom:
        die('say what went wrong with --symptom, or point at a failed eval with --last / --rid')
    loss = known_loss(symptom + '\n' + (error or ''))
    if loss and not a.force:
        die(f"a known loss ({loss['id']}, {loss['doc']}); --force files it anyway", 3)
    sig = signature(error or symptom)
    dup = next((c['id'] for c in cases() if c['signature'] == sig and c['status'] not in ('wontfix', 'out-of-scope')), None)
    dup = dup or next((r['case'] for r in ledger() if r.get('signature') == sig), None)
    os.makedirs(INBOX, mode=0o700, exist_ok=True)
    base = time.strftime('%Y%m%d') + '-' + slug(symptom)
    for n in range(1, 100):
        cid = base if n == 1 else f'{base}-{n}'
        try:
            os.mkdir(os.path.join(INBOX, cid))
            break
        except FileExistsError:
            continue
    case = {'id': cid, 'created': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'skill_rev': skill_rev(), 'symptom': symptom,
            'expected': a.expected or '', 'error': error or '', 'hint': (entry or {}).get('hint'), 'signature': sig,
            'file': (entry or {}).get('file', ''), 'backend': (entry or {}).get('backend', ''),
            'journal': ([entry] if entry else []), 'context': context, 'class': None, 'proposed_class': None,
            'repro_level': None, 'repro_path': None, 'status': 'dup' if dup else 'open', 'dup_of': dup, 'claim': None}
    save(case)
    with open(os.path.join(INBOX, cid, 'notes.md'), 'w') as f:
        f.write(f"# {symptom}\n\n## Expected\n{a.expected or '(source path:line, manifest entry or value)'}\n\n"
                "## Actual\n(recon lines, node ids, fidelity rows)\n\n## Oracle\n(lookup hits, probe verdicts)\n\n"
                "## Routes tried\n(each alternate route and its verdict; api-limit needs all of them failing)\n")
    print(json.dumps({'case': cid, 'status': case['status'], 'dup_of': dup, 'signature': sig, 'dir': os.path.join(INBOX, cid)}))


def oracle(text, limit=5):
    """The Plugin API members that best match an error or symptom, from the committed typings surface."""
    query = (text or '').strip().split('\n', 1)[0]
    if not query:
        return []
    try:
        p = subprocess.run(['node', os.path.join(os.path.dirname(HERE), 'api', 'figma_api.mjs'), 'lookup', '--json', '--limit', str(limit), query],
                           capture_output=True, text=True, timeout=30)
        hits = json.loads(p.stdout) if p.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return [{k: h[k] for k in ('member', 'ro', 'covered', 'docUrl')} for h in hits]


def cmd_triage(a):
    c = load(a.case)
    text = '\n'.join([c['symptom'], c['error']] + [e.get('error', '') for e in c['journal']])
    checks = []
    if ENV.search(text):
        proposed, why = 'env', 'a connection or browser error, not the Plugin API'
    elif PLAN.search(text):
        proposed, why = 'api-plan-limited', 'the error names a plan; confirm with a probe on the scratch file'
    elif c.get('hint'):
        proposed, why = 'agent-ignored-doc', f"a known error with a hint ({c['hint']}); check the session saw it"
        checks.append('rerun 3 reps: it is this class only if the miss repeats in 2 of 3')
    else:
        proposed, why = None, 'no deterministic signal; walk the checks'
    checks += [
        'env: does it reproduce? replay the journal script (L0/L1) or 3 reps (agent-level); 0 of 3 failing is env',
        'harness: does a manual read of the --keep page disagree with the scorer?',
        'source-extract: is figma_source.py output wrong or missing for the cited source?',
        'helper-bug: does a raw Plugin API script on a __probe page succeed where __fx or the importer fails?',
        'doc-wrong: does a probe contradict a reference line or the stub?',
        'api-unknown / api-plan-limited / api-limit: oracle lists the typings members that match (tests/api/figma_api.mjs lookup);'
        ' an uncovered one is an api-unknown lead. Probe each candidate (tests/probes/figma_probe.py) and try the alternate'
        ' routes; api-limit needs every route to fail',
        'agent-ignored-doc: is the recipe already in references or the cheat sheet, and missed in 2 of 3 reps?',
    ]
    c['proposed_class'] = proposed
    c['oracle'] = oracle(c['error'] or c['symptom'])
    save(c)
    print(json.dumps({'case': c['id'], 'proposed_class': proposed, 'why': why, 'oracle': c['oracle'], 'checks': checks}, indent=2))


def cmd_set(a):
    c = load(a.case)
    for kv in a.pairs:
        k, eq, v = kv.partition('=')
        if not eq:
            die(f'{kv}: use key=value')
        if k == 'class' and v not in CLASSES:
            die(f"class {v}: one of {', '.join(CLASSES)}")
        if k == 'status' and v not in STATUSES:
            die(f"status {v}: one of {', '.join(STATUSES)}")
        c[k] = None if v == '' else v
    save(c)
    print(json.dumps({k: c[k] for k in ['id', 'class', 'status'] + [kv.split('=', 1)[0] for kv in a.pairs]}))


def cmd_snapshot(a):
    """The failing subtree as a seed (tests/cases/snapshot.js): journal scripts name the user file's node
    ids, so only a seed can be rebuilt on the scratch file (tests/cases/rebuild.js) or the stub."""
    c = load(a.case)
    with open(os.path.join(HERE, 'snapshot.js'), encoding='utf-8') as f:
        src = f'const SNAP_ID = {json.dumps(a.node)}, SNAP_MAX = {a.max};\n' + f.read()
    p = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'figma_run.py'), '--file', a.file, '-'], input=src,
                       capture_output=True, text=True, env={**os.environ, 'FIGMA_CDP_JOURNAL': '0'})
    if p.returncode != 0:
        die(f'snapshot failed: {p.stderr.strip() or p.stdout.strip()}')
    seed = json.loads(p.stdout)
    with open(os.path.join(case_dir(c['id']), 'seed.json'), 'w') as f:
        json.dump(seed, f, indent=1, ensure_ascii=False)
        f.write('\n')
    c['snapshot'] = 'seed.json'
    save(c)
    print(json.dumps({'id': c['id'], 'snapshot': 'seed.json', 'nodes': seed['nodes'], 'truncated': seed['truncated']}))


def cmd_claim(a):
    c = load(a.case)
    lock = os.path.join(INBOX, c['id'], 'claim')
    try:
        os.mkdir(lock)
    except FileExistsError:
        held = c.get('claim') or {}
        age = time.time() - held.get('at', 0)
        if not a.steal or age < LEASE_S:
            die(f"claimed {int(age // 60)} min ago by {held.get('by', '?')}"
                + ('' if a.steal else f'; --steal after {LEASE_S // 3600} h'), 2)
    branch, wt = f"case/{c['id']}", os.path.join(REPO, '.claude', 'worktrees', f"case-{c['id']}")
    if not os.path.isdir(wt):
        exists = subprocess.run(['git', '-C', REPO, 'rev-parse', '--verify', '--quiet', branch], capture_output=True).returncode == 0
        r = subprocess.run(['git', '-C', REPO, 'worktree', 'add', wt] + ([branch] if exists else ['-b', branch, 'main']),
                           capture_output=True, text=True)
        if r.returncode:
            shutil.rmtree(lock, ignore_errors=True)
            die(f'git worktree add: {r.stderr.strip()}')
    c['claim'] = {'by': os.environ.get('CLAUDE_SESSION_ID') or os.environ.get('USER', '?'), 'at': time.time(), 'branch': branch, 'worktree': wt}
    c['status'] = 'claimed'
    save(c)
    print(json.dumps({'case': c['id'], 'branch': branch, 'worktree': wt}))


def cmd_close(a):
    c = load(a.case)
    if a.status == 'merged' and not a.commit:
        die('merged needs --commit <sha> of the fix')
    if a.status == 'merged' and not c.get('class'):
        die('set the class first: case.py set <case> class=<class>')
    row = {'case': c['id'], 'class': c.get('class'), 'signature': c['signature'], 'symptom': c['symptom'],
           'status': a.status, 'reason': a.reason, 'commit': a.commit, 'repro': c.get('repro_path'),
           'opened': c['created'], 'closed': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    os.makedirs(LEDGER, exist_ok=True)
    with open(os.path.join(LEDGER, c['id'] + '.json'), 'w') as f:
        json.dump(row, f, indent=2, ensure_ascii=False)
        f.write('\n')
    c['status'] = a.status
    save(c)
    shutil.rmtree(os.path.join(INBOX, c['id'], 'claim'), ignore_errors=True)
    print(json.dumps({'case': c['id'], 'status': a.status, 'ledger': os.path.relpath(os.path.join(LEDGER, c['id'] + '.json'), REPO)}))


def cmd_list(a):
    for c in cases():
        print(f"{c['id']}  {c['status']:<12} {c.get('class') or ('?' + (c.get('proposed_class') or '')):<20} {c['symptom'][:80]}")


def cmd_stats(a):
    rows = cases()
    by = lambda key: dict(sorted(((k, sum(1 for r in rows if (r.get(key) or 'none') == k)) for k in {r.get(key) or 'none' for r in rows})))
    sigs = {}
    for r in rows:
        sigs[r['signature']] = sigs.get(r['signature'], 0) + 1
    print(json.dumps({'cases': len(rows), 'by_status': by('status'), 'by_class': by('class'),
                      'repeated_signatures': {s: n for s, n in sorted(sigs.items(), key=lambda x: -x[1]) if n > 1},
                      'ledger': len(ledger())}, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('new')
    p.add_argument('--last', action='store_true', help='the latest failed eval in the journal')
    p.add_argument('--rid', help='a journal entry by request id')
    p.add_argument('--symptom')
    p.add_argument('--expected')
    p.add_argument('--force', action='store_true', help='file a known loss anyway')
    p = sub.add_parser('triage'); p.add_argument('case')
    p = sub.add_parser('set'); p.add_argument('case'); p.add_argument('pairs', nargs='+')
    p = sub.add_parser('snapshot'); p.add_argument('case'); p.add_argument('--node', required=True)
    p.add_argument('--file', required=True); p.add_argument('--max', type=int, default=2000)
    p = sub.add_parser('claim'); p.add_argument('case'); p.add_argument('--steal', action='store_true')
    p = sub.add_parser('close'); p.add_argument('case')
    p.add_argument('--status', required=True, choices=['merged', 'wontfix', 'parked', 'out-of-scope'])
    p.add_argument('--reason', required=True); p.add_argument('--commit')
    sub.add_parser('list'); sub.add_parser('stats')
    a = ap.parse_args()
    globals()['cmd_' + a.cmd](a)


if __name__ == '__main__':
    main()
