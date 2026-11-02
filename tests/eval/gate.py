#!/usr/bin/env python3
"""The live-run gate: fium compare on run.py outputs, plus a case's pass-rate rules.

  python3 tests/eval/gate.py [<baseline.json>] <candidate.json> [--tasks a,b]
                             [--require task:metric>=x ...] [--gain task:metric>=x ...]
  python3 tests/eval/gate.py --fium <run.json>          the run in fium's format, on stdout

Writes both runs in fium's run format (fium RULES K2), then runs `fium compare` with
tests/eval/noise.json and the Price: trailers since the baseline's rev, read from this repo. Per
task and rep metric: wall time is time and token counts are tokens (noisy kinds); turns, tool calls,
failed calls and unhinted errors are noisy counts, the other cost metrics exact counts; scorer
metrics and passed are quality, higher unless the scorer lists them lower, and noisy when the
run's reps disagree (passed stays exact). Dollars and a task's saturated metrics are left out.

--tasks keeps only those tasks in both runs (a paired run of the affected tasks); by default a run
stamped with its commit is gated on the tasks fium scope says that change can move.
--require task:metric>=x fails unless the candidate's median meets it, which gates a new task the
baseline lacks; --gain task:metric>=x fails unless the candidate beats the baseline's median by at
least x (ops: >= > <= < ==). A task with a worse metric gets its scorer notes printed under the rows.
Exit: 1 on a worse, limit, missing or stale verdict or an unmet rule, 3 inconclusive, else 0.
FIUM overrides the CLI's path (default ~/Documents/fium/fium).
"""
import argparse, json, operator, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
FIUM = os.environ.get('FIUM', os.path.expanduser('~/Documents/fium/fium'))
NOISE = os.path.join(HERE, 'noise.json')
# Counts an agent's run moves every time; fium judges them statistically.
NOISY_COUNTS = {'turns', 'tool_calls', 'failed_tool_calls', 'unhinted_errors'}
OPS = {'>=': operator.ge, '>': operator.gt, '<=': operator.le, '<': operator.lt, '==': operator.eq}


def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        sys.exit(f'gate.py: cannot read {p}: {e}')


def saturated(task):
    try:
        with open(os.path.join(HERE, 'tasks', task + '.json')) as f:
            return set(json.load(f).get('saturated') or [])
    except (OSError, ValueError):
        return set()


def fium(run):
    """The run in fium's run format: one metric per task and rep metric, samples per rep."""
    cost = set(run.get('cost_metrics') or [])
    out = {}
    for task, t in run['tasks'].items():
        lower, sat = set(t.get('lower') or []), saturated(task)
        names = []
        for r in t.get('reps', []):
            names += [k for k in r if k not in names]
        for k in names:
            vals = [int(v) if isinstance(v, bool) else v for v in (r.get(k) for r in t['reps'])]
            vals = [v for v in vals if isinstance(v, (int, float))]
            if not vals or k in ('rep', 'cost_usd') or k in sat:
                continue
            if k == 'wall_s':
                kind, d = 'time', 'lower'
            elif k.endswith('tokens') or k == 'tokens_total':
                kind, d = 'tokens', 'lower'
            elif k in cost:
                kind, d = 'count', 'lower'
            else:
                kind, d = 'quality', 'lower' if k in lower else 'higher'
            e = {'dir': d, 'kind': kind, 'samples': vals}
            if k in NOISY_COUNTS or (kind == 'quality' and k != 'passed' and min(vals) != max(vals)):
                e = {'dir': d, 'kind': kind, 'noisy': True, 'samples': vals}
            out[f'{task}.{k}'] = e
    meta = run.get('meta') or {}
    return {'commit': meta.get('rev'), 'dirty': bool(meta.get('dirty')), 'metrics': out, 'limits': {}}


def parse_rule(text):
    m = re.fullmatch(r'([\w-]+):(\w+)\s*(>=|<=|==|>|<)\s*(-?[\d.]+)', text.strip())
    if not m:
        raise argparse.ArgumentTypeError(f'{text!r}: want task:metric>=x')
    return m.group(1), m.group(2), m.group(3), float(m.group(4))


def median(run, task, metric):
    t = run['tasks'].get(task)
    if t is None:
        return None
    return t['pass_rate'] if metric == 'pass_rate' else t['median'].get(metric)


def rules(base, cand, require=(), gain=()):
    """(task, metric, base, cand, rule, met) for --require and --gain."""
    rows = []
    for task, metric, op, x in require:
        cv = median(cand, task, metric)
        rows.append((task, metric, median(base, task, metric), cv, f'{op} {x:g}', cv is not None and OPS[op](cv, x)))
    for task, metric, op, x in gain:
        bv, cv = median(base, task, metric), median(cand, task, metric)
        rows.append((task, metric, bv, cv, f'gain {op} {x:g}', bv is not None and cv is not None and OPS[op](round(cv - bv, 4), x)))
    return rows


def notes(run, task):
    seen = []
    for r in run['tasks'].get(task, {}).get('reps', []):
        for n in r.get('notes') or []:
            if n not in seen:
                seen.append(n)
    return seen


def command(base_path, run_path, rev):
    """fium compare on two exported runs, with this repo's noise file and Price: trailers since rev."""
    cmd = [FIUM, 'compare', base_path, run_path, '--noise', NOISE, '--repo', REPO]
    if rev and subprocess.run(['git', '-C', REPO, 'cat-file', '-e', rev + '^{commit}'], capture_output=True).returncode == 0:
        cmd += ['--since', rev]
    return cmd


def scope_command(rev, to):
    return [FIUM, 'scope', f'{rev}..{to}', '--repo', REPO, '--affects', os.path.join(HERE, 'affects.json'), '--json']


def default_tasks(cand):
    """For a run stamped with its commit: the tasks fium scope says the change from the baseline's last
    refresh to that commit can move ('*' is every task the runs share). None gates every shared task."""
    to = (cand.get('meta') or {}).get('rev')
    rev = subprocess.run(['git', '-C', REPO, 'log', '-1', '--format=%h', '--', 'tests/eval/baseline.json'],
                         capture_output=True, text=True).stdout.strip()
    if not to or not rev or not os.path.exists(FIUM):
        return None
    try:
        tasks = json.loads(subprocess.run(scope_command(rev, to), capture_output=True, text=True).stdout)['tasks']
    except (ValueError, KeyError):
        return None
    return None if tasks == '*' else set(tasks)


def only(run, tasks):
    return dict(run, tasks={t: v for t, v in run['tasks'].items() if t in tasks}) if tasks is not None else run


def gate(baseline, candidate, tasks=None, require=(), gain=()):
    base, cand = load(baseline), load(candidate)
    if tasks is None:
        tasks = default_tasks(cand)
        if tasks is not None:
            print(f"gate.py: tasks from fium scope: {', '.join(sorted(tasks)) or 'none'}")
    base, cand = only(base, tasks), only(cand, tasks)
    tmp = tempfile.mkdtemp(prefix='figma-eval-fium-')
    try:
        paths = []
        for name, run in (('base', base), ('run', cand)):
            p = os.path.join(tmp, name + '.json')
            with open(p, 'w') as f:
                json.dump(fium(run), f)
            paths.append(p)
        r = subprocess.run(command(*paths, base.get('meta', {}).get('rev')) + ['--json'], capture_output=True, text=True)
        try:
            rows = json.loads(r.stdout)
        except ValueError:
            sys.exit(f'gate.py: fium gave no verdict: {(r.stderr or r.stdout).strip()[:400]}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for row in rows:
        if row['verdict'] != 'same':
            q = '?' if row.get('low_n') else ''
            print(f"{row['verdict'] + q:>13}  {row['metric']}: {row.get('base')} -> {row.get('run')}")
    for task in sorted({row['metric'].split('.')[0] for row in rows if row['verdict'] in ('worse', 'missing')}):
        for n in notes(cand, task):
            print(f'  {task} note: {n}')
    checks = rules(base, cand, require, gain)
    for t, m, b, c, rule, met in checks:
        print(f"{'met' if met else 'unmet'}: {t}:{m} {rule} (baseline {b}, candidate {c})")
    print(f"{sum(row['verdict'] == 'same' for row in rows)} of {len(rows)} metrics the same"
          + (f", {sum(not c[5] for c in checks)} unmet rule(s)" if checks else ''))
    return 1 if r.returncode == 1 or any(not c[5] for c in checks) else r.returncode


def main():
    ap = argparse.ArgumentParser(prog='gate.py')
    ap.add_argument('runs', nargs='+', help='[baseline.json] candidate.json')
    ap.add_argument('--tasks', help='gate only these tasks (comma-separated)')
    ap.add_argument('--require', action='append', type=parse_rule, default=[], help="task:metric>=x on the candidate's median")
    ap.add_argument('--gain', action='append', type=parse_rule, default=[], help='task:metric>=x on candidate minus baseline')
    ap.add_argument('--fium', action='store_true', help="print the one run given in fium's format and exit")
    a = ap.parse_args()
    if a.fium:
        if len(a.runs) != 1:
            ap.error('--fium takes one run')
        json.dump(fium(load(a.runs[0])), sys.stdout, indent=1)
        print()
        return
    if len(a.runs) > 2:
        ap.error('give [baseline.json] candidate.json')
    baseline, candidate = (os.path.join(HERE, 'baseline.json'), a.runs[0]) if len(a.runs) == 1 else a.runs
    if not os.path.exists(FIUM):
        sys.exit(f'gate.py: no fium at {FIUM} (set FIUM)')
    sys.exit(gate(baseline, candidate, set(a.tasks.split(',')) if a.tasks else None, a.require, a.gain))


if __name__ == '__main__':
    main()
