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
    'SKILL.md': 5650,
    'figma-worker.md': 5078,
}
# Reference bytes per combo in SKILL.md's "Per-task reference combos" list; an optional
# "(+ x if ...)" reference counts, since some workers load it.
COMBO_CAPS = {
    'Build screens': 24307,
    'Copy/text edit': 15888,
    'Component/variant/design-system': 20393,
    'Color/effects/prototype': 10111,
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

    def test_worker_template_has_the_planning_slots_and_assumptions(self):
        text = docs()['figma-worker.md']
        for slot in ('## Component plan', '## Reuse', '## Manifest', 'assumptions: [{nodeId, field, value, reason}]',
                     '__fx.audit', '--lib --file'):
            self.assertIn(slot, text)
        for step in ('DISCOVER', 'READ', 'PLAN', 'EXECUTE', 'VERIFY + RETRY', 'CHECKPOINT', 'REPORT'):
            self.assertRegex(text, rf'### \d\. {re.escape(step)}', step)


if __name__ == '__main__':
    unittest.main()
