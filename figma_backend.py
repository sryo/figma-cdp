"""The perch daemon client figma_run.py and figma_capture.py share.

perch, at PERCH_DIR (default ~/.perch, then ~/Documents/perch), is the only backend. The daemon
is figma_perch.mjs `serve` behind a unix socket, started on first use.
"""
import fcntl, hashlib, json, os, socket, stat, subprocess, sys, time

def require_perch():
    """Exit before anything runs when FIGMA_BACKEND names a backend other than perch."""
    b = os.environ.get('FIGMA_BACKEND', '')
    if b and b.lower() != 'perch':
        sys.exit(f'FIGMA_BACKEND={b}: perch is the only backend; unset FIGMA_BACKEND')

def perch_dir():
    # ~/.perch is where perch's installer puts it; ~/Documents/perch is a dev checkout.
    if os.environ.get('PERCH_DIR'):
        return os.environ['PERCH_DIR']
    dirs = [os.path.expanduser(d) for d in ('~/.perch', '~/Documents/perch')]
    return next((d for d in dirs if os.path.isfile(os.path.join(d, 'server.js'))), dirs[0])

def js_int(s):
    """JSON from the page is JS numbers: an integer past 2^53 is a double."""
    n = int(s)
    return n if -2**53 <= n <= 2**53 else float(s)

class Dropped(Exception):
    pass

def daemon_sock(helper):
    """The figma_perch.mjs daemon's socket: per user, per perch checkout and helper version."""
    if os.environ.get('FIGMA_PERCH_SOCK'):
        return os.environ['FIGMA_PERCH_SOCK']
    try:
        st = [os.stat(p) for p in (os.path.join(perch_dir(), 'server.js'), helper)]
    except OSError:
        return None
    tag = '\0'.join([os.path.realpath(perch_dir()), os.path.realpath(helper)] +
                    [f'{x.st_mtime_ns}:{x.st_size}' for x in st])
    name = hashlib.sha1(tag.encode()).hexdigest()[:16] + '.sock'
    for base in (os.environ.get('TMPDIR') or '/tmp', '/tmp'):
        d = os.path.join(base, f'figma-perch-{os.getuid()}')
        if len(os.path.join(d, name).encode()) < 100:
            break
    else:
        return None
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        st = os.lstat(d)
        if st.st_uid != os.getuid() or not stat.S_ISDIR(st.st_mode):
            return None
        if st.st_mode & 0o077:
            os.chmod(d, 0o700)
    except OSError:
        return None
    return os.path.join(d, name)

def daemon_exchange(sock, req, wait=5):
    """The daemon's reply line; None when no daemon greeted, so nothing ran; Dropped once the
    request went out. `wait` bounds the reply: perch caps a main-world eval near 95s."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    f = None
    try:
        s.settimeout(5)
        s.connect(sock)
        f = s.makefile('rb')
        if not f.readline().startswith(b'{"perch_daemon"'):
            f.close()
            s.close()
            return None
    except OSError:
        if f:
            f.close()
        s.close()
        return None
    try:
        s.settimeout(wait)
        s.sendall(json.dumps(req).encode() + b'\n')
        data = f.readline()
    except socket.timeout:
        raise Dropped(f'no reply in {wait:.0f}s')
    except OSError as e:
        raise Dropped(str(e))
    finally:
        f.close()
        s.close()
    try:
        return json.loads(data, parse_int=js_int)
    except ValueError:
        raise Dropped('no reply')

def start_daemon(sock, helper):
    """Start figma_perch.mjs serve on sock unless one answers; True once it does."""
    try:
        lock = open(sock + '.lock', 'a')
    except OSError:
        return False
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if daemon_exchange(sock, {'op': 'ping'}):
                return True
        except Dropped:
            pass
        try:
            os.unlink(sock)
        except FileNotFoundError:
            pass
        except OSError:
            return False
        try:
            with open(sock + '.log', 'wb') as log:
                p = subprocess.Popen(['node', helper, 'serve', sock], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
        except OSError:
            return False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if os.path.exists(sock):
                try:
                    if daemon_exchange(sock, {'op': 'ping'}):
                        return True
                except Dropped:
                    pass
            if p.poll() is not None and not os.path.exists(sock):
                return False
            time.sleep(0.005)
        p.kill()
        return False

def timeout_seconds(flag):
    """--timeout, else FIGMA_TIMEOUT, else 100: seconds a perch eval may await, clamped to 1-300."""
    raw = flag if flag is not None else os.environ.get('FIGMA_TIMEOUT')
    if raw is None or str(raw).strip() == '':
        return 100.0
    try:
        v = float(raw)
    except ValueError:
        v = float('nan')
    if v != v or v in (float('inf'), float('-inf')):
        sys.exit(f"--timeout / FIGMA_TIMEOUT is seconds, 1 to 300; got '{raw}'")
    return min(300.0, max(1.0, v))
