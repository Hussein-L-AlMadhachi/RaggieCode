"""Cross-process chat locking via OS-level file locks.

Chats live as rows in the SQLite chat DB, but locks are anchored to plain
files named ".raggie/locks/chat-<id>.lock" under the raggie data dir
(respects dev mode via raggie_dirs.get_raggie_dir()).

The lock itself is an OS-level lock on the file descriptor:
- POSIX (Linux/macOS): fcntl.flock() with LOCK_EX | LOCK_NB. flock is
  per open-file-description, so a second fd in the same process cannot
  re-lock while we hold it (probe correctly reports False).
- Windows: msvcrt.locking() on 1 byte at offset 0. Locks are owned by the
  file handle, so a second handle (even in-process) conflicts as well.

Because the lock is owned by the kernel, it is released automatically when
the process dies (even SIGKILL), so there is no stale-lock cleanup to do.

Thread safety: a module-level threading.Lock guards the registry, and a
per-chat refcount makes acquire() re-entrant for the same process (web
server threads and subagents can nest acquisitions without blocking).
"""

import json
import os
import threading

try:
    import fcntl  # POSIX only

    _IS_POSIX = True
except ImportError:  # pragma: no cover - Windows only
    import msvcrt

    _IS_POSIX = False

from raggie_dirs import get_raggie_dir

# chat_id -> {"fd": int, "refs": int}, guarded by _registry_lock.
# The fd stays open for the whole lifetime of the lock (until refs hit 0);
# never re-open the file for a held chat (POSIX flock per-ofd safety).
_held = {}
_registry_lock = threading.Lock()


def _lock_path(chat_id) -> str:
    """Return the path of the lock anchor file for a chat."""
    lock_dir = get_raggie_dir() / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return str(lock_dir / f"chat-{chat_id}.lock")


def _open_and_lock(path: str) -> int:
    """Open the anchor file and try a non-blocking exclusive lock.

    Returns the fd on success. Raises OSError if the lock is taken
    (by another process or another fd/handle in this process).
    """
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if _IS_POSIX:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            # msvcrt.locking needs at least 1 byte to lock at offset 0.
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LCK_NBLCK, 1)
    except OSError:
        os.close(fd)
        raise
    return fd


def _unlock_and_close(fd: int) -> None:
    """Release the OS lock on fd and close it (best effort)."""
    try:
        if _IS_POSIX:
            fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LCK_UNLCK, 1)
    except OSError:
        pass  # closing the fd releases the lock anyway
    os.close(fd)


def _write_metadata(path: str, fd: int) -> None:
    """Write debug-only metadata (pid) into the anchor file.

    Cosmetic only, never used for correctness; failures are ignored.
    """
    try:
        payload = json.dumps({"pid": os.getpid()}).encode()
        if _IS_POSIX:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, payload)
        else:
            # Byte 0 is held by our lock; write metadata right after it.
            os.lseek(fd, 1, os.SEEK_SET)
            os.write(fd, payload)
    except OSError:
        pass


def acquire(chat_id) -> bool:
    """Acquire the chat lock (non-blocking).

    Returns True if THIS process now holds the lock. Re-entrant for the
    same process via refcounting, so nested acquisitions (subagents,
    concurrent web threads) never block. Returns False if another
    process/instance holds the lock.
    """
    key = str(chat_id)
    with _registry_lock:
        entry = _held.get(key)
        if entry is not None:
            entry["refs"] += 1
            return True
        path = _lock_path(key)
        try:
            fd = _open_and_lock(path)
        except OSError:
            return False
        _write_metadata(path, fd)
        _held[key] = {"fd": fd, "refs": 1}
        return True


def release(chat_id) -> None:
    """Release one reference on the chat lock.

    When the last reference is dropped, the OS lock is released and the
    fd closed. Unknown chat ids are a no-op.
    """
    key = str(chat_id)
    with _registry_lock:
        entry = _held.get(key)
        if entry is None:
            return
        entry["refs"] -= 1
        if entry["refs"] > 0:
            return
        del _held[key]
    _unlock_and_close(entry["fd"])


def is_held(chat_id) -> bool:
    """Return True only if THIS process currently holds the lock."""
    return str(chat_id) in _held


def probe(chat_id) -> bool:
    """Return True iff the chat lock is free.

    Implemented with a fresh fd/handle + non-blocking lock + unlock +
    close, so it never disturbs a lock this process already holds.
    While we hold the lock, this returns False (holds on both POSIX
    per-ofd flock semantics and Windows handle-owned locks).
    """
    try:
        fd = _open_and_lock(_lock_path(str(chat_id)))
    except OSError:
        return False
    _unlock_and_close(fd)
    return True
