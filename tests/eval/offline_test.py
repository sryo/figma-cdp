#!/usr/bin/env python3
"""Offline tests for the eval harness: no Figma, no API.

Seeds, scorers and harness ops run through the real figma_run.py → figma_perch.mjs daemon
path against tests/perch_stub with PERCH_STUB_FIGMA=full (tests/figma_stub.js's Plugin API),
so state persists across calls as it does in a Figma tab. Each scorer must pass a hand-built
good state (offline/<task>_good.js) and fail a bad one (offline/<task>_bad.js).

  python3 tests/eval/offline_test.py
"""
import json, os, re, shutil, socket, subprocess, sys, tempfile, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import compare, run, session  # noqa: E402

FILE = 'https://www.figma.com/design/AAA111/Stub'
RECON_ANSWER = ('Onboarding / Step 1 is 375x812 with 3 text layers, Onboarding / Step 2 is 375x812 with 2, '
                'and Paywall is 390x844 with 4.')


def stub_env(sock):
    return {'FIGMA_BACKEND': 'perch', 'PERCH_DIR': os.path.join(ROOT, 'tests', 'perch_stub'), 'PERCH_STUB_FIGMA': 'full',
            'FIGMA_PERCH_SOCK': sock, 'FIGMA_PERCH_DAEMON': '1'}


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


class StubFigma(unittest.TestCase):
    """One stub document per test, kept by a private daemon."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = os.path.join(self.tmp.name, 'd.sock')
        self.saved = {k: os.environ.get(k) for k in stub_env('')}
        for k in ('FIGMA_FILE', 'FIGMA_PERCH_TAB', 'FIGMA_CDP_PORT'):
            os.environ.pop(k, None)
        os.environ.update(stub_env(self.sock))
        self.a = types.SimpleNamespace(file=FILE, tab=None)
        with open(os.path.join(HERE, 'fixtures', 'expect.json')) as f:
            self.expect = json.load(f)

    def tearDown(self):
        stop_daemon(self.sock)
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def figma(self, rel, ctx):
        return run.figma(rel, ctx, self.a, self.tmp.name)

    def scored(self, task_id, state, rep=1):
        """setup → seed → state → score → cleanup for one task; the scorer's output."""
        with open(os.path.join(HERE, 'tasks', f'{task_id}.json')) as f:
            task = json.load(f)
        ctx = {'task': task_id, 'rep': rep, 'prefix': f'eval/{task_id}/{rep}', 'expect': self.expect}
        ctx.update(self.figma('ops/setup.js', ctx))
        ctx['seed'] = self.figma(task['seed'], ctx) if task.get('seed') else {}
        if state:
            self.figma(f'offline/{state}.js', ctx)
        ctx['answer'] = RECON_ANSWER if task_id == 'recon' and state != 'recon_bad' else ''
        out = self.figma(task['score'], ctx)
        left = self.figma('ops/cleanup.js', ctx)
        self.assertGreaterEqual(left['pages'], 1)
        return out


class Scorers(StubFigma):
    def check(self, task_id, prefix=None):
        prefix = prefix or task_id.replace('-', '_')
        good = self.scored(task_id, f'{prefix}_good')
        bad = self.scored(task_id, f'{prefix}_bad')
        self.assertTrue(good['passed'], json.dumps(good['metrics']))
        self.assertFalse(bad['passed'], json.dumps(bad['metrics']))
        return good['metrics'], bad['metrics']

    def test_reuse(self):
        g, b = self.check('reuse')
        self.assertEqual((g['buttonInstances'], g['inputInstances'], g['newDuplicateComponents']), (2, 2, 0))
        self.assertEqual(g['copy'], 1)
        self.assertEqual(g['onPalette'], 1)
        self.assertEqual(b['buttonInstances'] + b['inputInstances'], 0)
        self.assertGreaterEqual(b['newDuplicateComponents'], 1)
        self.assertLess(b['copy'], g['copy'])
        self.assertLess(b['onPalette'], 1)
        self.assertGreater(b['defaultNames'], g['defaultNames'])
        self.assertGreater(b['detachedLike'], g['detachedLike'])
        self.assertLess(b['boundPaintShare'], g['boundPaintShare'])

    def test_componentize(self):
        g, b = self.check('componentize')
        self.assertEqual((g['rowsInstanced'], g['rowComponents'], g['rawRows'], g['stateMatch'], g['onOffVariant']), (1, 1, 0, 1, 1))
        self.assertEqual((b['rowsInstanced'], b['rawRows'], b['onOffVariant']), (0, 5, 0))
        self.assertEqual(b['stateMatch'], 1, 'raw rows still read their state from the toggle color')
        self.assertLess(b['instanceRatio'], g['instanceRatio'])

    def test_variants(self):
        g, b = self.check('variants')
        self.assertEqual((g['coverage'], g['axesMatch'], g['labelProperty'], g['variantAutoLayout'], g['colorMatch']), (1, 1, 1, 1, 1))
        self.assertEqual(g['variantCount'], 4)
        self.assertEqual((b['axesMatch'], b['labelProperty']), (0, 0))
        self.assertLess(b['coverage'], 1)
        self.assertLess(b['variantAutoLayout'], 1)

    def test_layout(self):
        g, b = self.check('layout')
        for k in ('headerAutoLayout', 'gridAutoLayout', 'cardReuse', 'badgeConstrained', 'autoLayoutShare', 'copy'):
            self.assertEqual(g[k], 1, k)
        self.assertEqual(g['absoluteStacks'], 0)
        self.assertEqual(g['sizingShare'], 1)
        self.assertEqual((b['headerAutoLayout'], b['gridAutoLayout'], b['cardReuse'], b['badgeConstrained']), (0, 0, 0, 0))
        self.assertGreater(b['absoluteStacks'], 0)

    def test_fidelity_edit(self):
        g, b = self.check('fidelity-edit')
        for k in ('copyFixed', 'fontKept', 'colorFixed', 'missingAdded', 'idsPreserved', 'copy'):
            self.assertEqual(g[k], 1, k)
        self.assertEqual(g['newTopLevel'], 0)
        self.assertEqual(b['idsPreserved'], 0)
        untouched = self.scored('fidelity-edit', None)
        self.assertFalse(untouched['passed'])
        m = untouched['metrics']
        self.assertEqual((m['copyFixed'], m['colorFixed'], m['missingAdded'], m['idsPreserved']), (0, 0, 0, 1))

    def test_recon(self):
        g = self.scored('recon', None)
        self.assertTrue(g['passed'], g)
        self.assertEqual((g['metrics']['mutated'], g['metrics']['answerTextCounts']), (0, 1))
        b = self.scored('recon', 'recon_bad')
        self.assertFalse(b['passed'])
        self.assertEqual((b['metrics']['mutated'], b['metrics']['answerNames']), (1, 0))

    def test_effects(self):
        g, b = self.check('effects')
        self.assertEqual((g['dropShadow'], g['effectsKept']), (1, 1))
        self.assertEqual((b['dropShadow'], b['effectsKept']), (1, 0))

    def test_capture(self):
        self.check('capture')

    def test_scripts_measure_with_a_private_figma_lib(self):
        os.makedirs(os.path.join(self.tmp.name, 'src'))
        newer, probe = (os.path.join(self.tmp.name, 'src', n) for n in ('newer.js', 'probe.js'))
        with open(newer, 'w') as f:
            f.write('window.__fx = { v: 1e9, measure: null, DEFAULT_NAME: null }; return 1;')
        with open(probe, 'w') as f:
            f.write('return [typeof FX.measure, DEFAULT_NAME instanceof RegExp, window.__fx.v];')
        self.figma(newer, {})
        self.assertEqual(self.figma(probe, {}), ['function', True, 1e9],
                         "a newer __fx in the tab (the skill under test's) must not change what scorers measure")

    def test_every_task_has_offline_states(self):
        for f in os.listdir(os.path.join(HERE, 'tasks')):
            with open(os.path.join(HERE, 'tasks', f)) as fh:
                t = json.load(fh)
            self.assertEqual(f, t['id'] + '.json')
            for k in ('prompt', 'score', 'covers'):
                self.assertIn(k, t)
            for ph in ('{FILE_URL}', '{PAGE}'):
                self.assertIn(ph, t['prompt'], t['id'])
            for rel in (t['score'], t.get('seed')):
                if rel:
                    self.assertTrue(os.path.isfile(os.path.join(HERE, rel)), rel)
            self.assertTrue(os.path.isfile(os.path.join(HERE, 'offline', t['id'].replace('-', '_') + '_bad.js')), t['id'])

    def test_setup_clears_leftovers_and_cleanup_removes_variables(self):
        ctx = {'task': 'reuse', 'rep': 1, 'prefix': 'eval/reuse/1', 'expect': self.expect}
        ctx.update(self.figma('ops/setup.js', ctx))
        ctx['seed'] = self.figma('seeds/reuse.js', ctx)
        again = self.figma('ops/setup.js', ctx)
        self.assertEqual(again['cleared'], 2, 'the page and its library page')
        ctx.update(again)
        self.figma('seeds/reuse.js', ctx)
        out = self.figma('ops/cleanup.js', ctx)
        self.assertEqual(out, {'pages': 2, 'collections': 1})


class Fixture(unittest.TestCase):
    def test_expect_json_matches_the_fixture_source(self):
        with open(os.path.join(HERE, 'fixtures', 'expect.json')) as f:
            e = json.load(f)
        app = os.path.join(HERE, 'fixtures', 'app')
        src = ''
        for f in sorted(os.listdir(app)):
            with open(os.path.join(app, f)) as fh:
                src += fh.read()
        with open(os.path.join(app, 'tokens.css')) as fh:
            tokens = fh.read()
        for k, hexv in e['colors'].items():
            self.assertIn(f'--color-{k}: {hexv};', tokens, k)
        strings = (e['login']['copy'] + e['settings']['copy'] + [r[k] for r in e['settings']['rows'] for k in ('label', 'hint')]
                   + e['products']['nav'] + [c[k] for c in e['products']['cards'] for k in ('title', 'price', 'cta')])
        for s in strings:
            self.assertIn(s, src)
        for screen in ('login', 'settings', 'products', 'button'):
            for k in e[screen]['colors']:
                self.assertIn(k, e['colors'])
        with open(os.path.join(app, 'settings.html')) as fh:
            rows = re.findall(r'settings-row__label">([^<]+)<.*?aria-checked="(true|false)"', fh.read(), re.S)
        self.assertEqual([(r['label'], r['on']) for r in e['settings']['rows']], [(l, v == 'true') for l, v in rows])


class Compare(unittest.TestCase):
    def result(self, **tasks):
        out = {'meta': {'file': 'K', 'model': ''}, 'cost_metrics': run.COST, 'tasks': {}}
        for t, reps in tasks.items():
            out['tasks'][t] = run.summarize(reps)
        return out

    def rep(self, passed=True, wall=100.0, tokens=1000, copy=1.0, dupes=0):
        return {'passed': passed, 'wall_s': wall, 'tokens_total': tokens, 'copy': copy,
                'newDuplicateComponents': dupes, 'lower': ['newDuplicateComponents']}

    def verdicts(self, base, cand, floor=0.10):
        return {(t, m): v for t, m, _, _, _, v in compare.compare(base, cand, floor)}

    def test_same_results_are_not_a_regression(self):
        b = self.result(reuse=[self.rep(), self.rep()])
        self.assertFalse([v for v in self.verdicts(b, b).values() if v != 'ok'])

    def test_quality_drop_of_any_size_regresses(self):
        b = self.result(reuse=[self.rep()])
        c = self.result(reuse=[self.rep(copy=0.99)])
        self.assertEqual(self.verdicts(b, c)[('reuse', 'copy')], 'worse')

    def test_lower_is_better_metrics_flip_direction(self):
        b = self.result(reuse=[self.rep()])
        self.assertEqual(self.verdicts(b, self.result(reuse=[self.rep(dupes=1)]))[('reuse', 'newDuplicateComponents')], 'worse')
        self.assertEqual(self.verdicts(self.result(reuse=[self.rep(dupes=1)]), b)[('reuse', 'newDuplicateComponents')], 'better')

    def test_cost_noise_within_floor_is_ok(self):
        b = self.result(reuse=[self.rep(wall=100)])
        self.assertEqual(self.verdicts(b, self.result(reuse=[self.rep(wall=109)]))[('reuse', 'wall_s')], 'ok')
        self.assertEqual(self.verdicts(b, self.result(reuse=[self.rep(wall=111)]))[('reuse', 'wall_s')], 'worse')
        self.assertEqual(self.verdicts(b, self.result(reuse=[self.rep(wall=80)]))[('reuse', 'wall_s')], 'better')

    def test_cost_tolerance_widens_with_rep_spread(self):
        b = self.result(reuse=[self.rep(wall=60), self.rep(wall=100), self.rep(wall=140)])
        c = self.result(reuse=[self.rep(wall=135)])
        self.assertEqual(self.verdicts(b, c)[('reuse', 'wall_s')], 'ok', 'baseline spread 80 → tolerance 40')
        c = self.result(reuse=[self.rep(wall=141)])
        self.assertEqual(self.verdicts(b, c)[('reuse', 'wall_s')], 'worse')

    def test_pass_rate_drop_and_missing_task_regress(self):
        b = self.result(reuse=[self.rep(), self.rep()], recon=[self.rep()])
        c = self.result(reuse=[self.rep(), self.rep(passed=False)])
        v = self.verdicts(b, c)
        self.assertEqual(v[('reuse', 'pass_rate')], 'worse')
        self.assertEqual(v[('recon', '*')], 'missing')

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            b, c = os.path.join(d, 'b.json'), os.path.join(d, 'c.json')
            with open(b, 'w') as f:
                json.dump(self.result(reuse=[self.rep()]), f)
            with open(c, 'w') as f:
                json.dump(self.result(reuse=[self.rep(tokens=2000)]), f)
            cmd = [sys.executable, os.path.join(HERE, 'compare.py')]
            self.assertEqual(subprocess.run(cmd + [b, b], capture_output=True).returncode, 0)
            r = subprocess.run(cmd + [b, c], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn('tokens_total', r.stdout)
            self.assertEqual(subprocess.run(cmd + [b, os.path.join(d, 'nope.json')], capture_output=True).returncode, 2)


class Stream(unittest.TestCase):
    def test_parse_counts_subagents_and_sums_models(self):
        out = subprocess.run([sys.executable, os.path.join(HERE, 'offline', 'fake_claude.py'), '-p',
                              '/figma-eval:figma-cdp x', '--plugin-dir', ROOT + '/tests/eval/offline/plugin_absent'],
                             capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0, 'fake_claude checks the wrapper exists')
        with tempfile.TemporaryDirectory() as d:
            plugin = session.make_plugin(ROOT, d)
            r = subprocess.run([sys.executable, os.path.join(HERE, 'offline', 'fake_claude.py')] +
                               session.command('claude', plugin, 'x')[1:], capture_output=True, text=True,
                               env=session.clean_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        m, text = session.parse_stream(r.stdout.splitlines())
        self.assertEqual((m['tool_calls'], m['failed_tool_calls'], m['turns']), (3, 1, 4))
        self.assertEqual((m['input_tokens'], m['output_tokens'], m['cache_read_tokens'], m['cache_write_tokens']), (110, 55, 1000, 200))
        self.assertEqual(m['tokens_total'], 1365)
        self.assertEqual((m['cost_usd'], m['session_error'], m['skill_listed']), (0.5, False, True))
        self.assertEqual(text, 'Done.')

    def test_no_result_event_is_a_session_error(self):
        m, _ = session.parse_stream(['{"type":"system","subtype":"init","skills":[]}', 'not json'])
        self.assertTrue(m['session_error'])
        self.assertFalse(m['skill_listed'])

    def test_clean_env_drops_host_session_vars(self):
        saved = dict(os.environ)
        try:
            os.environ.update(CLAUDECODE='1', CLAUDE_CODE_SESSION_ID='s', CLAUDE_CODE_OAUTH_TOKEN='t')
            e = session.clean_env()
            self.assertNotIn('CLAUDECODE', e)
            self.assertNotIn('CLAUDE_CODE_SESSION_ID', e)
            self.assertEqual(e['CLAUDE_CODE_OAUTH_TOKEN'], 't')
        finally:
            os.environ.clear()
            os.environ.update(saved)


class RunEndToEnd(StubFigma):
    """run.py with the fake claude: recon passes (the fake answers it right and changes
    nothing), fidelity-edit fails (the fake fixes nothing), pages go away unless --keep."""

    def run_py(self, *args):
        out = os.path.join(self.tmp.name, 'out.json')
        r = subprocess.run([sys.executable, os.path.join(HERE, 'run.py'), '--file', FILE, '--claude',
                            os.path.join(HERE, 'offline', 'fake_claude.py'), '--out', out, *args],
                           capture_output=True, text=True, env=os.environ)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out) as f:
            return json.load(f), r.stderr

    def pages(self):
        path = os.path.join(self.tmp.name, 'pages.js')
        with open(path, 'w') as f:
            f.write('figma.root.children.map(function (p) { return p.name; })')
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_run.py'), path], capture_output=True, text=True)
        return json.loads(r.stdout)

    def test_two_tasks_two_reps(self):
        out, log = self.run_py('--tasks', 'recon,fidelity-edit', '--reps', '2')
        self.assertEqual(out['meta']['reps'], 2)
        self.assertEqual(out['cost_metrics'], run.COST)
        recon, fid = out['tasks']['recon'], out['tasks']['fidelity-edit']
        self.assertEqual(recon['pass_rate'], 1, recon['reps'])
        self.assertEqual(fid['pass_rate'], 0)
        self.assertEqual(recon['median']['tokens_total'], 1365)
        self.assertEqual(recon['median']['failed_tool_calls'], 1)
        self.assertEqual(recon['median']['mutated'], 0)
        self.assertEqual(fid['median']['idsPreserved'], 1)
        self.assertIn('newTopLevel', fid['lower'])
        self.assertEqual(len(fid['reps']), 2)
        self.assertIn('recon 2/2', log)
        self.assertEqual(self.pages(), ['Page 1'])

    def test_keep_leaves_the_pages(self):
        self.run_py('--tasks', 'effects', '--reps', '1', '--keep')
        self.assertEqual(self.pages(), ['Page 1', 'eval/effects/1'])

    def test_seed_failure_is_recorded_not_raised(self):
        os.environ['PERCH_STUB_ERROR'] = 'timeout: stub'
        try:
            out, _ = self.run_py('--tasks', 'recon', '--reps', '1')
        finally:
            os.environ.pop('PERCH_STUB_ERROR')
        rep = out['tasks']['recon']['reps'][0]
        self.assertFalse(rep['passed'])
        self.assertIn('setup', rep['error'])


@unittest.skipUnless(shutil.which(os.environ.get('CLAUDE_BIN', 'claude')) and not os.environ.get('EVAL_SKIP_PROBE'),
                     'needs the claude CLI (EVAL_SKIP_PROBE=1 skips)')
class SkillDirProbe(unittest.TestCase):
    """The real CLI, a fake Messages API: the session loads the --skill-dir copy only."""

    def test_probe(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, 'session.py'), 'probe'], capture_output=True, text=True,
                           timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
