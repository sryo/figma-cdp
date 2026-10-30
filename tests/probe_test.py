#!/usr/bin/env python3
"""tests/probes/figma_probe.py offline, through figma_run.py and the perch stub's full Plugin API
stub, plus the citations behind each refusal tests/figma_stub.js models.

  python3 tests/probe_test.py
"""
import glob, json, os, re, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBES = os.path.join(ROOT, 'tests', 'probes')
sys.path.insert(0, os.path.join(ROOT, 'tests'))
sys.path.insert(0, PROBES)
import figma_probe  # noqa: E402
from perch_backend_test import Harness  # noqa: E402

KEY = figma_probe.scratch_key()
TAB = json.dumps([{'app': 'Google Chrome', 'tabId': 'chrome:1', 'url': f'https://www.figma.com/design/{KEY}/figma-cdp-scratch', 'title': 'scratch – Figma'}])
STATE = r'''return {
  pages: figma.root.children.map((p) => p.name), current: figma.currentPage.name,
  collections: (await figma.variables.getLocalVariableCollectionsAsync()).map((c) => c.name),
  styles: (await figma.getLocalPaintStylesAsync()).map((s) => s.name) };'''


def read(path):
    with open(path) as f:
        return json.load(f)


class Runner(Harness):
    def env(self, **more):
        return {'PERCH_STUB_FIGMA': 'full', 'PERCH_STUB_TABS': TAB, 'FIGMA_CDP_LOCK_DIR': self.tmp.name, **more}

    def figma(self, src):
        p = self.run_helper('figma_run.py', '--file', KEY, '-', stdin=src, **self.env())
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def probe(self, *args):
        return self.run_helper(os.path.join('tests', 'probes', 'figma_probe.py'), '--file', KEY, *args, **self.env())

    def scratch(self):
        self.figma("figma.root.name = 'figma cdp scratch'; return 1")

    def body(self, name, src, spec=None):
        path = self.js(name + '.js', src)
        if spec is not None:
            with open(path[:-3] + '.json', 'w') as f:
                json.dump(spec, f)
        return path

    def test_the_prototyping_probe_reproduces_its_limits_on_the_stub(self):
        self.scratch()
        p = self.probe('prototyping')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual((out['passed'], out['failures'], out['drift']), (True, [], {}))
        self.assertEqual(self.figma(STATE), {'pages': ['Page 1'], 'current': 'Page 1', 'collections': [], 'styles': []})

    def test_a_crashed_probe_leaves_nothing_once_the_next_runs(self):
        self.scratch()
        # What a probe killed mid-run (a timeout, a closed tab) leaves behind.
        self.figma("""const p = figma.createPage(); p.name = '__probe'; await figma.setCurrentPageAsync(p);
          figma.variables.createVariableCollection('__probe vars'); figma.createPaintStyle().name = '__probe fill';
          figma.variables.createVariableCollection('Brand'); return 1""")
        p = self.probe(self.body('boom', "figma.createFrame(); throw new Error('boom');"))
        self.assertEqual(p.returncode, 1)
        out = json.loads(p.stdout)
        self.assertFalse(out['passed'])
        self.assertIn('boom', out['failures'][0]['got'])
        state = self.figma(STATE)
        self.assertEqual(state, {'pages': ['Page 1'], 'current': 'Page 1', 'collections': ['Brand'], 'styles': []})

    def test_only_the_scratch_file_runs_probes(self):
        p = self.run_helper(os.path.join('tests', 'probes', 'figma_probe.py'), '--file', 'https://www.figma.com/design/AAA111/Other', 'prototyping', **self.env())
        self.assertEqual(p.returncode, 2)
        self.assertIn(f'only on the scratch file {KEY}', p.stderr)
        self.assertEqual(self.calls('eval_js'), [])

    def test_a_file_not_named_as_the_scratch_file_is_left_alone(self):
        p = self.probe('prototyping')
        self.assertEqual(p.returncode, 2)
        self.assertIn('not the scratch file', p.stderr)
        self.assertEqual(self.figma(STATE)['pages'], ['Page 1'])

    def test_a_verdict_that_moved_is_drift(self):
        self.scratch()
        path = self.body('moved', "limit('FrameNode.overlayPositionType', 'ignored'); limit('X.y', 'works');",
                         {'limits': {'FrameNode.overlayPositionType': 'works'}})
        p = self.probe(path)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)['drift'], {'FrameNode.overlayPositionType': {'want': 'works', 'got': 'ignored'},
                                                         'X.y': {'want': None, 'got': 'works'}})

    def test_an_unknown_verdict_fails_the_probe(self):
        self.scratch()
        p = self.probe(self.body('odd', "limit('X.y', 'maybe');", {'limits': {'X.y': 'maybe'}}))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)['failures'][0]['what'], 'limit X.y')

    def test_record_writes_one_verdict_file_per_member(self):
        self.scratch()
        out = os.path.join(self.tmp.name, 'verdicts')
        p = self.probe('--record', '--record-dir', out, 'prototyping')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rows = {r['member']: r for r in (read(f) for f in glob.glob(os.path.join(out, '*.json')))}
        self.assertEqual(sorted(rows), ['Action.SET_VARIABLE', 'FrameNode.overlayBackgroundInteraction',
                                        'FrameNode.overlayPositionType', 'VariableCollection.addMode'])
        row = rows['Action.SET_VARIABLE']
        self.assertEqual((row['verdict'], row['plan'], row['probe'], row['editorType']), ('refused', 'free(assumed)', 'prototyping', 'figma'))
        self.assertIn('current plan', row['error'])
        self.assertIsNone(rows['FrameNode.overlayPositionType']['plan'])
        self.assertEqual(set(row), {'member', 'verdict', 'error', 'probe', 'typingsVersion', 'date', 'editorType', 'plan'})

    def test_case_snapshot_keeps_a_seed_beside_the_case(self):
        made = self.figma("""const f = figma.createFrame(); f.name = 'Card'; const r = figma.createRectangle(); f.appendChild(r);
          return f.id""")
        home = os.path.join(self.tmp.name, 'home')
        os.makedirs(os.path.join(home, 'inbox', 'c1'))
        with open(os.path.join(home, 'inbox', 'c1', 'case.json'), 'w') as f:
            json.dump({'id': 'c1', 'status': 'open', 'class': None}, f)
        p = self.run_helper(os.path.join('tests', 'cases', 'case.py'), 'snapshot', 'c1', '--node', made, '--file', KEY,
                            **self.env(FIGMA_CDP_HOME=home))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)['nodes'], 2)
        seed = read(os.path.join(home, 'inbox', 'c1', 'seed.json'))
        self.assertEqual([seed['root']['props']['name'], seed['root']['children'][0]['type']], ['Card', 'RECTANGLE'])
        self.assertEqual(read(os.path.join(home, 'inbox', 'c1', 'case.json'))['snapshot'], 'seed.json')


class Guard(unittest.TestCase):
    def test_lint_refuses_what_a_probe_did_not_create(self):
        for src in ("figma.root.children[0].remove()", "figma.currentPage.appendChild(x)", "await figma.saveVersionHistoryAsync('x')",
                    "await figma.importComponentByKeyAsync(k)", "await figma.getNodeByIdAsync('1:2')", "figma.getStyleById(s)",
                    "await figma.variables.getLocalVariablesAsync()", "await figma.loadAllPagesAsync()",
                    "figma.on('selectionchange', f)", "figma.closePlugin()", "figma.clientStorage.setAsync('k', 1)"):
            self.assertTrue(figma_probe.lint(src), src)

    def test_every_probe_here_passes_lint(self):
        for path in glob.glob(os.path.join(PROBES, '*.js')):
            with open(path) as f:
                self.assertEqual(figma_probe.lint(f.read()), [], path)

    def test_every_expected_verdict_is_a_known_one(self):
        for path in glob.glob(os.path.join(PROBES, '*.json')):
            with open(path) as f:
                spec = json.load(f)
            for member, verdict in spec.get('limits', {}).items():
                self.assertIn(verdict, figma_probe.VERDICTS, f'{path}: {member}')


class StubCitations(unittest.TestCase):
    """Every refusal or ignored assignment the stub models says what showed it."""

    def setUp(self):
        with open(os.path.join(PROBES, 'stub_citations.json')) as f:
            self.cites = json.load(f)
        with open(os.path.join(ROOT, 'tests', 'figma_stub.js')) as f:
            self.lines = [l for l in f if 'throw new Error(' in l or 'if (OVERLAY[k]) return true' in l]
        self.matches = [c['match'] for c in self.cites['probed']] + self.cites['known-before-ledger']

    def test_each_modeled_refusal_is_cited(self):
        for line in self.lines:
            self.assertTrue(any(m in line for m in self.matches), f'figma_stub.js models this with no citation: {line.strip()}')

    def test_each_citation_still_matches_the_stub(self):
        for m in self.matches:
            self.assertTrue(any(m in line for line in self.lines), f'stub_citations.json cites a line the stub no longer has: {m}')

    def test_each_probed_citation_names_what_its_probe_checks(self):
        for c in self.cites['probed']:
            with open(os.path.join(PROBES, c['probe'] + '.js')) as f:
                body = f.read()
            if 'member' in c:
                with open(os.path.join(PROBES, c['probe'] + '.json')) as f:
                    self.assertIn(c['member'], json.load(f)['limits'], c)
            else:
                self.assertRegex(body, r"\b(check|refuses)\('" + re.escape(c['check']) + "'", c)


if __name__ == '__main__':
    unittest.main()
