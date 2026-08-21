#!/usr/bin/env python3
"""
load-test-generator coordinator: Analyzes Go service endpoints and prepares for Claude to generate load test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate load test script for Go service"
    )
    parser.add_argument("repo_path", help="Path to Go repository")
    parser.add_argument(
        "--tool",
        default="k6",
        choices=["k6", "apache-bench", "wrk", "go"],
        help="Load testing tool to generate script for",
    )
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()

    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}")
        return 1

    if not (repo_path / "go.mod").exists():
        print(f"Error: Not a Go module (no go.mod found): {repo_path}")
        return 1

    # Analyze repository structure
    go_files = list(repo_path.glob("**/*.go"))
    if not go_files:
        print(f"Error: No Go source files found in {repo_path}")
        return 1

    prompt = f"""Analyze this Go repository and generate a load test script.

Repository: {repo_path}
Load Testing Tool: {args.tool}

Steps:
1. Read go.mod and main entrypoint (usually main.go)
2. Identify HTTP service port (typically :8080, :3000, :5000, etc.)
3. Find all HTTP route handlers and endpoints
4. Understand typical request patterns (GET, POST, payloads, authentication)
5. Generate a load test script in {args.tool} format that:
   - Hits the main endpoints
   - Uses realistic request patterns
   - Generates sustained load for profiling (good for ~30 second profiling window)
   - Can be run in parallel with profiler-executor

Output the complete load test script. The user will review and save it.

For {args.tool} format, consider:
- k6: JavaScript, high concurrency, good for profiling
- apache-bench: Simple bash-friendly, good for basic endpoints
- wrk: Lua scripting, high performance
- go: Custom Go binary, maximum control
"""

    print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
