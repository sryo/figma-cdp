#!/usr/bin/env python3
"""Run the skill's eval tasks against a live Figma file and score the result.

  python3 tests/eval/run.py --file <figma-url> [--skill-dir <dir>] [--tasks a,b] [--reps N]
                            [--out results.json] [--keep] [--tab <perch tabId>] [--model <m>]

Per task rep, holding a per-file lock (parallel callers on one file queue):
  1. a fresh page "eval/<task>/<n>" (leftovers of an earlier run with that name go first)
  2. the task's seed, run through this repo's figma_run.py
  3. a headless `claude -p` session on the task prompt, pinned to --skill-dir's copy of the
     skill (session.py has the mechanism); wall time, tokens, cost, turns, tool calls and
     failed tool calls come from its stream-json transcript, subagents included
  4. the task's scorer against the page, then the rep's pages are deleted unless --keep
The output holds every rep plus per-task medians, min and max; compare.py diffs two outputs.

The session runs unattended: dontAsk mode with Bash/Read/Write/Edit/Glob/Grep/Agent/Skill
allowed, so point it only at a scratch Figma file. --skill-dir defaults to this repo; use a
git worktree to measure a candidate change. The seeds and scorers always come from this repo.
"""
import argparse, fcntl, json, os, re, statistics, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import session, source  # noqa: E402

COST = ['wall_s', 'tokens_total', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens',
        'cost_usd', 'turns', 'tool_calls', 'failed_tool_calls']


def file_key(url):
    m = re.search(r'/(?:design|file|proto|board)/([A-Za-z0-9]+)', url)
    if not m:
        sys.exit(f'--file must be a Figma file URL, got {url!r}')
    return m.group(1)


def load_tasks(names):
    tasks = {}
    for f in sorted(os.listdir(os.path.join(HERE, 'tasks'))):
        if f.endswith('.json'):
            with open(os.path.join(HERE, 'tasks', f)) as fh:
                t = json.load(fh)
            tasks[t['id']] = t
    if not names:
        return [t for t in tasks.values() if t.get('default', True)]
    unknown = [n for n in names if n not in tasks]
    if unknown:
        sys.exit(f"unknown task(s) {', '.join(unknown)}; have {', '.join(tasks)}")
    return [tasks[n] for n in names]


def compose(rel, ctx):
    """One script for figma_run.py: lib.js and the body inside an async function given EVAL. A
    body line `// include: <path>` (relative to tests/eval) is replaced by that file."""
    with open(os.path.join(HERE, 'lib.js')) as f:
        lib = f.read()
    with open(os.path.join(HERE, rel)) as f:
        body = f.read()

    def include(m):
        with open(os.path.join(HERE, m.group(1))) as f:
            return f.read()
    body = re.sub(r'^// include: (\S+)$', include, body, flags=re.M)
    return f'(async function (EVAL) {{\n{lib}\n{body}\n}})({json.dumps(ctx)})\n'


class FigmaError(Exception):
    pass


def figma(rel, ctx, a, tmp):
    path = os.path.join(tmp, os.path.basename(rel))
    with open(path, 'w') as f:
        f.write(compose(rel, ctx))
    env = dict(os.environ)
    if a.tab:
        env['FIGMA_PERCH_TAB'] = a.tab
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_run.py'), '--file', a.file, '--timeout', '120', path],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise FigmaError(f'{rel}: {(r.stderr or r.stdout).strip()[:600]}')
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise FigmaError(f'{rel}: not JSON: {r.stdout.strip()[:300]}')
    if isinstance(out, dict) and out.get('error'):
        raise FigmaError(f"{rel}: {out['error']}")
    return out


def lock_path(key):
    # A fixed directory, not TMPDIR: callers in different sessions get different TMPDIRs, and
    # every one of them must queue on the same lock, since setup resets the whole file.
    return os.path.join('/tmp', f'figma-eval-{os.getuid()}', f'{key}.lock')


def file_lock(key):
    path = lock_path(key)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    f = open(path, 'a')
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def tab_problem(tabs, tab):
    """Why the run can't start with these tabs on the file, or None."""
    if not tabs:
        return 'no tab shows the file; open it in the browser'
    if tab:
        return None if any(t['tabId'] == tab for t in tabs) else f'--tab {tab} is not open on the file'
    if len(tabs) > 1:
        return ('several tabs show the file (' + ', '.join(t['tabId'] for t in tabs) +
                '); close the extras or pass --tab, since setup and the session could land on different tabs')
    return None


def file_tabs(key):
    """The perch tabs showing the file, via perch's own list_tabs."""
    perch = os.environ.get('PERCH_DIR', os.path.expanduser('~/Documents/perch'))
    # The path goes inside the script: as argv[1], server.js would take itself for the entry point
    # and start an MCP server.
    js = (f"import({json.dumps(os.path.join(perch, 'server.js'))}).then(async m => {{"
          f" const r = await m.handleCall('list_tabs', {{urlContains: {json.dumps(key)}}});"
          " process.stdout.write(r.content[0].text); process.exit(0); })")
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout).get('tabs', [])
    except ValueError:
        sys.exit(f'list_tabs failed: {(r.stderr or r.stdout).strip()[:300]}')


def session_env(a):
    """The session's env: perch only, so a failing perch call is an error rather than a fallback
    to CDP, which can reach another browser's stale copy of the file or the user's other files."""
    env = session.clean_env()
    env.pop('FIGMA_CDP_PORT', None)
    env['FIGMA_BACKEND'] = 'perch'
    if a.tab:
        env['FIGMA_PERCH_TAB'] = a.tab
    return env


def run_session(task, ctx, a, tmp):
    url = a.file.split('?')[0] + '?node-id=' + ctx['pageId'].replace(':', '-')
    prompt = (task['prompt'].replace('{FILE_URL}', url).replace('{PAGE}', ctx['pageName'])
              .replace('{FIXTURE}', os.path.join(HERE, 'fixtures', task.get('fixture', 'app'))))
    plugin = session.make_plugin(a.skill_dir, tmp)
    cwd = os.path.join(tmp, 'cwd')
    os.makedirs(cwd, exist_ok=True)
    dirs = [os.path.join(HERE, 'fixtures'), a.skill_dir, '/tmp', tempfile.gettempdir()]
    cmd = session.command(a.claude, plugin, prompt, model=a.model, add_dirs=dirs,
                          budget=a.max_budget)
    env = session_env(a)
    lines = []
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(timeout=a.session_timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        timed_out = True
    wall = time.monotonic() - t0
    lines = out.splitlines()
    if a.transcripts:
        os.makedirs(a.transcripts, exist_ok=True)
        with open(os.path.join(a.transcripts, f"{ctx['task']}-{ctx['rep']}.jsonl"), 'w') as f:
            f.write(out)
    m, answer = session.parse_stream(lines)
    m['wall_s'] = round(wall, 2)
    if timed_out:
        m['session_error'] = True
        m['error'] = f'session timed out after {a.session_timeout}s'
    elif m.get('session_error'):
        m['error'] = (answer or err.strip())[:400] or f'claude exited {p.returncode}'
    return m, answer


def run_rep(task, rep, a):
    expect = source.expect_for(task)
    prefix = f"eval/{task['id']}/{rep}"
    rec = {'rep': rep}
    with tempfile.TemporaryDirectory() as tmp:
        ctx = {'task': task['id'], 'rep': rep, 'prefix': prefix, 'expect': expect}
        try:
            ctx.update(figma('ops/setup.js', ctx, a, tmp))
            ctx['seed'] = figma(task['seed'], ctx, a, tmp) if task.get('seed') else {}
        except FigmaError as e:
            rec['error'] = f'setup: {e}'
            rec['passed'] = False
            return rec
        m, answer = run_session(task, ctx, a, tmp)
        rec.update(m)
        ctx['answer'] = answer[:4000]
        try:
            score = figma(task['score'], ctx, a, tmp)
            rec.update(score['metrics'])
            rec['passed'] = bool(score['passed']) and not m.get('session_error')
            rec['lower'] = score.get('lower', [])
        except FigmaError as e:
            rec['error'] = (rec.get('error', '') + f' score: {e}').strip()
            rec['passed'] = False
        if not a.keep:
            try:
                figma('ops/cleanup.js', ctx, a, tmp)
            except FigmaError as e:
                print(f'  cleanup failed ({e}); delete pages named {prefix}* by hand', file=sys.stderr)
    return rec


def summarize(reps):
    nums = {}
    for r in reps:
        for k, v in r.items():
            if k in ('rep', 'lower') or isinstance(v, str):
                continue
            if isinstance(v, bool):
                v = int(v)
            if isinstance(v, (int, float)):
                nums.setdefault(k, []).append(v)
    lower = sorted({x for r in reps for x in r.get('lower', [])})
    med = {k: round(statistics.median(v), 4) for k, v in nums.items()}
    return {'lower': lower, 'median': med, 'min': {k: min(v) for k, v in nums.items()},
            'max': {k: max(v) for k, v in nums.items()},
            'pass_rate': round(sum(1 for r in reps if r.get('passed')) / len(reps), 4), 'reps': reps}


def git_rev(d):
    try:
        rev = subprocess.run(['git', '-C', d, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', d, 'status', '--porcelain', '--', '.', ':!tests'],
                                    capture_output=True, text=True).stdout.strip())
        return rev, dirty
    except OSError:
        return '', False


def main():
    ap = argparse.ArgumentParser(prog='run.py', description=__doc__.split('\n\n')[0])
    ap.add_argument('--file', required=True, help='scratch Figma file URL')
    ap.add_argument('--skill-dir', default=ROOT, help='copy of the skill to measure (default: this repo)')
    ap.add_argument('--tasks', default='', help='comma-separated task ids (default: every task not marked default:false)')
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--out', default='results.json')
    ap.add_argument('--keep', action='store_true', help="leave each rep's pages in the file")
    ap.add_argument('--tab', help='perch tabId of the Figma tab (FIGMA_PERCH_TAB)')
    ap.add_argument('--model', help='model for the session (default: the CLI default)')
    ap.add_argument('--claude', default=os.environ.get('CLAUDE_BIN', 'claude'))
    ap.add_argument('--session-timeout', type=int, default=1800, help='seconds per session (default 1800)')
    ap.add_argument('--max-budget', type=float, help='USD cap per session (claude --max-budget-usd)')
    ap.add_argument('--transcripts', help='directory to keep each session transcript in')
    a = ap.parse_args()
    a.skill_dir = os.path.abspath(a.skill_dir)
    if not os.path.isfile(os.path.join(a.skill_dir, 'SKILL.md')):
        sys.exit(f'--skill-dir {a.skill_dir} has no SKILL.md')
    key = file_key(a.file)
    if os.environ.get('FIGMA_BACKEND', 'perch') == 'perch':
        problem = tab_problem(file_tabs(key), a.tab)
        if problem:
            sys.exit(f'run.py: {problem}')
    tasks = load_tasks([t for t in a.tasks.split(',') if t])
    rev, dirty = git_rev(a.skill_dir)
    out = {'meta': {'rev': rev, 'dirty': dirty, 'skill_dir': a.skill_dir, 'file': key, 'model': a.model or '',
                    'reps': a.reps, 'date': time.strftime('%Y-%m-%dT%H:%M:%S%z')},
           'cost_metrics': COST, 'tasks': {}}
    for task in tasks:
        reps = []
        for n in range(1, a.reps + 1):
            lock = file_lock(key)
            try:
                rec = run_rep(task, n, a)
            finally:
                lock.close()
            reps.append(rec)
            brief = {k: rec.get(k) for k in ('passed', 'wall_s', 'tokens_total', 'cost_usd', 'error') if k in rec}
            print(f"{task['id']} {n}/{a.reps} {json.dumps(brief)}", file=sys.stderr)
        out['tasks'][task['id']] = summarize(reps)
        with open(a.out, 'w') as f:
            json.dump(out, f, indent=1)
            f.write('\n')
    print(a.out)


if __name__ == '__main__':
    main()
