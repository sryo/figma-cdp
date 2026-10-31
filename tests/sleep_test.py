#!/usr/bin/env python3
"""tests/sleep/sleep.py, offline: hand-written transcripts and journal in a temp FIGMA_CDP_HOME, and
the repo's own lessons replayed against the helpers.

  python3 tests/sleep_test.py
"""
import json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLEEP = os.path.join(ROOT, 'tests', 'sleep', 'sleep.py')


def use(i, ts, name, inp):
    return {'type': 'assistant', 'timestamp': ts, 'sessionId': 'S1',
            'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': i, 'name': name, 'input': inp}]}}


def result(i, ts, text, err=False):
    return {'type': 'user', 'timestamp': ts, 'sessionId': 'S1',
            'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': i, 'is_error': err, 'content': text}]}}


def human(ts, text):
    return {'type': 'user', 'timestamp': ts, 'sessionId': 'S1', 'origin': {'kind': 'human'},
            'message': {'role': 'user', 'content': text}}


RUN = 'python3 figma_run.py --lib -e "await __fx.text({parent, chars: \'Hi\'})"'
TRANSCRIPT = [
    human('2026-10-30T10:00:00Z', 'build the login screen in figma'),
    use('t1', '2026-10-30T10:00:05Z', 'Bash', {'command': RUN}),
    result('t1', '2026-10-30T10:00:06Z', 'Exit code 1\n✗ Evaluation error: in set_characters: Cannot write to node with unloaded font "Inter Regular"', True),
    use('t2', '2026-10-30T10:00:10Z', 'Bash', {'command': RUN.replace('Hi', 'Hey')}),
    result('t2', '2026-10-30T10:00:11Z', 'Exit code 1\n✗ Evaluation error: in set_characters: Cannot write to node with unloaded font "Inter Bold"', True),
    use('t3', '2026-10-30T10:00:15Z', 'Bash', {'command': RUN.replace('Hi', 'Hello')}),
    result('t3', '2026-10-30T10:01:40Z', '{"id":"1:2"}'),
    use('t4', '2026-10-30T10:01:45Z', 'Read', {'file_path': '/x/figma_lib.js'}),
    result('t4', '2026-10-30T10:01:46Z', 'x' * 30000),
    use('t5', '2026-10-30T10:01:50Z', 'Agent', {'prompt': 'go'}),
    result('t5', '2026-10-30T10:09:50Z', 'done'),
    human('2026-10-30T10:10:00Z', "no, don't rebuild the header, edit it in place"),
    human('2026-10-30T10:11:00Z', '[Request interrupted by user]'),
    human('2026-10-30T10:12:00Z', '<system-reminder>not a person</system-reminder>'),
]


class Sleep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, 'home')
        self.src = os.path.join(self.tmp, 'projects', '-Users-me-Documents-figma-cdp')
        os.makedirs(os.path.join(self.src, 'S1', 'subagents'))
        self.write(os.path.join(self.src, 'S1.jsonl'), TRANSCRIPT)
        # A worker in a subagent transcript hits the same font error: one cluster, two places.
        self.write(os.path.join(self.src, 'S1', 'subagents', 'agent-w.jsonl'), [
            use('w1', '2026-10-30T10:05:00Z', 'Bash', {'command': RUN}),
            result('w1', '2026-10-30T10:05:01Z', '✗ Evaluation error: in set_characters: Cannot write to node with unloaded font "SF Pro"', True)])
        self.write(os.path.join(self.tmp, 'projects', '-Users-me-Documents-perch', 'P1.jsonl'), [
            use('p1', '2025-01-01T00:00:00Z', 'mcp__perch__click', {'selector': '#a'}),
            result('p1', '2025-01-01T00:00:01Z', 'tab_not_visible: the tab is hidden', True)])
        os.makedirs(os.path.join(self.home, 'journal'))
        self.write(os.path.join(self.home, 'journal', '2026-10-30.jsonl'), [
            {'ts': '2026-10-30T07:00:00-0300', 'rid': 'r1', 'tool': 'figma_run.py', 'ok': False,
             'error': 'Error: in set_layoutSizingHorizontal: FILL can only be set on children of auto-layout frames', 'hint': 'hint: x'},
            {'ts': '2026-10-30T07:00:01-0300', 'rid': 'r2', 'tool': 'figma_run.py', 'ok': True, 'result': '1'}])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, path, rows):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.writelines(json.dumps(r) + '\n' for r in rows)

    def sleep(self, *args, code=0, lessons=None):
        env = {**os.environ, 'FIGMA_CDP_HOME': self.home}
        if lessons is not None:
            env['FIGMA_CDP_LESSONS'] = lessons
        r = subprocess.run([sys.executable, SLEEP, *args], capture_output=True, text=True, env=env, cwd=ROOT)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def mine(self, *extra):
        out = os.path.join(self.tmp, 'signals.jsonl')
        self.sleep('mine', '--source', os.path.join(self.tmp, 'projects'), '--source', os.path.join(self.home, 'journal'), '--out', out, *extra)
        with open(out) as f:
            return [json.loads(l) for l in f]

    def lessons(self, rows):
        path = os.path.join(self.tmp, 'lessons.jsonl')
        self.write(path, rows)
        return path

    def test_mine_reads_every_kind_of_signal_with_its_evidence(self):
        sig = self.mine('--since', '2026-10-01')
        kinds = sorted({s['kind'] for s in sig})
        self.assertEqual(kinds, ['correction', 'error', 'heavy', 'retry', 'slow'])
        errs = [s for s in sig if s['kind'] == 'error']
        self.assertEqual(len(errs), 4)  # 2 in the main session, 1 in the worker, 1 from the journal
        font = [s for s in errs if 'unloaded font' in s['sig']]
        self.assertEqual({s['sig'] for s in font}, {'in set_characters: cannot write to node with unloaded font <s>'})
        self.assertEqual(font[0]['session'], 'S1')
        self.assertEqual(font[0]['project'], 'figma-cdp')
        self.assertEqual(font[0]['shape'], 'figma_run.py')
        self.assertTrue(font[0]['ts'].startswith('2026-10-30T10:00:06'))
        self.assertTrue(any(s['source'] == 'journal' for s in errs))
        slow = [s for s in sig if s['kind'] == 'slow']
        self.assertEqual([(s['shape'], s['value']) for s in slow], [('figma_run.py', 85.0)])  # Agent waits are not stalls
        heavy = [s for s in sig if s['kind'] == 'heavy']
        self.assertEqual([(s['shape'], s['value']) for s in heavy], [('Read figma_lib.js', 30000)])
        retry = [s for s in sig if s['kind'] == 'retry']
        self.assertEqual([(s['shape'], s['value']) for s in retry], [('figma_run.py', 3)])
        corr = [s for s in sig if s['kind'] == 'correction']
        self.assertEqual(len(corr), 2)
        self.assertIn("don't rebuild the header", corr[0]['text'])
        self.assertEqual(corr[0]['after'], 'Agent')
        self.assertEqual(corr[1]['sig'], 'interrupted')

    def test_mine_reads_eval_stream_json_and_kept_journals(self):
        run = os.path.join(self.tmp, 'run')
        rep = [dict(r, session_id='rep-0') for r in ([
            use('e1', '2026-10-30T11:00:00Z', 'Bash', {'command': 'S=/tmp/x; cd /tmp && cat references/building.md | head -50'}),
            result('e1', '2026-10-30T11:00:01Z', 'Exit code 1\nTraceback (most recent call last):\n  File "x.py", line 3\nKeyError: \'id\'', True),
            use('e2', '2026-10-30T11:00:02Z', 'Bash', {'command': 'python3 figma_run.py --recover 3f9aac0c1f2a'}),
            result('e2', '2026-10-30T11:00:03Z', 'request 3f9aac0c1f2a is still running in the page; figma_run.py --recover 3f9aac0c1f2a', True)])]
        for r in rep:
            r.pop('sessionId')
        self.write(os.path.join(run, 'r1_tx', 'layout-1.jsonl'), rep)
        self.write(os.path.join(run, 'r1_tx', 'layout-1', 'journal', '2026-10-30.jsonl'), [
            {'ts': '2026-10-30T08:00:00-0300', 'rid': 'j1', 'tool': 'figma_batch_run.py', 'ok': False, 'error': 'Error: in appendChild: oops'}])
        out = os.path.join(self.tmp, 'eval.jsonl')
        self.sleep('mine', '--all', '--source', run, '--out', out)
        with open(out) as f:
            sig = [json.loads(l) for l in f]
        errs = {s['sig']: s for s in sig if s['kind'] == 'error'}
        self.assertEqual(sorted(errs), ["error: in appendchild: oops", "keyerror: <s>",
                                        'request <hex> is still running in the page; figma_run.py --recover <hex>'])
        self.assertEqual(errs['keyerror: <s>']['session'], 'rep-0')
        self.assertEqual(errs['keyerror: <s>']['shape'], 'cat')
        self.assertEqual(errs['error: in appendchild: oops']['source'], 'journal')

    def test_mine_since_drops_older_sessions(self):
        sig = self.mine('--since', '2026-10-01')
        self.assertFalse([s for s in sig if s['project'] == 'perch'])
        sig = self.mine('--since', '2024-01-01')
        self.assertEqual([s['sig'] for s in sig if s['project'] == 'perch'], ['tab_not_visible: the tab is hidden'])

    def test_digest_clusters_ranks_and_marks_what_is_already_known(self):
        sig = self.mine('--since', '2026-10-01')
        sigs = os.path.join(self.tmp, 'signals.jsonl')
        lessons = self.lessons([{'id': 'fill-hint', 'kind': 'hint', 'signature': 'error: in set_layoutsizinghorizontal: fill can only be set on children of auto-layout frames',
                                 'error': 'FILL can only be set on children of auto-layout', 'expect': 'appendChild', 'added': '2026-10-29'}])
        out = os.path.join(self.tmp, 'digest.json')
        self.sleep('digest', sigs, '--json', out, '--top', '3', '--explore', '0', lessons=lessons)
        with open(out) as f:
            d = json.load(f)
        top = d['clusters']
        # The consolidated lesson's signal came back after the lesson was added: a relapse ranks first.
        self.assertEqual(top[0]['status'], 'relapse')
        self.assertEqual(top[0]['lesson'], 'fill-hint')
        font = next(c for c in d['all'] if 'unloaded font' in c['sig'])
        self.assertEqual((font['count'], font['sessions'], font['status']), (3, 1, 'hinted'))
        self.assertEqual(font['target'], 'agent-ignored-doc: move the rule to the point of use (hint fires but the call repeats)')
        self.assertEqual(len(font['evidence']), 3)
        self.assertEqual(font['evidence'][0]['session'], 'S1')
        self.assertEqual(len(top), 3)
        md = self.sleep('digest', sigs, '--top', '3', '--explore', '0', lessons=lessons)
        self.assertIn('| relapse |', md)

    def test_digest_explore_adds_random_unknowns_reproducibly(self):
        self.mine('--since', '2026-10-01')
        sigs = os.path.join(self.tmp, 'signals.jsonl')
        lessons = self.lessons([])
        a, b = (os.path.join(self.tmp, n) for n in ('a.json', 'b.json'))
        self.sleep('digest', sigs, '--json', a, '--top', '1', '--explore', '2', '--seed', '7', lessons=lessons)
        self.sleep('digest', sigs, '--json', b, '--top', '1', '--explore', '2', '--seed', '7', lessons=lessons)
        with open(a) as f, open(b) as g:
            da, db = json.load(f), json.load(g)
        self.assertEqual(da['clusters'], db['clusters'])
        self.assertEqual([c['pick'] for c in da['clusters']], ['top', 'explore', 'explore'])

    def test_replay_checks_each_lesson_against_both_helpers_and_the_docs(self):
        ok = self.lessons([
            {'id': 'font', 'kind': 'hint', 'error': 'Error: in set_characters: Cannot write to node with unloaded font "Inter"', 'expect': 'loadFontAsync'},
            {'id': 'skill-rule', 'kind': 'doc', 'file': 'SKILL.md', 'expect': 'figma_run'}])
        self.assertIn('2 lessons hold', self.sleep('replay', lessons=ok))
        bad = self.lessons([
            {'id': 'gone', 'kind': 'hint', 'error': 'Error: something nobody hints', 'expect': 'anything'},
            {'id': 'deleted-rule', 'kind': 'doc', 'file': 'SKILL.md', 'expect': 'a rule nobody wrote \\d{9}'}])
        out = self.sleep('replay', code=1, lessons=bad)
        self.assertIn('gone', out)
        self.assertIn('deleted-rule', out)

    def test_learn_appends_a_lesson_that_replay_then_holds(self):
        path = self.lessons([])
        self.sleep('learn', '--id', 'font', '--kind', 'hint', '--error', 'unloaded font "X"', '--expect', 'loadFontAsync',
                   '--signature', 'in set_characters: cannot write to node with unloaded font <s>', '--evidence', 'S1 2026-10-30T10:00:06Z', lessons=path)
        with open(path) as f:
            rows = [json.loads(l) for l in f]
        self.assertEqual(rows[0]['id'], 'font')
        self.assertTrue(rows[0]['added'])
        self.assertIn('unknown kind', self.sleep('learn', '--id', 'x', '--kind', 'vibe', '--expect', 'y', code=2, lessons=path))
        self.assertIn('already', self.sleep('learn', '--id', 'font', '--kind', 'hint', '--error', 'e', '--expect', 'y', code=2, lessons=path))
        self.assertIn('1 lessons hold', self.sleep('replay', lessons=path))

    def test_check_dry_run_lists_the_gates(self):
        out = self.sleep('check', '--dry-run', '--candidate', 'cand.json')
        for gate in ('tests/sleep_test.py', 'tests/budget_test.py', 'replay', 'compare.py', 'cand.json'):
            self.assertIn(gate, out)
        self.assertNotIn('compare.py', self.sleep('check', '--dry-run'))

    def test_the_repos_lessons_hold(self):
        self.sleep('replay', lessons=os.path.join(ROOT, 'tests', 'sleep', 'lessons.jsonl'))


if __name__ == '__main__':
    unittest.main()
