#!/usr/bin/env python3
"""Offline tests for figma_source.py: the source manifest extracted from the fixture app
(tests/eval/fixtures/app) and from small sources written per test.

  python3 tests/source_test.py
"""
import json, os, re, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'app')
with open(os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'expect.json')) as f:
    EXPECT = json.load(f)


def manifest(*paths, cwd=None):
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_source.py'), *paths],
                       capture_output=True, text=True, cwd=cwd)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def values(m, key):
    return {e['value'] for e in m[key]}


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.login = manifest(*(os.path.join(APP, f) for f in ('login.html', 'components.css', 'tokens.css')))
        cls.app = manifest(APP)

    def line_of(self, src):
        """The source line a `file:line` src points at."""
        f, n = src.rsplit(':', 1)
        with open(os.path.join(self.root, f)) as fh:
            return fh.read().splitlines()[int(n) - 1]

    root = APP

    def test_login_copy_is_exactly_what_the_page_shows(self):
        self.assertEqual(sorted(e['text'] for e in self.login['copy']), sorted(EXPECT['login']['copy']))

    def test_every_entry_cites_the_line_it_came_from(self):
        for e in self.app['copy']:
            self.assertIn(e['text'].split(' ')[0], self.line_of(e['src']), e)
        for t in self.app['tokens']:
            self.assertIn(t['name'], self.line_of(t['src']), t)
        for key in ('colors', 'spacing', 'radii', 'fontSizes', 'fontWeights', 'fontFamilies', 'variants', 'states'):
            for e in self.app[key]:
                self.assertRegex(e['src'], r'^[\w./-]+:\d+$', (key, e))

    def test_color_tokens_resolve_from_the_theme_file(self):
        tokens = {t['name']: t for t in self.app['tokens']}
        for k, hexv in EXPECT['colors'].items():
            t = tokens['--color-' + k]
            self.assertEqual((t['value'], t['kind']), (hexv, 'color'))
            self.assertTrue(t['src'].startswith('tokens.css:'))
        colors = {e['value']: e for e in self.app['colors']}
        self.assertEqual(set(colors), set(EXPECT['colors'].values()))
        self.assertEqual(colors['#4f46e5']['token'], '--color-primary')

    def test_scales_come_from_tokens_and_declarations(self):
        m = self.app
        self.assertLessEqual({4, 8, 12, 16, 24, 32}, values(m, 'spacing'))
        self.assertIn(80, values(m, 'spacing'), 'a literal margin in an inline style')
        self.assertIn(2, values(m, 'spacing'), 'a literal padding in the stylesheet')
        self.assertNotIn(240, values(m, 'spacing'), 'a width is not spacing')
        self.assertNotIn(0, values(m, 'spacing'), 'zero is always allowed, never listed')
        self.assertNotIn(1, values(m, 'spacing'), 'a border width is not spacing')
        self.assertEqual({6, 10, 999}, values(m, 'radii'))
        self.assertEqual({12, 14, 16, 20, 28}, values(m, 'fontSizes'))
        self.assertEqual({400, 500, 700}, values(m, 'fontWeights'))
        self.assertIn('Inter', values(m, 'fontFamilies'))
        sp = {e['value']: e for e in m['spacing']}
        self.assertEqual(sp[8]['token'], '--space-2')

    def test_variants_from_class_modifiers_and_prop_unions(self):
        groups = {(g['component'], g.get('prop')): g for g in self.app['variants']}
        css = [g for g in self.app['variants'] if g['component'] == 'button']
        self.assertTrue(css and set(css[0]['values']) >= {'primary', 'secondary'}, self.app['variants'])
        self.assertEqual(set(groups[('toggle', None)]['values']) if ('toggle', None) in groups else
                         set(next(g['values'] for g in self.app['variants'] if g['component'] == 'toggle')), {'on', 'off'})
        card = [g for g in self.app['variants'] if g['component'] == 'productcard']
        self.assertEqual((card[0]['prop'], card[0]['values']), ('soldOut', ['true', 'false']))
        self.assertTrue(card[0]['src'].startswith('components.jsx:'))

    def test_states_from_pseudo_classes_boolean_props_and_modifiers(self):
        states = {(s['component'], s['state']) for s in self.app['states']}
        self.assertIn(('button', 'disabled'), states)
        self.assertIn(('header__link', 'active'), states)
        self.assertFalse([g for g in self.app['variants'] if g['component'] == 'header__link'],
                         'a lone state-word modifier is a state, not a variant')
        srcs = [s['src'] for s in self.app['states'] if s['component'] == 'button']
        self.assertTrue(any(s.startswith('components.css:') for s in srcs) and any(s.startswith('components.jsx:') for s in srcs), srcs)

    def test_code_literals_give_copy_but_not_identifiers_or_class_lists(self):
        copy = {e['text'] for e in self.app['copy']}
        self.assertLessEqual({'Sold out', 'Add to cart', 'Orbit Headphones', '$129', 'Listening preferences'}, copy)
        for row in EXPECT['settings']['rows']:
            self.assertLessEqual({row['label'], row['hint']}, copy)
        for junk in ('primary', 'text', 'button button--primary', 'Sign in · Lumen', 'Cart', '🛒', 'Lumen UI components.'):
            self.assertNotIn(junk, copy)


class Generic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = os.path.join(self.tmp.name, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)
        return path

    def test_json_tokens_nested_and_dollar_value(self):
        self.write('tokens.json', json.dumps({
            'color': {'brand': {'$value': '#FF8800', '$type': 'color'}, 'ink': '#000'},
            'spacing': {'sm': '6px', 'lg': 18},
            'radius': {'card': {'value': '14px'}},
        }, indent=2))
        m = manifest(self.tmp.name)
        tokens = {t['name']: t for t in m['tokens']}
        self.assertEqual(tokens['color.brand']['value'], '#ff8800')
        self.assertEqual(tokens['color.ink']['value'], '#000000')
        self.assertEqual((tokens['spacing.lg']['value'], tokens['spacing.lg']['kind']), (18, 'spacing'))
        self.assertEqual(tokens['radius.card']['kind'], 'radius')
        self.assertEqual({6, 18}, values(m, 'spacing'))
        self.assertEqual({14}, values(m, 'radii'))
        self.assertTrue(tokens['color.brand']['src'].startswith('tokens.json:'))
        with open(os.path.join(self.tmp.name, 'tokens.json')) as f:
            self.assertIn('brand', f.read().splitlines()[int(tokens['color.brand']['src'].split(':')[1]) - 1])

    def test_string_table_json_is_copy(self):
        self.write('locales/en.json', json.dumps({'home': {'title': 'Good morning', 'cta': 'Start a session'}}, indent=2))
        m = manifest(self.tmp.name)
        self.assertEqual({'Good morning', 'Start a session'}, {e['text'] for e in m['copy']})

    def test_theme_object_in_code_and_color_forms(self):
        self.write('theme.ts', 'export const theme = {\n  brand: "#FF8800",\n  wash: "rgb(10, 20, 30)",\n'
                   '  accent: "hsl(0, 100%, 50%)",\n  paddingLarge: 20,\n};\n'
                   'const ink = Color(0xFF112233); // color\n')
        m = manifest(self.tmp.name)
        tokens = {t['name']: t['value'] for t in m['tokens']}
        self.assertEqual(tokens['brand'], '#ff8800')
        self.assertEqual(tokens['wash'], '#0a141e')
        self.assertEqual(tokens['accent'], '#ff0000')
        self.assertIn('#112233', values(m, 'colors'))
        self.assertIn(20, values(m, 'spacing'))

    def test_fragments_and_entities_are_not_colors(self):
        self.write('page.html', '<a href="#add">Add</a><a href="#bad">Bad</a><p>Ref&#123;</p>'
                   '<style>.x { color: #abc; }</style><script>var s = "Hidden script text";</script>\n')
        m = manifest(self.tmp.name)
        self.assertEqual({'#aabbcc'}, values(m, 'colors'))
        copy = {e['text'] for e in m['copy']}
        self.assertIn('Add', copy)
        self.assertNotIn('Hidden script text', copy)

    def test_unions_enums_and_typed_booleans(self):
        self.write('Chip.tsx', 'type Size = "sm" | "md" | "lg";\n'
                   'interface ChipProps {\n  tone?: "neutral" | "danger";\n  selected?: boolean;\n  dismissible: boolean;\n}\n'
                   'export function Chip(props: ChipProps) { return null; }\n')
        self.write('Badge.kt', 'enum class BadgeStyle {\n  Solid,\n  Outline,\n}\n')
        self.write('Pill.swift', 'enum PillTone {\n  case calm, loud\n  case muted\n  static let fallback = 1\n'
                   '  var isLoud: Bool { switch self { default: false } }\n}\n')
        m = manifest(self.tmp.name)
        by = {(g['component'], g['prop']): g['values'] for g in m['variants']}
        self.assertEqual(by[('chipprops', 'tone')], ['neutral', 'danger'])
        self.assertEqual(by[('size', 'Size')], ['sm', 'md', 'lg'])
        self.assertEqual(by[('badgestyle', 'BadgeStyle')], ['solid', 'outline'])
        self.assertEqual(by[('pilltone', 'PillTone')], ['calm', 'loud', 'muted'], 'members of an enum are not cases')
        self.assertEqual(by[('chipprops', 'dismissible')], ['true', 'false'])
        self.assertIn(('chipprops', 'selected'), {(s['component'], s['state']) for s in m['states']})

    def test_every_declaration_of_a_one_line_style_object(self):
        self.write('Card.jsx', 'export const Card = () => (\n'
                   '  <div style={{ padding: 12, borderRadius: 8, gap: 6, fontSize: 15 }}>Plan</div>\n);\n')
        m = manifest(self.tmp.name)
        self.assertEqual(({12, 6}, {8}, {15}), (values(m, 'spacing'), values(m, 'radii'), values(m, 'fontSizes')))

    def test_markup_text_keeps_its_expressions_as_placeholders(self):
        self.write('List.jsx', 'export function List({ count, user }) {\n  return (\n    <div>\n'
                   '      <p>You have {count} items left</p>\n      <h2>Hi {user.name}!</h2>\n'
                   '      <span>{count}</span>\n      <em>Total: {format(sum(a, b))}</em>\n    </div>\n  );\n}\n')
        m = manifest(self.tmp.name)
        copy = {e['text']: e['src'] for e in m['copy']}
        self.assertEqual(set(copy), {'You have {count} items left', 'Hi {user.name}!', 'Total: {…}'})
        self.assertEqual(copy['You have {count} items left'], 'List.jsx:4')

    def test_skips_vendor_dirs_and_writes_with_o(self):
        self.write('node_modules/x/a.css', ':root { --junk: #123456; }')
        self.write('src/__tests__/a.css', ':root { --junk2: #123456; }')
        self.write('src/Button.test.css', ':root { --junk3: #123456; }')
        self.write('AppTests/A.css', ':root { --junk4: #123456; }')
        self.write('src/a.css', ':root { --keep: #654321; }')
        out = os.path.join(self.tmp.name, 'm.json')
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_source.py'), self.tmp.name, '-o', out],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.strip(), r'^manifest: .*1 colors.* → ' + re.escape(out) + '$')
        with open(out) as f:
            m = json.load(f)
        self.assertEqual([t['name'] for t in m['tokens']], ['--keep'])
        self.assertEqual(m['tokens'][0]['src'], 'src/a.css:1')

    def test_components_are_styled_blocks_and_code_components_with_uses_and_nesting(self):
        self.write('ui.css', '.tabs { display: flex; border-bottom: 1px solid #ddd; }\n.tab { padding: 8px 0; color: #666; }\n'
                   '.tab--selected { color: #00f; }\n.card { padding: 16px; background: #fff; }\n.card__header { display: flex; }\n'
                   '.row { display: flex; gap: 24px; }\n.page { display: flex; }\n.page__head { display: flex; }\n'
                   '.list-item { display: flex; }\n.list-item__title { font-weight: 500; }\n'
                   '.avatar { width: 32px; background: #eee; }\n')
        item = '<div class="list-item"><span class="avatar">AB</span><span class="list-item__title">Ann</span></div>'
        tabs = '<nav class="tabs"><a class="tab tab--selected">One</a><a class="tab">Two</a></nav>'
        self.write('a.html', '<main class="page"><div class="page__head"><h1>A</h1></div>' + tabs +
                   '<section class="row"><div class="card"><div class="card__header"><h2>Recent</h2></div>' + item + item +
                   '</div><div class="card"><div class="card__header"><h2>Due</h2></div>' + item + '</div></section></main>')
        self.write('b.html', '<main class="page"><img src="x.png">' + tabs + '<div class="card"><br>' + item + '</div></main>')
        self.write('Bar.jsx', 'export function Toolbar({ children }) {\n  return <div>{children}</div>;\n}\n'
                   'export const Screen = () => (\n  <Toolbar>\n    <IconButton icon="a" />\n    <IconButton icon="b" />\n  </Toolbar>\n);\n')
        m = manifest(self.tmp.name)
        by = {c['component']: c for c in m['components']}
        self.assertEqual(set(by), {'tabs', 'tab', 'card', 'list-item', 'avatar', 'Toolbar', 'IconButton'},
                         'a block with only layout rules (row, page) is scaffolding, not a component')
        self.assertEqual({k: c['uses'] for k, c in by.items()},
                         {'tabs': 2, 'tab': 4, 'card': 3, 'list-item': 4, 'avatar': 4, 'Toolbar': 1, 'IconButton': 2})
        self.assertEqual(by['tabs']['nests'], ['tab'])
        self.assertEqual(by['card']['nests'], ['list-item'])
        self.assertEqual(by['list-item']['nests'], ['avatar'])
        self.assertEqual(by['Toolbar']['nests'], ['IconButton'])
        self.assertEqual(by['tab']['nests'], [])
        self.assertEqual(by['tabs']['src'], 'ui.css:1')
        self.assertEqual(by['IconButton']['src'], 'Bar.jsx:6')
        self.assertEqual([c['component'] for c in m['components']][:3], ['tab', 'list-item', 'avatar'], 'most used first')
        out = os.path.join(self.tmp.name, 'm.json')
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_source.py'), self.tmp.name, '-o', out],
                           capture_output=True, text=True)
        self.assertIn('\ncomponents: tab ×4 · list-item ×4 (avatar) · avatar ×4 · card ×3 (list-item) · IconButton ×2 · '
                      'tabs ×2 (tab) · Toolbar ×1 (IconButton)\n', r.stdout)

    def test_missing_path_is_an_error(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_source.py'), '/nope/nothing'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn('/nope/nothing', r.stderr)


if __name__ == '__main__':
    unittest.main()
