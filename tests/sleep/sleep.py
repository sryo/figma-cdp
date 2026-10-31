#!/usr/bin/env python3
"""The sleep pass: consolidate what past sessions show into lessons that later sessions keep.

  python3 tests/sleep/sleep.py mine [--since <date>|--all] [--source <dir> ...] [--out <signals.jsonl>]
  python3 tests/sleep/sleep.py digest [<signals.jsonl>] [--top 12] [--explore 3] [--seed N] [--json <out>] [--mark]
  python3 tests/sleep/sleep.py learn --id <slug> --kind hint|doc --expect <text> [--error <text>] [--file <doc>] [--signature <sig>] [--evidence "<session ts>"]
  python3 tests/sleep/sleep.py replay
  python3 tests/sleep/sleep.py check [--candidate <run.json>] [--baseline <run.json>] [--dry-run]

Wake: sessions leave short-term traces, the Claude Code transcripts under ~/.claude/projects (main
and subagents, for figma-cdp, perch and avis) and the eval journal in ~/.figma-cdp/journal.
`mine` reads them since the last sleep (--source replaces both: a run.py --transcripts folder, say,
whose kept journals it reads too) into signals, one JSON line each: a failed call, a call
slower than 60 s, a tool result over 20,000 chars, a retry chain (the same tool called again with
near-identical input after a failure), or a user correction or interruption, each with its session,
timestamp, a short excerpt and its signature (case.py's: ids, quoted text and numbers blanked).

`digest` clusters signals by signature and ranks them by impact. A cluster is `relapse` when its
signature is a lesson's and it occurred after the lesson was added (the consolidated fix is not
working; these rank first), `consolidated` when it is a lesson's and didn't recur, `ledger` when a
closed case has it, `hinted` when a HINTS row of the helpers already fires on it, else `new`. The
picks are the top N by impact plus a few random `new` clusters (--explore), so a rare kind of
failure gets looked at too. Each cluster names a consolidation target: an error hint, a helper
fix, a doc rule at the point of use, an eval case, or a memory.

Each fix lands test-first (AGENTS.md → Improving the skill), and `learn` records it in
tests/sleep/lessons.jsonl as an executable expectation: a `hint` lesson is an error text both
helpers must answer with a hint containing `expect`; a `doc` lesson is a regex its file must keep
matching. `replay` checks every lesson, so trimming a doc for bytes or rewriting a helper can't
silently drop what an earlier sleep learned. `check` is the no-regression gate for a sleep's
changes: the offline suites, budget, replay, and compare.py on a live run when one is given.
FIGMA_CDP_LESSONS points at another lessons file (tests).
"""
import argparse, ast, datetime, difflib, json, os, random, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
HOME = os.environ.get('FIGMA_CDP_HOME') or os.path.expanduser('~/.figma-cdp')
LESSONS = os.environ.get('FIGMA_CDP_LESSONS') or os.path.join(HERE, 'lessons.jsonl')
STATE = os.path.join(HOME, 'sleep', 'state.json')
PROJECTS = os.path.expanduser('~/.claude/projects')
sys.path.insert(0, os.path.join(REPO, 'tests', 'cases'))
import case  # noqa: E402  (signature, ledger, OFFLINE)

SLOW_S, HEAVY_CHARS, SIMILAR = 60, 20000, 0.8
# Waiting on these is the point of calling them, not a stall.
WAITS = re.compile(r'^(Agent|Task|Monitor|ScheduleWakeup|AskUserQuestion|mcp__ccd_session__.*)$')
CORRECTION = re.compile(r"^\s*(no\b|nope|don'?t|do not|stop\b|wrong|why (did|are|is|would)|never\b|i said|not (that|what)|"
                        r"instead\b|undo\b|revert\b|wait\b|that's not|thats not)", re.I)
WEIGHT = {'error': 1.0, 'slow': 1 / 30, 'heavy': 1 / 4000, 'retry': 1.0, 'correction': 5.0}
TARGET = {
    'error': 'error hint or helper fix: a HINTS row in both helpers (perch: an error that names its fix), then a hint lesson',
    'slow': 'helper fix (batch, background, a shorter wait) or an env note in connection.md',
    'heavy': 'trim the output at the helper, or point the doc at the exact section',
    'retry': 'doc rule at the point of use, or a validating helper that refuses the bad call',
    'correction': 'memory (feedback, with why) or an AGENTS.md rule',
}


def parse_ts(s):
    if not s:
        return None
    s = s.replace('Z', '+00:00')
    s = re.sub(r'([+-]\d\d)(\d\d)$', r'\1:\2', s)
    try:
        t = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def project(path):
    for name in ('figma-cdp', 'perch', 'avis'):
        if name in path:
            return name
    return 'other'


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(text_of(c.get('text') if c.get('type') == 'text' else c.get('content', '')) for c in content if isinstance(c, dict))
    return ''


def error_line(text):
    """The line that says what failed: a Python traceback's last line, else the first one."""
    lines = [l for l in (text or '').splitlines() if l.strip() and not re.match(r'^Exit code \d+', l)]
    if any(l.startswith('Traceback (most recent call last)') for l in lines):
        return lines[-1]
    return lines[0] if lines else (text or '').strip()


def signature(line):
    """case.py's signature, with request ids and other hex tokens blanked too."""
    return case.signature(re.sub(r'\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{8,}\b', '<hex>', line or ''))


def shape(name, inp):
    """What kind of call this was: the script a Bash command runs, the file a Read reads, else the tool."""
    if name == 'Bash':
        cmd = inp.get('command', '')
        m = re.search(r'[\w.-]+\.(?:py|mjs|cjs|js|sh)\b', cmd)
        if m:
            return m.group(0)
        for part in re.split(r'&&|\|\||;|\||\n', cmd):
            words = part.split()
            if words and not re.match(r'^(cd|export|echo|set|true)$|^\w+=', words[0]):
                return words[0]
        return 'Bash'
    if name == 'Read':
        return 'Read ' + os.path.basename(inp.get('file_path', ''))
    return re.sub(r'^mcp__[^_]+(?:_[^_]+)*?__', '', name)


def excerpt(s, n=200):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n - 1] + '…'


def transcripts(sources, since):
    for src in sources:
        for root, _, files in os.walk(src):
            for f in sorted(files):
                p = os.path.join(root, f)
                if f.endswith('.jsonl') and (since is None or os.path.getmtime(p) >= since.timestamp()):
                    yield p


def mine_file(path, since):
    proj, out = project(path), []
    uses, last_use, chain = {}, None, None
    sig = lambda kind, ts, sess, **kw: out.append({'kind': kind, 'project': proj, 'source': 'transcript', 'file': path,
                                                   'session': sess, 'ts': ts, **kw})
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if not re.search(r'"(tool_use|tool_result|user|ok)"', line):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if 'rid' in row and row.get('ok') is False:
                journal_error(out, row, since)
                continue
            msg, ts = row.get('message') or {}, row.get('timestamp')
            sess = row.get('sessionId') or row.get('session_id') or os.path.basename(path)[:-6]
            t = parse_ts(ts)
            content = msg.get('content')
            if row.get('type') == 'user' and (isinstance(content, str) or (isinstance(content, list) and not any(
                    isinstance(c, dict) and c.get('type') == 'tool_result' for c in content))):
                said = text_of(content).strip()
                if since and t and t < since or not said or said.startswith('<') or row.get('isMeta'):
                    continue
                if said.startswith('[Request interrupted'):
                    sig('correction', ts, sess, sig='interrupted', text=excerpt(said), after=last_use and last_use['name'])
                elif CORRECTION.match(said):
                    sig('correction', ts, sess, sig='correction: ' + ' '.join(said.lower().split()[:6]), text=excerpt(said),
                        after=last_use and last_use['name'])
                continue
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get('type') == 'tool_use':
                    u = {'name': c.get('name', ''), 'input': c.get('input') or {}, 'ts': t}
                    u['shape'] = shape(u['name'], u['input'])
                    u['flat'] = json.dumps(u['input'], sort_keys=True)[:4000]
                    uses[c.get('id')] = last_use = u
                elif c.get('type') == 'tool_result':
                    u = uses.pop(c.get('tool_use_id'), None)
                    if not u or since and t and t < since:
                        continue
                    body = text_of(c.get('content'))
                    failed = bool(c.get('is_error')) or bool(re.match(r'\s*(Exit code [1-9]|✗ |Error: )', body))
                    if failed:
                        line1 = error_line(body)
                        sig('error', ts, sess, sig=signature(line1), text=excerpt(line1), shape=u['shape'], call=excerpt(u['flat']))
                    if u['ts'] and t and not WAITS.match(u['name']) and not u['input'].get('run_in_background'):
                        secs = (t - u['ts']).total_seconds()
                        if secs >= SLOW_S:
                            sig('slow', ts, sess, sig=f"slow: {u['shape']}", value=round(secs, 1), shape=u['shape'], call=excerpt(u['flat']))
                    if len(body) >= HEAVY_CHARS:
                        sig('heavy', ts, sess, sig=f"heavy: {u['shape']}", value=len(body), shape=u['shape'], call=excerpt(u['flat']))
                    # A retry chain: calls to one tool, near-identical input, starting from a failure.
                    if chain and chain['name'] == u['name'] and difflib.SequenceMatcher(None, chain['flat'], u['flat']).ratio() >= SIMILAR:
                        chain['n'] += 1
                        chain['flat'] = u['flat']
                    else:
                        flush_chain(chain, sig)
                        chain = {'name': u['name'], 'shape': u['shape'], 'flat': u['flat'], 'n': 1, 'ts': ts, 'sess': sess,
                                 'call': excerpt(u['flat'])} if failed else None
    flush_chain(chain, sig)
    return out


def flush_chain(chain, sig):
    if chain and chain['n'] >= 2:
        sig('retry', chain['ts'], chain['sess'], sig=f"retry: {chain['shape']}", value=chain['n'], shape=chain['shape'], call=chain['call'])


def journal_error(out, e, since):
    t = parse_ts(e.get('ts'))
    if not (since and t and t < since):
        line1 = error_line(e.get('error'))
        out.append({'kind': 'error', 'project': 'figma-cdp', 'source': 'journal', 'session': e.get('rid', ''), 'ts': e.get('ts'),
                    'sig': signature(line1), 'text': excerpt(line1), 'shape': e.get('tool', ''), 'hinted': bool(e.get('hint'))})


def state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def cmd_mine(a):
    if a.all:
        since = None
    elif a.since:
        since = parse_ts(a.since if 'T' in a.since else a.since + 'T00:00:00+00:00')
    else:
        last = state().get('last_sleep')
        since = parse_ts(last) if last else datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)
    sources = a.source or ([os.path.join(PROJECTS, d) for d in sorted(os.listdir(PROJECTS)) if re.search(r'figma-cdp|perch|avis', d)]
                           if os.path.isdir(PROJECTS) else []) + [case.JOURNAL]
    signals = []
    for p in transcripts(sources, since):
        signals += mine_file(p, since)
    signals.sort(key=lambda s: s.get('ts') or '')
    out = a.out or os.path.join(HOME, 'sleep', datetime.date.today().isoformat(), 'signals.jsonl')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w') as f:
        f.writelines(json.dumps(s, ensure_ascii=False) + '\n' for s in signals)
    counts = {}
    for s in signals:
        counts[s['kind']] = counts.get(s['kind'], 0) + 1
    print(f"{len(signals)} signals since {since.isoformat() if since else 'the start'} → {out}: "
          + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))


def lessons():
    if not os.path.isfile(LESSONS):
        return []
    with open(LESSONS) as f:
        return [json.loads(l) for l in f if l.strip()]


def helper_hints(name):
    """The HINTS table of a helper, read without running it."""
    with open(os.path.join(REPO, name)) as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'HINTS' for t in node.targets):
            return ast.literal_eval(node.value)
    return []


def hint_for(table, error):
    message = (error or '').split('\n', 1)[0]
    return next((fix for pattern, fix in table if re.search(pattern, message)), None)


def cluster(signals, known):
    by = {}
    for s in signals:
        c = by.setdefault((s['kind'], s['sig']), {'kind': s['kind'], 'sig': s['sig'], 'project': s['project'], 'count': 0,
                                                   'value': 0, 'sessions': set(), 'evidence': [], 'last': '', 'hinted': False})
        c['count'] += 1
        c['value'] += s.get('value', 1)
        c['sessions'].add(s['session'])
        c['last'] = max(c['last'], s.get('ts') or '')
        c['hinted'] = c['hinted'] or s.get('hinted', False)
        if len(c['evidence']) < 5:
            c['evidence'].append({k: s[k] for k in ('session', 'ts', 'text', 'call', 'value', 'source') if k in s})
    table = helper_hints('figma_run.py')
    out = []
    for c in by.values():
        c['sessions'] = len(c['sessions'])
        lesson = known['lessons'].get(c['sig'])
        if lesson:
            added = parse_ts(lesson.get('added'))
            recurred = added and parse_ts(c['last']) and parse_ts(c['last']) > added
            c['status'], c['lesson'] = ('relapse' if recurred else 'consolidated'), lesson['id']
        elif c['sig'] in known['ledger']:
            c['status'] = 'ledger'
        elif c['kind'] == 'error' and (c['hinted'] or hint_for(table, (c['evidence'][0].get('text') or ''))):
            c['status'] = 'hinted'
        else:
            c['status'] = 'new'
        c['impact'] = round(c['value'] * WEIGHT[c['kind']] if c['kind'] in ('slow', 'heavy') else c['count'] * WEIGHT[c['kind']], 2)
        if c['status'] == 'relapse':
            c['target'] = f"relapse of lesson {c['lesson']}: the consolidated fix isn't working; move it to the point of use"
        elif c['status'] == 'hinted':
            c['target'] = 'agent-ignored-doc: move the rule to the point of use (hint fires but the call repeats)'
        else:
            c['target'] = TARGET[c['kind']]
        del c['hinted']
        out.append(c)
    order = {'relapse': 0, 'new': 1, 'hinted': 1, 'ledger': 2, 'consolidated': 3}
    out.sort(key=lambda c: (order[c['status']], -c['impact'], c['sig']))
    return out


def cmd_digest(a):
    path = a.signals or os.path.join(HOME, 'sleep', datetime.date.today().isoformat(), 'signals.jsonl')
    with open(path) as f:
        signals = [json.loads(l) for l in f if l.strip()]
    known = {'lessons': {l['signature']: l for l in lessons() if l.get('signature')},
             'ledger': {r.get('signature') for r in case.ledger()} | {c.get('signature') for c in case.cases() if c.get('status') != 'open'}}
    every = cluster(signals, known)
    live = [c for c in every if c['status'] in ('relapse', 'new', 'hinted')]
    picks = [dict(c, pick='top') for c in live[:a.top]]
    rest = [c for c in live[a.top:] if c['status'] == 'new']
    picks += [dict(c, pick='explore') for c in random.Random(a.seed).sample(rest, min(a.explore, len(rest)))]
    if a.json:
        with open(a.json, 'w') as f:
            json.dump({'signals': path, 'clusters': picks, 'all': every}, f, indent=2, ensure_ascii=False)
    print(f'# Sleep digest: {len(signals)} signals, {len(every)} clusters, {len(picks)} picked\n')
    print('| # | pick | status | kind | project | count | sessions | impact | signature | target |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    for i, c in enumerate(picks, 1):
        print(f"| {i} | {c['pick']} | {c['status']} | {c['kind']} | {c['project']} | {c['count']} | {c['sessions']} | {c['impact']} | "
              f"`{c['sig'][:80]}` | {c['target']} |")
    for i, c in enumerate(picks, 1):
        print(f"\n## {i}. {c['sig'][:120]}")
        for e in c['evidence'][:3]:
            print(f"- {e.get('session', '')} {e.get('ts', '')}: {e.get('text') or e.get('call', '')}")
    if a.mark:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        st = state()
        st['last_sleep'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(STATE, 'w') as f:
            json.dump(st, f, indent=2)


def cmd_learn(a):
    if a.kind not in ('hint', 'doc'):
        case.die(f'unknown kind {a.kind}: hint or doc', 2)
    rows = lessons()
    if any(r['id'] == a.id for r in rows):
        case.die(f'lesson {a.id} already exists', 2)
    if a.kind == 'hint' and not a.error or a.kind == 'doc' and not a.file:
        case.die('a hint lesson needs --error, a doc lesson --file', 2)
    row = {'id': a.id, 'kind': a.kind, 'expect': a.expect, 'added': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
    row.update({k: v for k, v in (('error', a.error), ('file', a.file), ('signature', a.signature), ('evidence', a.evidence)) if v})
    with open(LESSONS, 'a') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'learned {a.id}')


def replay():
    tables = {h: helper_hints(h) for h in ('figma_run.py', 'figma_batch_run.py')}
    failures, rows = [], lessons()
    for l in rows:
        if l['kind'] == 'hint':
            for h, table in tables.items():
                got = hint_for(table, l['error'])
                if not got or l['expect'] not in got:
                    failures.append(f"{l['id']}: {h} answers {l['error']!r} with {got!r}, not one containing {l['expect']!r}")
        elif l['kind'] == 'doc':
            try:
                with open(os.path.join(REPO, l['file'])) as f:
                    body = f.read()
            except OSError:
                body = ''
            if not re.search(l['expect'], body):
                failures.append(f"{l['id']}: {l['file']} no longer matches /{l['expect']}/")
    return rows, failures


def cmd_replay(a):
    rows, failures = replay()
    for f in failures:
        print(f'forgotten: {f}')
    if failures:
        sys.exit(1)
    print(f'{len(rows)} lessons hold')


def cmd_check(a):
    py = sys.executable
    gates = [s if s[0] == 'node' else [py] + s for s in case.OFFLINE] + [[py, 'tests/budget_test.py'], [py, __file__, 'replay']]
    if a.candidate:
        gates.append([py, 'tests/eval/compare.py', a.baseline or 'tests/eval/baseline.json', a.candidate, '--flaky'])
    for g in gates:
        print('$ ' + ' '.join(g), flush=True)
        if not a.dry_run and subprocess.run(g, cwd=REPO).returncode:
            case.die(f"gate failed: {' '.join(g)}")
    if not a.dry_run:
        print('every gate passed')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('mine')
    p.add_argument('--since'); p.add_argument('--all', action='store_true')
    p.add_argument('--source', action='append'); p.add_argument('--out')
    p = sub.add_parser('digest')
    p.add_argument('signals', nargs='?'); p.add_argument('--top', type=int, default=12); p.add_argument('--explore', type=int, default=3)
    p.add_argument('--seed', type=int, default=0); p.add_argument('--json'); p.add_argument('--mark', action='store_true')
    p = sub.add_parser('learn')
    p.add_argument('--id', required=True); p.add_argument('--kind', required=True); p.add_argument('--expect', required=True)
    for k in ('--error', '--file', '--signature', '--evidence'):
        p.add_argument(k)
    sub.add_parser('replay')
    p = sub.add_parser('check')
    p.add_argument('--candidate'); p.add_argument('--baseline'); p.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    {'mine': cmd_mine, 'digest': cmd_digest, 'learn': cmd_learn, 'replay': cmd_replay, 'check': cmd_check}[a.cmd](a)


if __name__ == '__main__':
    main()
