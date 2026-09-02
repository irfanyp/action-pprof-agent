from __future__ import annotations

from typing import Literal

from skill.load_test_generator.coordinator import run_load_test_generator


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
    return run_load_test_generator(repo_path, tool)
