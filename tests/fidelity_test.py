#!/usr/bin/env python3
"""Offline tests for figma_fidelity.py: the fixture's login screen built on the stub Plugin API
(tests/fidelity_login.js) checked against the manifest figma_source.py extracts from the
fixture source. Runs through the real figma_run.py → figma_perch.mjs daemon path against
tests/perch_stub with PERCH_STUB_FIGMA=full, so the built tree persists between calls.

  python3 tests/fidelity_test.py
"""
import json, os, socket, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'app')
FILE = 'https://www.figma.com/design/AAA111/Stub'


def stop_daemon(sock):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(5)
        s.connect(sock)
        f = s.makefile('rb')
        f.readline()
        s.sendall(b'{"op":"stop"}\n')
        f.read()
    except OSError:
        pass
    finally:
        s.close()


class Fidelity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = os.path.join(self.tmp.name, 'd.sock')
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ('FIGMA_FILE', 'FIGMA_PERCH_TAB', 'FIGMA_CDP_PORT', 'PERCH_STUB_ERROR')}
        self.env.update(FIGMA_BACKEND='perch', PERCH_DIR=os.path.join(ROOT, 'tests', 'perch_stub'), PERCH_STUB_FIGMA='full',
                        FIGMA_PERCH_SOCK=self.sock, FIGMA_PERCH_DAEMON='1')
        self.manifest = os.path.join(self.tmp.name, 'manifest.json')
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_source.py'), '-o', self.manifest,
                            *(os.path.join(APP, f) for f in ('login.html', 'components.css', 'tokens.css'))],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self):
        stop_daemon(self.sock)
        self.tmp.cleanup()

    def build(self, bad):
        with open(os.path.join(ROOT, 'tests', 'eval', 'lib.js')) as f:
            lib = f.read()
        with open(os.path.join(ROOT, 'tests', 'fidelity_login.js')) as f:
            body = f.read()
        with open(os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'expect.json')) as f:
            expect = json.load(f)
        ctx = {'prefix': 'fid', 'expect': expect, 'bad': bad}
        path = os.path.join(self.tmp.name, 'build.js')
        with open(path, 'w') as f:
            f.write(f'(async function (EVAL) {{\n{lib}\n{body}\n}})({json.dumps(ctx)})\n')
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_run.py'), '--file', FILE, path],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def fidelity(self, root, *args, manifest=None):
        return subprocess.run([sys.executable, os.path.join(ROOT, 'figma_fidelity.py'), manifest or self.manifest, root,
                               '--file', FILE, *args], capture_output=True, text=True, env=self.env)

    def report(self, root):
        r = self.fidelity(root, '--json')
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return json.loads(r.stdout), r.returncode

    def test_good_build_has_no_gaps(self):
        ids = self.build(False)
        r = self.fidelity(ids['rootId'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertRegex(lines[0], r'^fidelity \S+ "Login": 0 gaps')
        self.assertIn('not checked (no component in the subtree): toggle', r.stdout)
        self.assertLessEqual(len(lines), 3, 'a clean report stays short')

    def test_bad_build_names_every_gap(self):
        ids = self.build(True)
        rep, code = self.report(ids['rootId'])
        self.assertEqual(code, 1)
        g = rep['gaps']
        self.assertEqual(sorted(e['text'] for e in g['missing copy']), ['Forgot your passphrase?', 'Welcome back to Lumen'])
        self.assertTrue(all(e['src'].startswith('login.html:') for e in g['missing copy']))
        self.assertEqual([e['text'] for e in g['invented copy']], ['Remember me'])
        self.assertEqual([e['value'] for e in g['off-manifest colors']], ['#2563eb'])
        self.assertEqual(g['off-manifest colors'][0]['ids'], [ids['primaryId']])
        self.assertEqual([e['value'] for e in g['off-manifest spacing']], [18])
        self.assertEqual(g['off-manifest spacing'][0]['ids'], [ids['formId']])
        self.assertEqual([e['value'] for e in g['off-manifest radii']], [7])
        self.assertEqual([e['value'] for e in g['off-manifest font sizes']], [15])
        self.assertEqual([e['value'] for e in g['off-manifest fonts']], ['Roboto'])
        unbound = {e['value']: e for e in g['unbound']}
        self.assertEqual(sorted(unbound, key=str), ['#6b7280', 24])
        self.assertEqual((unbound['#6b7280']['variable'], unbound['#6b7280']['token']), ('color/text-muted', '--color-text-muted'))
        self.assertEqual(unbound['#6b7280']['ids'], [ids['subId']])
        self.assertEqual((unbound[24]['variable'], unbound[24]['token']), ('space/6', '--space-6'))
        self.assertEqual([(e['component'], e['values']) for e in g['missing variants']], [('button', ['secondary'])])
        self.assertEqual([(e['component'], e['state']) for e in g['missing states']], [('button', 'disabled')])
        self.assertEqual(rep['count'], sum(len(v) for v in g.values()))

    def test_text_report_is_one_line_per_kind(self):
        ids = self.build(True)
        r = self.fidelity(ids['rootId'])
        self.assertEqual(r.returncode, 1)
        out = r.stdout
        self.assertRegex(out.splitlines()[0], r'^fidelity \S+ "Login": 12 gaps')
        for line in ('missing copy (2): "Welcome back to Lumen" login.html:',
                     'invented copy (1): "Remember me" ' + ids['rootId'].split(':')[0] + ':',
                     'off-manifest colors (1): #2563eb ×1 (' + ids['primaryId'] + ')',
                     'off-manifest spacing (1): 18 ×1 (' + ids['formId'] + ')',
                     'unbound (2): ', '#6b7280 ×1 → color/text-muted (' + ids['subId'] + ')',
                     'missing variants (1): button: secondary (components.css:',
                     'missing states (1): button: disabled (components.css:'):
            self.assertIn(line, out)
        kinds = [l.split(' (')[0] for l in out.splitlines()[1:]]
        self.assertEqual(len(kinds), len(set(kinds)), out)

    def test_manifest_without_a_category_skips_it(self):
        ids = self.build(True)
        with open(self.manifest) as f:
            m = json.load(f)
        m['copy'] = []
        m['radii'] = []
        path = os.path.join(self.tmp.name, 'partial.json')
        with open(path, 'w') as f:
            json.dump(m, f)
        r = self.fidelity(ids['rootId'], '--json', manifest=path)
        g = json.loads(r.stdout)['gaps']
        for k in ('missing copy', 'invented copy', 'off-manifest radii'):
            self.assertEqual(g[k], [], k)
        self.assertTrue(g['off-manifest spacing'])

    def test_missing_node_and_bad_manifest_exit_2(self):
        self.build(False)
        r = self.fidelity('9:999')
        self.assertEqual(r.returncode, 2)
        self.assertIn('9:999', r.stderr)
        bad = os.path.join(self.tmp.name, 'bad.json')
        with open(bad, 'w') as f:
            f.write('not json')
        r = self.fidelity('1:1', manifest=bad)
        self.assertEqual(r.returncode, 2)
        self.assertIn('bad.json', r.stderr)

    def test_one_eval_per_check(self):
        ids = self.build(True)
        log = os.path.join(self.tmp.name, 'calls.jsonl')
        stop_daemon(self.sock)
        self.env['PERCH_STUB_LOG'] = log
        self.env['FIGMA_PERCH_SOCK'] = os.path.join(self.tmp.name, 'd2.sock')
        self.sock = self.env['FIGMA_PERCH_SOCK']
        self.fidelity(ids['rootId'])
        with open(log) as f:
            evals = [l for l in f if '"eval_js"' in l]
        self.assertEqual(len(evals), 1)


if __name__ == '__main__':
    unittest.main()
