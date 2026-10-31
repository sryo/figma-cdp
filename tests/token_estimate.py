#!/usr/bin/env python3
"""What a docs change costs before any live run: always-loaded bytes, priced by turns.

  python3 tests/token_estimate.py [<base-rev>]        default: the commit that last refreshed baseline.json

Each turn of a session re-reads the always-loaded docs (SKILL.md, figma-worker.md) from cache, so
a change of d bytes costs about d / 4 tokens per turn. Summed over the tasks the change can move
(affects.json, through case.affected) at baseline.json's median turns, that is the expected token
delta per rep set. References a task reads on demand are not counted: they cost once, not per turn.
"""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALWAYS = ('SKILL.md', 'figma-worker.md')


def estimate(dbytes, tasks, baseline):
    """Tokens a set of byte changes {file: delta} adds over tasks at their median turns."""
    loaded = sum(d for f, d in dbytes.items() if f in ALWAYS)
    turns = sum(baseline['tasks'].get(t, {}).get('median', {}).get('turns', 0) for t in tasks)
    return round(loaded / 4 * turns)


def size_at(rev, path):
    r = subprocess.run(['git', '-C', ROOT, 'cat-file', '-s', f'{rev}:{path}'], capture_output=True, text=True)
    return int(r.stdout) if r.returncode == 0 else 0


def main():
    rev = sys.argv[1] if len(sys.argv) > 1 else subprocess.run(
        ['git', '-C', ROOT, 'log', '-1', '--format=%h', '--', 'tests/eval/baseline.json'], capture_output=True, text=True).stdout.strip()
    files = subprocess.run(['git', '-C', ROOT, 'diff', '--name-only', rev], capture_output=True, text=True).stdout.split()
    sys.path.insert(0, os.path.join(ROOT, 'tests', 'cases'))
    import case
    with open(os.path.join(ROOT, 'tests', 'eval', 'baseline.json')) as f:
        baseline = json.load(f)
    dbytes = {f: (os.path.getsize(os.path.join(ROOT, f)) if os.path.exists(os.path.join(ROOT, f)) else 0) - size_at(rev, f) for f in files}
    tasks = case.affected(files, ROOT)
    for f in ALWAYS:
        if dbytes.get(f):
            print(f'{f}: {dbytes[f]:+d} bytes')
    print(f"since {rev}: tasks {', '.join(tasks) or 'none'}; about {estimate(dbytes, tasks, baseline):+d} tokens per rep set from always-loaded docs")


if __name__ == '__main__':
    main()
