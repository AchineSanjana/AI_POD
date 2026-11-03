"""Atomic YAML persistence utilities with thread-level and cross-process safety.

Provides atomic file replacement (write temp -> flush -> fsync -> os.replace)
guaranteed to work across platforms (including Windows). Protected by both
a process-level threading.Lock and an OS-level atomic lockfile.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PATH_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_MUTEX = threading.Lock()


def get_thread_lock(path: Path | str) -> threading.Lock:
    """Retrieve or initialize a process-level threading.Lock for a given resolved path."""
    key = str(Path(path).resolve()).lower()
    with _LOCKS_MUTEX:
        if key not in _PATH_LOCKS:
            _PATH_LOCKS[key] = threading.Lock()
        return _PATH_LOCKS[key]


@contextmanager
def file_lock(lock_path: Path | str, timeout: float = 10.0, poll_interval: float = 0.05):
    """Simple cross-process lockfile using atomic os.open with O_CREAT | O_EXCL."""
    path = Path(lock_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    start_time = time.time()
    acquired = False
    fd = None

    while time.time() - start_time < timeout:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            acquired = True
            break
        except FileExistsError:
            # Handle stale locks (e.g. crashed process after 60s)
            try:
                if time.time() - os.path.getmtime(str(path)) > 60.0:
                    os.unlink(str(path))
            except OSError:
                pass
            time.sleep(poll_interval)
        except OSError:
            time.sleep(poll_interval)

    if not acquired:
        raise TimeoutError(f"Could not acquire cross-process file lock: {path}")

    try:
        yield
    finally:
        if acquired:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.unlink(str(path))
            except OSError:
                pass


@contextmanager
def atomic_yaml_write_lock(target_path: Path | str, timeout: float = 10.0):
    """Acquire both process-level threading lock and cross-process file lock for a target file."""
    path = Path(target_path).resolve()
    thread_lock = get_thread_lock(path)
    lock_file_path = path.with_suffix(path.suffix + ".lock")

    with thread_lock:
        with file_lock(lock_file_path, timeout=timeout):
            yield


def atomic_dump_yaml(
    target_path: Path | str,
    data: Any,
    sort_keys: bool = False,
    default_flow_style: bool = False,
    acquire_lock: bool = True,
) -> None:
    """Atomically persist YAML data to target_path.

    Writes to a temporary file in the same directory, flushes and fsyncs to disk,
    closes the file handle, and executes an atomic os.replace onto target_path.
    Cleans up temp file on any exception to prevent corruption.
    """
    path = Path(target_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    def _do_write() -> None:
        temp_file_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                delete=False,
                mode="w",
                encoding="utf-8",
                prefix=f".{path.name}.",
                suffix=".tmp",
            ) as tf:
                temp_file_path = Path(tf.name)
                yaml.safe_dump(
                    data,
                    tf,
                    sort_keys=sort_keys,
                    default_flow_style=default_flow_style,
                )
                tf.flush()
                os.fsync(tf.fileno())

            # File is cleanly closed before replacement (mandatory on Windows)
            max_replace_attempts = 15
            for attempt in range(max_replace_attempts):
                try:
                    os.replace(temp_file_path, path)
                    break
                except PermissionError:
                    if attempt == max_replace_attempts - 1:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        finally:
            if temp_file_path and temp_file_path.exists():
                try:
                    temp_file_path.unlink()
                except OSError:
                    pass

    if acquire_lock:
        with atomic_yaml_write_lock(path):
            _do_write()
    else:
        _do_write()
