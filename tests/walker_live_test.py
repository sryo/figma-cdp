#!/usr/bin/env python3
"""figma_walker.js in a real browser: what an inline SVG's serialized markup carries, so that
createNodeFromSvg (tests/probes/svg_paint.js says what it reads) paints it as the page does.
Needs a browser perch can open a background tab in; nothing touches Figma.

  FIGMA_LIVE=1 [FIGMA_CAPTURE_APP="Google Chrome"] python3 tests/walker_live_test.py   # Arc runs page JS only in a shown tab
"""
import json, os, re, subprocess, sys, unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, 'tests', 'svg_paint_fixture.html')
NS = '{http://www.w3.org/2000/svg}'


def paint(el, prop):
    style = dict(kv.split(':', 1) for kv in (el.get('style') or '').replace('; ', ';').split(';') if ':' in kv)
    return (style.get(prop) or el.get(prop) or '').strip()


@unittest.skipUnless(os.environ.get('FIGMA_LIVE') == '1', 'walks a page in a real browser (FIGMA_LIVE=1)')
class SvgPaint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_capture.py'), 'walk', 'file://' + FIXTURE, '500'],
                           capture_output=True, text=True, timeout=180)
        assert p.returncode == 0, p.stderr
        path = re.search(r'^spec: (\S+)', p.stdout, re.M).group(1)
        with open(path) as f:
            spec = json.load(f)
        cls.nodes = spec['nodes']
        cls.svgs = {}
        for a in spec.get('assets', {}).values():
            if a.get('svg'):
                root = ET.fromstring(a['svg'])
                cls.svgs[root.get('aria-label')] = root

    def test_elements_carry_their_class_list(self):
        icon = next(n for n in self.nodes if n.get('axName') == 'page-class')
        self.assertEqual(icon.get('cls'), ['icon'])
        self.assertEqual(sorted({tuple(n['cls']) for n in self.nodes if n['tag'] == 'span' and n.get('cls')}), [('tinted',)])
        self.assertNotIn('cls', next(n for n in self.nodes if n.get('axName') == 'page-var'))

    def shape(self, label, tag='path'):
        return self.svgs[label].find(f'.//{NS}{tag}')

    def test_no_paint_needs_the_page_to_resolve(self):
        self.assertEqual(sorted(self.svgs), ['alpha', 'current-color', 'gradient', 'page-class', 'page-var', 'stroke-current'])
        for label, root in self.svgs.items():
            markup = ET.tostring(root, encoding='unicode')
            for word in ('var(', 'currentColor', 'color(srgb'):
                self.assertNotIn(word, markup, label)

    def test_each_shape_carries_its_computed_paint(self):
        self.assertEqual(paint(self.shape('page-var'), 'fill'), 'rgb(255, 0, 0)')
        self.assertEqual(paint(self.shape('current-color'), 'fill'), 'rgb(0, 0, 255)')
        self.assertRegex(paint(self.shape('page-class'), 'fill'), r'^rgb\(0, 12[78], 0\)$')
        self.assertEqual(paint(self.shape('stroke-current'), 'stroke'), 'rgb(0, 0, 255)')
        self.assertEqual(paint(self.shape('stroke-current'), 'fill'), 'none')
        alpha = self.shape('alpha')
        self.assertEqual((paint(alpha, 'fill'), paint(alpha, 'fill-opacity')), ('rgb(255, 0, 0)', '0.5'))

    def test_gradients_keep_their_url_and_resolve_their_stops(self):
        self.assertEqual(paint(self.shape('gradient'), 'fill'), 'url("#g")' if 'url("' in paint(self.shape('gradient'), 'fill') else 'url(#g)')
        stops = self.svgs['gradient'].findall(f'.//{NS}stop')
        self.assertEqual([paint(s, 'stop-color') for s in stops], ['rgb(255, 0, 0)', 'rgb(0, 0, 0)'])



@unittest.skipUnless(os.environ.get('FIGMA_LIVE') == '1', 'walks a page in a real browser (FIGMA_LIVE=1)')
class Gaps(unittest.TestCase):
    """What a capture used to lose: vertical text, text beside a hidden element, a tiled
    background's tile, an SVG file an <image> shows, and content waiting to fade in."""
    @classmethod
    def setUpClass(cls):
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_capture.py'), 'walk',
                            'file://' + os.path.join(ROOT, 'tests', 'capture_gaps_fixture.html'), '500', '--width', '0'],
                           capture_output=True, text=True, timeout=180)
        assert p.returncode == 0, p.stderr
        cls.stderr = p.stderr
        with open(re.search(r'^spec: (\S+)', p.stdout, re.M).group(1)) as f:
            cls.spec = json.load(f)
        cls.nodes = cls.spec['nodes']

    def node(self, cls_name):
        return next(n for n in self.nodes if cls_name in (n.get('cls') or []))

    def test_vertical_text_says_so(self):
        self.assertEqual(self.node('vert')['styles'].get('writingMode'), 'vertical-rl')

    def test_text_beside_a_hidden_element_is_kept(self):
        # The <time> is inline text in its <p>, so its text, pseudo glyph included, is the <p>'s.
        self.assertIn('\u201903', [n.get('text') for n in self.nodes])

    def test_a_tiled_background_carries_its_tile(self):
        img = self.node('tiled')['image']
        self.assertEqual((img['mode'], img['tile']['w'], img['tile']['h'], img['tile']['repeat']), ('TILE', 6, 288, 'repeat-y'))

    def test_an_svg_image_is_inlined_with_its_ids_prefixed(self):
        svg = next(a['svg'] for a in self.spec['assets'].values() if 'with-image' in (a.get('svg') or ''))
        self.assertNotIn('<image', svg)
        self.assertRegex(svg, r'<svg x="10" y="5" width="40" height="40" viewBox="0 0 40 40">')
        self.assertRegex(svg, r'id="fx\w+-0-dot"')

    def test_content_waiting_to_fade_in_is_shown(self):
        self.assertEqual(self.node('fade')['styles'].get('opacity', 1), 1)

    def test_visually_hidden_text_is_left_out(self):
        self.assertFalse([n for n in self.nodes if 'Screen reader' in (n.get('text') or '')])

    def test_text_beside_a_block_child_is_kept(self):
        li = self.node('step')
        loose = [n for n in self.nodes if n['parent'] == li['i'] and n.get('text') == 'Rest your thumb.']
        self.assertEqual(len(loose), 1, [n.get('text') for n in self.nodes if n['parent'] == li['i']])
        self.assertEqual(len(loose[0]['runs']), 3)
        self.assertGreater(loose[0]['rect']['w'], 20)

    def test_auto_margins_say_which_side_they_push_from(self):
        self.assertEqual((self.node('col')['styles'].get('mx'), self.node('end')['styles'].get('mx')), ('c', 'r'))

    def test_a_raised_sibling_paints_after_a_later_one(self):
        raised, flat = self.node('raised'), self.node('flat')
        self.assertEqual(raised['styles'].get('z'), 5)
        self.assertGreater(raised['i'], flat['i'])

    def test_a_webgl_canvas_is_drawn_or_says_why_not(self):
        img = self.node('gl')['image']
        asset = self.spec['assets'][img['asset']]
        if 'in the background' in self.stderr:
            self.assertEqual(asset.get('error'), 'webgl')
            self.assertIn('WebGL', self.stderr)
        else:
            self.assertTrue(asset.get('b64'))


if __name__ == '__main__':
    unittest.main()
