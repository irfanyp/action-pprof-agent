#!/usr/bin/env python3
"""
profiler-executor: Runs Go CPU profiling with concurrent load testing.
Produces cpu.prof for pprof-analyzer skill.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


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

    repo_path = Path(args.repo_path).resolve()

    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}")
        return 1

    if not (repo_path / "go.mod").exists():
        print(f"Error: Not a Go module (no go.mod found): {repo_path}")
        return 1

    # Create output directory
    output_dir = repo_path / ".ai_output"
    output_dir.mkdir(exist_ok=True)

    print(f"[profiler-executor] Repository: {repo_path}")
    print(f"[profiler-executor] Service port: {args.port}")
    print(f"[profiler-executor] Profiling duration: {args.duration}s")

    # Step 1: Build the service
    print("\n[1/4] Building service...")
    try:
        result = subprocess.run(
            ["go", "build", "-o", "service_bin", "."],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"Error building service:\n{result.stderr}")
            return 1
        print("✓ Service built")
    except FileNotFoundError:
        print("Error: go command not found. Please install Go.")
        return 1
    except subprocess.TimeoutExpired:
        print("Error: Service build timed out")
        return 1

    # Step 2: Start the service
    print("\n[2/4] Starting service...")
    service_proc = subprocess.Popen(
        ["./service_bin"],
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for service to start
    time.sleep(2)

    if service_proc.poll() is not None:
        stdout, stderr = service_proc.communicate()
        print(f"Error: Service failed to start\n{stderr}")
        return 1

    print(f"✓ Service started (PID: {service_proc.pid})")

    try:
        # Step 3: Run profiler and load test in parallel
        print(f"\n[3/4] Running profiler and load test in parallel (duration: {args.duration}s)...")

        profiler_cmd = [
            "go",
            "tool",
            "pprof",
            "-text",
            f"http://localhost:9987/debug/pprof/profile?seconds={args.duration}",
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
        if args.load_cmd:
            load_proc = subprocess.Popen(
                args.load_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        else:
            # Default: simple curl loop
            load_script = f"""
for i in {{1..{args.duration * 10}}}; do
  curl -s http://localhost:{args.port}/ > /dev/null 2>&1 || true
  sleep 0.1
done
"""
            load_proc = subprocess.Popen(
                ["bash", "-c", load_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        print("✓ Profiler and load test started")

        # Wait for profiler to finish
        profiler_returncode = profiler_proc.wait(timeout=args.duration + 10)
        if profiler_returncode != 0:
            print("Warning: Profiler exited with non-zero status")

        # Wait for load test to finish (with timeout)
        try:
            load_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            load_proc.kill()

        print("✓ Profiling completed")

        # Step 4: Verify output
        print("\n[4/4] Verifying output...")
        if profile_output.exists() and profile_output.stat().st_size > 0:
            size_kb = profile_output.stat().st_size / 1024
            print(f"✓ CPU profile saved: {profile_output} ({size_kb:.1f} KB)")
        else:
            print(f"Error: Profile not generated or is empty")
            return 1

    finally:
        # Clean up: stop the service
        print("\n[cleanup] Stopping service...")
        service_proc.terminate()
        try:
            service_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            service_proc.kill()
        print("✓ Service stopped")

        # Clean up binary
        (repo_path / "service_bin").unlink(missing_ok=True)

    print("\n" + "=" * 60)
    print("SUCCESS: Profiling completed")
    print("=" * 60)
    print(f"\nNext steps:")
    print(f"1. Run pprof-analyzer on the profile:")
    print(f"   /pprof-analyzer {repo_path} --profile {profile_output} --reference med")
    print(f"\n2. Or analyze manually:")
    print(f"   go tool pprof {profile_output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
