#!/usr/bin/env python3
"""Run the skill's eval tasks against a live Figma file and score the result.

  python3 tests/eval/run.py --file <figma-url> [--skill-dir <dir>] [--tasks a,b] [--reps N]
                            [--out ~/.fium/runs/figma-cdp/results.json] [--keep] [--tab <perch tabId>] [--model <m>]

Per task rep, holding a per-file lock (parallel callers on one file queue):
  1. a fresh page "eval/<task>/<n>" (leftovers of an earlier run with that name go first)
  2. the task's seed, run through this repo's figma_run.py
  3. a headless `claude -p` session on the task prompt, pinned to --skill-dir's copy of the
     skill (session.py has the mechanism); wall time, tokens, cost, turns, tool calls and
     failed tool calls come from its stream-json transcript, subagents included, with the process
     metrics (lost replies, --recover uses, retries, unhinted errors) and the failed calls' text
  4. the task's scorer against the page ({metrics, lower, passed, notes}; notes say why, and
     gate.py prints them beside a regression), then the rep's pages are deleted unless --keep
The output holds every rep plus per-task medians, min and max; gate.py judges two outputs with fium.

Choosing the tasks, pricing them and checking the tab is tests/eval/plan.py (this file's entry point).

The session runs unattended: dontAsk mode with Bash/Read/Write/Edit/Glob/Grep/Agent/Skill
allowed, so point it only at a scratch Figma file. --skill-dir defaults to this repo; use a
git worktree to measure a candidate change. The seeds and scorers always come from this repo.
"""
import json, os, re, statistics, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import session, source  # noqa: E402
from figma_lock import file_lock, lock_path  # noqa: E402,F401

COST = ['wall_s', 'tokens_total', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens',
        'cost_usd', 'turns', 'tool_calls', 'failed_tool_calls', 'lost_replies', 'recover_uses', 'retries', 'unhinted_errors']


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
    # A scorer's result (it has metrics) also carries lib.js's MISSES, report only.
    return (f'(async function (EVAL) {{\n{lib}\nvar __out = await (async function () {{\n{body}\n}})();\n'
            f'if (__out && __out.metrics && Object.keys(MISSES).length) __out.misses = MISSES;\nreturn __out;\n}})({json.dumps(ctx)})\n')


class FigmaError(Exception):
    pass


def figma(rel, ctx, a, tmp):
    path = os.path.join(tmp, os.path.basename(rel))
    with open(path, 'w') as f:
        f.write(compose(rel, ctx))
    env = dict(os.environ, FIGMA_CDP_JOURNAL='0')
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
    # The session's eval journal (figma_run.py) stays with the run, out of the user's ~/.figma-cdp.
    env['FIGMA_CDP_HOME'] = os.path.join(a.transcripts, f"{ctx['task']}-{ctx['rep']}") if a.transcripts else tmp
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
            keep_misses(rec, score)
            if score.get('notes'):
                rec['notes'] = [str(n)[:300] for n in score['notes']][:10]
        except FigmaError as e:
            rec['error'] = (rec.get('error', '') + f' score: {e}').strip()
            rec['passed'] = False
        if not a.keep:
            try:
                figma('ops/cleanup.js', ctx, a, tmp)
            except FigmaError as e:
                print(f'  cleanup failed ({e}); delete pages named {prefix}* by hand', file=sys.stderr)
    return rec


def keep_misses(rec, score):
    """The scorer's misses, the nodes behind each check's shortfall, kept beside its metrics."""
    if score.get('misses'):
        rec['misses'] = score['misses']


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


if __name__ == '__main__':
    import plan
    plan.main()
