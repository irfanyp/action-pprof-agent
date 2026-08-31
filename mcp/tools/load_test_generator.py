from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

# Add skills directory to path
_skills_path = Path(__file__).parent.parent.parent / ".claude" / "skills"
if str(_skills_path) not in sys.path:
    sys.path.insert(0, str(_skills_path))

from load_test_generator.coordinator import run_load_test_generator  # type: ignore


def generate_load_test(
    repo_path: str,
    tool: Literal["k6", "apache-bench", "wrk", "go"] = "k6",
) -> str:
    """Generate a load test script for a Go service.

    This tool returns a prompt for the LLM to analyze the service and generate a load test script,
    not a finished artifact. The calling agent should use this prompt to reason over the
    service endpoints and generate an appropriate load test.

    Args:
        repo_path: Path to the Go repository
        tool: Load testing tool to use ("k6", "apache-bench", "wrk", or "go")

    Returns:
        Markdown prompt for LLM to generate load test script

    Raises:
        FileNotFoundError: If repo not found
        ValueError: If repo is not valid or tool is invalid
    """
    return run_load_test_generator(repo_path, tool)  # type: ignore
