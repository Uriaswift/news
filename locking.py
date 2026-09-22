"""OS-managed locks are released even when a process crashes."""
import os
from contextlib import contextmanager
from paths import DATA_DIR, ensure_directories

@contextmanager
def lock(name):
    ensure_directories()
    with open(DATA_DIR / (name + '.lock'), 'a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            if not handle.read(1):
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
        try:
            acquire()
        except OSError:
            raise RuntimeError(f'{name} is already running') from None
        try:
            yield
        finally:
            handle.seek(0)
            release()
