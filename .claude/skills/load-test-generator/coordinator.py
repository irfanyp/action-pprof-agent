#!/usr/bin/env python3
"""
load-test-generator coordinator: Analyzes Go service endpoints and prepares for Claude to generate load test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def run_load_test_generator(repo_path: str | Path, tool: str = "k6") -> str:
    """Run load test generator and return prompt (importable wrapper for MCP).

    Args:
        repo_path: Path to Go repository
        tool: Load testing tool to use ("k6", "apache-bench", "wrk", or "go")

    Returns:
        Markdown prompt for Claude analysis

    Raises:
        FileNotFoundError: If repo not found
        ValueError: If repo is not valid or tool is invalid
    """
    repo_path = Path(repo_path).resolve()
    tool = tool.lower()

    if not repo_path.exists():
        raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

    if not (repo_path / "go.mod").exists():
        raise ValueError(f"Not a Go module (no go.mod found): {repo_path}")

    # Validate tool choice
    valid_tools = {"k6", "apache-bench", "wrk", "go"}
    if tool not in valid_tools:
        raise ValueError(f"Invalid tool: {tool}. Must be one of: {valid_tools}")

    # Analyze repository structure
    go_files = list(repo_path.glob("**/*.go"))
    if not go_files:
        raise ValueError(f"No Go source files found in {repo_path}")

    prompt = f"""Analyze this Go repository and generate a load test script.

Repository: {repo_path}
Load Testing Tool: {tool}

Steps:
1. Read go.mod and main entrypoint (usually main.go)
2. Identify HTTP service port (typically :8080, :3000, :5000, etc.)
3. Find all HTTP route handlers and endpoints
4. Understand typical request patterns (GET, POST, payloads, authentication)
5. Generate a load test script in {tool} format that:
   - Hits the main endpoints
   - Uses realistic request patterns
   - Generates sustained load for profiling (good for ~30 second profiling window)
   - Can be run in parallel with profiler-executor

Output the complete load test script. The user will review and save it.

For {tool} format, consider:
- k6: JavaScript, high concurrency, good for profiling
- apache-bench: Simple bash-friendly, good for basic endpoints
- wrk: Lua scripting, high performance
- go: Custom Go binary, maximum control
"""

    return prompt


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

    try:
        prompt = run_load_test_generator(args.repo_path, args.tool)
        print(prompt)
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
