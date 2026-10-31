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

    def test_summary_prints_the_values_a_plan_needs(self):
        d = os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'harbor')
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_source.py')]
                               + [os.path.join(d, f) for f in ('tokens.css', 'components.css', 'dashboard.html')]
                               + ['-o', os.path.join(tmp, 'm.json')], capture_output=True, text=True)
        lines = r.stdout.splitlines()
        self.assertIn('variants: avatar(lg) · badge(success, warning, danger) · button(primary, secondary)', lines)
        self.assertIn('states: input(focus, error, disabled) · tab(selected) · listitem(selected)', lines)
        self.assertIn('scales: spacing 2 4 8 12 16 24 32 · radii 6 10 999 · font sizes 12 14 16 20 28 · '
                      'weights 400 500 700 · families Inter, system-ui, sans-serif', lines)

    def test_a_style_component_carries_its_rules(self):
        page = os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'harbor-pages', 'notes.html')
        comps = {c['component']: c for c in manifest(page)['components']}
        css = comps['button']['css']
        self.assertEqual(list(css), ['.button', '.button--primary', '.button--secondary'])
        self.assertEqual(css['.button'], 'display: inline-flex; align-items: center; gap: var(--space-2); flex: none; '
                         'padding: var(--space-2) var(--space-4); border-radius: var(--radius-sm); border: 1px solid transparent; '
                         'font-size: var(--text-sm); font-weight: var(--weight-medium); text-decoration: none;')
        self.assertEqual(css['.button--primary'], 'background: var(--color-primary); color: var(--color-on-primary);')
        self.assertIn('.avatar--lg', comps['avatar']['css'])
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'a.html'), 'w') as f:
                f.write('<div class="card"><span class="card__title">Hello there friend</span></div>')
            with open(os.path.join(tmp, 'a.css'), 'w') as f:
                f.write('/* .card { color: red; } */\n.card { color: #123456; }\n.card:hover,\n.card--on { background: #fff; }\n'
                        + ''.join(f'.card__p{i} {{ padding: {i}px {i}px {i}px {i}px; margin: {i}px; }}\n' for i in range(200)))
            with open(os.path.join(tmp, 'Row.jsx'), 'w') as f:
                f.write('export function App() { return <Row label="Hello there friend" /> }\n')
            comps = {c['component']: c for c in manifest(tmp)['components']}
            css = comps['card']['css']
            self.assertEqual(list(css)[:2], ['.card', '.card:hover, .card--on'], 'comments skipped, selector lists kept whole')
            self.assertLessEqual(len(json.dumps(css)), 1600, 'a component\'s rules stay bounded')
            self.assertRegex(css['…'], r'^\d+ more rules in a\.css$')
            self.assertNotIn('css', comps['Row'], 'a code component has no style rules')

    def test_a_component_lists_the_usages_its_column_parent_stretches(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'a.css'), 'w') as f:
                f.write('.col { display: flex; flex-direction: column; }\n'
                        '.center { display: flex; flex-flow: column wrap; align-items: center; }\n'
                        '.row { display: flex; }\n'
                        '.stat { display: flex; flex-direction: column; background: #fff; }\n'
                        '.stat .badge { align-self: flex-start; }\n'
                        '.badge { display: inline-flex; padding: 2px; background: #eee; }\n'
                        '.badge--wide { width: 120px; }\n'
                        '.self { align-self: center; }\n'
                        '.col.tight { align-items: stretch; }\n')
            with open(os.path.join(tmp, 'a.html'), 'w') as f:
                f.write('<div class="col"><span class="badge">A</span></div>\n'
                        '<div class="center"><span class="badge">B</span></div>\n'
                        '<div class="col"><span class="badge badge--wide">C</span></div>\n'
                        '<div class="col"><span class="badge self">D</span></div>\n'
                        '<div class="stat"><span class="badge">E</span></div>\n'
                        '<div class="row"><span class="badge">F</span></div>\n'
                        '<div class="col"><span class="badge" style="width: 40px">G</span></div>\n'
                        '<div class="col tight">\n  <p>Some text here</p>\n  <span class="badge badge--x">H</span>\n</div>\n'
                        '<div class="col"><div class="wrap"><span class="badge">I</span></div></div>\n')
            comps = {c['component']: c for c in manifest(tmp)['components']}
            self.assertEqual(comps['badge']['fillAcross'], ['a.html:1 in .col', 'a.html:10 in .col.tight'],
                             'only a column parent with default or stretch align-items, and a child with no width or align-self')
            self.assertNotIn('fillAcross', comps['stat'], 'a component nothing stretches has no fill list')
        harbor = {c['component']: c for c in manifest(os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'harbor'))['components']}
        self.assertEqual(harbor['stat-card']['files'], ['components.html', 'dashboard.html'], 'the markup files that use it, sorted')
        self.assertIn('customers.html', harbor['badge']['files'])
        page = os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'harbor', 'customers.html')
        fill = {c['component']: c.get('fillAcross', []) for c in manifest(page)['components']}
        self.assertIn('customers.html:69 in .card.grow', fill['badge'], 'the Customer details badge stretches')
        self.assertFalse([u for u in fill['badge'] if not u.startswith('customers.html:69 ')],
                         'list-item badges sit in a centered row')

    def test_a_page_brings_its_linked_and_imported_style_sheets(self):
        page = os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'harbor-pages', 'notes.html')
        m = manifest(page)
        self.assertTrue(any(t['name'] == '--space-4' for t in m['tokens']), 'tokens.css, via components.css @import')
        self.assertTrue(any(c['component'] == 'button' for c in m['components']), 'components.css, via <link>')
        self.assertTrue(any(e['src'].startswith('harbor/tokens.css:') for e in m['tokens']))
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'a.html'), 'w') as f:
                f.write('<link rel="stylesheet" href="https://cdn.example.com/x.css"><link rel="stylesheet" href="gone.css">'
                        '<link href="a.css" rel="stylesheet"><p>Hi there friend</p>')
            with open(os.path.join(tmp, 'a.css'), 'w') as f:
                f.write('@import url("a.css");\n.card { color: #123456; }\n')
            m = manifest(os.path.join(tmp, 'a.html'), os.path.join(tmp, 'a.css'))
            self.assertEqual([e['src'] for e in m['colors']], ['a.css:2'])

    def test_svg_path_data_is_not_copy(self):
        icons = os.path.join(ROOT, 'tests', 'eval', 'fixtures', 'harbor', 'icons.svg')
        self.assertEqual(manifest(icons)['copy'], [])
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'Bell.tsx'), 'w') as f:
                f.write('export const Bell = () => (\n  <svg viewBox="0 0 20 20"><path d="M5 8a5 5 0 0 1 10 0c0 4 1.5 5.5 1.5 5.5h-13S5 12 5 8Z"/>'
                        '<polyline points="1 2 3 4"/></svg>\n);\n')
            self.assertEqual([c['text'] for c in manifest(os.path.join(tmp, 'Bell.tsx'))['copy']], [])

    def test_missing_path_is_an_error(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_source.py'), '/nope/nothing'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn('/nope/nothing', r.stderr)


DESIGN = os.path.join(ROOT, 'tests', 'design')


def run_source(*args):
    return subprocess.run([sys.executable, os.path.join(ROOT, 'figma_source.py'), *args], capture_output=True, text=True)


class DesignMd(unittest.TestCase):
    """DESIGN.md (Google's format): YAML front matter tokens are the source, cited by line."""

    @classmethod
    def setUpClass(cls):
        cls.m = manifest(os.path.join(DESIGN, 'DESIGN.md'))
        cls.tokens = {t['name']: t for t in cls.m['tokens']}
        with open(os.path.join(DESIGN, 'DESIGN.md')) as f:
            cls.lines = f.read().splitlines()

    def test_tokens_cite_their_design_md_line(self):
        for name in ('colors.primary', 'colors.canvas-dark', 'typography.fs-s.fontSize', 'rounded.r-tile', 'spacing.gap'):
            t = self.tokens[name]
            f, n = t['src'].rsplit(':', 1)
            self.assertEqual(f, 'DESIGN.md')
            self.assertIn(name.split('.')[-1] + ':', self.lines[int(n) - 1], t)

    def test_values_and_refs_resolve(self):
        v = lambda n: (self.tokens[n]['value'], self.tokens[n]['kind'])
        self.assertEqual(v('colors.primary'), ('#2f5bea', 'color'))
        self.assertEqual(v('colors.on-primary'), ('#faf9f6', 'color'))
        self.assertEqual(v('components.button.textColor'), ('#faf9f6', 'color'))
        self.assertEqual(v('typography.fs-s.fontSize'), (14, 'fontSize'))
        self.assertEqual(v('typography.fs-s.fontWeight'), (500, 'fontWeight'))
        self.assertEqual(v('typography.fs-s.fontFamily'), ('Inter', 'fontFamily'))
        self.assertEqual(v('rounded.r-tile'), (20, 'radius'))
        self.assertEqual(v('spacing.gap'), (16, 'spacing'))
        self.assertEqual({e['value'] for e in self.m['colors']} >= {'#2f5bea', '#0e0f13'}, True)

    def test_each_theme_is_its_own_collection(self):
        self.assertEqual(self.m['design']['themes'], ['light', 'dark'])
        self.assertEqual(self.m['design']['collections'], ['Lede/light', 'Lede/dark'])
        dark, base = self.tokens['colors.canvas-dark'], self.tokens['colors.canvas']
        self.assertEqual((dark['theme'], dark['collection'], dark['variable']), ('dark', 'Lede/dark', 'colors/canvas'))
        self.assertEqual((base['theme'], base['collection'], base['variable']), ('light', 'Lede/light', 'colors/canvas'))
        self.assertEqual(self.tokens['typography.fs-s.fontSize']['variable'], 'typography/fs-s/fontSize')
        self.assertNotIn('variable', self.tokens['components.button.textColor'])

    def test_prose_colors_are_not_usages(self):
        self.assertFalse(any(e['src'].startswith('DESIGN.md:') and int(e['src'].split(':')[1]) > 26 for e in self.m['colors']))
        self.assertEqual(self.m['copy'], [])

    def test_broken_ref_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'DESIGN.md'), 'w') as f:
                f.write('---\nname: X\ncolors:\n  primary: "#000000"\n  ghost: "{colors.nope}"\n---\n')
            r = run_source(os.path.join(tmp, 'DESIGN.md'))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)['design']['brokenRefs'],
                             [{'token': 'colors.ghost', 'ref': '{colors.nope}', 'src': 'DESIGN.md:5'}])
            self.assertIn('DESIGN.md:5', r.stderr)
            self.assertIn('{colors.nope}', r.stderr)

    def test_yaml_blocks_merge_and_duplicate_keys_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'DESIGN.md'), 'w') as f:
                f.write('---\nname: X\n---\n\n## Colors\n\n```yaml\ncolors:\n  primary: "#112233"  # ink\n```\n\n'
                        '## Shapes\n\n```yaml\nrounded:\n  sm: 4px\ncolors:\n  extra: "#445566"\n```\n')
            m = manifest(os.path.join(tmp, 'DESIGN.md'))
            t = {e['name']: e for e in m['tokens']}
            self.assertEqual((t['colors.primary']['value'], t['colors.primary']['src']), ('#112233', 'DESIGN.md:9'))
            self.assertEqual(t['rounded.sm']['value'], 4)
            self.assertEqual(m['design']['collections'], ['X'])
            self.assertEqual(len(m['design']['errors']), 1)
            self.assertIn('colors', m['design']['errors'][0]['message'])
            self.assertEqual(m['design']['errors'][0]['src'], 'DESIGN.md:17')

    def test_a_directory_reads_its_design_md(self):
        m = manifest(DESIGN)
        names = {t['name'] for t in m['tokens']}
        self.assertIn('colors.primary', names)
        self.assertIn('--primary', names)
        self.assertEqual(next(t for t in m['tokens'] if t['name'] == 'colors.primary')['src'], 'DESIGN.md:7')

    def test_other_markdown_is_still_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'README.md'), 'w') as f:
                f.write('---\ncolors:\n  a: "#123456"\n---\n')
            with open(os.path.join(tmp, 'a.css'), 'w') as f:
                f.write('.a { color: #654321; }\n')
            m = manifest(tmp)
            self.assertNotIn('design', m)
            self.assertEqual([e['value'] for e in m['colors']], ['#654321'])


class Check(unittest.TestCase):
    """--check DESIGN.md <code>: tokens missing from code, values that differ, code tokens DESIGN.md lacks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(DESIGN, 'tokens.css')) as f:
            self.css = f.read()

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, css=None, name='tokens.css', design=None):
        path = os.path.join(DESIGN, 'tokens.css')
        if css is not None:
            path = os.path.join(self.tmp.name, name)
            with open(path, 'w') as f:
                f.write(css)
        return run_source('--check', design or os.path.join(DESIGN, 'DESIGN.md'), path)

    def findings(self, r):
        return r.stdout.splitlines()[1:]

    def test_matching_code_is_clean(self):
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout.strip(), r'^check: 0 drift')

    def test_changed_value_and_extra_var_give_two_findings_with_file_line(self):
        css = self.css.replace('--ink:#1A1D2E;', '--ink:#1A1D2F;').replace('  --gap:16px;\n', '  --gap:16px;\n  --extra:#ABCDEF;\n')
        r = self.check(css)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        rows = self.findings(r)
        self.assertEqual(len(rows), 2, r.stdout)
        self.assertRegex(rows[0], r'^different colors\.ink DESIGN\.md:9 #1a1d2e, .*tokens\.css:3 --ink #1a1d2f$')
        self.assertRegex(rows[1], r'^undocumented --extra .*tokens\.css:8 = #ABCDEF$')
        self.assertRegex(r.stdout.splitlines()[0], r'^check: 2 drift \(1 different, 1 undocumented\)')

    def test_token_missing_from_code(self):
        r = self.check(self.css.replace('  --r-tile:20px;\n', ''))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.findings(r), ['missing rounded.r-tile DESIGN.md:19 = 20'])

    def test_a_theme_matches_its_own_block(self):
        r = self.check(self.css.replace('--ink:#EDEEF3;', '--ink:#EDEEF4;'))
        self.assertEqual(r.returncode, 1)
        rows = self.findings(r)
        self.assertEqual(len(rows), 1, r.stdout)
        self.assertRegex(rows[0], r'^different colors\.ink-dark DESIGN\.md:12 #edeef3, .*tokens\.css:11 --ink \(dark\) #edeef4$')
        r = self.check(self.css.replace('  --canvas:#0E0F13; --ink:#EDEEF3;\n', '  --canvas:#0E0F13;\n'))
        self.assertEqual(self.findings(r), ['missing colors.ink-dark DESIGN.md:12 = #edeef3'])

    def test_style_blocks_in_markup(self):
        page = ('<!doctype html>\n<script>if (a) { b({c: 1}); }</script>\n<style>\n' + self.css + '</style>\n'
                '<script>const x = {y: "--nope:#000000"};</script>\n')
        r = self.check(page, name='index.html')
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_broken_ref_is_drift(self):
        with open(os.path.join(DESIGN, 'DESIGN.md')) as f:
            text = f.read().replace('"{colors.canvas}"', '"{colors.paper}"')
        design = os.path.join(self.tmp.name, 'DESIGN.md')
        with open(design, 'w') as f:
            f.write(text)
        r = self.check(design=design)
        self.assertEqual(r.returncode, 1)
        self.assertIn('broken colors.on-primary DESIGN.md:10 {colors.paper}', r.stdout)


class OmittedAndAlpha(unittest.TestCase):
    """DESIGN.md's omitted: names code properties left out on purpose; colors keep their alpha."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(DESIGN, 'DESIGN.md')) as f:
            self.design = f.read()
        with open(os.path.join(DESIGN, 'tokens.css')) as f:
            self.css = f.read()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, 'w') as f:
            f.write(text)
        return path

    def check(self, design, css):
        return run_source('--check', self.write('DESIGN.md', design), self.write('tokens.css', css))

    def test_omitted_parses(self):
        d = self.design.replace('themes: [light, dark]\n', 'themes: [light, dark]\nomitted:\n  - "--a-*"\n  - --extra\n')
        m = manifest(self.write('DESIGN.md', d))
        self.assertEqual(m['design']['omitted'], ['--a-*', '--extra'])

    def test_check_skips_omitted_code_names(self):
        d = self.design.replace('themes: [light, dark]\n', 'themes: [light, dark]\nomitted: ["--a-*", "--extra"]\n')
        css = self.css.replace('  --gap:16px;\n', '  --gap:16px;\n  --a-rest:50%; --a-pale:16%;\n  --extra:#ABCDEF;\n  --other:1px;\n')
        r = self.check(d, css)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(r.stdout.splitlines()[1:], [l for l in r.stdout.splitlines()[1:] if '--other' in l])
        self.assertEqual(len(r.stdout.splitlines()), 2, r.stdout)

    def test_an_omitted_name_that_is_a_token_is_reported(self):
        d = self.design.replace('themes: [light, dark]\n', 'themes: [light, dark]\nomitted: ["--ink"]\n')
        r = self.check(d, self.css)
        self.assertEqual(r.returncode, 1, r.stdout)
        rows = r.stdout.splitlines()[1:]
        self.assertEqual(len(rows), 1, r.stdout)
        self.assertRegex(rows[0], r'^omitted colors\.ink DESIGN\.md:10 is also omitted by --ink \(DESIGN\.md:6\)$')

    def test_colors_keep_alpha(self):
        d = self.design.replace('  ink-dark: "#EDEEF3"\n', '  ink-dark: "#EDEEF3"\n  veil: "#1A1D2E80"\n  solid: "#FFFFFFFF"\n')
        t = {e['name']: e for e in manifest(self.write('DESIGN.md', d))['tokens']}
        self.assertEqual((t['colors.veil']['value'], t['colors.solid']['value']), ('#1a1d2e80', '#ffffff'))

    def test_alpha_only_difference_is_drift(self):
        r = self.check(self.design, self.css.replace('--ink:#1A1D2E;', '--ink:#1A1D2E80;'))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertRegex(r.stdout.splitlines()[1], r'^different colors\.ink DESIGN\.md:9 #1a1d2e, \S+ --ink #1a1d2e80$')
        r = self.check(self.design, self.css.replace('--ink:#1A1D2E;', '--ink:rgba(26, 29, 46, 1);'))
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == '__main__':
    unittest.main()
