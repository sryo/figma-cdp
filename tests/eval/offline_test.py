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
import compare, run, session, source  # noqa: E402

FILE = 'https://www.figma.com/design/AAA111/Stub'
RECON_ANSWER = ('Onboarding / Step 1 is 375x812 with 3 text layers, Onboarding / Step 2 is 375x812 with 2, '
                'and Paywall is 390x844 with 4.')


def stub_env(sock):
    return {'FIGMA_BACKEND': 'perch', 'PERCH_DIR': os.path.join(ROOT, 'tests', 'perch_stub'), 'PERCH_STUB_FIGMA': 'full',
            'FIGMA_PERCH_SOCK': sock, 'FIGMA_PERCH_DAEMON': '1', 'FIGMA_CDP_JOURNAL': '0'}


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
        ctx = {'task': task_id, 'rep': rep, 'prefix': f'eval/{task_id}/{rep}', 'expect': source.expect_for(task)}
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

    APP_HIGHER = ('instanceShare', 'reusedComponentized', 'variantCoverage', 'variantMatch', 'nestedShare',
                  'listItemAvatarNested', 'sizingMatch', 'copy', 'autoLayoutShare')
    APP_LOWER = ('rawUsages', 'splitComponents', 'inventedCopy', 'hardcodedPaints')

    def test_app_screens(self):
        g, b = self.check('app-screens')
        for k in self.APP_HIGHER + ('screensFound', 'boundPaintShare'):
            self.assertEqual(g[k], 1, k)
        for k in ('rawUsages', 'missingUsages', 'splitComponents', 'unusedComponents', 'inventedCopy', 'hardcodedPaints'):
            self.assertEqual(g[k], 0, k)
        self.assertEqual(g['usages'], 81, 'every component usage in the three screens')
        self.assertEqual((b['instanceShare'], b['reusedComponentized'], b['variantCoverage'], b['nestedShare']), (0, 0, 0, 0))
        self.assertGreaterEqual(b['inventedCopy'], 3)
        self.assertLess(b['copy'], 0.95)
        self.assertGreater(b['defaultNames'], 20)
        self.assertLess(b['autoLayoutShare'], 0.5)

    def test_app_screens_grades_a_half_way_build_between(self):
        g = self.scored('app-screens', 'app_screens_good')['metrics']
        out = self.scored('app-screens', 'app_screens_mid')
        m, b = out['metrics'], self.scored('app-screens', 'app_screens_bad')['metrics']
        self.assertFalse(out['passed'], json.dumps(m))
        for k in self.APP_HIGHER:
            if k in ('autoLayoutShare',):
                continue
            self.assertLess(m[k], g[k], k)
            self.assertLessEqual(b[k], m[k], k)
        for k in self.APP_LOWER:
            self.assertGreater(m[k], g[k], k)
        self.assertGreater(m['splitComponents'], 0)
        self.assertEqual(m['listItemAvatarNested'], 0, 'the Avatar is drawn inside the row, not instanced')
        self.assertEqual(m['variantCoverage'] < 1 and m['variantCoverage'] > 0, True)
        self.assertEqual(m['inventedCopy'], 3, 'one made-up line per screen')

    def test_app_screens_ignores_layer_names(self):
        g = self.scored('app-screens', 'app_screens_good')['metrics']
        r = self.scored('app-screens', 'app_screens_renamed')['metrics']
        for k in self.APP_HIGHER + ('rawUsages', 'splitComponents', 'missingUsages', 'inventedCopy', 'unusedComponents'):
            self.assertEqual(r[k], g[k], k)
        self.assertGreater(r['defaultNames'], g['defaultNames'])

    def test_pattern_detect(self):
        g, b = self.check('pattern-detect')
        keys = ('newRowsInstanced', 'oldRowsLinked', 'rowSplit', 'newRawRows', 'rawRowCopies', 'headerInstanced',
                'headerLinked', 'oldCopyKept', 'copy', 'inventedCopy')
        self.assertEqual(tuple(g[k] for k in keys), (1, 1, 0, 0, 0, 1, 1, 1, 1, 0))
        self.assertEqual(tuple(b[k] for k in keys), (0, 0, 0, 4, 8, 0, 0, 1, 1, 0))
        out = self.scored('pattern-detect', 'pattern_detect_mid')
        m = out['metrics']
        self.assertTrue(out['passed'], 'new components, no raw copy: passes, graded below linking the old screen')
        self.assertEqual(tuple(m[k] for k in keys), (1, 0, 0, 0, 4, 1, 0, 1, 1, 0))
        untouched = self.scored('pattern-detect', None)
        self.assertFalse(untouched['passed'])
        self.assertEqual((untouched['metrics']['newRowsInstanced'], untouched['metrics']['oldCopyKept']), (0, 1))

    def test_responsive(self):
        g, b = self.check('responsive')
        keys = ('found', 'sizingMatch', 'maxWidth', 'wrap', 'paragraphResize', 'spaceBetween', 'spacerFrames', 'fabPinned',
                'sidebarWidth', 'copy')
        self.assertEqual(tuple(g[k] for k in keys), (1, 1, 1, 1, 1, 1, 0, 1, 1, 1))
        self.assertEqual((b['maxWidth'], b['wrap'], b['paragraphResize'], b['spaceBetween'], b['spacerFrames'], b['fabPinned']),
                         (0, 0, 0, 0, 1, 0))
        self.assertLess(b['sizingMatch'], 0.5)
        out = self.scored('responsive', 'responsive_mid')
        m = out['metrics']
        self.assertFalse(out['passed'])
        self.assertEqual((m['maxWidth'], m['wrap'], m['paragraphResize'], m['spaceBetween'], m['spacerFrames'], m['fabPinned']),
                         (0, 1, 1, 0, 1, 0))
        self.assertTrue(b['sizingMatch'] < m['sizingMatch'] < g['sizingMatch'], (b['sizingMatch'], m['sizingMatch']))

    def test_saturated_metrics_score_1_on_the_bad_state_too(self):
        """A task's "saturated" metrics are the ones that do not reward its good state over its bad one."""
        for t in ('reuse', 'componentize', 'variants'):
            with open(os.path.join(HERE, 'tasks', f'{t}.json')) as f:
                names = json.load(f)['saturated']
            g = self.scored(t, f'{t}_good')['metrics']
            b = self.scored(t, f'{t}_bad')['metrics']
            for k in names:
                self.assertEqual(b[k], 1, (t, k))
                self.assertLessEqual(g[k], b[k], (t, k))

    def test_every_task_has_offline_states(self):
        for f in os.listdir(os.path.join(HERE, 'tasks')):
            with open(os.path.join(HERE, 'tasks', f)) as fh:
                t = json.load(fh)
            self.assertEqual(f, t['id'] + '.json')
            for k in ('prompt', 'score', 'covers'):
                self.assertIn(k, t)
            for ph in ('{FILE_URL}', '{PAGE}'):
                self.assertIn(ph, t['prompt'], t['id'])
            if t.get('fixture'):
                self.assertTrue(os.path.isdir(os.path.join(HERE, 'fixtures', t['fixture'])), t['id'])
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

    def test_setup_resets_the_whole_scratch_file(self):
        """Whatever an earlier session left (pages, top-level nodes, variable collections) is gone,
        so every rep starts from the same empty file."""
        ctx = {'task': 'reuse', 'rep': 1, 'prefix': 'eval/reuse/1', 'expect': self.expect}
        self.figma('offline/leftovers.js', ctx)
        ctx.update(self.figma('ops/setup.js', ctx))
        left = self.figma('offline/file_state.js', ctx)
        self.assertEqual(left, {'pages': ['eval/reuse/1'], 'nodes': 0, 'collections': 0})


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


class HarborFixture(unittest.TestCase):
    """source.py's reading of the Harbor fixtures, which the app-screens, pattern-detect and
    responsive scorers rely on."""

    def walk(self, usages):
        for u in usages:
            yield u
            yield from self.walk(u['kids'])

    def screens(self):
        for name in ('harbor', 'harbor-pages'):
            e = source.load(name)
            for stem, s in e['screens'].items():
                with open(os.path.join(HERE, 'fixtures', name, s['file'])) as f:
                    yield e, stem, s, f.read()

    def test_usages_match_the_class_names_in_the_html(self):
        marks = dict(source.COMPONENTS, **source.ROLE_CLASSES)
        for e, stem, s, html in self.screens():
            self.assertTrue(s['title'], stem)
            found = {}
            for u in self.walk(s['usages']):
                found[u['c']] = found.get(u['c'], 0) + 1
            for cls, c in marks.items():
                n = len(re.findall(r'class="(?:[^"]*\s)?%s(?:\s[^"]*)?"' % re.escape(cls), html))
                self.assertEqual(found.get(c, 0), n, (stem, cls))

    def test_every_modifier_is_a_known_variant_value(self):
        for e, stem, s, html in self.screens():
            for cls in re.findall(r'class="([^"]+)"', html):
                for tok in cls.split():
                    if '--' not in tok:
                        continue
                    block, mod = tok.split('--', 1)
                    if block not in source.COMPONENTS:
                        continue
                    axes = source.AXES.get(source.COMPONENTS[block], {})
                    self.assertTrue(any(mod in a['values'] or (a.get('boolean') and mod == name) for name, a in axes.items()),
                                    (stem, tok))

    def test_sibling_usages_are_told_apart_by_their_strings(self):
        for e, stem, s, html in self.screens():
            def check(us):
                keyed = [u for u in us if u['c'] != 'Icon']
                for u in keyed:
                    self.assertTrue(u['key'], (stem, u['c']))
                sets = [(u['c'], tuple(sorted(u['texts']))) for u in keyed]
                self.assertEqual(len(sets), len(set(sets)), (stem, sets))
                for u in us:
                    check(u['kids'])
            check(s['usages'])

    def test_colors_come_from_the_tokens(self):
        e = source.load('harbor')
        self.assertEqual(e['colors'], source.load('harbor-pages')['colors'])
        css = ''
        for d, f in (('harbor', 'components.css'), ('harbor-pages', 'notes.html')):
            with open(os.path.join(HERE, 'fixtures', d, f)) as fh:
                css += fh.read()
        for k in set(re.findall(r'var\(--color-([a-z0-9-]+)\)', css)):
            self.assertIn(k, e['colors'])

    def test_paragraphs_and_roles(self):
        notes = source.load('harbor-pages')['screens']['notes']
        self.assertEqual(len(notes['paragraphs']), 3)
        roles = {u['c'] for u in self.walk(notes['usages'])} & set(source.ROLES)
        self.assertEqual(roles, set(source.ROLES) - {'paragraph'})


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

    def test_saturated_metrics_are_info_not_regressions(self):
        b = {'passed': True, 'sizingShare': 0.9}
        c = {'passed': True, 'sizingShare': 0.7}
        v = self.verdicts(self.result(componentize=[b]), self.result(componentize=[c]))
        self.assertEqual(v[('componentize', 'sizingShare')], 'info')

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

    def test_turns_count_every_model_response_workers_included(self):
        """One turn per assistant response, a worker's too, as tool_calls already counts; a message
        streamed in several events (one per content block) is one turn."""
        a = lambda mid, parent=None: json.dumps({'type': 'assistant', 'parent_tool_use_id': parent,
                                                 'message': {'id': mid, 'content': []}})
        res = json.dumps({'type': 'result', 'num_turns': 1, 'total_cost_usd': 1.0})
        m, _ = session.parse_stream([a('m1'), a('m1'), a('m2'), a('w1', 'toolu_1'), a('w2', 'toolu_1'), res])
        self.assertEqual(m['turns'], 4)

    def test_turns_fall_back_to_num_turns_without_message_ids(self):
        res = lambda turns: json.dumps({'type': 'result', 'num_turns': turns, 'total_cost_usd': 1.0})
        m, _ = session.parse_stream([res(10), res(1), res(3)])
        self.assertEqual(m['turns'], 14)

    def test_reparse_refreshes_session_metrics_and_keeps_scores(self):
        import reparse
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'layout-1.jsonl'), 'w') as f:
                f.write('\n'.join(json.dumps({'type': 'result', 'num_turns': n, 'total_cost_usd': 2.0}) for n in (10, 4)))  # no ids: num_turns
            res = {'tasks': {'layout': run.summarize([{'rep': 1, 'turns': 4, 'copy': 1, 'wall_s': 9, 'passed': True}])}}
            m = reparse.reparse(res, d)['tasks']['layout']['median']
            self.assertEqual((m['turns'], m['copy'], m['wall_s'], m['cost_usd']), (14, 1, 9, 2.0))

    def test_no_result_event_is_a_session_error(self):
        m, _ = session.parse_stream(['{"type":"system","subtype":"init","skills":[]}', 'not json'])
        self.assertTrue(m['session_error'])
        self.assertFalse(m['skill_listed'])

    def test_the_file_lock_ignores_tmpdir(self):
        """Callers in different sessions have different TMPDIRs and must still queue on one lock."""
        saved = os.environ.get('TMPDIR')
        try:
            os.environ['TMPDIR'] = tempfile.mkdtemp()
            tempfile.tempdir = None
            a = run.lock_path('K')
            os.environ['TMPDIR'] = tempfile.mkdtemp()
            tempfile.tempdir = None
            self.assertEqual(a, run.lock_path('K'))
        finally:
            if saved is None:
                os.environ.pop('TMPDIR', None)
            else:
                os.environ['TMPDIR'] = saved
            tempfile.tempdir = None

    def test_sessions_reach_figma_only_through_perch(self):
        """No CDP fallback: it can reach another browser's copy of the file, or the user's other files."""
        saved = dict(os.environ)
        try:
            os.environ.update(FIGMA_BACKEND='cdp', FIGMA_CDP_PORT='9222')
            e = run.session_env(types.SimpleNamespace(tab=None))
            self.assertEqual(e['FIGMA_BACKEND'], 'perch')
            self.assertNotIn('FIGMA_CDP_PORT', e)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_sessions_cannot_call_agent_browser(self):
        cmd = session.command('claude', '/p', 'x')
        self.assertEqual(cmd[cmd.index('--disallowedTools') + 1], 'Bash(agent-browser:*)')

    def test_two_tabs_on_the_file_need_an_explicit_tab(self):
        """Setup and the session could each land on a different tab, one of them out of date."""
        two = [{'tabId': 'arc:1'}, {'tabId': 'canary:2'}]
        self.assertIn('--tab', run.tab_problem(two, None))
        self.assertIsNone(run.tab_problem(two, 'arc:1'))
        self.assertIn('not open', run.tab_problem(two, 'arc:9'))
        self.assertIsNone(run.tab_problem([{'tabId': 'arc:1'}], None))
        self.assertIn('no tab', run.tab_problem([], None))

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

    def test_fixture_tasks_score_an_untouched_page(self):
        out, _ = self.run_py('--tasks', 'app-screens,pattern-detect,responsive', '--reps', '1')
        for t in ('app-screens', 'pattern-detect', 'responsive'):
            rep = out['tasks'][t]['reps'][0]
            self.assertNotIn('error', rep, t)
            self.assertFalse(rep['passed'], t)
        self.assertEqual(out['tasks']['pattern-detect']['median']['oldCopyKept'], 1)
        self.assertEqual(out['tasks']['app-screens']['median']['screensFound'], 0)
        self.assertEqual(self.pages(), ['Page 1'])

    def test_keep_leaves_the_pages(self):
        self.run_py('--tasks', 'effects', '--reps', '1', '--keep')
        self.assertEqual(self.pages(), ['eval/effects/1'])

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
