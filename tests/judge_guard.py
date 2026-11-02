#!/usr/bin/env python3
"""A fix may not grade itself: no single commit both changes the skill and edits what judges it.

  python3 tests/judge_guard.py [<rev-range>]     # default main..HEAD; exit 1 on a violation

A commit violates when it touches a skill file (SKILL.md, figma-worker.md, references/, the
figma_* helpers) and also modifies or deletes an existing judge file: a path bench/judge's globs
match (the eval runner, scorers, tasks, seeds, fixtures, noise and baseline, the byte budget, a
probe's expected verdicts), the file fium try reads, or bench/judge itself. Adding a judge file is allowed, so a case's red commit can bring a
new task, scorer or probe. A commit whose message has a `Judge-Change: <why>` line passes; that
line is for a human-reviewed change of the judges (a baseline refresh, a scorer fix).
"""
import os, re, subprocess, sys
from fnmatch import fnmatch

SKILL = re.compile(r'^(SKILL\.md|figma-worker\.md|references/|figma_[^/]+\.(js|mjs|py)$)')


def judges(repo):
    """bench/judge's globs (one per line, # comments), with the file itself."""
    p = os.path.join(repo, 'bench', 'judge')
    try:
        with open(p) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
    except OSError:
        sys.exit(f'judge guard: no {p}')
    return ['bench/judge'] + [l for l in lines if l != '!defaults']


def is_judge(path, globs):
    return any(fnmatch(path, g) for g in globs)


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True, check=True).stdout


def violations(repo='.', rev_range='main..HEAD'):
    """[(sha, subject, [judge files it edits])] for the commits in rev_range that break the rule."""
    out, js = [], judges(repo)
    for sha in git(repo, 'rev-list', '--no-merges', rev_range).split():
        msg = git(repo, 'log', '-1', '--format=%B', sha)
        if re.search(r'^Judge-Change:\s*\S', msg, re.M):
            continue
        rows = [l.split('\t') for l in git(repo, 'diff-tree', '--no-commit-id', '-r', '--name-status', '-M', sha).splitlines() if l]
        # A rename counts as editing (or removing) the old path.
        touched = [r[-1] for r in rows] + [r[1] for r in rows if r[0].startswith('R')]
        edited = sorted({r[1] for r in rows if r[0][0] in 'MDR' and is_judge(r[1], js)})
        if edited and any(SKILL.match(p) for p in touched):
            out.append((sha[:12], msg.split('\n', 1)[0], edited))
    return out


def main():
    rng = sys.argv[1] if len(sys.argv) > 1 else 'main..HEAD'
    bad = violations('.', rng)
    for sha, subject, files in bad:
        print(f'{sha} {subject}\n  changes the skill and edits its judges: {", ".join(files)}\n'
              '  split the judge edit into its own commit, or add a reviewed "Judge-Change: <why>" line')
    if not bad:
        print(f'judge guard: ok ({rng})')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
