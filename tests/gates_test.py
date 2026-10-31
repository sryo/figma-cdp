#!/usr/bin/env python3
"""The gates a case's fix passes, offline: gate.py's fium verdict, --require/--gain/--tasks and notes,
session.py's process metrics, affects.json, the judge guard, and case.py verify end to end on a
throwaway repo whose suites, probe runner and run.py are stand-ins.

  python3 tests/gates_test.py
"""
import json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL = os.path.join(ROOT, 'tests', 'eval')
sys.path.insert(0, EVAL)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
import session  # noqa: E402
import judge_guard  # noqa: E402


def run_json(task_rates, metrics=None, notes=None, reps=3):
    """A run.py output: per task, reps passing at the rate given, each scoring metrics."""
    import run
    tasks = {}
    for t, rate in task_rates.items():
        passing = round(rate * reps)
        tasks[t] = run.summarize([dict(metrics or {}, rep=i + 1, passed=i < passing, **({'notes': notes} if notes else {}))
                                  for i in range(reps)])
    return {'meta': {'file': 'K', 'model': 'm'}, 'cost_metrics': [], 'tasks': tasks}


class Gate(unittest.TestCase):
    """tests/eval/gate.py: fium price compare for regressions, plus a case's --require/--gain rules."""

    def setUp(self):
        import gate
        if not os.path.exists(gate.FIUM):
            self.skipTest('no fium at ' + gate.FIUM)
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def gate(self, base, cand, *args):
        paths = []
        for name, run in (('b', base), ('c', cand)):
            paths.append(os.path.join(self.tmp, name + '.json'))
            with open(paths[-1], 'w') as f:
                json.dump(run, f)
        p = subprocess.run([sys.executable, os.path.join(EVAL, 'gate.py'), *paths, *args], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def test_require_gates_a_task_the_baseline_lacks(self):
        base, cand = run_json({'recon': 1}), run_json({'recon': 1, 'overlay': 1})
        self.assertEqual(self.gate(base, cand)[0], 0)
        code, out = self.gate(base, cand, '--require', 'overlay:pass_rate>=0.67')
        self.assertEqual(code, 0, out)
        code, out = self.gate(base, cand, '--require', 'overlay:pass_rate>1')
        self.assertEqual(code, 1)
        self.assertIn('unmet: overlay:pass_rate > 1', out)
        self.assertEqual(self.gate(base, cand, '--require', 'nope:pass_rate>=0')[0], 1)

    def test_gain_needs_the_candidate_ahead_by_the_margin(self):
        # 3 reps: one more passing rep (1/3) is not enough; two are.
        base = run_json({'t': 0.3333})
        self.assertEqual(self.gate(base, run_json({'t': 1}), '--gain', 't:pass_rate>=0.34')[0], 0)
        self.assertEqual(self.gate(base, run_json({'t': 0.6667}), '--gain', 't:pass_rate>=0.34')[0], 1)

    def test_tasks_limits_the_comparison(self):
        base = run_json({'a': 1, 'b': 1})
        self.assertEqual(self.gate(base, run_json({'a': 1}))[0], 1, 'a task the candidate lacks is missing')
        self.assertEqual(self.gate(base, run_json({'a': 1}), '--tasks', 'a')[0], 0)

    def test_a_regression_prints_the_scorer_notes(self):
        code, out = self.gate(run_json({'t': 1}, {'copy': 1}), run_json({'t': 1}, {'copy': 0.5}, notes=['no drop shadow on "Main"']))
        self.assertEqual(code, 1)
        self.assertIn('t note: no drop shadow on "Main"', out)


class Process(unittest.TestCase):
    def test_process_metrics_and_errors_come_from_the_transcript(self):
        ev = lambda **e: json.dumps(e)
        use = lambda i, cmd: ev(type='assistant', message={'id': 'm' + i, 'content': [{'type': 'tool_use', 'id': i, 'name': 'Bash', 'input': {'command': cmd}}]})
        res = lambda i, text, err=False: ev(type='user', message={'content': [{'type': 'tool_result', 'tool_use_id': i, 'is_error': err, 'content': [{'type': 'text', 'text': text}]}]})
        lines = [use('a', 'figma_run.py x.js'), res('a', 'Error: in set_x: readonly', True),
                 use('b', 'figma_run.py x.js'), res('b', 'timeout: 120s\nIt may still finish: figma_run.py --recover r1 prints its result then', True),
                 use('c', 'figma_run.py --recover r1'), res('c', '{"ok":1}'),
                 use('d', 'figma_run.py y.js'), res('d', 'Error: unloaded font\nhint: load it', True),
                 ev(type='result', is_error=False, num_turns=4, result='ok', total_cost_usd=0.1, usage={})]
        m, _ = session.parse_stream(lines)
        self.assertEqual({k: m[k] for k in ('failed_tool_calls', 'lost_replies', 'recover_uses', 'retries', 'unhinted_errors')},
                         {'failed_tool_calls': 3, 'lost_replies': 1, 'recover_uses': 1, 'retries': 1, 'unhinted_errors': 2})
        self.assertEqual(m['errors'][0], {'tool': 'Bash', 'text': 'Error: in set_x: readonly'})

    def test_run_py_counts_process_metrics_as_cost(self):
        import run
        for k in ('lost_replies', 'recover_uses', 'retries', 'unhinted_errors'):
            self.assertIn(k, run.COST)


class Affects(unittest.TestCase):
    def test_every_skill_file_maps_to_existing_tasks(self):
        import fnmatch, re
        with open(os.path.join(EVAL, 'affects.json')) as f:
            rules = json.load(f)['rules']
        tasks = {f[:-5] for f in os.listdir(os.path.join(EVAL, 'tasks'))}
        for r in rules:
            self.assertTrue(r['tasks'] in ('*', 'none') or set(r['tasks']) <= tasks, r)
        files = subprocess.run(['git', '-C', ROOT, 'ls-files'], capture_output=True, text=True).stdout.split()
        for path in files:
            if judge_guard.SKILL.match(path):
                self.assertTrue(any(fnmatch.fnmatch(path, g) for r in rules for g in r['files']), f'affects.json has no rule for {path}')


    def test_skip_rules_map_docs_to_the_trio_and_tooling_to_nothing(self):
        sys.path.insert(0, os.path.join(ROOT, 'tests', 'cases'))
        import case
        trio = ['recon', 'effects', 'fidelity-edit']
        hit = lambda *files: case.affected(list(files), ROOT)
        self.assertEqual(hit('SKILL.md'), trio, 'app-screens runs only when a case targets it')
        self.assertEqual(hit('figma-worker.md'), trio)
        self.assertEqual(hit('figma_run.py'), ['recon'])
        self.assertEqual(hit('figma_perch.mjs'), ['recon'])
        self.assertEqual(hit('tests/eval/gate.py', 'tests/eval/reparse.py', 'tests/gates_test.py', 'README.md', 'GOALS.md', 'AGENTS.md'), [])
        every = sorted(t['id'] for t in (read(os.path.join(EVAL, 'tasks', f)) for f in os.listdir(os.path.join(EVAL, 'tasks'))) if t.get('default', True))
        self.assertEqual(sorted(hit('some/new_helper.py')), every, 'an unmatched file could move anything')


    def test_each_tasks_own_judge_files_move_only_the_tasks_that_use_them(self):
        """A task's definition, seed, scorer and fixture change what it measures, and reparse can't re-score
        them (final trees aren't kept), so they get a live run of the tasks that read them; shared code all."""
        sys.path.insert(0, os.path.join(ROOT, 'tests', 'cases'))
        import case
        tasks = {f[:-5]: read(os.path.join(EVAL, 'tasks', f)) for f in os.listdir(os.path.join(EVAL, 'tasks'))}
        every = sorted(t for t, d in tasks.items() if d.get('default', True))
        users = {}
        for t, d in tasks.items():
            for f in (f'tests/eval/tasks/{t}.json', f'tests/eval/scorers/{t.replace("-", "_")}.js',
                      *([f"tests/eval/{d['seed']}"] if d.get('seed') else []),
                      f"tests/eval/fixtures/{d.get('fixture', 'app')}/components.css"):
                users.setdefault(f, set()).add(t)
        for f, ts in users.items():
            if os.path.exists(os.path.join(ROOT, f)):
                self.assertEqual(set(case.affected([f], ROOT)), ts, f)
        self.assertEqual(sorted(case.affected(['tests/eval/lib.js'], ROOT)), every, 'shared scorer code moves everything')
        self.assertEqual(case.affected(['tests/eval/gate.py', 'tests/eval/session.py', 'tests/eval/offline/app_screens_good.js'], ROOT), [],
                         'transcript reading and offline states are re-judged offline')


def read(path):
    with open(path) as f:
        return json.load(f)


def git(repo, *a):
    return subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', *a], capture_output=True, text=True, check=True).stdout


def write(repo, path, text='x\n'):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w') as f:
        f.write(text)


class Guard(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        git(self.repo, 'init', '-q', '-b', 'main')
        for p in ('figma_lib.js', 'tests/eval/scorers/effects.js', 'tests/probes/proto.json', 'tests/eval/baseline.json'):
            write(self.repo, p)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'root')
        git(self.repo, 'checkout', '-q', '-b', 'case/x')

    def tearDown(self):
        shutil.rmtree(self.repo)

    def commit(self, msg, *paths):
        for p in paths:
            write(self.repo, p, msg + '\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', msg)

    def test_the_fium_gate_and_its_noise_are_judges(self):
        for p in ('tests/eval/gate.py', 'tests/eval/noise.json', 'tests/eval/reparse.py'):
            self.assertTrue(judge_guard.JUDGE.match(p), p)

    def test_a_commit_that_edits_its_own_judge_fails(self):
        self.commit('loosen the scorer and patch the lib', 'figma_lib.js', 'tests/eval/scorers/effects.js')
        self.assertEqual([v[1:] for v in judge_guard.violations(self.repo)],
                         [('loosen the scorer and patch the lib', ['tests/eval/scorers/effects.js'])])
        self.commit('drop the probe expectation', 'references/x.md')
        os.remove(os.path.join(self.repo, 'tests', 'probes', 'proto.json'))
        self.commit('and delete it', 'SKILL.md')
        self.assertEqual(len(judge_guard.violations(self.repo)), 2)

    def test_a_red_commit_may_add_judges_and_a_reviewed_change_may_edit_them(self):
        self.commit('red: overlay task', 'tests/eval/scorers/overlay.js', 'tests/eval/tasks/overlay.json', 'tests/probes/new.json')
        self.commit('fix', 'figma_lib.js')
        self.commit('refresh the baseline\n\nJudge-Change: measured after the fix', 'tests/eval/baseline.json', 'SKILL.md')
        self.commit('fix the scorer on its own', 'tests/eval/scorers/effects.js')
        self.assertEqual(judge_guard.violations(self.repo), [])
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'tests', 'judge_guard.py')], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout.strip()), (0, 'judge guard: ok (main..HEAD)'))


STAND_IN_RUN = r'''import json, sys
a = sys.argv
out, skill, tasks = a[a.index('--out') + 1], a[a.index('--skill-dir') + 1], a[a.index('--tasks') + 1].split(',')
rate = 0.0 if skill.endswith('/base') else 1.0
with open(out, 'w') as f:
    json.dump({'meta': {'file': 'K', 'model': a[a.index('--model') + 1]}, 'cost_metrics': [],
               'tasks': {t: {'lower': [], 'median': {}, 'min': {}, 'max': {}, 'pass_rate': rate if t == 'overlay' else 1, 'reps': []} for t in tasks}}, f)
with open(out + '.argv', 'w') as f:
    json.dump(a[1:], f)
'''


class Verify(unittest.TestCase):
    """case.py verify on a repo whose suites pass trivially: the real judge guard and gate.py,
    a stand-in probe runner, and a run.py that writes a result where the candidate beats the base."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo, self.home = os.path.join(self.tmp, 'repo'), os.path.join(self.tmp, 'home')
        os.makedirs(self.repo)
        git(self.repo, 'init', '-q', '-b', 'main')
        for p in ('tests/cases_test.py', 'tests/probe_test.py', 'tests/gates_test.py', 'tests/drift_test.py', 'tests/importer_test.py', 'tests/source_test.py',
                  'tests/fidelity_test.py', 'tests/fidelity_elements_test.py', 'tests/pixels_test.py', 'tests/eval/offline_test.py', 'tests/perch_backend_test.py', 'tests/budget_test.py',
                  'tests/probes/figma_probe.py'):
            write(self.repo, p, 'import sys; sys.exit(0)\n')
        for p in ('tests/figma_lib_test.js', 'tests/snapshot_test.js', 'tests/api_test.mjs'):
            write(self.repo, p, "require('node:test').test('ok', () => {});\n" if not p.endswith('.mjs') else "import { test } from 'node:test'; test('ok', () => {});\n")
        write(self.repo, 'tests/eval/run.py', STAND_IN_RUN)
        for p in ('tests/judge_guard.py', 'tests/eval/gate.py', 'tests/eval/noise.json', 'tests/eval/affects.json', 'tests/known_losses.json'):
            shutil.copy(os.path.join(ROOT, p), os.path.join(self.repo, p))
        for t in ('recon', 'effects', 'fidelity-edit', 'capture'):
            write(self.repo, f'tests/eval/tasks/{t}.json', json.dumps({'id': t}))
        write(self.repo, 'figma_lib.js')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'root')

    def tearDown(self):
        subprocess.run(['git', '-C', self.repo, 'worktree', 'prune'], capture_output=True)
        shutil.rmtree(self.tmp)

    def case(self, *args, code=0):
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'tests', 'cases', 'case.py'), *args], capture_output=True, text=True,
                           env={**os.environ, 'FIGMA_CDP_HOME': self.home, 'FIGMA_CDP_REPO': self.repo})
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return p.stdout

    def claimed(self, repro):
        cid = json.loads(self.case('new', '--symptom', 'the overlay opens centered'))['case']
        self.case('set', cid, f'repro_path={repro}', 'repro_level=L2')
        wt = json.loads(self.case('claim', cid))['worktree']
        return cid, wt

    def test_verify_runs_gates_one_to_six_and_records_them(self):
        cid, wt = self.claimed('tests/eval/tasks/overlay.json')
        write(wt, 'tests/eval/tasks/overlay.json', json.dumps({'id': 'overlay', 'default': False}))
        git(wt, 'add', '-A'); git(wt, 'commit', '-q', '-m', 'red: overlay task')
        write(wt, 'figma_lib.js', 'fixed\n')
        git(wt, 'add', '-A'); git(wt, 'commit', '-q', '-m', 'fix')
        out = self.case('verify', cid, '--file', 'https://www.figma.com/design/K/s', '--model', 'm')
        self.assertEqual([l.split(':')[1].strip() for l in out.splitlines() if l.startswith('gate ')],
                         ['pass', 'pass', 'pass', 'skip (no probe repro)', 'pass', 'pass'])
        d = os.path.join(self.home, 'inbox', cid)
        argv = read(os.path.join(d, 'gate5.json.argv'))
        self.assertEqual(argv[argv.index('--tasks') + 1], 'overlay,recon,effects,fidelity-edit')
        self.assertEqual(argv[argv.index('--case') + 1], cid)
        self.assertFalse(os.path.exists(os.path.join(d, 'base')), 'the base worktree is removed')
        gates = read(os.path.join(d, 'case.json'))['gates']['results']
        self.assertEqual([g['verdict'] for g in gates], ['pass', 'pass', 'pass', 'skip', 'pass', 'pass'])
        packet = self.case('packet', cid).strip()
        with open(packet) as f:
            text = f.read()
        self.assertIn('| 6 | paired base/candidate, 3 reps | pass |', text)
        self.assertIn('- SKILL.md: 0 → 0 bytes (+0)', text)
        self.assertIn('not recorded: set symptom_check', text)

    def test_verify_stops_at_the_judge_guard(self):
        cid, wt = self.claimed('tests/eval/tasks/recon.json')
        write(wt, 'tests/eval/gate.py', '# looser\n')
        write(wt, 'figma_lib.js', 'fixed\n')
        git(wt, 'add', '-A'); git(wt, 'commit', '-q', '-m', 'fix and loosen')
        out = self.case('verify', cid, code=1)
        self.assertIn('gate 3 judge guard: fail', out)
        self.assertNotIn('gate 4', out)

    def test_without_a_file_the_live_gates_leave_it_unverified(self):
        cid, wt = self.claimed('tests/probes/proto.js')
        write(wt, 'figma_run.py', 'x\n')
        git(wt, 'add', '-A'); git(wt, 'commit', '-q', '-m', 'fix')
        out = self.case('verify', cid, '--dry-run')
        self.assertIn('tests/perch_backend_test.py', out, 'a perch-side change runs the perch suite')
        self.assertIn('gate 4 probe: skip (needs --file <scratch-url>)', out)
        out = self.case('verify', cid, code=3)
        self.assertIn('gate 4 probe: skip (needs --file', out)
        self.assertNotIn('gate 5', out)


if __name__ == '__main__':
    unittest.main()
