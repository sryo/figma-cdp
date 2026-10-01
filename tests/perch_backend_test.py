#!/usr/bin/env python3
"""Offline tests for the perch backend of figma_run.py / figma_batch_run.py.

No browser and no perch: PERCH_DIR points at tests/perch_stub, whose server.js
runs each script in Node against a stub `figma` global.

  python3 tests/perch_backend_test.py
"""
import json, os, socket, stat, subprocess, sys, tempfile, threading, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUB = os.path.join(ROOT, 'tests', 'perch_stub')
TWO_FILES = [
    {'app': 'Google Chrome', 'tabId': 'chrome:1', 'url': 'https://www.figma.com/design/AAA111/One', 'title': 'One – Figma'},
    {'app': 'Google Chrome', 'tabId': 'chrome:2', 'url': 'https://www.figma.com/design/BBB222/Two?node-id=1-2', 'title': 'Two – Figma'},
    {'app': 'Google Chrome', 'tabId': 'chrome:3', 'url': 'https://www.figma.com/design/BBB222/Two', 'title': 'Two – Figma', 'active': True},
    {'app': 'Google Chrome', 'tabId': 'chrome:4', 'url': 'https://example.com/figma.com/design/CCC333', 'title': 'Not Figma'},
]


def stop_daemon(sock):
    """Ask the daemon on sock to exit; False when none answered."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(5)
        s.connect(sock)
        f = s.makefile('rb')
        f.readline()
        s.sendall(b'{"op":"stop"}\n')
        f.read()
        return True
    except OSError:
        return False
    finally:
        s.close()


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Harness(unittest.TestCase):
    daemon = '1'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, 'calls.jsonl')
        self.sock = os.path.join(self.tmp.name, 'd.sock')

    def tearDown(self):
        stop_daemon(self.sock)
        self.tmp.cleanup()

    def js(self, name, src):
        path = os.path.join(self.tmp.name, name)
        with open(path, 'w') as f:
            f.write(src)
        return path

    def popen_helper(self, script, *args, **env):
        e = self.helper_env(env)
        return subprocess.Popen([sys.executable, os.path.join(ROOT, script), *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e)

    def run_helper(self, script, *args, **env):
        return subprocess.run([sys.executable, os.path.join(ROOT, script), *args],
                              capture_output=True, text=True, env=self.helper_env(env))

    def helper_env(self, env):
        e = {**os.environ, 'FIGMA_BACKEND': 'perch', 'PERCH_DIR': STUB, 'PERCH_STUB_LOG': self.log,
             'FIGMA_PERCH_SOCK': self.sock, 'FIGMA_PERCH_DAEMON': self.daemon}
        for k in ('FIGMA_FILE', 'FIGMA_PERCH_TAB', 'PERCH_STUB_TABS', 'PERCH_STUB_FIGMA', 'PERCH_STUB_ERROR',
                  'PERCH_STUB_TABS_FILE', 'PERCH_STUB_DELAY', 'FIGMA_PERCH_IDLE', 'FIGMA_TIMEOUT',
                  'FIGMA_TIMEOUT_MS', 'PERCH_STUB_OLD'):
            e.pop(k, None)
        e.update(env)
        return e

    def calls(self, name=None):
        try:
            with open(self.log) as f:
                rows = [json.loads(line) for line in f]
        except OSError:
            return []
        return [r for r in rows if name is None or r['name'] == name]



class PerchBackend(Harness):
    """Every test runs through the daemon here and through one-shot runs in PerchBackendOneShot."""

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

    def test_output_matches_agent_browser_print(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '({ z: 1, a: { d: [], c: {} }, s: "ñ 😀", '
                            'tiny: 1e-7, big: 1e21, huge: 12345678901234567890, f: 0.5 })'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, '{\n  "a": {\n    "c": {},\n    "d": []\n  },\n  "big": 1e+21,\n  "f": 0.5,\n'
                         '  "huge": 1.2345678901234567e+19,\n  "s": "ñ 😀",\n  "tiny": 1e-7,\n  "z": 1\n}\n')

    def test_batch_output_matches_agent_browser_print(self):
        r = self.run_helper('figma_batch_run.py', self.js('a.js', '({ z: 1, a: ["ñ", 1e-7] })'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[1], '{"origin": "https://www.figma.com/design/AAA111/Stub?node-id=0-1", '
                         '"result": {"a": ["\\u00f1", 1e-07], "z": 1}}')

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

    # ---- await timeout

    def eval_timeouts(self):
        return [c['args'].get('timeout') for c in self.calls('eval_js')]

    def test_default_timeout_is_two_minutes(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.eval_timeouts(), [120000])

    def test_timeout_is_honoured(self):
        slow = self.js('a.js', 'new Promise(r => setTimeout(() => r("late"), 1500))')
        r = self.run_helper('figma_run.py', '--timeout', '1', slow)
        self.assertEqual(r.returncode, 1)
        self.assertIn('perch: timeout: eval_js (world main) timed out after 1000ms', r.stderr)
        self.assertIn('ran past the 1s it was given (--timeout or FIGMA_TIMEOUT', r.stderr)
        r = self.run_helper('figma_run.py', '--timeout', '3', slow)
        self.assertEqual((r.returncode, r.stdout), (0, '"late"\n'), r.stderr)
        self.assertEqual(self.eval_timeouts(), [1000, 3000])

    def test_timeout_from_env_and_flag_wins(self):
        self.run_helper('figma_run.py', self.js('a.js', '1'), FIGMA_TIMEOUT='45')
        self.run_helper('figma_run.py', '--timeout', '2.5', self.js('a.js', '1'), FIGMA_TIMEOUT='45')
        self.run_helper('figma_batch_run.py', '--timeout', '7', self.js('a.js', '1'), self.js('b.js', '2'))
        self.assertEqual(self.eval_timeouts(), [45000, 2500, 7000, 7000])

    def test_timeout_is_clamped_to_1_to_300_seconds(self):
        for v in ('0.2', '0', '-5', '900', '300'):
            r = self.run_helper('figma_run.py', '--timeout', v, self.js('a.js', '1'))
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.eval_timeouts(), [1000, 1000, 1000, 300000, 300000])

    def test_bad_timeout_is_refused_before_running(self):
        for flag, env in ((['--timeout', 'abc'], {}), ([], {'FIGMA_TIMEOUT': 'nan'}), (['--timeout', 'inf'], {})):
            r = self.run_helper('figma_run.py', *flag, self.js('a.js', '1'), **env)
            self.assertEqual(r.returncode, 1)
            self.assertIn('--timeout / FIGMA_TIMEOUT is seconds, 1 to 300', r.stderr)
        r = self.run_helper('figma_batch_run.py', '--timeout', 'soon', self.js('a.js', '1'))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.calls('eval_js'), [])

    def test_older_perch_gets_no_timeout_and_says_so(self):
        r = self.run_helper('figma_run.py', '--timeout', '1', self.js('a.js', 'new Promise(r => setTimeout(r, 30))'),
                            PERCH_STUB_OLD='1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.eval_timeouts(), [None])
        stop_daemon(self.sock)  # a daemon keeps the environment it started with
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), PERCH_STUB_OLD='1',
                            PERCH_STUB_ERROR='timeout: eval_js (world main) timed out after 30000ms')
        self.assertIn('This perch awaits at most 30s; update perch', r.stderr)

    def test_perch_error_code_passes_through(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'),
                            PERCH_STUB_ERROR='timeout: eval_js (world main) timed out after 30000ms')
        self.assertEqual(r.returncode, 1)
        self.assertIn('perch: timeout: eval_js', r.stderr)
        self.assertIn('ran past the 120s it was given', r.stderr)

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
        url = 'https://www.figma.com/design/AAA111/Stub?node-id=0-1'
        self.assertEqual(lines[:4], ['== 1.js ==', '{"origin": "%s", "result": "set"}' % url,
                                     '== 2.js ==', 'Evaluation error: Error: mid'])
        self.assertEqual(lines[-2:], ['== 3.js ==', '{"origin": "%s", "result": {"n": 2}}' % url])
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


class PerchBackendOneShot(PerchBackend):
    daemon = '0'


class PerchDaemon(Harness):
    """The daemon itself: start, reuse, idle exit, stale socket, concurrency, fallback, the cached tab."""

    def pids(self, name='eval_js'):
        return {c['pid'] for c in self.calls(name)}

    def tabs_file(self, rows):
        path = os.path.join(self.tmp.name, 'tabs.json')
        with open(path, 'w') as f:
            json.dump(rows, f)
        return path

    def test_first_call_starts_a_private_daemon(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '"hi"'), FIGMA_PERCH_SOCK='', TMPDIR=self.tmp.name)
        self.assertEqual((r.returncode, r.stdout), (0, '"hi"\n'), r.stderr)
        d = os.path.join(self.tmp.name, f'figma-perch-{os.getuid()}')
        socks = [n for n in os.listdir(d) if n.endswith('.sock')]
        self.assertEqual(len(socks), 1)
        self.sock = os.path.join(d, socks[0])
        self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.sock).st_mode), 0o600)
        pid = self.pids().pop()
        self.assertNotEqual(pid, os.getpid())
        self.assertTrue(alive(pid))

    def test_calls_reuse_one_daemon_and_its_tab(self):
        for i in range(3):
            r = self.run_helper('figma_run.py', '--file', 'AAA111', self.js('a.js', f'{i}'))
            self.assertEqual((r.returncode, r.stdout), (0, f'{i}\n'), r.stderr)
        self.assertEqual(len(self.pids()), 1)
        self.assertEqual(len(self.calls('list_tabs')), 1)

    def test_calls_without_a_file_list_tabs_each_time(self):
        for _ in range(2):
            self.assertEqual(self.run_helper('figma_run.py', self.js('a.js', '1')).returncode, 0)
        self.assertEqual(len(self.calls('list_tabs')), 2)
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), PERCH_STUB_TABS=json.dumps(TWO_FILES))
        self.assertEqual(len(self.pids('list_tabs')), 1)

    def test_daemon_exits_when_idle(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), FIGMA_PERCH_IDLE='0.3')
        self.assertEqual(r.returncode, 0, r.stderr)
        pid = self.pids().pop()
        deadline = time.monotonic() + 5
        while (alive(pid) or os.path.exists(self.sock)) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(alive(pid))
        self.assertFalse(os.path.exists(self.sock))
        r = self.run_helper('figma_run.py', self.js('a.js', '2'))
        self.assertEqual((r.returncode, r.stdout), (0, '2\n'), r.stderr)
        self.assertEqual(len(self.pids()), 2)

    def test_stale_socket_is_replaced(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(self.sock)
        s.close()
        self.assertTrue(os.path.exists(self.sock))
        r = self.run_helper('figma_run.py', self.js('a.js', '"fresh"'))
        self.assertEqual((r.returncode, r.stdout), (0, '"fresh"\n'), r.stderr)
        self.assertNotEqual(self.pids().pop(), os.getpid())

    def test_stale_regular_file_is_replaced(self):
        open(self.sock, 'w').close()
        r = self.run_helper('figma_run.py', self.js('a.js', '1'))
        self.assertEqual((r.returncode, r.stdout), (0, '1\n'), r.stderr)
        self.assertTrue(stat.S_ISSOCK(os.stat(self.sock).st_mode))

    def test_concurrent_clients_share_one_daemon(self):
        n = 8
        procs = [self.popen_helper('figma_run.py', '--file', 'AAA111', self.js(f'{i}.js', f'({{ i: {i} }})'),
                                   PERCH_STUB_DELAY='50') for i in range(n)]
        outs = [p.communicate(timeout=60) for p in procs]
        for i, (p, (out, err)) in enumerate(zip(procs, outs)):
            self.assertEqual((p.returncode, json.loads(out or 'null')), (0, {'i': i}), err)
        self.assertEqual(len(self.pids()), 1)
        self.assertEqual(len(self.calls('eval_js')), n)

    def test_falls_back_to_one_shot_when_the_daemon_cannot_start(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'),
                            FIGMA_PERCH_SOCK=os.path.join(self.tmp.name, 'missing', 'd.sock'))
        self.assertEqual((r.returncode, r.stdout), (0, '1\n'), r.stderr)
        r = self.run_helper('figma_run.py', self.js('a.js', '1'),
                            FIGMA_PERCH_SOCK=os.path.join(self.tmp.name, 'missing', 'd.sock'))
        self.assertEqual(len(self.pids()), 2)

    def test_daemon_that_fails_to_load_falls_back(self):
        old = os.path.join(self.tmp.name, 'broken')
        os.makedirs(old)
        with open(os.path.join(old, 'server.js'), 'w') as f:
            f.write('export const buildMainKick = 1; throw new Error("boom");\n')
        with open(os.path.join(old, 'package.json'), 'w') as f:
            f.write('{"type":"module"}')
        t = time.monotonic()
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), PERCH_DIR=old)
        self.assertEqual(r.returncode, 1)
        self.assertIn('boom', r.stderr)
        self.assertLess(time.monotonic() - t, 8)
        self.assertFalse(os.path.exists(self.sock))

    def test_disabled_daemon_leaves_no_socket(self):
        r = self.run_helper('figma_run.py', self.js('a.js', '1'), FIGMA_PERCH_DAEMON='0')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.sock))

    def test_cached_tab_that_left_the_file_is_not_run_there(self):
        tabs = self.tabs_file([{'tabId': 'chrome:1', 'url': 'https://www.figma.com/design/AAA111/One', 'title': 'One'}])
        script = self.js('a.js', 'globalThis.__runs = (globalThis.__runs || 0) + 1; [__runs, location.pathname]')
        r = self.run_helper('figma_run.py', '--file', 'AAA111', script, PERCH_STUB_TABS_FILE=tabs)
        self.assertEqual(json.loads(r.stdout), [1, '/design/AAA111/One'], r.stderr)
        self.tabs_file([{'tabId': 'chrome:1', 'url': 'https://www.figma.com/design/BBB222/Two', 'title': 'Two'},
                        {'tabId': 'chrome:5', 'url': 'https://www.figma.com/design/AAA111/One', 'title': 'One'}])
        r = self.run_helper('figma_run.py', '--file', 'AAA111', script, PERCH_STUB_TABS_FILE=tabs)
        self.assertEqual(json.loads(r.stdout), [2, '/design/AAA111/One'], r.stderr)
        self.assertEqual([c['args']['target']['tabId'] for c in self.calls('eval_js')], ['chrome:1', 'chrome:1', 'chrome:5'])
        self.assertEqual(len(self.calls('list_tabs')), 2)

    def test_cached_tab_that_closed_is_looked_up_again(self):
        tabs = self.tabs_file([{'tabId': 'chrome:1', 'url': 'https://www.figma.com/design/AAA111/One', 'title': 'One'}])
        self.assertEqual(self.run_helper('figma_run.py', '--file', 'AAA111', self.js('a.js', '1'),
                                         PERCH_STUB_TABS_FILE=tabs).returncode, 0)
        self.tabs_file([{'tabId': 'chrome:6', 'url': 'https://www.figma.com/design/AAA111/One', 'title': 'One'}])
        r = self.run_helper('figma_run.py', '--file', 'AAA111', self.js('a.js', '2'), PERCH_STUB_TABS_FILE=tabs)
        self.assertEqual((r.returncode, r.stdout), (0, '2\n'), r.stderr)
        self.assertEqual(self.calls('eval_js')[-1]['args']['target'], {'tabId': 'chrome:6'})

    def test_batch_stops_when_the_tab_leaves_the_file_mid_batch(self):
        tabs = self.tabs_file([{'tabId': 'chrome:1', 'url': 'https://www.figma.com/design/AAA111/One', 'title': 'One'}])
        moved = json.dumps([{'tabId': 'chrome:1', 'url': 'https://www.figma.com/design/BBB222/Two', 'title': 'Two'}])
        go = self.js('1.js', '(async () => { (await import("node:fs")).writeFileSync(%s, %s); return "moved"; })()'
                     % (json.dumps(tabs), json.dumps(moved)))
        r = self.run_helper('figma_batch_run.py', '--file', 'AAA111', go, self.js('2.js', 'globalThis.__ran2 = 1'),
                            PERCH_STUB_TABS_FILE=tabs)
        self.assertEqual(r.returncode, 1)
        self.assertIn('stale_tab: tab chrome:1 no longer shows file AAA111', r.stderr)
        self.assertIn('stopped after 1 of 2', r.stderr)

    def test_stop_lets_a_call_in_flight_finish(self):
        self.assertEqual(self.run_helper('figma_run.py', self.js('a.js', '0')).returncode, 0)
        pid = self.pids().pop()
        p = self.popen_helper('figma_run.py', self.js('b.js', '"slow"'), PERCH_STUB_DELAY='600')
        deadline = time.monotonic() + 5
        while len(self.calls('eval_js')) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(stop_daemon(self.sock))
        self.assertFalse(os.path.exists(self.sock))
        out, err = p.communicate(timeout=30)
        self.assertEqual((p.returncode, out), (0, '"slow"\n'), err)
        deadline = time.monotonic() + 5
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(alive(pid))

    def test_reply_line_is_enough_without_eof(self):
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock)
        srv.listen(1)
        held = []

        def serve():
            c, _ = srv.accept()
            held.append(c)
            c.sendall(b'{"perch_daemon":1,"pid":1}\n')
            c.makefile('rb').readline()
            c.sendall(json.dumps({'tab': {}, 'origin': 'https://www.figma.com',
                                  'results': [{'ok': True, 'value': 7, 'href': 'x'}]}).encode() + b'\n')

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        try:
            r = self.run_helper('figma_run.py', self.js('a.js', '7'))
            self.assertEqual((r.returncode, r.stdout), (0, '7\n'), r.stderr)
        finally:
            for c in held:
                c.close()
            srv.close()

    def test_a_call_the_daemon_dropped_is_not_rerun(self):
        r = self.run_helper('figma_run.py', self.js('a.js', 'process.exit(3)'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('perch_daemon: the daemon dropped the call', r.stderr)
        self.assertEqual(len(self.calls('eval_js')), 1)


if __name__ == '__main__':
    unittest.main()
