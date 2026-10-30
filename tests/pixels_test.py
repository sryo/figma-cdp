#!/usr/bin/env python3
"""figma_fidelity.py --pixels offline: the PNG codec, and the residual on hand-made images. The
"screenshot" and the "export" are the same flat page except where a test paints a fault: inside a
text box (masked), on an element a row already names (explained), or elsewhere (unexplained).

  python3 tests/pixels_test.py
"""
import json, os, subprocess, sys, tempfile, unittest, zlib, struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import figma_fidelity as ff  # noqa: E402

W, H = 200, 120


def image(paint=()):
    px = bytearray([255] * W * H * 3)
    for (x, y, w, h, rgb) in paint:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                px[(yy * W + xx) * 3:(yy * W + xx) * 3 + 3] = bytes(rgb)
    return W, H, px


SPEC = {'meta': {'viewport': {'w': W}}, 'nodes': [
    {'i': 0, 'parent': -1, 'rect': {'x': 0, 'y': 0, 'w': W, 'h': H}, 'text': ''},
    {'i': 1, 'parent': 0, 'rect': {'x': 10, 'y': 10, 'w': 60, 'h': 20}, 'text': 'Hello'},
    {'i': 2, 'parent': 0, 'rect': {'x': 100, 'y': 10, 'w': 40, 'h': 40}, 'text': ''},
]}


class Codec(unittest.TestCase):
    def test_a_written_png_reads_back(self):
        w, h, px = image([(5, 5, 20, 10, (12, 200, 99))])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'a.png')
            ff.png_write(path, w, h, px)
            with open(path, 'rb') as f:
                self.assertEqual(ff.png_read(f.read()), (w, h, px))

    def test_filters_and_alpha_decode(self):
        # Two rows, RGBA: row 0 unfiltered, row 1 with the Up filter; the second pixel half transparent.
        raw = b'\x00' + bytes([255, 0, 0, 255, 0, 0, 255, 128]) + b'\x02' + bytes([0, 0, 0, 0, 0, 0, 0, 0])
        chunk = lambda k, b: struct.pack('>I', len(b)) + k + b + struct.pack('>I', zlib.crc32(k + b) & 0xffffffff)
        data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
        w, h, px = ff.png_read(data)
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(list(px[:6]), [255, 0, 0, 127, 127, 255])
        self.assertEqual(px[6:], px[:6])


class Residual(unittest.TestCase):
    def test_a_fault_no_row_explains_is_unexplained(self):
        fig = image([(20, 70, 30, 30, (40, 40, 40))])
        out = ff.residual(SPEC, {'rows': []}, image(), fig)
        self.assertEqual([g['rect'] for g in out], [[16, 64, 40, 40]])
        self.assertGreater(out[0]['cells'], 20)

    def test_text_is_masked_and_rows_explain_their_element(self):
        fig = image([(12, 12, 40, 10, (0, 0, 0)), (104, 14, 20, 20, (200, 0, 0))])
        self.assertEqual(len(ff.residual(SPEC, {'rows': []}, image(), fig)), 1, 'the text box is masked, the frame is not')
        row = {'kind': 'color', 'source': {'i': 2, 'css_prop': 'background-color', 'value': None}, 'figma': None}
        self.assertEqual(ff.residual(SPEC, {'rows': [row]}, image(), fig), [])

    def test_a_retina_screenshot_scales_to_the_export(self):
        w, h, px = image([(20, 70, 30, 30, (40, 40, 40))])
        big = bytearray()
        for y in range(h * 2):
            line = px[(y // 2) * w * 3:(y // 2 + 1) * w * 3]
            big += b''.join(bytes(line[x * 3:x * 3 + 3]) * 2 for x in range(w))
        out = ff.residual(SPEC, {'rows': []}, (w * 2, h * 2, big), image())
        self.assertEqual([g['rect'] for g in out], [[16, 64, 40, 40]])

    def test_crops_are_written_for_each_region(self):
        fig = image([(20, 70, 30, 30, (40, 40, 40))])
        with tempfile.TemporaryDirectory() as d:
            [g] = ff.residual(SPEC, {'rows': []}, image(), fig, crops=d)
            self.assertEqual([os.path.basename(c) for c in g['crops']], ['unexplained-1-source.png', 'unexplained-1-figma.png'])
            with open(g['crops'][1], 'rb') as f:
                self.assertEqual(ff.png_read(f.read())[:2], (40, 40))


class Cli(unittest.TestCase):
    """--pixels end to end on the stub: the elements build of fidelity_elements_test, a blend-mode
    style fault painted only into the "export", and a screenshot that is the faithful render."""

    def test_pixels_adds_unexplained_regions_to_the_report(self):
        sys.path.insert(0, os.path.join(ROOT, 'tests'))
        from fidelity_elements_test import Elements
        case = Elements('test_a_faithful_build_has_no_gaps')
        Elements.setUpClass()
        case.setUp()
        try:
            spec = case.spec
            vw, vh = int(spec['nodes'][0]['rect']['w']), int(spec['nodes'][0]['rect']['h'])
            blank = (vw, vh, bytearray([255] * vw * vh * 3))
            # The fault sits where no element of the fixture's right column is.
            fault = bytearray(blank[2])
            for y in range(900, 940):
                for x in range(900, 950):
                    fault[(y * vw + x) * 3:(y * vw + x) * 3 + 3] = bytes([20, 20, 20])
            d = case.tmp.name
            ff.png_write(os.path.join(d, 'page.png'), vw, vh, blank[2])
            ff.png_write(os.path.join(d, 'export.png'), vw, vh, fault)
            rep = case.check('--pixels', os.path.join(d, 'page.png'), '--figma-png', os.path.join(d, 'export.png'), '--crops', os.path.join(d, 'crops'))
            self.assertEqual(rep['rows'], [])
            self.assertEqual(len(rep['unexplained']), 1)
            self.assertEqual(len(rep['unexplained'][0]['crops']), 2)
        finally:
            case.tearDown()


if __name__ == '__main__':
    unittest.main()
