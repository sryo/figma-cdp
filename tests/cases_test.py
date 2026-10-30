#!/usr/bin/env python3
"""tests/cases/case.py and tests/figma_lock.py, offline: a temp FIGMA_CDP_HOME with a hand-written
journal and a throwaway git repo for claim.

  python3 tests/cases_test.py
"""
import json, os, shutil, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASE = os.path.join(ROOT, 'tests', 'cases', 'case.py')
sys.path.insert(0, os.path.join(ROOT, 'tests'))


def read(path):
    with open(path) as f:
        return json.load(f)


class Cases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home, self.repo = os.path.join(self.tmp, 'home'), os.path.join(self.tmp, 'repo')
        os.makedirs(os.path.join(self.repo, 'tests'))
        shutil.copy(os.path.join(ROOT, 'tests', 'known_losses.json'), os.path.join(self.repo, 'tests'))
        git = lambda *a: subprocess.run(['git', '-C', self.repo, *a], capture_output=True, check=True)
        git('init', '-q', '-b', 'main')
        git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'root')

    def tearDown(self):
        subprocess.run(['git', '-C', self.repo, 'worktree', 'prune'], capture_output=True)
        shutil.rmtree(self.tmp)

    def journal(self, *entries):
        d = os.path.join(self.home, 'journal')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, '2026-10-30.jsonl'), 'a') as f:
            for e in entries:
                f.write(json.dumps({'ts': '', 'tool': 'figma_run.py', 'backend': 'perch', 'label': '-e[1]', 'sha': '', 'script': 'x', **e}) + '\n')

    def case(self, *args, code=0):
        r = subprocess.run([sys.executable, CASE, *args], capture_output=True, text=True,
                           env={**os.environ, 'FIGMA_CDP_HOME': self.home, 'FIGMA_CDP_REPO': self.repo})
        self.assertEqual(r.returncode, code, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip().startswith('{') else (r.stdout + r.stderr)

    def test_new_from_the_last_failed_eval_keeps_its_script_and_context(self):
        self.journal({'rid': 'a1', 'file': 'K', 'ok': True, 'result': '1'},
                     {'rid': 'b2', 'file': 'K', 'ok': False, 'error': 'Error: in set_overlayPositionType: node 12:34 "Menu" rejected 3 values', 'hint': None},
                     {'rid': 'c3', 'file': 'K', 'ok': True, 'result': '2'})
        out = self.case('new', '--last', '--expected', 'src/Menu.tsx:40 opens below the button')
        self.assertEqual(out['status'], 'open')
        self.assertEqual(out['signature'], 'error: in set_overlaypositiontype: node <id> <s> rejected # values')
        c = read(os.path.join(out['dir'], 'case.json'))
        self.assertEqual([e['rid'] for e in c['journal']], ['b2'])
        self.assertEqual([e['rid'] for e in c['context']], ['a1'])
        self.assertTrue(c['id'].endswith('error-in-set-overlaypositiontype-node-12'))
        self.assertTrue(os.path.isfile(os.path.join(out['dir'], 'notes.md')))
        again = self.case('new', '--rid', 'b2')
        self.assertEqual((again['status'], again['dup_of']), ('dup', out['case']))

    def test_known_losses_are_refused_unless_forced(self):
        self.assertIn('known loss (mask-image-icon', self.case('new', '--symptom', 'icons with mask-image came in as boxes', code=3))
        self.assertEqual(self.case('new', '--symptom', 'icons with mask-image came in as boxes', '--force')['status'], 'open')

    def test_triage_proposes_from_deterministic_signals(self):
        for symptom, want in [('perch: tab_not_visible: eval_js needs the tab', 'env'),
                              ('SET_VARIABLE requires a paid plan', 'api-plan-limited'),
                              ('You cannot use Set Variable actions in Reactions with your current plan.', 'api-plan-limited'),
                              ('in addMode: Limited to 1 modes only', 'api-plan-limited'),
                              ('the overlay opens centered, not under the button', None)]:
            cid = self.case('new', '--symptom', symptom)['case']
            self.assertEqual(self.case('triage', cid)['proposed_class'], want, symptom)
        oracle = self.case('triage', self.case('new', '--symptom', 'in addMode: Limited to 1 modes only', '--force')['case'])['oracle']
        self.assertEqual(oracle[0]['member'], 'VariableCollection.addMode')
        self.assertEqual(set(oracle[0]), {'member', 'ro', 'covered', 'docUrl'})
        self.journal({'rid': 'h', 'file': 'K', 'ok': False, 'error': 'unloaded font', 'hint': 'hint: load it'})
        cid = self.case('new', '--rid', 'h')['case']
        self.assertEqual(self.case('triage', cid)['proposed_class'], 'agent-ignored-doc')

    def test_claim_makes_a_worktree_and_holds_a_lease(self):
        cid = self.case('new', '--symptom', 'svg var() colors lost')['case']
        out = self.case('claim', cid)
        self.assertEqual(out['branch'], f'case/{cid}')
        self.assertTrue(os.path.isdir(out['worktree']))
        self.assertIn('claimed 0 min ago', self.case('claim', cid, code=2))
        self.assertIn('claimed', self.case('claim', cid, '--steal', code=2))
        path = os.path.join(self.home, 'inbox', cid, 'case.json')
        c = read(path)
        c['claim']['at'] = time.time() - 5 * 3600
        with open(path, 'w') as f:
            json.dump(c, f)
        self.assertEqual(self.case('claim', cid, '--steal')['worktree'], out['worktree'])

    def test_close_writes_the_ledger_row_and_dedupes_later_cases_against_it(self):
        cid = self.case('new', '--symptom', 'overlayPositionType = MANUAL is ignored')['case']
        self.assertIn('set the class first', self.case('close', cid, '--status', 'merged', '--reason', 'r', '--commit', 'abc', code=1))
        self.assertIn('class bogus', self.case('set', cid, 'class=bogus', code=1))
        self.case('set', cid, 'class=api-limit', 'repro_path=tests/prototyping_probe.js')
        out = self.case('close', cid, '--status', 'merged', '--reason', 'documented with the overlay workaround', '--commit', 'a8a1d19')
        row = read(os.path.join(self.repo, out['ledger']))
        self.assertEqual((row['class'], row['commit'], row['repro']), ('api-limit', 'a8a1d19', 'tests/prototyping_probe.js'))
        shutil.rmtree(os.path.join(self.home, 'inbox'))
        self.assertEqual(self.case('new', '--symptom', 'overlayPositionType = MANUAL is ignored')['dup_of'], cid)
        stats = self.case('stats')
        self.assertEqual((stats['cases'], stats['ledger'], stats['by_status']), (1, 1, {'dup': 1}))


class Lock(unittest.TestCase):
    def test_every_live_entry_point_takes_the_shared_lock(self):
        import figma_lock
        sys.path.insert(0, os.path.join(ROOT, 'tests', 'eval'))
        import run
        self.assertIs(run.file_lock, figma_lock.file_lock)
        sys.path.insert(0, os.path.join(ROOT, 'tests', 'probes'))
        import figma_probe
        self.assertIs(figma_probe.file_lock, figma_lock.file_lock)

    def test_the_lock_is_exclusive(self):
        import figma_lock
        key = f'cases-test-{os.getpid()}'
        held = figma_lock.file_lock(key)
        try:
            probe = 'import fcntl,sys; f=open(sys.argv[1],"a")\ntry:\n fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB); print("free")\nexcept OSError: print("held")'
            r = subprocess.run([sys.executable, '-c', probe, figma_lock.lock_path(key)], capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), 'held')
        finally:
            held.close()
            os.remove(figma_lock.lock_path(key))


if __name__ == '__main__':
    unittest.main()
