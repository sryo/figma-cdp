#!/usr/bin/env python3
"""Offline tests for the perch backend of figma_run.py / figma_batch_run.py / figma_capture.py.

No browser and no perch: PERCH_DIR points at tests/perch_stub, whose server.js
runs each script in Node against a stub `figma` global.

  python3 tests/perch_backend_test.py
"""
import ast, json, os, shutil, socket, stat, subprocess, sys, tempfile, threading, time, unittest

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

    def test_runs_from_a_directory_reached_through_a_symlink(self):
        # macOS's /tmp, where the skill copies the helpers, is a symlink to /private/tmp.
        real = os.path.join(self.tmp.name, 'real')
        os.makedirs(real)
        for name in ('figma_run.py', 'figma_perch.mjs'):
            shutil.copy(os.path.join(ROOT, name), real)
        link = os.path.join(self.tmp.name, 'link')
        os.symlink(real, link)
        r = subprocess.run([sys.executable, os.path.join(link, 'figma_run.py'), self.js('a.js', '"linked"')],
                           capture_output=True, text=True, env=self.helper_env({}))
        self.assertEqual((r.returncode, r.stdout), (0, '"linked"\n'), r.stderr)

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


PNG_1PX = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
SPEC = {
    'meta': {'url': 'https://example.com/', 'title': 'T', 'viewport': {'w': 400, 'h': 300}, 'dpr': 1, 'nodeCount': 4},
    'flagged': [],
    'assets': {'a1': {'kind': 'image', 'mime': 'image/png', 'b64': PNG_1PX, 'w': 1, 'h': 1}},
    'nodes': [
        {'i': 0, 'parent': -1, 'tag': 'html', 'rect': {'x': 0, 'y': 0, 'w': 400, 'h': 300}, 'text': '', 'kids': 1,
         'role': None, 'axName': None},
        {'i': 1, 'parent': 0, 'tag': 'body', 'rect': {'x': 0, 'y': 0, 'w': 400, 'h': 300}, 'text': '', 'kids': 2,
         'role': None, 'axName': None},
        {'i': 2, 'parent': 1, 'tag': 'p', 'rect': {'x': 8, 'y': 8, 'w': 100, 'h': 20}, 'text': 'Hello ñ', 'lines': 1,
         'role': 'paragraph', 'axName': None},
        {'i': 3, 'parent': 1, 'tag': 'img', 'rect': {'x': 8, 'y': 40, 'w': 50, 'h': 50}, 'text': '',
         'image': {'asset': 'a1', 'mode': 'FILL'}, 'role': 'img', 'axName': 'pic'},
    ],
}
# Stands in for figma_walker.js, which needs a DOM the stub doesn't have.
FAKE_WALKER = """// a DOM-free walker
(async function () {
  await new Promise(function (r) { setTimeout(r, 5); });
  if (location.pathname.indexOf('boom') >= 0) throw new Error('boom');
  if (location.pathname.indexOf('empty') >= 0) return { meta: {} };
  return { meta: { url: location.href, title: 'Stub page', viewport: { w: 400, h: 300 }, dpr: 1, nodeCount: 1 },
           flagged: [{ i: 0, reason: 'grid' }], assets: { a1: { kind: 'svg', svg: '<svg/>', w: 1, h: 1 } },
           nodes: [{ i: 0, parent: -1, tag: 'html', rect: { x: 0, y: 0, w: 400, h: 300 }, text: 'ñ' }] };
})();
"""


class CapturePerch(Harness):
    """figma_capture.py on the perch backend: walk in a background tab, import as one perch request."""

    def setUp(self):
        super().setUp()
        # walk runs the figma_walker.js next to figma_capture.py, so this copy gets the DOM-free one.
        self.app = os.path.join(self.tmp.name, 'app')
        os.makedirs(self.app)
        for name in ('figma_capture.py', 'figma_perch.mjs', 'figma_importer.js'):
            shutil.copy(os.path.join(ROOT, name), self.app)
        with open(os.path.join(self.app, 'figma_walker.js'), 'w') as f:
            f.write(FAKE_WALKER)
        self.outs = []

    def tearDown(self):
        for path in self.outs:
            try:
                os.unlink(path)
            except OSError:
                pass
        super().tearDown()

    def capture(self, *args, **env):
        return subprocess.run([sys.executable, os.path.join(self.app, 'figma_capture.py'), *args],
                              capture_output=True, text=True, env=self.helper_env(env))

    def walk(self, path, *args, **env):
        tag = f'{path}-{os.getpid()}-{id(self)}'
        out = f'/tmp/figma_capture_example-com-{tag}.json'
        self.outs.append(out)
        url = f'https://example.com/{tag}'
        return url, out, self.capture('walk', url, *args, **env)

    def spec(self, spec=SPEC):
        return self.js('spec.json', json.dumps(spec))

    # ---- walk

    def test_walk_runs_the_walker_in_a_background_tab_and_closes_it(self):
        url, out, r = self.walk('page', '0')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f'spec: {out}\nnodes: 1  flagged: 1  assets: 1\n')
        with open(out) as f:
            spec = json.load(f)
        self.assertEqual((spec['meta']['url'], spec['nodes'][0]['text']), (url, 'ñ'))
        self.assertEqual([c['name'] for c in self.calls()], ['new_tab', 'wait', 'eval_js', 'close_tab'])
        self.assertEqual(self.calls('new_tab')[0]['args'], {'url': url})
        ev = self.calls('eval_js')[0]['args']
        tab = ev['target']['tabId']
        self.assertEqual((ev['world'], ev['awaitPromise'], ev['timeout']), ('main', True, 120000))
        self.assertEqual(self.calls('wait')[0]['args']['target'], {'tabId': tab})
        self.assertEqual(self.calls('close_tab')[0]['args'], {'tabId': tab})

    def test_walk_waits_for_the_page_not_the_new_tabs_blank_document(self):
        # A new tab reports the initial about:blank as readyState complete before the URL commits.
        url, out, r = self.walk('page', '0')
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out) as f:
            self.assertEqual(json.load(f)['meta']['url'], url)

    def test_walk_waits_the_settle_time(self):
        t = time.monotonic()
        _, _, r = self.walk('settle', '400')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreaterEqual(time.monotonic() - t, 0.4)

    def test_walk_timeout_reaches_eval_js(self):
        _, _, r = self.walk('page', '0', '--timeout', '30')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls('eval_js')[0]['args']['timeout'], 30000)

    def test_walker_throw_is_reported_and_the_tab_closed(self):
        _, out, r = self.walk('boom', '0')
        self.assertEqual(r.returncode, 1)
        self.assertIn('figma_capture.py: walker failed — Error: boom', r.stderr)
        self.assertNotIn('open and close any Figma plugin', r.stderr)
        self.assertEqual(len(self.calls('close_tab')), 1)
        self.assertFalse(os.path.exists(out))

    def test_walker_result_without_nodes_is_refused(self):
        _, _, r = self.walk('empty', '0')
        self.assertEqual(r.returncode, 1)
        self.assertIn('walker result missing nodes', r.stderr)

    def test_walk_perch_failure_is_reported_and_the_tab_closed(self):
        _, _, r = self.walk('page', '0', PERCH_STUB_ERROR='timeout: eval_js (world main) timed out after 120000ms')
        self.assertEqual(r.returncode, 1)
        self.assertIn('figma_capture.py: walker failed — timeout: eval_js', r.stderr)
        self.assertEqual(len(self.calls('close_tab')), 1)

    def test_walk_url_perch_refuses_runs_nothing(self):
        r = self.capture('walk', 'ftp://example.com/x', '0')
        self.assertEqual(r.returncode, 1)
        self.assertIn('bad_url', r.stderr)
        self.assertEqual(self.calls('eval_js'), [])

    def test_real_walker_parses_as_the_page_script(self):
        prog = ('import { wrapExpr } from %s; import { readFileSync } from "node:fs";\n'
                'new (Object.getPrototypeOf(async function () {}).constructor)(wrapExpr(readFileSync(%s, "utf8")));\n'
                'console.info("ok");') % (json.dumps('file://' + os.path.join(ROOT, 'figma_perch.mjs')),
                                          json.dumps(os.path.join(ROOT, 'figma_walker.js')))
        r = subprocess.run(['node', '--input-type=module', '-e', prog], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stderr), (0, 'ok\n'))

    # ---- import

    def test_import_runs_every_eval_in_one_request_and_prints_the_report(self):
        dry = os.path.join(self.tmp.name, 'dry')
        self.assertEqual(self.capture('import', self.spec(), '--dry-run', dry).returncode, 0)
        n = len(os.listdir(dry))
        r = self.capture('import', self.spec(), PERCH_STUB_FIGMA='full')
        self.assertEqual(r.returncode, 0, r.stderr)
        body, summary = r.stdout.rstrip('\n').rsplit('\n', 1)
        rep = json.loads(body)
        self.assertEqual(body, json.dumps(rep, indent=1))
        self.assertEqual((rep['created'], rep['batchDone'], rep['warnings']), (4, 4, []))
        self.assertEqual(summary, 'created=4 flagged=0 fontsFallenBack=0 instantiated=0 warnings=0')
        self.assertEqual(len(self.calls('eval_js')), n)
        self.assertEqual(len(self.calls('list_tabs')), 1)
        self.assertEqual({c['args']['target']['tabId'] for c in self.calls('eval_js')}, {'chrome:1'})

    def test_import_targets_the_named_file(self):
        r = self.capture('import', self.spec(), '--file', 'BBB222', PERCH_STUB_FIGMA='full',
                         PERCH_STUB_TABS=json.dumps(TWO_FILES))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({c['args']['target']['tabId'] for c in self.calls('eval_js')}, {'chrome:3'})
        r = self.capture('import', self.spec(), PERCH_STUB_FIGMA='full', PERCH_STUB_TABS=json.dumps(TWO_FILES))
        self.assertEqual(r.returncode, 1)
        self.assertIn('ambiguous_tab', r.stderr)

    def test_import_stops_at_the_first_failing_eval(self):
        big = dict(SPEC, nodes=[dict(n, axName='x' * 100_000) if n['i'] >= 2 else n for n in SPEC['nodes']])
        dry = os.path.join(self.tmp.name, 'dry')
        self.assertEqual(self.capture('import', self.spec(big), '--dry-run', dry).returncode, 0)
        kinds = sorted(os.listdir(dry))
        first = next(i for i, k in enumerate(kinds) if '_nodes-' in k)
        self.assertGreater(len(kinds), first + 1)
        r = self.capture('import', self.spec(big), PERCH_STUB_FIGMA='0')
        self.assertEqual(r.returncode, 1)
        self.assertIn(f'figma_capture.py: eval {first} ({kinds[first][3:-3]}) failed — ReferenceError: figma is not defined',
                      r.stderr)
        self.assertEqual(len(self.calls('eval_js')), first + 1)

    def test_stop_ends_the_run_at_a_result_capture_treats_as_failure(self):
        for first in ('({ error: "spec missing" })', 'undefined'):
            os.unlink(self.log) if os.path.exists(self.log) else None
            req = {'op': 'eval', 'paths': [self.js('a.js', first), self.js('b.js', '1')], 'stop': True}
            r = subprocess.run(['node', os.path.join(self.app, 'figma_perch.mjs'), 'call', json.dumps(req)],
                               capture_output=True, text=True, env=self.helper_env({}))
            self.assertEqual(len(json.loads(r.stdout)['results']), 1, r.stdout)
            self.assertEqual(len(self.calls('eval_js')), 1, first)

    def test_import_perch_failure_names_the_eval(self):
        r = self.capture('import', self.spec(), PERCH_STUB_ERROR='stale_tab: the tab closed')
        self.assertEqual(r.returncode, 1)
        self.assertIn('figma_capture.py: eval 0 (reset) failed — stale_tab: the tab closed', r.stderr)

    def test_import_has_no_eval_ceiling_on_perch(self):
        huge = dict(SPEC, nodes=[dict(n, text='y' * 400_000) if n['i'] == 2 else n for n in SPEC['nodes']])
        r = self.capture('import', self.spec(huge), PERCH_STUB_FIGMA='full')
        self.assertEqual(r.returncode, 0, r.stderr[:400])
        self.assertIn('created=4 ', r.stdout)

    # ---- backend choice

    def test_capture_follows_the_helpers_backend_choice(self):
        r = self.capture('import', self.spec(), FIGMA_BACKEND='ws')
        self.assertEqual(r.returncode, 1)
        self.assertIn("FIGMA_BACKEND must be 'cdp' or 'perch'", r.stderr)
        for env in ({'FIGMA_BACKEND': 'cdp'}, {'FIGMA_BACKEND': '', 'FIGMA_CDP_PORT': '9'},
                    {'FIGMA_BACKEND': '', 'PERCH_DIR': os.path.join(self.tmp.name, 'none')}):
            r = self.capture('walk', 'https://example.com/x', '0', PATH=self.tmp.name, **env)
            self.assertEqual(r.returncode, 1)
            self.assertIn('agent-browser not found', r.stderr)
        self.assertEqual(self.calls(), [])
        _, _, r = self.walk('auto', '0', FIGMA_BACKEND='')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_perch_client_matches_the_helpers(self):
        """figma_capture.py carries its own copy of the helpers' perch client; the copies stay identical."""
        shared = ('perch_dir', 'perch_ready', 'backend', 'js_int', 'Dropped', 'daemon_sock', 'daemon_exchange',
                  'start_daemon', 'timeout_seconds')

        def defs(name):
            with open(os.path.join(ROOT, name)) as f:
                tree = ast.parse(f.read())
            return {d.name: ast.dump(d) for d in tree.body if isinstance(d, (ast.FunctionDef, ast.ClassDef))}

        cap, run, batch = defs('figma_capture.py'), defs('figma_run.py'), defs('figma_batch_run.py')
        for name in shared:
            self.assertEqual(cap.get(name), batch[name], name)
            self.assertEqual(run[name], batch[name], name)


class CapturePerchOneShot(CapturePerch):
    daemon = '0'


if __name__ == '__main__':
    unittest.main()
