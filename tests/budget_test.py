#!/usr/bin/env python3
"""Byte caps on what the skill loads into context, the cheapest proxy for its token cost.

SKILL.md loads into every conversation the skill triggers in, figma-worker.md into every
worker, and each per-task reference combo listed in SKILL.md into every worker given that
task. A change may shrink any of them; growing one past its cap fails here. When a change
shrinks a file, lower its cap to the new size in the same change, so the room it freed
can't be spent silently later.

  python3 tests/budget_test.py
"""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILE_CAPS = {
    'SKILL.md': 9749,
    'figma-worker.md': 5084,
}
# Reference bytes per combo in SKILL.md's "Per-task reference combos" list; an optional
# "(+ x if ...)" reference counts, since some workers load it.
COMBO_CAPS = {
    'Build screens': 42645,
    'Copy/text edit': 31043,
    'Component/variant/design-system': 35861,
    'Color/effects/prototype': 31426,
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


if __name__ == '__main__':
    unittest.main()
