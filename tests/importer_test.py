#!/usr/bin/env python3
"""Offline tests for the capture import: figma_capture.py's componentize pass and
figma_importer.js's sizing, constraints and component output.

No Figma: tests/import_replay.js replays `figma_capture.py import --dry-run` evals against
the stub Plugin API in tests/figma_stub.js and dumps the resulting node tree.
tests/capture_spec.json is a hand-built walker spec mirroring tests/capture_fixture.html.

  python3 tests/importer_test.py
"""
import copy, json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, 'tests', 'capture_spec.json')
sys.path.insert(0, ROOT)
import figma_capture  # noqa: E402


def load_spec():
    with open(SPEC) as f:
        return json.load(f)


def run_stub(spec_path, *flags):
    with tempfile.TemporaryDirectory() as d:
        dump = os.path.join(d, 'tree.json')
        r = subprocess.run(['node', os.path.join(ROOT, 'tests', 'import_replay.js'), spec_path,
                            '--dump', dump, *flags], capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(f'import_replay exit {r.returncode}\n{r.stdout}\n{r.stderr}')
        with open(dump) as f:
            out = json.load(f)
    byId = {}

    def index(n):
        byId[n['id']] = n
        for c in n.get('children', []):
            index(c)
    for n in out['tree']:
        index(n)
    out['node'] = lambda i: byId[out['ids'][str(i)]]
    out['all'] = list(byId.values())
    return out


def run_edited(edit, *flags):
    """Run the stub on a copy of capture_spec.json changed by edit(nodes)."""
    spec = load_spec()
    edit(spec['nodes'])
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(spec, f)
    try:
        return spec, run_stub(f.name, *flags)
    finally:
        os.unlink(f.name)


def lis_of(nodes):
    return [n for n in nodes if n['tag'] == 'li']


def idx(spec, ax):
    return next(n['i'] for n in spec['nodes'] if n['axName'] == ax)


class Sizing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_spec()
        cls.out = run_stub(SPEC)

    def sizing(self, i):
        return self.out['node'](i)['sizing']

    def test_no_warnings(self):
        self.assertEqual(self.out['report']['warnings'], [])

    def test_auto_width_in_flow_stretches_and_auto_height_hugs(self):
        self.assertEqual(self.sizing(idx(self.spec, 'card-list')), ['FILL', 'HUG'])
        self.assertEqual(self.sizing(idx(self.spec, 'root')), ['FILL', 'HUG'])

    def test_parent_of_a_filling_child_keeps_its_captured_size(self):
        row = self.out['node'](idx(self.spec, 'flex-row'))
        self.assertEqual(row['sizing'], ['FILL', 'FIXED'])
        self.assertEqual(row['height'], 80)

    def test_root_keeps_its_captured_width(self):
        self.assertEqual(self.sizing(0), ['FIXED', 'HUG'])

    def test_flex_grow_and_pct_fill_px_stays_fixed(self):
        self.assertEqual(self.sizing(idx(self.spec, 'grow-card')), ['FILL', 'FILL'])
        self.assertEqual(self.sizing(idx(self.spec, 'px-card')), ['FIXED', 'FILL'])
        self.assertEqual(self.sizing(idx(self.spec, 'pct-card')), ['FILL', 'FILL'])

    def test_unstretched_single_line_textbox_hugs(self):
        button = next(n for n in self.spec['nodes'] if n['tag'] == 'button')
        self.assertEqual(self.sizing(button['i']), ['HUG', 'HUG'])

    def test_leaf_frames_never_hug(self):
        self.assertEqual(self.sizing(idx(self.spec, 'overlay')), ['FIXED', 'FIXED'])

    def test_wrapping_text_fills_its_stretched_slot(self):
        card = next(n for n in self.spec['nodes'] if n['tag'] == 'li')
        body = next(n for n in self.spec['nodes'] if n['parent'] == card['i'] and n['tag'] == 'p')
        node = self.out['node'](body['i'])
        self.assertEqual(node['type'], 'TEXT')
        self.assertEqual(node['sizing'][0], 'FILL')

    def test_frame_with_only_positioned_children_keeps_its_height(self):
        def all_absolute(nodes):
            nodes[7]['styles']['position'] = 'absolute'
        for flags in [(), ('--chunk-bytes', '1500')]:
            spec, out = run_edited(all_absolute, *flags)
            self.assertEqual(out['node'](idx(spec, 'abs-parent'))['sizing'], ['FILL', 'FIXED'])
            self.assertEqual(out['node'](idx(spec, 'card-list'))['sizing'], ['FILL', 'HUG'])

    def test_wrapping_row_never_hugs_its_width(self):
        def wrap(nodes):
            nodes[44]['styles'].update(flexWrap='wrap', alignSelf='flex-start')
        spec, out = run_edited(wrap)
        self.assertEqual(out['node'](44)['sizing'], ['FIXED', 'HUG'])

    def test_no_legacy_layout_fields(self):
        for n in self.out['all']:
            self.assertEqual(n.get('layoutGrow', 0), 0, n['name'])
            self.assertEqual(n.get('layoutAlign', 'INHERIT'), 'INHERIT', n['name'])


class Constraints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_spec()
        cls.out = run_stub(SPEC)

    def node(self, ax):
        return self.out['node'](idx(self.spec, ax))

    def test_right_top_badge_is_absolute_and_pinned_right(self):
        n = self.node('abs-child')
        self.assertEqual(n['positioning'], 'ABSOLUTE')
        self.assertEqual(n['constraints'], ['MAX', 'MIN'])

    def test_both_edges_stretch(self):
        self.assertEqual(self.node('overlay')['constraints'], ['STRETCH', 'STRETCH'])

    def test_centered_and_bottom(self):
        self.assertEqual(self.node('centered')['constraints'], ['CENTER', 'MAX'])

    def test_absolute_child_of_none_parent(self):
        n = self.node('grid-pin')
        self.assertEqual(n['positioning'], 'AUTO')
        self.assertEqual(n['constraints'], ['MAX', 'MAX'])

    def test_in_flow_children_keep_default_constraints(self):
        self.assertEqual(self.node('px-card')['constraints'], ['MIN', 'MIN'])


class Annotate(unittest.TestCase):
    def setUp(self):
        self.spec = load_spec()

    def groups(self, nodes):
        figma_capture.componentize(nodes)
        return sorted(n['i'] for n in nodes if n.get('rep') and 'name' in n['rep'])

    def test_cards_and_cousin_stats_become_components(self):
        nodes = self.spec['nodes']
        masters = self.groups(nodes)
        tags = [nodes[i]['tag'] for i in masters]
        self.assertEqual(sorted(tags), ['div', 'li'])
        li = next(nodes[i] for i in masters if nodes[i]['tag'] == 'li')
        self.assertEqual(li['rep'], {'m': li['i'], 'name': 'listitem'})
        stat = next(nodes[i] for i in masters if nodes[i]['tag'] == 'div')
        self.assertEqual(stat['rep']['name'], 'stat')

    def test_only_varying_text_becomes_a_property(self):
        nodes = self.spec['nodes']
        figma_capture.componentize(nodes)
        li = next(n for n in nodes if n['tag'] == 'li')
        kids = [n for n in nodes if n['parent'] == li['i']]
        self.assertEqual([k['rep'].get('prop') for k in kids], ['heading', 'p', None])
        self.assertTrue(all(k['rep']['c'] == li['i'] for k in kids))

    def test_other_members_point_at_master_layers(self):
        nodes = self.spec['nodes']
        figma_capture.componentize(nodes)
        lis = [n for n in nodes if n['tag'] == 'li']
        self.assertEqual(lis[2]['rep'], {'m': lis[0]['i']})
        kid = next(n for n in nodes if n['parent'] == lis[2]['i'])
        self.assertEqual(kid['rep'], {'src': lis[0]['i'] + 1, 'in': lis[2]['i']})

    def test_style_difference_splits_a_group(self):
        nodes = self.spec['nodes']
        self.groups(nodes)
        chips = [n for n in nodes if n['parent'] == idx(self.spec, 'chips')]
        self.assertTrue(all('rep' not in n for n in chips))

    def test_two_members_are_not_enough(self):
        nodes = self.spec['nodes']
        lis = [n['i'] for n in nodes if n['tag'] == 'li']
        drop = set(range(lis[2], lis[2] + 8))  # the last two cards and their kids
        kept = [copy.deepcopy(n) for n in nodes if n['i'] not in drop]
        for k, n in enumerate(kept):
            n['i'] = k
        remap = {old: k for k, old in enumerate(n0['i'] for n0 in nodes if n0['i'] not in drop)}
        for n, old in zip(kept, [n0 for n0 in nodes if n0['i'] not in drop]):
            n['parent'] = remap.get(old['parent'], -1)
        masters = self.groups(kept)
        self.assertEqual([kept[i]['tag'] for i in masters], ['div'])

    def split_off(self, edit):
        """Mark after edit(nodes); return which li cards stayed in the group."""
        nodes = self.spec['nodes']
        edit(nodes)
        figma_capture.componentize(nodes)
        return ['rep' in li for li in lis_of(nodes)]

    def test_transform_splits_a_member(self):
        def tilt(ns):
            lis_of(ns)[1]['xf'] = [0.98, 0.17, -0.17, 0.98, 0, 0]
        self.assertEqual(self.split_off(tilt), [True, False, True, True])

    def test_wrapping_text_splits_a_member(self):
        def wrap(ns):
            ns[lis_of(ns)[2]['i'] + 2]['lines'] = 2
        self.assertEqual(self.split_off(wrap), [True, True, False, True])

    def test_fixed_size_difference_splits_a_member(self):
        def fixed(ns):
            for li in lis_of(ns):
                ns[li['i'] + 3]['styles']['sz'] = ['px', 'auto']
            ns[lis_of(ns)[3]['i'] + 3]['rect']['w'] = 120
        self.assertEqual(self.split_off(fixed), [True, True, True, False])

    def test_offset_outside_auto_layout_splits_a_member(self):
        def grid(ns):
            for li in lis_of(ns):
                li['styles']['display'] = 'grid'
            ns[lis_of(ns)[1]['i'] + 3]['rect']['x'] += 40
        self.assertEqual(self.split_off(grid), [True, False, True, True])

    def test_image_mode_splits_a_member(self):
        def img(ns):
            for k, li in enumerate(lis_of(ns)):
                ns[li['i'] + 3]['image'] = {'asset': 'a1', 'mode': 'TILE' if k == 0 else 'FILL'}
        self.assertEqual(self.split_off(img), [False, True, True, True])

    def test_outermost_group_wins(self):
        nodes = self.spec['nodes']
        figma_capture.componentize(nodes)
        li = next(n for n in nodes if n['tag'] == 'li')
        button = next(n for n in nodes if n['parent'] == li['i'] and n['tag'] == 'button')
        self.assertNotIn('m', button['rep'])


class Componentize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_spec()
        cls.runs = [run_stub(SPEC, '--componentize'),
                    run_stub(SPEC, '--componentize', '--chunk-bytes', '1500')]

    def test_chunk_bytes_must_be_positive(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'figma_capture.py'), 'import', SPEC,
                            '--chunk-bytes', '0', '--dry-run', tempfile.gettempdir()],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('--chunk-bytes must be a positive', r.stderr)

    def test_off_by_default(self):
        out = run_stub(SPEC)
        types = [n['type'] for n in out['all']]
        self.assertNotIn('COMPONENT', types)
        self.assertNotIn('INSTANCE', types)

    def test_components_and_instances(self):
        for out in self.runs:
            comps = [n for n in out['all'] if n['type'] == 'COMPONENT']
            self.assertEqual(sorted(c['name'] for c in comps), ['listitem', 'stat'])
            insts = [n for n in out['all'] if n['type'] == 'INSTANCE']
            self.assertEqual(sorted(i['main'] for i in insts), ['listitem'] * 3 + ['stat'] * 2)
            self.assertEqual(out['report']['warnings'], [])
            self.assertEqual(len(out['report']['components']), 2)

    def test_text_overrides_land_on_instances(self):
        lis = [n for n in self.spec['nodes'] if n['tag'] == 'li']
        for out in self.runs:
            for li in lis:
                title = self.spec['nodes'][li['i'] + 1]
                node = out['node'](title['i'])
                self.assertEqual(node['characters'], title['text'])
            comp = out['node'](lis[0]['i'])
            self.assertEqual(sorted(comp['props']), ['heading', 'p'])
            self.assertEqual(comp['children'][0]['name'], '[cap:%d] heading' % (lis[0]['i'] + 1))

    def test_instances_sit_in_their_slots(self):
        lis = [n for n in self.spec['nodes'] if n['tag'] == 'li']
        for out in self.runs:
            parent = out['node'](lis[0]['parent'])
            kids = [c['type'] for c in parent['children']]
            self.assertEqual(kids, ['COMPONENT', 'INSTANCE', 'INSTANCE', 'INSTANCE'])
            self.assertEqual(out['node'](lis[1]['i'])['sizing'], ['FILL', 'HUG'])

    def test_every_capture_id_resolves(self):
        for out in self.runs:
            self.assertEqual(len(out['ids']), len(self.spec['nodes']))

    def run_marked(self, edit):
        spec = load_spec()
        figma_capture.componentize(spec['nodes'])
        edit(spec['nodes'])
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(spec, f)
        try:
            return spec, run_stub(f.name)
        finally:
            os.unlink(f.name)

    def test_members_of_a_missing_master_build_as_plain_frames(self):
        def drop_master(nodes):
            del next(n for n in nodes if n['tag'] == 'li')['rep']
        spec, out = self.run_marked(drop_master)
        lis = [n for n in spec['nodes'] if n['tag'] == 'li']
        self.assertEqual([out['node'](li['i'])['type'] for li in lis], ['FRAME'] * 4)
        self.assertEqual(out['node'](lis[1]['i'] + 1)['characters'], 'Beta')
        self.assertEqual(out['report']['warnings'], [])

    def test_text_without_a_property_is_overridden_directly(self):
        def drop_prop(nodes):
            del nodes[lis_of(nodes)[0]['i'] + 1]['rep']['prop']
        spec, out = self.run_marked(drop_prop)
        for li in lis_of(spec['nodes']):
            title = spec['nodes'][li['i'] + 1]
            self.assertEqual(out['node'](title['i'])['characters'], title['text'])
        self.assertEqual(out['report']['warnings'], [])

    def test_instances_hug_only_where_their_master_does(self):
        def pinned(ns):
            for li in lis_of(ns):
                for k in (1, 2, 3):
                    ns[li['i'] + k]['styles']['position'] = 'absolute'
        spec, out = run_edited(pinned, '--componentize')
        for li in lis_of(spec['nodes']):
            self.assertEqual(out['node'](li['i'])['sizing'], ['FILL', 'FIXED'])

    def test_mapped_category_root_stays_an_instance_of_that_component(self):
        spec, out = run_edited(lambda ns: None, '--componentize', '--stub-components', 'listitem')
        comps = [c['name'] for c in out['report']['components']]
        self.assertEqual(comps, ['stat'])
        lis = lis_of(spec['nodes'])
        self.assertEqual([out['node'](li['i']).get('main') for li in lis], ['listitem'] * 4)
        self.assertEqual(out['report']['warnings'], [])

    def test_mapped_category_inside_a_master_stays_a_nested_instance(self):
        def labels(ns):
            for li, word in zip(lis_of(ns), ['Open', 'Edit', 'View', 'Share']):
                ns[li['i'] + 3]['text'] = ns[li['i'] + 3]['axName'] = word
        for flags in [(), ('--chunk-bytes', '1500')]:
            spec, out = run_edited(labels, '--componentize', '--stub-components', 'button', *flags)
            for li in lis_of(spec['nodes']):
                button = out['node'](li['i'] + 3)
                self.assertEqual(button['type'], 'INSTANCE')
                self.assertEqual(button['main'], 'button')
                self.assertEqual(button['children'][0]['characters'], spec['nodes'][li['i'] + 3]['text'])
            self.assertEqual(out['report']['warnings'], [])

    def test_a_class_key_maps_the_elements_with_that_class(self):
        # The page's own components: cls is the element's class list as the walker records it.
        def classes(ns):
            for i in (3, 4, 5):
                ns[i]['cls'] = ['card', 'card--wide'] if i == 4 else ['card']
            ns[6]['cls'] = ['card']
        spec, out = run_edited(classes, '--stub-components', '.card,card')
        self.assertEqual([out['node'](i).get('main') for i in (3, 4, 5, 6)], ['.card'] * 4)
        self.assertEqual(out['node'](11).get('main'), 'card', 'an element without the class keeps its role category')
        self.assertEqual(out['report']['warnings'], [])

    def test_the_first_listed_class_key_wins(self):
        def classes(ns):
            ns[4]['cls'] = ['card', 'tile']
        spec, out = run_edited(classes, '--stub-components', '.tile,.card')
        self.assertEqual(out['node'](4).get('main'), '.tile')

    def test_unmatched_instance_layer_is_built_loose(self):
        def break_layer(nodes):
            li = [n for n in nodes if n['tag'] == 'li'][1]
            nodes[li['i'] + 1]['rep']['src'] = 0
        spec, out = self.run_marked(break_layer)
        li = [n for n in spec['nodes'] if n['tag'] == 'li'][1]
        node = out['node'](li['i'] + 1)
        self.assertEqual(node['characters'], 'Beta')
        self.assertIn(node['id'], [n['id'] for n in out['tree']])
        self.assertEqual(len(out['report']['warnings']), 1)


if __name__ == '__main__':
    unittest.main()
