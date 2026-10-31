#!/usr/bin/env python3
"""The live-run gate: fium price compare on run.py outputs.

  python3 tests/eval/gate.py [<baseline.json>] <candidate.json>

Writes both runs in fium's run format (compare.py's fium()), then runs
`fium price compare` with tests/eval/noise.json and the Price: trailers since the baseline's rev.
Exit as fium's: 0 better or same, 1 worse, a limit or a missing metric, 3 inconclusive.
compare.py's verdict follows as a reference that does not gate. FIUM overrides the CLI's path
(default ~/Documents/fium/fium).
"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compare  # noqa: E402

FIUM = os.environ.get('FIUM', os.path.expanduser('~/Documents/fium/fium'))
NOISE = os.path.join(HERE, 'noise.json')


REPO = os.path.dirname(os.path.dirname(HERE))


def command(base_path, run_path, rev):
    """fium price compare on two exported runs, with this repo's noise file and Price: trailers since rev."""
    cmd = [FIUM, 'price', 'compare', base_path, run_path, '--noise', NOISE, '--repo', REPO]
    if rev and subprocess.run(['git', '-C', REPO, 'cat-file', '-e', rev + '^{commit}'], capture_output=True).returncode == 0:
        cmd += ['--since', rev]
    return cmd


def gate(baseline, candidate):
    base, cand = compare.load(baseline), compare.load(candidate)
    tmp = tempfile.mkdtemp(prefix='figma-eval-fium-')
    try:
        paths = []
        for name, run in (('base', base), ('run', cand)):
            p = os.path.join(tmp, name + '.json')
            with open(p, 'w') as f:
                json.dump(compare.fium(run), f)
            paths.append(p)
        return subprocess.run(command(*paths, base.get('meta', {}).get('rev'))).returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    args = sys.argv[1:]
    if len(args) not in (1, 2) or any(a.startswith('-') for a in args):
        sys.exit(__doc__.strip())
    baseline, candidate = (os.path.join(HERE, 'baseline.json'), args[0]) if len(args) == 1 else args
    if not os.path.exists(FIUM):
        sys.exit(f'gate.py: no fium at {FIUM} (set FIUM)')
    code = gate(baseline, candidate)
    print('\nreference, not gating: compare.py --flaky', flush=True)
    subprocess.run([sys.executable, os.path.join(HERE, 'compare.py'), baseline, candidate, '--flaky'])
    sys.exit(code)


if __name__ == '__main__':
    main()
