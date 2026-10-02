#!/usr/bin/env python3
"""Compare two run.py outputs; exit 1 when the candidate regresses on anything.

  python3 tests/eval/compare.py <baseline.json> <candidate.json> [--floor 0.10] [--all]

Per task, per metric, on the rep medians:
  quality (scorer metrics and pass_rate): any move in the worse direction is a regression;
      a scorer's `lower` list names the metrics where less is better
  cost (the run's cost_metrics: wall time, tokens, cost, turns, tool calls, failed calls):
      lower is better, and a move counts only past a noise tolerance of
      max(floor x baseline median, half the larger min-max spread of either run's reps);
      floor defaults to 10%, so with one rep a cost metric may grow 10% before it counts
A task or metric the baseline has and the candidate lacks is a regression too. The default
baseline is tests/eval/baseline.json.
"""
import argparse, json, os, sys

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


def compare(base, cand, floor=0.10):
    """Rows of (task, metric, base, cand, tol, verdict); verdict in ok|better|worse|missing|new."""
    cost = set(base.get('cost_metrics') or []) | set(cand.get('cost_metrics') or [])
    rows = []
    for task, b in base['tasks'].items():
        c = cand['tasks'].get(task)
        if c is None:
            rows.append((task, '*', None, None, None, 'missing'))
            continue
        lower = set(b.get('lower') or []) | set(c.get('lower') or [])
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
            if k in cost:
                spread = max((b['max'].get(k, bv) - b['min'].get(k, bv)) / 2, (c['max'].get(k, cv) - c['min'].get(k, cv)) / 2)
                tol = max(floor * abs(bv), spread)
                verdict = 'worse' if cv > bv + tol else 'better' if cv < bv - tol else 'ok'
            else:
                tol = 0
                sign = -1 if k in lower else 1
                d = (cv - bv) * sign
                verdict = 'worse' if d < 0 else 'better' if d > 0 else 'ok'
            rows.append((task, k, bv, cv, tol, verdict))
    for task in cand['tasks']:
        if task not in base['tasks']:
            rows.append((task, '*', None, None, None, 'new'))
    return rows


def main():
    ap = argparse.ArgumentParser(prog='compare.py')
    ap.add_argument('baseline', nargs='?', default=os.path.join(HERE, 'baseline.json'))
    ap.add_argument('candidate')
    ap.add_argument('--floor', type=float, default=0.10, help='relative noise floor for cost metrics (default 0.10)')
    ap.add_argument('--all', action='store_true', help='print unchanged metrics too')
    a = ap.parse_args()
    base, cand = load(a.baseline), load(a.candidate)
    for k in ('file', 'model'):
        bk, ck = base.get('meta', {}).get(k), cand.get('meta', {}).get(k)
        if bk != ck:
            print(f'warning: {k} differs (baseline {bk!r}, candidate {ck!r}); the runs may not be comparable')
    rows = compare(base, cand, a.floor)
    head = ('task', 'metric', 'baseline', 'candidate', 'tol', 'verdict')
    shown = [r for r in rows if a.all or r[5] != 'ok']
    table = [head] + [(t, m, fmt(b), fmt(c), fmt(tol), v) for t, m, b, c, tol, v in shown]
    widths = [max(len(str(r[i])) for r in table) for i in range(len(head))]
    for r in table:
        print('  '.join(str(x).ljust(w) for x, w in zip(r, widths)).rstrip())
    bad = [r for r in rows if r[5] in ('worse', 'missing')]
    print(f"\n{len(bad)} regression(s), {sum(1 for r in rows if r[5] == 'better')} improvement(s) "
          f'over {len(rows)} metric(s)')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
