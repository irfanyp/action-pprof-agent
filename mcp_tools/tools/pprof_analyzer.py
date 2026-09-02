from __future__ import annotations

from typing import Literal

from skill.pprof_analyzer.analyzer import build_analysis_prompt, run_analyzer


def analyze_pprof_profile(
    profile_path: str,
    repo_path: str,
    reference_level: Literal["low", "med", "high"] = "med",
) -> str:
    """Analyze a Go pprof CPU profile and generate performance optimization guidance.

    This tool returns a prompt for the LLM to analyze the profile and generate code changes,
    not a finished artifact. The calling agent should use this prompt to reason over the
    analysis and generate patches.

    Requires `profile_path` and `repo_path` to exist on the machine running this tool —
    only safe when the MCP server runs on the same host as the caller (e.g. local stdio).
    For a remote/HTTP deployment, use build_pprof_analysis_prompt instead.

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


def build_pprof_analysis_prompt(
    analyzer_result: str,
    file_list: list[str],
    reference_level: Literal["low", "med", "high"] = "med",
) -> str:
    """Build the pprof analysis prompt from already-gathered content (remote-safe).

    Unlike analyze_pprof_profile, this tool never touches a filesystem path on the
    machine running the MCP server — it only does text templating. This makes it
    safe to call against a remote/shared MCP server, since the raw profile and the
    repository source never need to be sent to or resident on the server.

    Before calling this tool, gather the inputs locally (on the machine that has
    the actual profile and repo):
      1. Convert the profile to markdown: `pprof-to-md --format detailed <profile> -o result.md`,
         then read result.md as `analyzer_result`.
      2. List the repo's Go files: `git ls-files -- '*.go'`, as `file_list`.

    Args:
        analyzer_result: Markdown produced by `pprof-to-md` from the raw profile
        file_list: List of Go file paths in the repository (from `git ls-files`)
        reference_level: Profiling depth ("low", "med", or "high")

    Returns:
        Markdown prompt for LLM analysis

    Raises:
        ValueError: If reference_level is invalid
    """
    return build_analysis_prompt(analyzer_result, file_list, reference_level)
