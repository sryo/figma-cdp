#!/usr/bin/env python3
"""Compare two run.py outputs; exit 1 when the candidate regresses on anything.

  python3 tests/eval/compare.py <baseline.json> <candidate.json> [--floor 0.10] [--all] [--tasks a,b]
                                [--require task:metric>=x ...] [--gain task:metric>=x ...] [--flaky]

Per task, per metric, on the rep medians:
  quality (scorer metrics and pass_rate): any move in the worse direction is a regression;
      a scorer's `lower` list names the metrics where less is better
  cost (the run's cost_metrics: wall time, tokens, cost, turns, tool calls, failed calls):
      lower is better, and a move counts only past a noise tolerance of
      max(floor x baseline median, half the larger min-max spread of either run's reps);
      floor defaults to 10%, so with one rep a cost metric may grow 10% before it counts
A task or metric the baseline has and the candidate lacks is a regression too. A metric a
task lists as "saturated" (it scores the same on good and bad output) is shown as `info`
and never counts. The default baseline is tests/eval/baseline.json.

--tasks limits the comparison to those tasks (a paired run of the affected tasks only).
--require task:metric>=x fails unless the candidate's median meets it, which gates a new task
the baseline lacks (shown only as `new` otherwise); --gain task:metric>=x fails unless the
candidate beats the baseline by at least x (ops: >= > <= < ==). --flaky lists the quality
metrics whose baseline reps disagree (min != max) and shows their moves as `flaky`: neither a
regression nor a win a patch can claim. A regressed task's scorer notes are printed under it.
"""
import argparse, json, operator, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f'compare.py: cannot read {p}: {e}', file=sys.stderr)
        sys.exit(2)


def fmt(v):
    if v is None:
        return '-'
    return f'{v:.4g}' if isinstance(v, float) else str(v)


def saturated(task):
    try:
        with open(os.path.join(HERE, 'tasks', task + '.json')) as f:
            return set(json.load(f).get('saturated') or [])
    except (OSError, ValueError):
        return set()


OPS = {'>=': operator.ge, '>': operator.gt, '<=': operator.le, '<': operator.lt, '==': operator.eq}


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
    """Rows of (task, metric, base, cand, rule, verdict) for --require and --gain; verdict met|unmet."""
    rows = []
    for task, metric, op, x in require:
        cv = median(cand, task, metric)
        rows.append((task, metric, median(base, task, metric), cv, f'{op} {x:g}', 'met' if cv is not None and OPS[op](cv, x) else 'unmet'))
    for task, metric, op, x in gain:
        bv, cv = median(base, task, metric), median(cand, task, metric)
        ok = bv is not None and cv is not None and OPS[op](round(cv - bv, 4), x)
        rows.append((task, metric, bv, cv, f'gain {op} {x:g}', 'met' if ok else 'unmet'))
    return rows


def flaky(base):
    """{task: {quality metric}} whose baseline reps disagree."""
    cost = set(base.get('cost_metrics') or [])
    out = {}
    for task, b in base['tasks'].items():
        ks = {k for k in b.get('median', {}) if k not in cost and b['min'].get(k) != b['max'].get(k)}
        if ks:
            out[task] = ks
    return out


def compare(base, cand, floor=0.10, tasks=None, flaky_metrics=None):
    """Rows of (task, metric, base, cand, tol, verdict); verdict in ok|better|worse|missing|new|info|flaky."""
    cost = set(base.get('cost_metrics') or []) | set(cand.get('cost_metrics') or [])
    rows = []
    for task, b in base['tasks'].items():
        if tasks and task not in tasks:
            continue
        c = cand['tasks'].get(task)
        if c is None:
            rows.append((task, '*', None, None, None, 'missing'))
            continue
        lower = set(b.get('lower') or []) | set(c.get('lower') or [])
        sat = saturated(task)
        bm = dict(b['median'], pass_rate=b['pass_rate'])
        cm = dict(c['median'], pass_rate=c['pass_rate'])
        for k in sorted(set(bm) | set(cm)):
            if k not in cm:
                rows.append((task, k, bm[k], None, None, 'missing'))
                continue
            if k not in bm:
                rows.append((task, k, None, cm[k], None, 'new'))
                continue
            bv, cv = bm[k], cm[k]
            if k in sat:
                rows.append((task, k, bv, cv, None, 'info' if bv != cv else 'ok'))
                continue
            if k in cost:
                spread = max((b['max'].get(k, bv) - b['min'].get(k, bv)) / 2, (c['max'].get(k, cv) - c['min'].get(k, cv)) / 2)
                tol = max(floor * abs(bv), spread)
                verdict = 'worse' if cv > bv + tol else 'better' if cv < bv - tol else 'ok'
            else:
                tol = 0
                sign = -1 if k in lower else 1
                d = (cv - bv) * sign
                verdict = 'worse' if d < 0 else 'better' if d > 0 else 'ok'
            if verdict != 'ok' and k in (flaky_metrics or {}).get(task, ()):
                verdict = 'flaky'
            rows.append((task, k, bv, cv, tol, verdict))
    for task in cand['tasks']:
        if task not in base['tasks'] and (not tasks or task in tasks):
            rows.append((task, '*', None, None, None, 'new'))
    return rows


def notes(run, task):
    seen = []
    for r in run['tasks'].get(task, {}).get('reps', []):
        for n in r.get('notes') or []:
            if n not in seen:
                seen.append(n)
    return seen


def main():
    ap = argparse.ArgumentParser(prog='compare.py')
    ap.add_argument('baseline', nargs='?', default=os.path.join(HERE, 'baseline.json'))
    ap.add_argument('candidate')
    ap.add_argument('--floor', type=float, default=0.10, help='relative noise floor for cost metrics (default 0.10)')
    ap.add_argument('--all', action='store_true', help='print unchanged metrics too')
    ap.add_argument('--tasks', help='compare only these tasks (comma-separated)')
    ap.add_argument('--require', action='append', type=parse_rule, default=[], help="task:metric>=x on the candidate's median")
    ap.add_argument('--gain', action='append', type=parse_rule, default=[], help='task:metric>=x on candidate minus baseline')
    ap.add_argument('--flaky', action='store_true', help='quality metrics whose baseline reps disagree count neither way')
    a = ap.parse_args()
    base, cand = load(a.baseline), load(a.candidate)
    for k in ('file', 'model'):
        bk, ck = base.get('meta', {}).get(k), cand.get('meta', {}).get(k)
        if bk != ck:
            print(f'warning: {k} differs (baseline {bk!r}, candidate {ck!r}); the runs may not be comparable')
    tasks = set(a.tasks.split(',')) if a.tasks else None
    shaky = flaky(base) if a.flaky else None
    listed = [f"{t}: {', '.join(sorted(ks))}" for t, ks in sorted((shaky or {}).items()) if not tasks or t in tasks]
    if listed:
        print('flaky (baseline reps disagree): ' + '; '.join(listed))
    rows = compare(base, cand, a.floor, tasks, shaky)
    head = ('task', 'metric', 'baseline', 'candidate', 'tol', 'verdict')
    shown = [r for r in rows if a.all or r[5] != 'ok']
    table = [head] + [(t, m, fmt(b), fmt(c), fmt(tol), v) for t, m, b, c, tol, v in shown]
    widths = [max(len(str(r[i])) for r in table) for i in range(len(head))]
    for r in table:
        print('  '.join(str(x).ljust(w) for x, w in zip(r, widths)).rstrip())
    for task in sorted({r[0] for r in rows if r[5] in ('worse', 'missing')}):
        for n in notes(cand, task):
            print(f'  {task} note: {n}')
    bad = [r for r in rows if r[5] in ('worse', 'missing')]
    checks = rules(base, cand, a.require, a.gain)
    for t, m, b, c, rule, v in checks:
        print(f'{v}: {t}:{m} {rule} (baseline {fmt(b)}, candidate {fmt(c)})')
    unmet = [r for r in checks if r[5] == 'unmet']
    print(f"\n{len(bad)} regression(s), {sum(1 for r in rows if r[5] == 'better')} improvement(s) "
          f'over {len(rows)} metric(s)' + (f', {len(unmet)} unmet requirement(s)' if checks else ''))
    sys.exit(1 if bad or unmet else 0)


if __name__ == '__main__':
    main()
