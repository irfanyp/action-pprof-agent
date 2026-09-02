#!/usr/bin/env python3
"""
profiler-executor: Runs Go CPU profiling with concurrent load testing.
Produces cpu.prof for pprof-analyzer skill.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _terminate_proc(proc: subprocess.Popen, timeout: int = 5) -> None:
    """Terminate a subprocess gracefully: SIGTERM, then SIGKILL if it doesn't exit in time."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _wait_for_service(port: int, timeout: int = 10) -> bool:
    """Poll the service's HTTP port until it responds or the timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{port}/", timeout=1)
            return True
        except urllib.error.HTTPError:
            # Got an HTTP response (even a non-2xx one) — the service is up.
            return True
        except Exception:
            time.sleep(0.2)
    return False


def run_profiler(
    repo_path: str | Path,
    port: int = 8080,
    load_cmd: str | None = None,
    duration: int = 30,
) -> str:
    """Run CPU profiler and return summary (importable wrapper for MCP).

    Args:
        repo_path: Path to Go repository
        port: Service main port (default 8080)
        load_cmd: Optional load test command to run
        duration: CPU profiling duration in seconds (default 30)

    Returns:
        Summary of profiling results

    Raises:
        FileNotFoundError: If repo not found
        ValueError: If repo is not valid
        RuntimeError: If profiling fails
    """
    repo_path = Path(repo_path).resolve()

    if not repo_path.exists():
        raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

    if not (repo_path / "go.mod").exists():
        raise ValueError(f"Not a Go module (no go.mod found): {repo_path}")

    # Create output directory
    output_dir = repo_path / ".ai_output"
    output_dir.mkdir(exist_ok=True)

    # Step 1: Build the service
    try:
        result = subprocess.run(
            ["go", "build", "-o", "service_bin", "."],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Service build failed:\n{result.stderr}")
    except FileNotFoundError:
        raise RuntimeError("go command not found. Please install Go.") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("Service build timed out") from None

    # Step 2: Start the service
    service_proc = subprocess.Popen(
        ["./service_bin"],
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for service to become ready (bounded poll instead of a fixed sleep,
    # since startup time varies with DB connections, migrations, etc.)
    if not _wait_for_service(port, timeout=10):
        _terminate_proc(service_proc)
        stdout, stderr = service_proc.communicate()
        raise RuntimeError(f"Service did not become ready on port {port} within timeout\n{stderr}")

    try:
        # Step 3: Run profiler and load test in parallel
        profiler_cmd = [
            "go",
            "tool",
            "pprof",
            "-text",
            f"http://localhost:9987/debug/pprof/profile?seconds={duration}",
        ]

        # Start profiler
        profile_output = output_dir / "cpu.prof"
        with open(profile_output, "w") as f:
            profiler_proc = subprocess.Popen(
                profiler_cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                text=True,
            )

        # Start load test if provided, otherwise use simple curl loop
        load_proc = None
        if load_cmd:
            load_proc = subprocess.Popen(
                shlex.split(load_cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        else:
            # Default: simple curl loop
            load_script = f"""
for i in {{1..{duration * 10}}}; do
  curl -s http://localhost:{port}/ > /dev/null 2>&1 || true
  sleep 0.1
done
"""
            load_proc = subprocess.Popen(
                ["bash", "-c", load_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        # Wait for profiler to finish
        try:
            profiler_returncode = profiler_proc.wait(timeout=duration + 10)
            if profiler_returncode != 0:
                print(f"Warning: profiler exited with code {profiler_returncode}", file=sys.stderr)
        except subprocess.TimeoutExpired:
            profiler_proc.kill()
            profiler_proc.wait()
            load_proc.kill()
            raise RuntimeError(f"Profiler did not finish within {duration + 10}s and was killed")

        # Wait for load test to finish (with timeout)
        try:
            load_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            load_proc.kill()

        # Step 4: Verify output
        if not (profile_output.exists() and profile_output.stat().st_size > 0):
            raise RuntimeError("Profile not generated or is empty")

        size_kb = profile_output.stat().st_size / 1024
        summary = f"""SUCCESS: CPU profiling completed
Profile: {profile_output}
Size: {size_kb:.1f} KB

Next steps:
1. Run pprof-analyzer on the profile:
   /pprof-analyzer {repo_path} --profile {profile_output} --reference med

2. Or analyze manually:
   go tool pprof {profile_output}
"""
        return summary

    finally:
        # Clean up: stop the service
        _terminate_proc(service_proc)

        # Clean up binary
        (repo_path / "service_bin").unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute Go CPU profiling with load test"
    )
    parser.add_argument("repo_path", help="Path to Go repository")
    parser.add_argument(
        "--port",
        default="8080",
        help="Service main port (default: 8080)",
    )
    parser.add_argument(
        "--load-cmd",
        help="Load test command to run (optional, defaults to curl loop)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="CPU profiling duration in seconds (default: 30)",
    )
    args = parser.parse_args()

    try:
        print(f"[profiler-executor] Repository: {args.repo_path}")
        print(f"[profiler-executor] Service port: {args.port}")
        print(f"[profiler-executor] Profiling duration: {args.duration}s")

        print("\n[1/4] Building service...")
        print("[2/4] Starting service...")
        print(f"[3/4] Running profiler and load test in parallel (duration: {args.duration}s)...")
        print("[4/4] Verifying output...")

        summary = run_profiler(
            args.repo_path,
            port=int(args.port),
            load_cmd=args.load_cmd,
            duration=args.duration,
        )

        print("\n" + "=" * 60)
        print(summary)
        print("=" * 60)
        return 0

    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
