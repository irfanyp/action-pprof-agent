from __future__ import annotations

from typing import Literal

from skill.pprof_analyzer.analyzer import run_analyzer


def analyze_pprof_profile(
    profile_path: str,
    repo_path: str,
    reference_level: Literal["low", "med", "high"] = "med",
) -> str:
    """Analyze a Go pprof CPU profile and generate performance optimization guidance.

    This tool returns a prompt for the LLM to analyze the profile and generate code changes,
    not a finished artifact. The calling agent should use this prompt to reason over the
    analysis and generate patches.

    Args:
        profile_path: Path to the pprof profile file (e.g., cpu.prof)
        repo_path: Path to the Go repository being analyzed
        reference_level: Profiling depth ("low", "med", or "high")

    Returns:
        Markdown prompt for LLM analysis

    Raises:
        FileNotFoundError: If profile or repo not found
        ValueError: If validation fails
    """
    return run_analyzer(profile_path, repo_path, reference_level)
