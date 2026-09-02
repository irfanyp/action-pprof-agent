from __future__ import annotations

from skill.pprof_integrator.coordinator import run_integrator


def integrate_pprof_endpoint(repo_path: str) -> str:
    """Analyze a Go service and generate pprof endpoint integration guidance.

    This tool returns a prompt for the LLM to analyze the service and generate integration code,
    not a finished artifact. The calling agent should use this prompt to reason over the
    integration strategy and generate code changes.

    Args:
        repo_path: Path to the Go repository

    Returns:
        Markdown prompt for LLM to generate pprof integration code

    Raises:
        FileNotFoundError: If repo or guide not found
        ValueError: If repo is not valid
    """
    return run_integrator(repo_path)
