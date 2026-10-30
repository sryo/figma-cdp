#!/usr/bin/env python3
"""figma_fidelity.py --elements offline: tests/capture_spec.json built on the stub Plugin API as
the importer names it ([cap:i] frames, a "[cap:i] text" layer for text), then broken on purpose
(moved, resized, recolored, retyped, removed, an extra layer) and diffed per element. Runs through
figma_run.py and the perch stub's full Plugin API (PERCH_STUB_FIGMA=full).

  python3 tests/fidelity_elements_test.py
"""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, 'tests', 'capture_spec.json')
sys.path.insert(0, os.path.join(ROOT, 'tests'))
from fidelity_test import stop_daemon  # noqa: E402

# The spec as a faithful importer would leave it: absolute frames at each rect, text in a child.
BUILD = r'''
const spec = %s, made = {};
const W = { 100: 'Thin', 200: 'Extra Light', 300: 'Light', 400: 'Regular', 500: 'Medium', 600: 'Semi Bold', 700: 'Bold', 800: 'Extra Bold', 900: 'Black' };
const solid = (c) => [{ type: 'SOLID', visible: true, opacity: c.a === undefined ? 1 : c.a, color: { r: c.r, g: c.g, b: c.b } }];
for (const s of Object.values(W)) await figma.loadFontAsync({ family: 'Inter', style: s });
for (const n of spec.nodes) {
  const up = n.parent < 0 ? figma.currentPage : made[n.parent];
  const at = n.parent < 0 ? { x: 0, y: 0 } : spec.nodes[n.parent].rect;
  const f = figma.createFrame();
  up.appendChild(f);
  f.name = '[cap:' + n.i + '] ' + (n.axName || n.role || n.tag);
  f.x = n.rect.x - at.x; f.y = n.rect.y - at.y; f.resize(Math.max(n.rect.w, 1), Math.max(n.rect.h, 1));
  f.fills = n.styles.bg ? solid(n.styles.bg) : [];
  if (n.styles.radius) f.cornerRadius = n.styles.radius;
  if (n.styles.opacity !== undefined) f.opacity = n.styles.opacity;
  made[n.i] = f;
  if (n.text) {
    const t = figma.createText();
    f.appendChild(t);
    t.name = '[cap:' + n.i + '] text';
    t.fontName = { family: 'Inter', style: W[n.styles.fontWeight || 400] };
    t.fontSize = n.styles.fontSize || 16;
    t.characters = n.text;
    t.fills = solid(n.styles.color || { r: 0, g: 0, b: 0, a: 1 });
    t.resize(Math.max(n.rect.w, 1), Math.max(n.rect.h, 1));
  }
}
return made[0].id;
'''


def node_where(spec, **want):
    return next(n for n in spec['nodes'] if all(n.get(k) == v for k, v in want.items()))


class Elements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SPEC) as f:
            cls.spec = json.load(f)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = os.path.join(self.tmp.name, 'd.sock')
        self.env = {k: v for k, v in os.environ.items() if k not in ('FIGMA_FILE', 'FIGMA_PERCH_TAB', 'FIGMA_CDP_PORT', 'PERCH_STUB_ERROR')}
        self.env.update(FIGMA_BACKEND='perch', PERCH_DIR=os.path.join(ROOT, 'tests', 'perch_stub'), PERCH_STUB_FIGMA='full',
                        FIGMA_PERCH_SOCK=self.sock, FIGMA_CDP_JOURNAL='0', FIGMA_CDP_HOME=self.tmp.name)
        self.root = self.figma(BUILD % json.dumps(self.spec))

    def tearDown(self):
        stop_daemon(self.sock)
        self.tmp.cleanup()

    def figma(self, src):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_run.py'), '-'], input=src, capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def check(self, *extra):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_fidelity.py'), '--elements', SPEC, self.root, '--json', *extra],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def edit(self, i, body):
        """Run body on the frame the build named [cap:i] (as n) and its text layer (as t)."""
        self.figma(f'''const root = await figma.getNodeByIdAsync({json.dumps(self.root)});
            const n = root.name.startsWith('[cap:{i}] ') ? root : root.findOne((x) => x.name.startsWith('[cap:{i}] ') && x.type !== 'TEXT');
            const t = n.findOne ? n.findOne((x) => x.name === '[cap:{i}] text') : null;
            {body}; return 1''')

    def rows(self, rep, i):
        return sorted(r['kind'] for r in rep['rows'] if r['source'] and r['source']['i'] == i)

    def test_a_faithful_build_has_no_gaps(self):
        rep = self.check()
        self.assertEqual((rep['pairing'], rep['rows']), ('cap', []))
        self.assertEqual(rep['paired'], len(self.spec['nodes']))

    def test_each_injected_fault_is_one_row_on_its_element(self):
        card, px, pct = (node_where(self.spec, axName=a)['i'] for a in ('grow-card', 'px-card', 'pct-card'))
        self.edit(card, 'n.x += 20')
        self.edit(px, 'n.resize(n.width + 30, n.height)')
        self.edit(pct, "n.fills = [{type: 'SOLID', visible: true, opacity: 1, color: {r: 1, g: 0, b: 0}}]")
        texted = node_where(self.spec, axName='abs-child')['i']
        self.edit(texted, "t.characters = 'Something else'")
        rep = self.check()
        self.assertEqual(self.rows(rep, card), ['position'])
        self.assertEqual(self.rows(rep, px), ['size'])
        self.assertEqual(self.rows(rep, pct), ['color'])
        self.assertEqual(self.rows(rep, texted), ['text'])
        color = next(r for r in rep['rows'] if r['kind'] == 'color')
        self.assertEqual((color['source']['css_prop'], color['figma']['prop'], color['figma']['value']), ('background-color', 'fills', '#ff0000'))
        moved = next(r for r in rep['rows'] if r['kind'] == 'position')
        self.assertEqual(moved['figma']['value'][0] - moved['source']['value'][0], 20)

    def test_type_faults_name_the_text_property(self):
        i = next(n['i'] for n in self.spec['nodes'] if n['text'] and n['styles'].get('fontSize'))
        self.edit(i, 't.fontSize = t.fontSize + 6')
        self.edit(i, "t.fills = [{type: 'SOLID', visible: true, opacity: 1, color: {r: 0, g: 0.6, b: 0}}]")
        rep = self.check()
        self.assertEqual(self.rows(rep, i), ['color', 'font-size'])
        self.assertEqual(next(r for r in rep['rows'] if r['kind'] == 'color')['source']['css_prop'], 'color')

    def test_a_removed_element_is_missing_once_and_an_added_layer_is_extra(self):
        gone = node_where(self.spec, axName='abs-parent')['i']
        kids = [n['i'] for n in self.spec['nodes'] if n['parent'] == gone]
        self.assertTrue(kids)
        self.edit(gone, 'n.remove()')
        self.figma(f'''const root = await figma.getNodeByIdAsync({json.dumps(self.root)});
            const x = figma.createFrame(); root.appendChild(x); x.name = 'Badge'; x.resize(40, 40); return 1''')
        rep = self.check()
        missing = [r for r in rep['rows'] if r['kind'] == 'missing-node']
        self.assertEqual([r['source']['i'] for r in missing], [gone], 'descendants of a missing element are not listed again')
        self.assertGreater(missing[0]['weight'], 0)
        extra = [r for r in rep['rows'] if r['kind'] == 'extra-node']
        self.assertEqual([r['figma']['name'] for r in extra], ['Badge'])

    def test_waived_losses_are_counted_not_listed(self):
        flagged = self.spec['flagged'][0]
        self.edit(flagged['i'], 'n.x += 50')
        rep = self.check()
        self.assertIn(flagged['i'], [r['source']['i'] for r in rep['rows']])
        rep = self.check('--waive', os.path.join(ROOT, 'tests', 'known_losses.json'))
        self.assertNotIn(flagged['i'], [r['source']['i'] for r in rep['rows'] if r['source']])
        self.assertEqual(rep['waived'], {'grid-display': 1})

    def test_without_cap_names_elements_pair_by_text_and_geometry(self):
        self.figma(f'''const root = await figma.getNodeByIdAsync({json.dumps(self.root)});
            for (const n of [root].concat(root.findAll(() => true))) n.name = n.type === 'TEXT' ? 'Label' : 'Frame';
            return 1''')
        rep = self.check()
        self.assertEqual(rep['pairing'], 'geometry')
        self.assertEqual(rep['rows'], [])
        texted = node_where(self.spec, axName='abs-child')['i']
        self.figma(f'''const root = await figma.getNodeByIdAsync({json.dumps(self.root)});
            const t = root.findAll((x) => x.type === 'TEXT').find((x) => x.characters === {json.dumps(self.spec['nodes'][texted]['text'])});
            t.characters = t.characters + '!'; return 1''')
        self.assertEqual(self.rows(self.check(), texted), ['text'])

    def test_the_summary_line_counts_rows_by_kind(self):
        self.edit(node_where(self.spec, axName='grow-card')['i'], 'n.x += 20')
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_fidelity.py'), '--elements', SPEC, self.root],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.splitlines()[0], r'^elements .*: 1 gap \(position 1\), \d+ of \d+ paired by cap')


if __name__ == '__main__':
    unittest.main()
