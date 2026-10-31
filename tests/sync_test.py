#!/usr/bin/env python3
"""Offline tests for figma_sync.py. Figma is tests/figma_stub.js behind tests/perch_stub (the real
figma_run.py → figma_perch.mjs daemon path, so the stub document lives across calls), seeded by
tests/design/seed_vars.js. git and gh are tests/sync_stub's loggers: git runs the real git against a
scratch repo whose origin is a local bare repo; gh keeps pull requests in a JSON file.

  python3 tests/sync_test.py
"""
import http.server, json, os, shutil, subprocess, sys, tempfile, threading, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGN = os.path.join(ROOT, 'tests', 'design')
STUBS = os.path.join(ROOT, 'tests', 'sync_stub')
FILE = 'https://www.figma.com/design/AAA111/Stub'
DATE = '2026-10-31'
BRANCH = f'design-sync/{DATE}'
sys.path.insert(0, os.path.join(ROOT, 'tests'))
from fidelity_test import stop_daemon

SNAPSHOT = r'''
(async function () {
  var cols = await figma.variables.getLocalVariableCollectionsAsync(), vars = await figma.variables.getLocalVariablesAsync();
  return { pages: figma.root.children.map(function (p) { return p.name; }),
    cols: cols.map(function (c) { return { name: c.name, vars: vars.filter(function (v) { return v.variableCollectionId === c.id; })
      .map(function (v) { return [v.name, JSON.stringify(v.valuesByMode[c.defaultModeId])]; }) }; }) };
})()
'''


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.sock = os.path.join(t, 'd.sock')
        self.log = os.path.join(t, 'calls.jsonl')
        self.gh_state = os.path.join(t, 'prs.json')
        git = shutil.which('git')
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ('FIGMA_FILE', 'FIGMA_PERCH_TAB', 'FIGMA_CDP_PORT', 'PERCH_STUB_ERROR', 'PERCH_STUB_TABS', 'FIGMA_TOKEN',
                                 'FIGMA_API_URL', 'GIT_DIR', 'GIT_WORK_TREE')}
        self.env.update(FIGMA_BACKEND='perch', PERCH_DIR=os.path.join(ROOT, 'tests', 'perch_stub'), PERCH_STUB_FIGMA='full',
                        FIGMA_PERCH_SOCK=self.sock, FIGMA_PERCH_DAEMON='1', FIGMA_CDP_JOURNAL='0',
                        PATH=STUBS + os.pathsep + os.environ['PATH'], SYNC_REAL_GIT=git, SYNC_STUB_LOG=self.log,
                        GH_STUB_STATE=self.gh_state, GIT_AUTHOR_NAME='T', GIT_AUTHOR_EMAIL='t@example.com',
                        GIT_COMMITTER_NAME='T', GIT_COMMITTER_EMAIL='t@example.com', GIT_CONFIG_GLOBAL=os.devnull)
        self.origin = os.path.join(t, 'origin.git')
        self.repo = os.path.join(t, 'repo')
        real = lambda *a, cwd=t: subprocess.run([git, *a], cwd=cwd, capture_output=True, text=True, check=True, env=self.env).stdout
        real('init', '-q', '--bare', '-b', 'next', self.origin)
        real('init', '-q', '-b', 'next', self.repo)
        for f in ('DESIGN.md', 'tokens.css'):
            shutil.copy(os.path.join(DESIGN, f), self.repo)
        real('add', 'DESIGN.md', 'tokens.css', cwd=self.repo)
        real('commit', '-q', '-m', 'start', cwd=self.repo)
        real('remote', 'add', 'origin', self.origin, cwd=self.repo)
        real('push', '-q', 'origin', 'next', cwd=self.repo)
        real('remote', 'set-head', 'origin', 'next', cwd=self.repo)
        self.git = real
        self.figma(path=os.path.join(DESIGN, 'seed_vars.js'))

    def tearDown(self):
        stop_daemon(self.sock)
        self.tmp.cleanup()

    def figma(self, script=None, path=None, **env):
        cmd = [sys.executable, os.path.join(ROOT, 'figma_run.py'), '--file', FILE] + ([path] if path else ['-e', script])
        r = subprocess.run(cmd, capture_output=True, text=True, env={**self.env, **env})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def sync(self, *args, **env):
        open(self.log, 'w').close()
        return subprocess.run([sys.executable, os.path.join(ROOT, 'figma_sync.py'), *args, '--repo', self.repo, '--file', FILE,
                               '--date', DATE], capture_output=True, text=True, env={**self.env, **env})

    def calls(self, cmd, *head):
        with open(self.log) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        args = [r['args'][2:] if r['args'][:1] == ['-C'] else r['args'] for r in rows if r['cmd'] == cmd]
        return [a for a in args if a[:len(head)] == list(head)]

    def repo_state(self):
        return (self.git('status', '--porcelain', '--untracked-files=all', cwd=self.repo), self.git('rev-parse', 'HEAD', cwd=self.repo),
                self.git('branch', '--list', '--all', cwd=self.repo), self.git('worktree', 'list', '--porcelain', cwd=self.repo),
                self.git('for-each-ref', cwd=self.origin), self.read(os.path.join(self.repo, 'DESIGN.md')))

    def read(self, path):
        with open(path) as f:
            return f.read()

    # ---- report

    def test_report_writes_nothing(self):
        before, figma_before = self.repo_state(), self.figma(SNAPSHOT)
        r = self.sync('report')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('variables: 4 drift', r.stdout)
        self.assertIn('check: 0 drift', r.stdout)
        self.assertIn('different Lede/light colors/ink', r.stdout)
        self.assertEqual(self.repo_state(), before)
        self.assertEqual(self.figma(SNAPSHOT), figma_before)
        self.assertEqual(self.calls('gh'), [])
        for args in self.calls('git'):
            self.assertNotIn(args[0], ('add', 'commit', 'push', 'worktree', 'branch', 'checkout', 'switch', 'reset'), args)

    def test_report_without_a_file_checks_code_only(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_sync.py'), 'report', '--repo', self.repo],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('check: 0 drift', r.stdout)
        self.assertIn('figma: skipped', r.stdout)

    def test_signed_out_names_the_fix(self):
        tabs = [{'app': 'room:main', 'tabId': 'room:main:R2', 'url': 'https://www.figma.com/login?cont=%2Fdesign%2FAAA111', 'title': 'Login'}]
        other = os.path.join(self.tmp.name, 'e.sock')
        r = self.sync('report', PERCH_STUB_TABS=json.dumps(tabs), FIGMA_PERCH_SOCK=other)
        stop_daemon(other)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn('signed_out', r.stderr)
        self.assertIn('fix: rooms signin main https://www.figma.com/login', r.stderr)

    def test_plugin_not_ready_names_the_fix(self):
        r = self.sync('report', PERCH_STUB_FIGMA='0', FIGMA_PERCH_SOCK=os.path.join(self.tmp.name, 'e.sock'))
        stop_daemon(os.path.join(self.tmp.name, 'e.sock'))
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn('fix: open and close any Figma plugin once', r.stderr)

    # ---- propose --to code

    def pushes(self):
        return self.calls('git', 'push')

    def test_propose_to_code_opens_one_pr_from_its_own_branch(self):
        user = self.repo_state()
        r = self.sync('propose', '--to', 'code')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pushes = self.pushes()
        self.assertEqual(len(pushes), 1, pushes)
        self.assertTrue(any(BRANCH in a for a in pushes[0]), pushes)
        self.assertFalse(any(a in ('next', 'HEAD:next', 'refs/heads/next') or a.endswith(':refs/heads/next') for a in pushes[0]), pushes)
        self.assertFalse(any(a.startswith(('-f', '--force', '+')) for a in pushes[0]), pushes)
        creates = self.calls('gh', 'pr', 'create')
        self.assertEqual(len(creates), 1)
        self.assertEqual((creates[0][creates[0].index('--base') + 1], creates[0][creates[0].index('--head') + 1]), ('next', BRANCH))
        self.assertEqual(self.git('diff', '--name-only', 'next', BRANCH, cwd=self.origin).split(), ['DESIGN.md'])
        diff = self.git('diff', 'next', BRANCH, cwd=self.origin)
        self.assertIn('+  ink: "#000000"', diff)
        self.assertIn('+  old: "#ffffff"', diff)
        self.assertEqual(self.git('rev-parse', 'next', cwd=self.origin), user[1], 'the base is never pushed')
        self.assertEqual(self.repo_state()[0], user[0], "the user's checkout is untouched")
        self.assertEqual(self.repo_state()[5], user[5])
        self.assertIn('https://github.com/o/r/pull/1', r.stdout)
        msg = self.git('log', '-1', '--format=%B', BRANCH, cwd=self.origin)
        self.assertNotIn('Co-Authored-By', msg)

    def test_second_run_updates_the_open_pr(self):
        self.assertEqual(self.sync('propose', '--to', 'code').returncode, 0)
        self.figma("(async function(){ var v = (await figma.variables.getLocalVariablesAsync()).find(function (v) { return v.name === 'colors/primary'; });"
                   " v.setValueForMode('m1', {r: 0.0667, g: 0.0667, b: 0.0667, a: 1}); return 1; })()")
        r = self.sync('propose', '--to', 'code', '--date', '2026-11-02')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pushes = self.pushes()
        self.assertEqual(len(pushes), 1, pushes)
        self.assertTrue(any(BRANCH in a for a in pushes[0]), 'pushes to the open PR branch, not a new one')
        self.assertEqual(self.calls('gh', 'pr', 'create'), [])
        self.assertEqual(len(self.calls('gh', 'pr', 'edit')), 1)
        self.assertEqual(self.calls('gh', 'pr', 'edit')[0][2], '1')
        self.assertIn('+  primary: "#111111"', self.git('diff', 'next', BRANCH, cwd=self.origin))
        self.assertEqual(self.git('rev-list', '--count', f'next..{BRANCH}', cwd=self.origin).strip(), '2')

    def test_no_figma_drift_proposes_nothing(self):
        clean = os.path.join(self.tmp.name, 'clean.js')
        with open(clean, 'w') as f:
            f.write("(async function(){ var vars = await figma.variables.getLocalVariablesAsync(), cols = await figma.variables.getLocalVariableCollectionsAsync();"
                    " var light = cols.find(function (c) { return c.name === 'Lede/light'; });"
                    " vars.forEach(function (v) { if (v.name === 'colors/ink' && v.variableCollectionId === light.id) v.setValueForMode('m1', {r: 0x1a/255, g: 0x1d/255, b: 0x2e/255, a: 1});"
                    " if (v.name === 'colors/old') v.remove(); }); return 1; })()")
        self.figma(path=clean)
        r = self.sync('propose', '--to', 'code')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('nothing to propose', r.stdout)
        self.assertEqual(self.pushes(), [])
        self.assertEqual(self.calls('gh'), [])

    # ---- propose --to figma

    def test_propose_to_figma_writes_a_proposed_page_and_one_comment(self):
        posts = []

        class Api(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                posts.append((self.path, self.headers.get('X-Figma-Token'), body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"id": "c1"}')

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Api)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        before = self.figma(SNAPSHOT)
        try:
            r = self.sync('propose', '--to', 'figma', FIGMA_TOKEN='figd_test', FIGMA_API_URL=f'http://127.0.0.1:{srv.server_port}')
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = self.figma(SNAPSHOT)
        self.assertIn(f'Proposed {DATE}', after['pages'])
        cols = {c['name']: dict(c['vars']) for c in after['cols']}
        for c in before['cols']:
            self.assertEqual(cols[c['name']], dict(c['vars']), 'the live collections are not applied to')
        light = cols[f'Proposed {DATE}/Lede/light']
        self.assertEqual(set(light), {'colors/ink', 'spacing/gap'})
        self.assertEqual(json.loads(light['spacing/gap']), 16)
        self.assertEqual(set(cols[f'Proposed {DATE}/Lede/dark']), {'colors/ink'})
        self.assertIn('version', r.stdout)
        self.assertEqual(len(posts), 1)
        path, token, body = posts[0]
        self.assertEqual((path, token), ('/v1/files/AAA111/comments', 'figd_test'))
        self.assertIn('node_id', body['client_meta'])
        self.assertIn(f'Proposed {DATE}', body['message'])
        self.assertEqual(self.calls('git', 'push'), [])

    def test_propose_to_figma_without_a_token_skips_the_comment(self):
        r = self.sync('propose', '--to', 'figma')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('comment: skipped (no FIGMA_TOKEN)', r.stdout)


if __name__ == '__main__':
    unittest.main()
