#!/usr/bin/env python3
"""tests/api/drift.py and figma_api.mjs diff/runtime, offline: a stand-in npm serves a small
typings package, and a runtime_surface result is a hand-written one.

  python3 tests/drift_test.py
"""
import json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(ROOT, 'tests', 'api')
with open(os.path.join(API, 'typings.lock')) as _f:
    LOCK = _f.read().strip()

TYPINGS = '''interface PluginAPI {
  readonly apiVersion: '1.0.0'
  createFrame(): FrameNode
  createShinyThing(): FrameNode
}
interface FrameNode extends MinimalFillsMixin {
  readonly type: 'FRAME'
}
interface MinimalFillsMixin {
  fills: ReadonlyArray<Paint>
  setFillsAsync(paints: ReadonlyArray<Paint>): Promise<void>
}
'''

FAKE_NPM = r'''import io, os, sys, tarfile
a = sys.argv[1:]
if a[0] == 'view':
    print(os.environ['FAKE_NPM_LATEST'])
elif a[0] == 'pack':
    name = 'figma-plugin-typings-' + a[1].rsplit('@', 1)[1] + '.tgz'
    with tarfile.open(name, 'w:gz') as t:
        data = open(os.environ['FAKE_NPM_TYPINGS'], 'rb').read()
        info = tarfile.TarInfo('package/plugin-api.d.ts'); info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    print(name)
'''


class Drift(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.npm = os.path.join(self.tmp, 'npm')
        with open(self.npm, 'w') as f:
            f.write(f'#!{sys.executable}\n' + FAKE_NPM)
        os.chmod(self.npm, 0o755)
        self.typings = os.path.join(self.tmp, 'plugin-api.d.ts')
        with open(self.typings, 'w') as f:
            f.write(TYPINGS)
        self.home = os.path.join(self.tmp, 'home')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def drift(self, *args, latest=LOCK):
        return subprocess.run([sys.executable, os.path.join(API, 'drift.py'), *args], capture_output=True, text=True,
                              env={**os.environ, 'FIGMA_API_NPM': self.npm, 'FAKE_NPM_LATEST': latest,
                                   'FAKE_NPM_TYPINGS': self.typings, 'FIGMA_CDP_HOME': self.home})

    def test_check_says_whether_the_lock_is_current(self):
        p = self.drift('check')
        self.assertEqual(p.returncode, 0, p.stderr)
        p = self.drift('check', latest='9.9.9')
        self.assertEqual(p.returncode, 1)
        self.assertIn('run drift.py bump 9.9.9', p.stdout)

    def test_a_bump_opens_a_case_with_the_diff(self):
        p = self.drift('bump', latest='9.9.9')
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual((out['version'], out['added']), ('9.9.9', 1))
        d = os.path.join(self.home, 'inbox', out['case'])
        with open(os.path.join(d, 'case.json')) as f:
            case = json.load(f)
        self.assertIn(f'plugin typings 9.9.9 (locked {LOCK})', case['symptom'])
        with open(os.path.join(d, 'notes.md')) as f:
            notes = f.read()
        self.assertIn('- added (1): PluginAPI.createShinyThing', notes)
        self.assertIn('developers.figma.com/docs/plugins/updates', notes)

    def test_bumping_to_the_locked_version_is_refused(self):
        self.assertEqual(self.drift('bump', LOCK).returncode, 1)


class Diff(unittest.TestCase):
    def node(self, *args):
        p = subprocess.run(['node', os.path.join(API, 'figma_api.mjs'), *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_diff_lists_added_removed_and_readonly_changes(self):
        with tempfile.TemporaryDirectory() as d:
            old, new = os.path.join(d, 'old.d.ts'), os.path.join(d, 'new.d.ts')
            with open(old, 'w') as f:
                f.write('interface A {\n  x: number\n  y: number\n  /** @deprecated no */\n  z: number\n}\n')
            with open(new, 'w') as f:
                f.write('interface A {\n  readonly x: number\n  /**\n   * @deprecated use w\n   */\n  y: number\n  w(): void\n}\n')
            self.assertEqual(self.node('diff', old, new, '--json'),
                             {'added': ['A.w'], 'removed': ['A.z'], 'readonly': ['A.x'], 'writable': [], 'deprecated': ['A.y']})

    def test_runtime_names_untyped_members_and_readonly_disagreements(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'r.json')
            with open(path, 'w') as f:
                json.dump({'notes': {'FrameNode': {'fills': 'prop', 'secretThing': 'prop', 'overlayPositionType': 'prop', 'setFillsAsync': 'method'}}}, f)
            r = self.node('runtime', path, '--json')['FrameNode']
        self.assertEqual(r['untyped'], ['secretThing'])
        self.assertEqual(r['writableAtRuntime'], ['overlayPositionType'])
        self.assertIn('resize', r['missing'])
        self.assertNotIn('fills', r['missing'])


if __name__ == '__main__':
    unittest.main()
