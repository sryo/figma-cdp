#!/usr/bin/env python3
"""Choose, price and start a live eval run; run.py does each rep.

  python3 tests/eval/run.py --file <figma-url> [--skill-dir <dir>] [--tasks a,b] [--reps N]
                            [--out results.json] [--keep] [--tab <perch tabId>] [--model <m>]

(run.py's entry point is this module's main.) Without --tasks it runs the tasks fium scope reads
from affects.json for the change since baseline.json was last refreshed, and prints them with the
expected tokens at baseline medians before it starts; a change that moves no task gets no run. It
checks the perch tab first: the file's one room tab by default, or the --tab given. Everything here
is tooling (affects.json maps it to none): what it changes is which runs happen, never what a rep
measures, which lives in run.py.
"""
import argparse, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import run  # noqa: E402
from run import COST, file_lock, run_rep, summarize  # noqa: E402


def file_key(url):
    m = re.search(r'/(?:design|file|proto|board)/([A-Za-z0-9]+)', url)
    if not m:
        sys.exit(f'--file must be a Figma file URL, got {url!r}')
    return m.group(1)


FIUM = os.environ.get('FIUM', os.path.expanduser('~/Documents/fium/fium'))


def scope_command(rev):
    return [FIUM, 'scope', f'{rev}..HEAD', '--repo', ROOT, '--affects', os.path.join(HERE, 'affects.json'), '--json']


def scoped(scope):
    """fium scope's answer as task ids: '*' is every default task."""
    return [t['id'] for t in load_tasks([])] if scope['tasks'] == '*' else list(scope['tasks'])


def expected_tokens(tasks, reps, baseline):
    return sum(round(baseline['tasks'].get(t, {}).get('median', {}).get('tokens_total', 0)) for t in tasks) * reps


def default_tasks(baseline):
    """The tasks the change since baseline.json was last refreshed can move (fium scope over
    affects.json), or None when fium is missing, so every default task runs."""
    rev = subprocess.run(['git', '-C', ROOT, 'log', '-1', '--format=%h', '--', 'tests/eval/baseline.json'],
                         capture_output=True, text=True).stdout.strip() or baseline.get('meta', {}).get('rev')
    if not rev or not os.path.exists(FIUM):
        return None, rev
    r = subprocess.run(scope_command(rev), capture_output=True, text=True)
    try:
        return scoped(json.loads(r.stdout)), rev
    except (ValueError, KeyError):
        sys.exit(f'run.py: fium scope failed: {(r.stderr or r.stdout).strip()[:300]}')


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


def default_tab(tabs, tab):
    """--tab as given, else the file's one room tab (perch rooms run minimized or locked), else None."""
    if tab:
        return tab
    rooms = [t['tabId'] for t in tabs if t['tabId'].startswith('room:')]
    return rooms[0] if len(rooms) == 1 else None


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


def git_rev(d):
    try:
        rev = subprocess.run(['git', '-C', d, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', d, 'status', '--porcelain', '--', '.', ':!tests'],
                                    capture_output=True, text=True).stdout.strip())
        return rev, dirty
    except OSError:
        return '', False


def main():
    ap = argparse.ArgumentParser(prog='run.py', description=run.__doc__.split('\n\n')[0])
    ap.add_argument('--file', required=True, help='scratch Figma file URL')
    ap.add_argument('--skill-dir', default=ROOT, help='copy of the skill to measure (default: this repo)')
    ap.add_argument('--tasks', default='', help='comma-separated task ids (default: the tasks fium scope says the change since the baseline can move)')
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--out', default='results.json')
    ap.add_argument('--keep', action='store_true', help="leave each rep's pages in the file")
    ap.add_argument('--tab', help='perch tabId of the Figma tab (FIGMA_PERCH_TAB); default: the file\'s one room tab')
    ap.add_argument('--model', help='model for the session (default: the CLI default)')
    ap.add_argument('--claude', default=os.environ.get('CLAUDE_BIN', 'claude'))
    ap.add_argument('--session-timeout', type=int, default=1800, help='seconds per session (default 1800)')
    ap.add_argument('--max-budget', type=float, help='USD cap per session (claude --max-budget-usd)')
    ap.add_argument('--transcripts', help='directory to keep each session transcript in')
    ap.add_argument('--case', help='the case (tests/cases/case.py) this run gates, stamped in meta')
    a = ap.parse_args()
    a.skill_dir = os.path.abspath(a.skill_dir)
    if not os.path.isfile(os.path.join(a.skill_dir, 'SKILL.md')):
        sys.exit(f'--skill-dir {a.skill_dir} has no SKILL.md')
    key = file_key(a.file)
    if os.environ.get('FIGMA_BACKEND', 'perch') == 'perch':
        tabs = file_tabs(key)
        a.tab = default_tab(tabs, a.tab)
        problem = tab_problem(tabs, a.tab)
        if problem:
            sys.exit(f'run.py: {problem}')
        print(f'run.py: tab {a.tab or tabs[0]["tabId"]}', file=sys.stderr)
    names = [t for t in a.tasks.split(',') if t]
    with open(os.path.join(HERE, 'baseline.json')) as f:
        baseline = json.load(f)
    if not names:
        names, rev = default_tasks(baseline)
        if names == []:
            sys.exit(f'run.py: the change since {rev} moves no eval task (affects.json): re-judge it offline with '
                     'reparse.py and gate.py on kept runs, or pass --tasks')
        print(f"run.py: tasks from fium scope since {rev}: {', '.join(names)}" if names is not None
              else 'run.py: no fium scope; every default task', file=sys.stderr)
    tasks = load_tasks(names or [])
    print(f"run.py: {', '.join(t['id'] for t in tasks)} x {a.reps} reps, about "
          f"{expected_tokens([t['id'] for t in tasks], a.reps, baseline) / 1e6:.1f}M tokens at baseline medians", file=sys.stderr)
    rev, dirty = git_rev(a.skill_dir)
    out = {'meta': {'rev': rev, 'dirty': dirty, 'skill_dir': a.skill_dir, 'file': key, 'model': a.model or '', 'case': a.case,
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
