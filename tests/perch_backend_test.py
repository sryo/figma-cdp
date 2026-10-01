#!/usr/bin/env python3
"""Offline tests for the perch backend of figma_run.py / figma_batch_run.py.

No browser and no perch: PERCH_DIR points at tests/perch_stub, whose server.js
runs each script in Node against a stub `figma` global.

  python3 tests/perch_backend_test.py
"""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUB = os.path.join(ROOT, 'tests', 'perch_stub')
TWO_FILES = [
    {'app': 'Google Chrome', 'tabId': 'chrome:1', 'url': 'https://www.figma.com/design/AAA111/One', 'title': 'One – Figma'},
    {'app': 'Google Chrome', 'tabId': 'chrome:2', 'url': 'https://www.figma.com/design/BBB222/Two?node-id=1-2', 'title': 'Two – Figma'},
    {'app': 'Google Chrome', 'tabId': 'chrome:3', 'url': 'https://www.figma.com/design/BBB222/Two', 'title': 'Two – Figma', 'active': True},
    {'app': 'Google Chrome', 'tabId': 'chrome:4', 'url': 'https://example.com/figma.com/design/CCC333', 'title': 'Not Figma'},
]


class PerchBackend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, 'calls.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def js(self, name, src):
        path = os.path.join(self.tmp.name, name)
        with open(path, 'w') as f:
            f.write(src)
        return path

    def run_helper(self, script, *args, **env):
        e = {**os.environ, 'FIGMA_BACKEND': 'perch', 'PERCH_DIR': STUB, 'PERCH_STUB_LOG': self.log}
        for k in ('FIGMA_FILE', 'FIGMA_PERCH_TAB', 'PERCH_STUB_TABS', 'PERCH_STUB_FIGMA', 'PERCH_STUB_ERROR'):
            e.pop(k, None)
        e.update(env)
        return subprocess.run([sys.executable, os.path.join(ROOT, script), *args],
                              capture_output=True, text=True, env=e)

    def calls(self, name=None):
        try:
            with open(self.log) as f:
                rows = [json.loads(line) for line in f]
        except OSError:
            return []
        return [r for r in rows if name is None or r['name'] == name]

    # ---- figma_run.py

    def test_expression_result_matches_agent_browser_output(self):
        r = self.run_helper('figma_run.py', self.js('a.js', 'figma.currentPage.name'))
        self.assertEqual((r.returncode, r.stdout), (0, '"Page 1"\n'), r.stderr)
        ev = self.calls('eval_js')[0]['args']
        self.assertEqual((ev['world'], ev['awaitPromise'], ev['target']), ('main', True, {'tabId': 'chrome:1'}))

    def test_statements_and_async_iife(self):
        r = self.run_helper('figma_run.py', self.js('a.js', 'const n = 2;\n(async () => {\n'
                            '  await figma.loadAllPagesAsync();\n'
                            '  return { pages: figma.root.children.map(p => p.name), n };\n})()'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'pages': ['Page 1', 'Page 2'], 'n': 2})
        self.assertIn('\n  "pages"', r.stdout)

    def test_undefined_completion_is_null(self):
        r = self.run_helper('figma_run.py', self.js('a.js', 'void 0'))
        self.assertEqual(r.stdout, 'null\n')

    def test_throw_reports_evaluation_error(self):
        r = self.run_helper('figma_run.py', self.js('a.js', 'throw new Error("Node not found")'))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.startswith('✗ Evaluation error: Error: Node not found'), r.stderr)
        self.assertNotIn('open and close', r.stderr)

    def test_rejected_promise_reports_evaluation_error(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '(async () => { throw new TypeError("bad"); })()'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('TypeError: bad', r.stderr)

    def test_figma_undefined_points_at_the_plugin_fix(self):
        r = self.run_helper('figma_run.py', self.js('a.js', 'figma.currentPage.name'), PERCH_STUB_FIGMA='0')
        self.assertEqual(r.returncode, 1)
        self.assertIn('open and close any Figma plugin once', r.stderr)

    def test_typeof_figma_undefined_is_a_result_not_an_error(self):
        r = self.run_helper('figma_run.py', self.js('a.js', 'typeof figma'), PERCH_STUB_FIGMA='0')
        self.assertEqual((r.returncode, r.stdout), (0, '"undefined"\n'))

    def test_large_result_round_trips(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '"x".repeat(3_000_000)'))
        self.assertEqual(r.returncode, 0, r.stderr[:300])
        self.assertEqual(len(json.loads(r.stdout)), 3_000_000)

    def test_payload_over_cdp_cap_runs_on_perch(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '/*' + 'p' * 300_000 + '*/ 1'))
        self.assertEqual((r.returncode, r.stdout), (0, '1\n'), r.stderr[:300])

    def test_perch_error_code_passes_through(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'),
                            PERCH_STUB_ERROR='timeout: eval_js (world main) timed out after 30000ms')
        self.assertEqual(r.returncode, 1)
        self.assertIn('perch: timeout: eval_js', r.stderr)
        self.assertIn('perch caps an eval at 30s', r.stderr)

    def test_missing_js_file(self):
        r = self.run_helper('figma_run.py', os.path.join(self.tmp.name, 'nope.js'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('no such file', r.stderr)
        self.assertEqual(self.calls(), [])

    # ---- tab choice

    def test_several_files_need_file(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), PERCH_STUB_TABS=json.dumps(TWO_FILES))
        self.assertEqual(r.returncode, 1)
        self.assertIn('ambiguous_tab', r.stderr)
        self.assertIn('AAA111 (One – Figma)', r.stderr)
        self.assertEqual(self.calls('eval_js'), [])

    def test_file_url_picks_its_tab_preferring_the_shown_one(self):
        r = self.run_helper('figma_run.py', '--file', 'https://www.figma.com/design/BBB222/Two?node-id=9-9',
                            self.js('a.js', '1'), PERCH_STUB_TABS=json.dumps(TWO_FILES))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls('eval_js')[0]['args']['target'], {'tabId': 'chrome:3'})

    def test_file_key_from_env(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'),
                            PERCH_STUB_TABS=json.dumps(TWO_FILES), FIGMA_FILE='AAA111')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls('eval_js')[0]['args']['target'], {'tabId': 'chrome:1'})

    def test_no_tab_for_file(self):
        r = self.run_helper('figma_run.py', '--file', 'ZZZ999', self.js('a.js', '1'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('no_tab', r.stderr)

    def test_pinned_tab_skips_listing(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), FIGMA_PERCH_TAB='canary:42')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls('list_tabs'), [])
        self.assertEqual(self.calls('eval_js')[0]['args']['target'], {'tabId': 'canary:42'})

    # ---- screenshot

    def test_screenshot_writes_png(self):
        out = os.path.join(self.tmp.name, 'shot.png')
        r = self.run_helper('figma_run.py', '--screenshot', out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, 'rb') as f:
            self.assertEqual(f.read(8), b'\x89PNG\r\n\x1a\n')
        self.assertEqual(self.calls('screenshot')[0]['args']['target'], {'tabId': 'chrome:1'})

    # ---- figma_batch_run.py

    def test_batch_runs_in_order_sharing_state(self):
        paths = [self.js('1.js', 'window.__batchState = { n: 1 }; "set"'),
                 self.js('2.js', 'throw new Error("mid")'),
                 self.js('3.js', '({ n: window.__batchState.n + 1 })')]
        r = self.run_helper('figma_batch_run.py', *paths)
        self.assertEqual(r.returncode, 1)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[:4], ['== 1.js ==', '{"origin": "https://www.figma.com", "result": "set"}',
                                     '== 2.js ==', 'Evaluation error: Error: mid'])
        self.assertEqual(lines[-2:], ['== 3.js ==', '{"origin": "https://www.figma.com", "result": {"n": 2}}'])
        self.assertEqual(len(self.calls('list_tabs')), 1)
        self.assertEqual(len(self.calls('eval_js')), 3)

    def test_batch_all_ok_exits_zero(self):
        r = self.run_helper('figma_batch_run.py', self.js('1.js', '1'), self.js('2.js', '2'))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_batch_perch_failure_stops_and_says_where(self):
        r = self.run_helper('figma_batch_run.py', self.js('1.js', '1'), self.js('2.js', '2'),
                            PERCH_STUB_ERROR='stale_tab: the tab closed')
        self.assertEqual(r.returncode, 1)
        self.assertIn('perch: stale_tab', r.stderr)

    # ---- backend choice

    def test_unknown_backend(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), FIGMA_BACKEND='ws')
        self.assertEqual(r.returncode, 1)
        self.assertIn("FIGMA_BACKEND must be 'cdp' or 'perch'", r.stderr)

    def test_auto_picks_perch_when_it_has_main_world(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '"auto"'), FIGMA_BACKEND='')
        self.assertEqual((r.returncode, r.stdout), (0, '"auto"\n'), r.stderr)

    def test_auto_keeps_cdp_when_its_port_is_set(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), FIGMA_BACKEND='', FIGMA_CDP_PORT='9',
                            PATH=self.tmp.name)
        self.assertEqual(r.returncode, 1)
        self.assertIn('agent-browser not found', r.stderr)
        self.assertEqual(self.calls(), [])

    def test_auto_falls_back_to_cdp_without_perch(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), FIGMA_BACKEND='',
                            PERCH_DIR=os.path.join(self.tmp.name, 'none'), PATH=self.tmp.name)
        self.assertEqual(r.returncode, 1)
        self.assertIn('agent-browser not found', r.stderr)

    def test_perch_without_main_world_is_named(self):
        old = os.path.join(self.tmp.name, 'oldperch')
        os.makedirs(old)
        with open(os.path.join(old, 'server.js'), 'w') as f:
            f.write('export async function handleCall() {}\n')
        with open(os.path.join(old, 'package.json'), 'w') as f:
            f.write('{"type":"module"}')
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), PERCH_DIR=old)
        self.assertEqual(r.returncode, 1)
        self.assertIn('no_perch', r.stderr)
        self.assertIn('world:"main"', r.stderr)


if __name__ == '__main__':
    unittest.main()
