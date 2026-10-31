#!/usr/bin/env python3
"""The sleep pass: consolidate what past sessions show into lessons that later sessions keep.

  python3 tests/sleep/sleep.py mine [--since <date>|--all] [--source <dir> ...] [--out <signals.jsonl>]
  python3 tests/sleep/sleep.py digest [<signals.jsonl>] [--top 12] [--explore 3] [--seed N] [--json <out>] [--mark]
  python3 tests/sleep/sleep.py digest --stale [--source <dir> ...]
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
fix, a doc rule at the point of use, an eval case, or a memory. `digest --stale` turns it around:
over every source (all time), how often each hint row and each lesson's signature fired, listing
the ones that never did with their file and line. It only flags; pruning one is a change like any
other, with a lean live check.

Each fix lands test-first (AGENTS.md → Improving the skill), and `learn` records it in
tests/sleep/lessons.jsonl as an executable expectation: a `hint` lesson is an error text both
helpers must answer with a hint containing `expect`; a `doc` lesson is a regex its file must keep
matching. `learn` refuses a lesson that doesn't hold yet (the fix hasn't landed) and one whose
text is a bare negative claim ("X doesn't work") with no way through. `replay` checks every lesson, so trimming a doc for bytes or rewriting a helper can't
silently drop what an earlier sleep learned. `check` is the no-regression gate for a sleep's
changes: the offline suites, budget, replay, and tests/eval/gate.py (fium price compare) on a live run when one is given.
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
READS = {'Read', 'Grep', 'Glob', 'NotebookRead'}
ERROR_LINE = re.compile(r'✗ |Evaluation error|^\s*(Error|TypeError|ReferenceError): ')
# A lesson's text saying X doesn't work, with nothing that says what to do instead.
NEGATIVE = re.compile(r"\b(doesn'?t|does not|don'?t|do not|won'?t|will not|can'?t|cannot|can not|never)\s+(work|run|load|support)|"
                      r"\bis (broken|unsupported|not supported)\b|\bnot (supported|possible)\b|\bno way to\b", re.I)
WAY_THROUGH = re.compile(r"\b(use|instead|try|run|call|ask|pass|set|switch|retry|prefer|fall back|show|load|await|find|collect)\b|→", re.I)


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
    if a.stale:
        return cmd_stale(a)
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


def hint_rows():
    """Every hint the helpers give, with its place: (file, line, label, matcher), where a matcher takes
    an error line (the HINTS patterns) or a whole tool result (figma_perch.mjs's *_HINT messages)."""
    rows = []
    for h in ('figma_run.py', 'figma_batch_run.py'):
        with open(os.path.join(REPO, h)) as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'HINTS' for t in node.targets):
                rows += [(h, e.lineno, ast.literal_eval(e.elts[0]), 'pattern') for e in node.value.elts]
    with open(os.path.join(REPO, 'figma_perch.mjs')) as f:
        for i, line in enumerate(f, 1):
            m = re.match(r'const (\w+_HINT)\s*=\s*["\'`](.{20,}?)[(:,.]', line)
            if m:
                rows.append(('figma_perch.mjs', i, m.group(1), m.group(2)))
    return rows


def failed_results(sources):
    """The error text of every call in sources: a failed transcript tool result whole (is_error, or an
    exit code, ✗ or Error: up front), the error lines of any other result (a batch that exited 0 still
    reports a failed item), and kept journal errors with the hint they got. Results of file reads and
    searches are skipped: a helper's source or a doc quotes its errors."""
    for p in transcripts(sources, None):
        names = {}
        with open(p, encoding='utf-8', errors='replace') as f:
            for line in f:
                if '"rid"' in line and '"ok": false' in line:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    yield (e.get('error') or '') + '\n' + (e.get('hint') or '')
                elif '"tool_use"' in line or '"tool_result"' in line:
                    try:
                        content = (json.loads(line).get('message') or {}).get('content')
                    except ValueError:
                        continue
                    for c in content if isinstance(content, list) else []:
                        if not isinstance(c, dict):
                            continue
                        if c.get('type') == 'tool_use':
                            names[c.get('id')] = c.get('name', '')
                        elif c.get('type') == 'tool_result' and names.get(c.get('tool_use_id')) not in READS:
                            body = text_of(c.get('content'))
                            if c.get('is_error') or re.match(r'\s*(Exit code [1-9]|✗ |Error: )', body):
                                yield body
                            else:
                                errors = [l for l in body.split('\n') if ERROR_LINE.search(l)]
                                if errors:
                                    yield '\n'.join(errors)


def cmd_stale(a):
    sources = a.source or ([os.path.join(PROJECTS, d) for d in sorted(os.listdir(PROJECTS)) if re.search(r'figma-cdp|perch|avis', d)]
                           if os.path.isdir(PROJECTS) else []) + [case.JOURNAL]
    hints, rows = hint_rows(), lessons()
    fired = {(f, n): 0 for f, n, _, _ in hints}
    seen = {l['signature']: 0 for l in rows if l.get('signature')}
    # A helper answers with its first matching row, so that row is the one that fired.
    ordered = {h: [(f, n, pat) for f, n, pat, kind in hints if f == h and kind == 'pattern'] for h in ('figma_run.py', 'figma_batch_run.py')}
    calls = 0
    for text in failed_results(sources):
        calls += 1
        hit = set()
        for line in (l for l in text.split('\n') if 0 < len(l) < 2000):
            for table in ordered.values():
                first = next(((f, n) for f, n, pat in table if re.search(pat, line)), None)
                if first:
                    hit.add(first)
            if signature(line) in seen:
                seen[signature(line)] += 1
        hit |= {(f, n) for f, n, _, msg in hints if msg != 'pattern' and msg in text}
        for k in hit:
            fired[k] += 1
    rel = os.path.relpath(LESSONS, REPO) if os.path.abspath(LESSONS).startswith(REPO + os.sep) else LESSONS
    never, counts = [], []
    for f, n, label, kind in hints:
        (never if not fired[(f, n)] else counts).append((f'{f}:{n}', 'hint', label, fired[(f, n)]))
    unmeasured = []
    for i, l in enumerate(rows, 1):
        if not l.get('signature'):
            unmeasured.append((f'{rel}:{i}', l['kind'], l['id'], l.get('file', '')))
        else:
            (never if not seen[l['signature']] else counts).append((f'{rel}:{i}', 'lesson', l['id'], seen[l['signature']]))
    measurable = sum(1 for l in rows if l.get('signature'))
    print(f"# Stale: {sum(k == 'hint' for _, k, _, _ in never)} of {len(hints)} hints and {sum(k == 'lesson' for _, k, _, _ in never)} of "
          f'{measurable} measurable lessons never fired, over {calls} failed calls in {len(sources)} sources\n')
    print('Candidates only: a rule that never fired may still prevent its error. Prune one with a lean live check of the task it serves.\n')
    print('## Never fired\n')
    for place, kind, label, _ in never:
        print(f'- {place} {kind} `{label}`')
    print('\n## Fired\n')
    for place, kind, label, n in sorted(counts, key=lambda c: -c[3]):
        print(f'- {place} {kind} `{label}`: {n}')
    print('\n## Unmeasured (doc lessons with no signature)\n')
    for place, kind, lid, file in unmeasured:
        print(f'- {place} {kind} {lid} ({file})')


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
    # A lesson records a fix that already landed, so it must hold now; and what it guards must not
    # be a bare "X doesn't work", which hardens into a refusal long after X is fixed.
    tables = helper_tables()
    failure = forgotten(row, tables)
    if failure:
        case.die(f'no fix in place: {failure}; land the fix (test first), then learn it', 2)
    for text in guarded(row, tables):
        if NEGATIVE.search(text) and not WAY_THROUGH.search(text):
            case.die(f'negative claim with no way through: {text.strip()!r}; say what to do instead', 2)
    with open(LESSONS, 'a') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'learned {a.id}')


def helper_tables():
    return {h: helper_hints(h) for h in ('figma_run.py', 'figma_batch_run.py')}


def doc_body(l):
    try:
        with open(os.path.join(REPO, l['file'])) as f:
            return f.read()
    except OSError:
        return ''


def forgotten(l, tables):
    """Why lesson l no longer holds, or None."""
    if l['kind'] == 'hint':
        for h, table in tables.items():
            got = hint_for(table, l['error'])
            if not got or l['expect'] not in got:
                return f"{h} answers {l['error']!r} with {got!r}, not one containing {l['expect']!r}"
    elif l['kind'] == 'doc' and not re.search(l['expect'], doc_body(l)):
        return f"{l['file']} no longer matches /{l['expect']}/"
    return None


def guarded(l, tables):
    """The text a lesson keeps in place: the hints both helpers give, or the doc lines its pattern matches."""
    if l['kind'] == 'hint':
        return [hint_for(t, l['error']) or '' for t in tables.values()]
    body = doc_body(l)
    m = re.search(l['expect'], body)
    if not m:
        return []
    end = body.find('\n', m.end())
    return [body[body.rfind('\n', 0, m.start()) + 1:end if end >= 0 else len(body)]]


def replay():
    tables, rows = helper_tables(), lessons()
    return rows, [f"{l['id']}: {f}" for l in rows for f in [forgotten(l, tables)] if f]


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
        gates.append([py, 'tests/eval/gate.py', a.baseline or 'tests/eval/baseline.json', a.candidate])
    for g in gates:
        print('$ ' + ' '.join(g), flush=True)
        if not a.dry_run and subprocess.run(g, cwd=REPO).returncode:
            print(f"sleep.py: gate failed: {' '.join(g)}", file=sys.stderr); sys.exit(1)
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
    p.add_argument('--stale', action='store_true'); p.add_argument('--source', action='append')
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
