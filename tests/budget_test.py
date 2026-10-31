#!/usr/bin/env python3
"""Byte caps on what the skill loads into context, the cheapest proxy for its token cost.

SKILL.md loads into every conversation the skill triggers in, figma-worker.md into every
worker, and each per-task reference combo listed in SKILL.md into every worker given that
task. A change may shrink any of them; growing one past its cap fails here. When a change
shrinks a file, lower its cap to the new size in the same change, so the room it freed
can't be spent silently later.

It also lints the runtime docs (Docs): every reference listed in SKILL.md's table, helpers
run from the skill directory, one rule for variant property timing, the worker's slots.

  python3 tests/budget_test.py
"""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILE_CAPS = {
    'SKILL.md': 6512,
    'figma-worker.md': 6984,
}
# Reference bytes per combo in SKILL.md's "Per-task reference combos" list; an optional
# "(+ x if ...)" reference counts, since some workers load it.
COMBO_CAPS = {
    'Build screens': 27476,
    'Copy/text edit': 15888,
    'Component/variant/design-system': 23256,
    'Color/effects/prototype': 16198,
}


def size(rel):
    return os.path.getsize(os.path.join(ROOT, rel))


def combos():
    with open(os.path.join(ROOT, 'SKILL.md')) as f:
        text = f.read()
    start = text.index('Per-task reference combos')
    out = {}
    for line in text[start:].splitlines()[1:]:
        if not line.startswith('- '):
            break
        name, rest = line[2:].split(':', 1)
        out[name.strip()] = [t for t in re.findall(r'[a-z][a-z-]*', rest)
                             if os.path.isfile(os.path.join(ROOT, 'references', t + '.md'))]
    return out


class Budget(unittest.TestCase):
    def test_always_loaded_files_stay_under_their_caps(self):
        for rel, cap in FILE_CAPS.items():
            n = size(rel)
            self.assertLessEqual(n, cap, f'{rel} is {n} bytes, cap {cap}: it loads every time, cut before adding')

    def test_every_combo_has_a_cap(self):
        self.assertEqual(sorted(combos()), sorted(COMBO_CAPS),
                         'SKILL.md combo list changed: give each combo a cap at its current size')

    def test_combos_stay_under_their_caps(self):
        for name, refs in combos().items():
            self.assertGreaterEqual(len(refs), 2, f'{name}: parsed only {refs}')
            n = sum(size(f'references/{r}.md') for r in refs)
            self.assertLessEqual(n, COMBO_CAPS[name], f"{name} ({' + '.join(refs)}) is {n} bytes, cap {COMBO_CAPS[name]}")

    def test_combos_name_only_existing_references(self):
        with open(os.path.join(ROOT, 'SKILL.md')) as f:
            text = f.read()
        block = text[text.index('Per-task reference combos'):].split('\n\n')[0]
        for name in re.findall(r'(?<=[:+] )([a-z][a-z-]+)', block):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, 'references', name + '.md')), f'combo names {name}')


def docs():
    """Every runtime doc the skill can load: SKILL.md, figma-worker.md, references/*.md."""
    out = {'SKILL.md': None, 'figma-worker.md': None}
    out.update({f'references/{n}': None for n in os.listdir(os.path.join(ROOT, 'references')) if n.endswith('.md')})
    for rel in out:
        with open(os.path.join(ROOT, rel)) as f:
            out[rel] = f.read()
    return out


class Docs(unittest.TestCase):
    """The runtime docs agree with each other and with how the helpers run."""

    def test_every_reference_is_in_the_skill_table_and_exists(self):
        text = docs()['SKILL.md']
        listed = set(re.findall(r'^\| `references/([a-z-]+\.md)` \|', text, re.M))
        present = {n for n in os.listdir(os.path.join(ROOT, 'references')) if n.endswith('.md')}
        self.assertEqual(listed, present, 'SKILL.md references table and references/ differ')

    def test_helpers_run_from_the_skill_dir(self):
        for rel, text in docs().items():
            self.assertIsNone(re.search(r'/tmp/figma_(run|batch_run|capture|perch|lib|source|fidelity)\b', text),
                              f'{rel} still runs or copies a helper in /tmp')

    def test_one_rule_for_when_variant_properties_are_added(self):
        for rel, text in docs().items():
            self.assertNotRegex(text, r'(?i)properties\W+BEFORE\W+`?combineAsVariants', rel)

    def test_an_edit_patches_in_place_before_any_component_plan(self):
        text = docs()['SKILL.md']
        flow = text[text.index('## Flow'):text.index('## Work decomposition')]
        edit = re.search(r'(?i)\bedit\b[^\n]*"make it match"[^\n]*', flow)
        self.assertIsNotNone(edit, 'Flow has no rule for an edit or "make it match" task')
        self.assertLess(edit.start(), flow.index('**Component plan'), 'the edit rule must come before the component plan')
        self.assertRegex(edit.group(0), r'(?i)in place')
        self.assertRegex(edit.group(0), r'(?i)never[^.]*(replace|remove)[^.]*instance')

    def test_an_edit_reads_its_target_with_props_in_the_recon_call(self):
        text = docs()['SKILL.md']
        edit = next(l for l in text.splitlines() if '"make it match"' in l)
        self.assertRegex(edit, r'recon\(\{nodeId[^)]*props: true\}\)', 'an edit reads its target without layout, paints and effects')
        self.assertRegex(edit, r'(?i)step 3.s call', 'the props read is a second call instead of part of recon')

    def test_section_pointers_resolve(self):
        for rel, text in docs().items():
            for ref, sec in re.findall(r'`references/([a-z-]+\.md)` → ([A-Z][\w-]*(?: [\w-]+)*)', text):
                heads = [h.strip().lower() for h in re.findall(r'^#+ (.+)$', docs()['references/' + ref], re.M)]
                self.assertTrue(any(h.startswith(sec.lower()) or sec.lower().startswith(h) for h in heads), f'{rel} points at {ref} → {sec}, no such section')

    def test_a_repeated_pattern_has_a_recipe_that_links_the_copies(self):
        plan = next(l for l in docs()['SKILL.md'].splitlines() if '**Component plan' in l)
        self.assertIn('PATTERN the task touches becomes a component first. Recipe: `references/building.md` → Repeated patterns', plan)
        text = docs()['references/building.md']
        sec = text[text.index('## Repeated patterns'):].split('\n## ')[0]
        self.assertIn('createComponentFromNode', sec)
        self.assertRegex(sec, r'(?i)best match[^.]*source', 'which copy becomes the master')
        self.assertRegex(sec, r'(?i)same structure[^.]*swap|swap[^.]*same structure', 'copies swap only when their structure matches')
        self.assertRegex(sec, r'(?i)override[^.]*(text|characters)[^.]*fill[^.]*visib', 'a copy keeps its differences as overrides')
        self.assertRegex(sec, r'(?i)position and size', 'a swapped copy keeps its place')
        self.assertRegex(sec, r'(?i)leave it raw[^.]*(say|report)', 'a copy that does not match stays and is reported')
        self.assertRegex(sec, r'(?i)re-?read|fidelity', 'the screen is checked after the swap')
        self.assertRegex(sec, r'(?i)source names?[^.]*manifest[^.]*`?size=sm\|lg`?', 'variant values are named as the source names them')
        self.assertRegex(sec, r'(?i)part[^.]*itself a source component[^.]*instance[^.]*variant', 'nested source components stay paint overrides')
        self.assertRegex(sec, r'(?i)keep[^.]*propert[^.]*as (it is|they are)[^.]*(report|say)', 'promotion fixes what the task did not ask for')
        self.assertIn('__fx.linkCopies(', sec, 'the recipe has the agent write the promote and swap by hand')
        self.assertIn('linkCopies(', docs()['figma-worker.md'], 'the worker sheet does not list linkCopies')
        self.assertIn('__fx.linkCopies(', docs()['references/execution.md'])
        check = next(l for l in sec.splitlines() if '**Check:**' in l)
        self.assertRegex(check, r'(?i)same eval[^.]*only the lines that (differ|changed)', 'the check returns whole trees')
        use = next(l for l in sec.splitlines() if '**Use it:**' in l)
        self.assertRegex(use, r'(?i)new screen[^.]*sizing from the source[^.]*instance override', 'new instances inherit the copy\'s sizing')
        self.assertRegex(use, r'(?i)report[^.]*master', 'the master\'s gap goes unreported')

    def test_the_manifest_is_read_instead_of_the_source_files(self):
        step = next(l for l in docs()['SKILL.md'].splitlines() if l.startswith('2. **Source.'))
        self.assertRegex(step, r'(?i)read the manifest[^.]*not the source files', 'the source is cat whole beside its manifest')
        self.assertRegex(step, r'(?i)markup', 'a screen\'s markup is still read from its file')
        fid = docs()['references/fidelity.md']
        self.assertRegex(fid, r'`css`[^.]*selector[^.]*declarations', 'the manifest docs do not say what css holds')

    def test_worker_names_variants_from_the_source_and_reads_async(self):
        worker = docs()['figma-worker.md']
        line = next(l for l in worker.splitlines() if l.startswith('Variants:'))
        self.assertNotIn('Size=Md', line, 'the example invents variant values')
        self.assertRegex(line, r"(?i)source's names", 'clones are not named from the source')
        for call in ('getNodeByIdAsync', 'getMainComponentAsync', 'figma.variables.getLocalVariablesAsync'):
            self.assertIn(call, worker, f'the worker sheet does not name {call} for dynamic-page reads')

    def test_flex_default_stretch_maps_to_fill_across(self):
        conv = docs()['references/conventions.md']
        row = next((l for l in conv.splitlines() if 'stretch' in l.lower() and 'align-items' in l), '')
        self.assertRegex(row, r'(?i)no `?align-items`?[^|]*\|[^|]*FILL', 'default cross-axis stretch has no mapping')
        self.assertRegex(row, r'(?i)align-self[^|]*(start|center|end)[^|]*HUG|HUG[^|]*align-self', 'an align-self opt-out is not HUG')
        self.assertRegex(row, r'(?i)inline-flex[^|]*inline-block|inline-block[^|]*inline-flex', 'inline-level flex items are not said to stretch too')
        self.assertIn('blockif', row, 'the row does not say a flex parent blockifies its items')

    def test_rooms_are_preferred_unattended_and_never_fall_back(self):
        d = docs()
        skill = d['SKILL.md']
        for word in ('room', '--where', 'signed_out', 'locked'):
            self.assertIn(word, skill, f'SKILL.md Setup does not mention {word}')
        conn = d['references/connection.md']
        self.assertRegex(conn, r'(?i)### Mode R[^\n]*room', 'connection.md has no room mode')
        self.assertRegex(conn, r'(?i)minimized or (the screen )?locked', 'connection.md does not say a room runs locked')
        self.assertIn('rooms view', conn)
        self.assertRegex(d['figma-worker.md'], r'signed_out[^\n]*BLOCKED', 'the worker sheet does not stop on a signed-out room')

    def test_the_brief_copies_stretched_usages_from_the_manifest(self):
        d = docs()
        self.assertRegex(d['SKILL.md'], r'`fill`[^.]*FILL across', 'SKILL.md does not have the brief copy the manifest fill list')
        self.assertIn('fill?', d['references/fidelity.md'], 'fidelity.md does not document a component\'s fill list')

    def test_capture_inline_exception_is_for_block_parents_only(self):
        cap = docs()['references/capture.md']
        row = next((l for l in cap.splitlines() if 'not inline-level' in l), '')
        self.assertIn('blockif', row, 'capture.md reads inline-level flex items as not stretching')

    def test_variant_axes_come_from_manifest_variants_and_states(self):
        text = docs()['references/building.md']
        sec = text[text.index('## Repeated patterns'):].split('\n## ')[0]
        self.assertRegex(sec, r"manifest's `variants` and `states`", 'states the source names are left out of the axes')
        worker = docs()['figma-worker.md']
        line = next(l for l in worker.splitlines() if l.startswith('Variants:'))
        self.assertRegex(line, r"manifest's `variants` and `states`")

    def test_worker_builds_icons_with_fx_icon_only(self):
        worker = docs()['figma-worker.md']
        line = next(l for l in worker.splitlines() if 'icon(svg' in l)
        self.assertRegex(line, r'(?i)never by hand', 'a hand-built icon has no auto layout')

    def test_component_plan_covers_the_manifest_components_and_containers(self):
        plan = next(l for l in docs()['SKILL.md'].splitlines() if '**Component plan' in l)
        self.assertRegex(plan, r'manifest `components` entry', 'the plan does not start from the manifest components')
        self.assertRegex(plan, r'(?i)container[^.;]*still a component[^.;]*header[^.;]*createSlot',
                         'a container whose content varies per use is left as plain frames')
        self.assertRegex(plan, r'(?i)wrapper of repeated items[^.;]*instances')
        self.assertRegex(plan, r'(?i)repeating 2\+ times, existing screens too',
                         'a unit shared with a screen already in the file is not counted as repeated')
        reuse = re.search(r'REUSE `<id>` as is[^.]*', plan)
        self.assertIsNotNone(reuse, 'a reused inventory component is not instantiated as is')
        self.assertRegex(reuse.group(0), r'(?i)per-use[^.;]*instance overrides', 'per-use differences are not overrides')
        self.assertRegex(reuse.group(0), r'(?i)never[^.;]*renam[^.;]*variant[^.;]*set[^.;]*unless',
                         'nothing stops a reused component from being renamed, given variants or made a set')
        self.assertIn('`components` `[{component, uses, nests, src, css?, fill?}]`', docs()['references/fidelity.md'])

    def test_audit_gates_only_what_the_session_built(self):
        gate = next(l for l in docs()['SKILL.md'].splitlines() if 'Final gate' in l)
        self.assertRegex(gate, r'(?i)(all 0|empty)[^.]*(you|it) (built|created|added)', 'gate demands a clean audit on an edit too')
        worker = docs()['figma-worker.md']
        fix = next(l for l in worker.splitlines() if l.startswith('Fix ONLY'))
        self.assertRegex(fix, r'(?i)audit (counts|lines) on nodes you (built|created)', 'worker chases counts it did not cause')

    def test_worker_template_has_the_planning_slots_and_assumptions(self):
        text = docs()['figma-worker.md']
        for slot in ('## Component plan', '## Reuse', '## Manifest', 'assumptions: [{nodeId, field, value, reason}]',
                     '__fx.audit', '--lib --file'):
            self.assertIn(slot, text)
        for step in ('DISCOVER', 'READ', 'PLAN', 'EXECUTE', 'VERIFY + RETRY', 'CHECKPOINT', 'REPORT'):
            self.assertRegex(text, rf'### \d\. {re.escape(step)}', step)


if __name__ == '__main__':
    unittest.main()
