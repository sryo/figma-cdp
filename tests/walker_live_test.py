#!/usr/bin/env python3
"""figma_walker.js in a real browser: what an inline SVG's serialized markup carries, so that
createNodeFromSvg (tests/probes/svg_paint.js says what it reads) paints it as the page does.
Needs a browser perch or CDP can open a background tab in; nothing touches Figma.

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
        cls.svgs = {}
        for a in spec.get('assets', {}).values():
            if a.get('svg'):
                root = ET.fromstring(a['svg'])
                cls.svgs[root.get('aria-label')] = root

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


if __name__ == '__main__':
    unittest.main()
