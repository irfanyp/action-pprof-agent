#!/usr/bin/env python3
"""
pprof-integrator coordinator: Reads pprof_integration.md and prepares repo analysis for Claude.
Claude will then generate code changes for user review.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def run_integrator(repo_path: str | Path) -> str:
    """Run integration analyzer and return prompt (importable wrapper for MCP).

    Args:
        repo_path: Path to Go repository

    Returns:
        Markdown prompt for Claude analysis

    Raises:
        FileNotFoundError: If repo or guide not found
        ValueError: If repo is not valid
    """
    repo_path = Path(repo_path).resolve()

    if not repo_path.exists():
        raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

    if not (repo_path / "go.mod").exists():
        raise ValueError(f"Not a Go module (no go.mod found): {repo_path}")

    # Read the pprof integration guide
    guide_path = Path(__file__).parent / "pprof_integration.md"

    if not guide_path.exists():
        raise FileNotFoundError(f"pprof_integration.md not found at {guide_path}")

    with open(guide_path) as f:
        integration_guide = f.read()

    # Prepare analysis prompt for Claude
    prompt = f"""You are integrating Go net/http/pprof endpoint into a service using this guide:

<PPROF_INTEGRATION_GUIDE>
{integration_guide}
</PPROF_INTEGRATION_GUIDE>

Analyze this repository: {repo_path}

Steps:
1. Read go.mod to detect the framework in use
2. Find the main() entrypoint and main listener setup
3. Check if pprof is already integrated (search for "net/http/pprof" or "debug/pprof")
4. Follow the appropriate phase from the guide:
   - If not integrated: Phases 1-6 (fresh install)
   - If integrated on separate port: Scenario A (just relocate port)
   - If improperly exposed: Scenario B (fix isolation + relocate)
5. Generate code changes needed

Output your analysis and code changes. The user will review and apply them manually.
"""

    return prompt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Integrate pprof endpoint into Go service"
    )
    parser.add_argument("repo_path", help="Path to Go repository")
    args = parser.parse_args()

    try:
        prompt = run_integrator(args.repo_path)
        print(prompt)
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
