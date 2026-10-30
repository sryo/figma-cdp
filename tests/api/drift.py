#!/usr/bin/env python3
"""Notice when Figma ships new plugin typings, and open a case with what changed.

  python3 tests/api/drift.py check            # offline-safe: exit 0 when typings.lock is current, 1 when not
  python3 tests/api/drift.py bump [<version>] # fetch that version (default: the latest), diff it, open a case

check only asks npm for the latest @figma/plugin-typings version, so it can run on a schedule.
bump packs that version into a temp dir, diffs its plugin-api.d.ts against surface.json
(figma_api.mjs diff) and files a case (tests/cases/case.py new) whose notes hold the diff and
the changelog link. It changes nothing in the repo: the case's fix regenerates surface.json and
typings.lock, re-probes on the scratch file (figma_probe.py --record, then --pin for a verdict
that moved), and updates the references a changed member touches. FIGMA_API_NPM names the npm to
run (tests use a stand-in).
"""
import json, os, subprocess, sys, tarfile, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PKG = '@figma/plugin-typings'
CHANGELOG = 'https://developers.figma.com/docs/plugins/updates/'


def npm(*args, cwd=None):
    p = subprocess.run([os.environ.get('FIGMA_API_NPM', 'npm'), *args], capture_output=True, text=True, cwd=cwd, timeout=120)
    if p.returncode:
        sys.exit(f'drift.py: npm {" ".join(args)} failed: {(p.stderr or p.stdout).strip()[:300]}')
    return p.stdout.strip()


def locked():
    with open(os.path.join(HERE, 'typings.lock')) as f:
        return f.read().strip()


def latest():
    return npm('view', PKG, 'version').splitlines()[-1].strip()


def cmd_check():
    have, now = locked(), latest()
    print(f'typings.lock {have}, npm latest {now}' + ('' if have == now else f': run drift.py bump {now}'))
    sys.exit(0 if have == now else 1)


def cmd_bump(version):
    version = version or latest()
    if version == locked():
        sys.exit(f'drift.py: {version} is already locked')
    with tempfile.TemporaryDirectory() as d:
        name = npm('pack', f'{PKG}@{version}', '--silent', cwd=d).splitlines()[-1].strip()
        with tarfile.open(os.path.join(d, name)) as t:
            member = t.getmember('package/plugin-api.d.ts')
            with t.extractfile(member) as src, open(os.path.join(d, 'plugin-api.d.ts'), 'wb') as dst:
                dst.write(src.read())
        p = subprocess.run(['node', os.path.join(HERE, 'figma_api.mjs'), 'diff', os.path.join(HERE, 'surface.json'),
                            os.path.join(d, 'plugin-api.d.ts'), '--json'], capture_output=True, text=True)
    if p.returncode:
        sys.exit(f'drift.py: diff failed: {p.stderr.strip()[:300]}')
    d = json.loads(p.stdout)
    counts = ', '.join(f'{len(v)} {k}' for k, v in d.items() if v) or 'no member changes'
    symptom = f'plugin typings {version} (locked {locked()}): {counts}'
    case = subprocess.run([sys.executable, os.path.join(REPO, 'tests', 'cases', 'case.py'), 'new', '--symptom', symptom,
                           '--expected', f'surface.json and typings.lock at {version}, probes re-run, references updated'],
                          capture_output=True, text=True)
    if case.returncode:
        sys.exit(f'drift.py: case.py new failed: {case.stderr.strip()[:300]}')
    cid = json.loads(case.stdout)['case']
    home = os.environ.get('FIGMA_CDP_HOME') or os.path.expanduser('~/.figma-cdp')
    with open(os.path.join(home, 'inbox', cid, 'notes.md'), 'a') as f:
        f.write(f'\n## Typings diff {locked()} → {version}\n\nChangelog: {CHANGELOG}\n\n')
        for k, v in d.items():
            if v:
                f.write(f'- {k} ({len(v)}): ' + ', '.join(v) + '\n')
        f.write('\nRe-probe after regenerating surface.json: figma_probe.py --file <scratch> --record, and --pin a verdict that moved.\n')
    print(json.dumps({'case': cid, 'version': version, **{k: len(v) for k, v in d.items()}}))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('check', 'bump'):
        sys.exit(__doc__.strip().split('\n\n')[1])
    if sys.argv[1] == 'check':
        cmd_check()
    cmd_bump(sys.argv[2] if len(sys.argv) > 2 else None)


if __name__ == '__main__':
    main()
