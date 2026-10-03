#!/usr/bin/env python3
"""Recompute a run's session metrics from its saved transcripts, keeping the scores.

  python3 tests/eval/reparse.py <results.json> <transcripts-dir> [--out <new.json>]

For a change in how session.parse_stream reads a transcript: earlier runs get the new numbers
without running again. Each rep's transcript is <dir>/<task>-<rep>.jsonl, as run.py --transcripts
writes it; a rep without one keeps its numbers. wall_s is not in the transcript and stays."""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run, session  # noqa: E402


def reparse(res, tx):
    for task, t in res['tasks'].items():
        for rep in t['reps']:
            p = os.path.join(tx, f"{task}-{rep['rep']}.jsonl")
            if not os.path.isfile(p):
                continue
            with open(p) as f:
                m, _ = session.parse_stream(f.read().splitlines())
            m.pop('session_error', None)
            rep.update(m)
        res['tasks'][task] = run.summarize(t['reps'])
    return res


def main():
    ap = argparse.ArgumentParser(prog='reparse.py')
    ap.add_argument('results')
    ap.add_argument('transcripts')
    ap.add_argument('--out')
    a = ap.parse_args()
    with open(a.results) as f:
        res = json.load(f)
    with open(a.out or a.results, 'w') as f:
        json.dump(reparse(res, a.transcripts), f, indent=1)


if __name__ == '__main__':
    main()
