"""The one lock every live dev entry point takes before touching the scratch Figma file: eval reps
(tests/eval/run.py), probes, and case repros (tests/cases/case.py). An eval rep's setup resets the
whole file, so anything else running on it at the same time would lose its pages.

  from figma_lock import file_lock
  with file_lock(file_key):
      ...
"""
import fcntl, os


def lock_path(key):
    # A fixed directory, not TMPDIR: callers in different sessions get different TMPDIRs, and
    # every one of them must queue on the same lock.
    return os.path.join('/tmp', f'figma-eval-{os.getuid()}', f'{key}.lock')


def file_lock(key):
    """An open file holding an exclusive flock on key's lock; closing it (or leaving a `with`) frees it."""
    path = lock_path(key)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    f = open(path, 'a')
    fcntl.flock(f, fcntl.LOCK_EX)
    return f
