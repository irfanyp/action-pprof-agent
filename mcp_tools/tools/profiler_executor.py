from __future__ import annotations

import os
import threading

from skill.profiler_executor.profiler import run_profiler

# Module-level lock dictionary, keyed by real path of repo_path
_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_lock(repo_path: str) -> threading.Lock:
    """Get or create a lock for the given repo path."""
    real_path = os.path.realpath(repo_path)
    with _locks_lock:
        if real_path not in _locks:
            _locks[real_path] = threading.Lock()
        return _locks[real_path]


def run_cpu_profile(
    repo_path: str,
    port: int = 8080,
    load_cmd: str | None = None,
    duration: int = 30,
) -> str:
    """Execute CPU profiling on a Go service with optional concurrent load testing.

    This tool has side effects: it builds the service, starts it, runs profiling, and captures
    a pprof profile. The profile is written to .ai_output/cpu.prof in the target repo.

    Concurrency note: This tool is guarded by a per-repo lock within this server process.
    If a call is already running for the same repo_path, subsequent calls will immediately fail
    with RuntimeError rather than attempting to run concurrently (to avoid port/binary conflicts).

    Args:
        repo_path: Path to the Go repository
        port: Service port to bind to (default 8080)
        load_cmd: Optional load test command to run concurrently with profiling
        duration: Profiling duration in seconds (default 30)

    Returns:
        Profiling summary + location where profile was written

    Raises:
        RuntimeError: If repo validation fails, profiler is already running, or profiling fails
        FileNotFoundError: If repo not found
        ValueError: If repo is not valid
    """
    lock = _get_lock(repo_path)
    if not lock.acquire(blocking=False):
        raise RuntimeError(
            f"run_cpu_profile is already running for {repo_path}; wait for it to finish before calling again"
        )

    real_path = os.path.realpath(repo_path)
    try:
        summary = run_profiler(repo_path, port=port, load_cmd=load_cmd, duration=duration)
        return summary + f"\n\nProfile written to: {repo_path}/.ai_output/cpu.prof"
    finally:
        lock.release()
        with _locks_lock:
            if _locks.get(real_path) is lock and not lock.locked():
                del _locks[real_path]
