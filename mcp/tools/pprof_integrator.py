from __future__ import annotations

import sys
from pathlib import Path

# Add skills directory to path
_skills_path = Path(__file__).parent.parent.parent / ".claude" / "skills"
if str(_skills_path) not in sys.path:
    sys.path.insert(0, str(_skills_path))

from pprof_integrator.coordinator import run_integrator  # type: ignore


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
