#!/usr/bin/env python3
"""install.sh, run as `curl ... | bash` runs it (the script on stdin), with a temp HOME and
FIGMA_CDP_REPO on a file:// clone of this repo: the clone and the Claude link land, a second
run changes nothing, and a directory or a link to somewhere else is left in place.

  python3 tests/install_test.py
"""
import os, shutil, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERCH_HINT = 'curl -fsSL https://raw.githubusercontent.com/sryo/perch/main/install.sh | bash'


class Install(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='figma-cdp-install-')
        cls.origin = os.path.join(cls.tmp, 'origin.git')
        subprocess.run(['git', 'clone', '--quiet', '--bare', ROOT, cls.origin], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def setUp(self):
        self.home = tempfile.mkdtemp(dir=self.tmp)
        self.skill = os.path.join(self.home, '.agents', 'skills', 'figma-cdp')
        self.link = os.path.join(self.home, '.claude', 'skills', 'figma-cdp')

    def run_install(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('FIGMA_CDP_', 'PERCH_', 'GIT_'))}
        env.update(HOME=self.home, FIGMA_CDP_REPO='file://' + self.origin)
        with open(os.path.join(ROOT, 'install.sh')) as script:
            p = subprocess.run(['bash'], stdin=script, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout

    def test_installs_then_is_idempotent(self):
        out = self.run_install()
        self.assertTrue(os.path.isfile(os.path.join(self.skill, 'SKILL.md')))
        self.assertEqual(os.readlink(self.link), self.skill)
        self.assertIn(PERCH_HINT, out)
        self.assertIn('personal access token', out)
        head = subprocess.run(['git', '-C', self.skill, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout
        out = self.run_install()
        self.assertIn('pulling latest', out)
        self.assertIn('already links to', out)
        self.assertEqual(os.readlink(self.link), self.skill)
        self.assertEqual(subprocess.run(['git', '-C', self.skill, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout, head)

    def test_perch_found_skips_the_hint(self):
        os.makedirs(os.path.join(self.home, '.perch'))
        open(os.path.join(self.home, '.perch', 'server.js'), 'w').close()
        self.assertNotIn(PERCH_HINT, self.run_install())

    def test_leaves_a_directory_in_place(self):
        os.makedirs(self.link)
        out = self.run_install()
        self.assertFalse(os.path.islink(self.link))
        self.assertIn("exists and isn't a link; leaving it", out)

    def test_leaves_a_link_elsewhere_in_place(self):
        other = os.path.join(self.home, 'other')
        os.makedirs(os.path.dirname(self.link))
        os.symlink(other, self.link)
        out = self.run_install()
        self.assertEqual(os.readlink(self.link), other)
        self.assertIn('links to %s, not %s; leaving it' % (other, self.skill), out)

    def test_an_install_elsewhere_is_not_cloned_again(self):
        other = os.path.join(self.home, 'Documents', 'figma-cdp')
        os.makedirs(other)
        open(os.path.join(other, 'SKILL.md'), 'w').close()
        os.makedirs(os.path.dirname(self.link))
        os.symlink(other, self.link)
        out = self.run_install()
        self.assertIn('already installed', out)
        self.assertFalse(os.path.exists(self.skill))
        self.assertEqual(os.readlink(self.link), other)


if __name__ == '__main__':
    unittest.main()
