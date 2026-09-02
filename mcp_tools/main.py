from __future__ import annotations

import asyncio
from typing import Literal

from mcp_tools.tools.pprof_analyzer import analyze_pprof_profile, build_pprof_analysis_prompt
from mcp_tools.tools.pprof_integrator import integrate_pprof_endpoint
from mcp_tools.tools.load_test_generator import generate_load_test
from mcp_tools.tools.profiler_executor import run_cpu_profile

from mcp.server import MCPServer

# Create the MCP server
server = MCPServer("pprof-analyzer")


@server.tool()
def analyze_pprof_profile_tool(
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
        reference_level: Profiling depth ("low", "med", or "high", default "med")

    Returns:
        Markdown prompt for LLM analysis
    """
    return analyze_pprof_profile(profile_path, repo_path, reference_level)


@server.tool()
def build_pprof_analysis_prompt_tool(
    analyzer_result: str,
    file_list: list[str],
    reference_level: Literal["low", "med", "high"] = "med",
) -> str:
    """Build the pprof analysis prompt from already-gathered content (remote-safe).

    Use this instead of analyze_pprof_profile_tool when this MCP server is not on
    the same machine as the profile/repo (e.g. a shared cloud deployment). It does
    no filesystem access on the server — the raw profile and repo source never need
    to be sent to or resident on the server.

    Before calling this tool, gather the inputs locally on the machine that has the
    actual profile and repo:
      1. Convert the profile to markdown: `pprof-to-md --format detailed <profile> -o result.md`,
         then read result.md as `analyzer_result`.
      2. List the repo's Go files: `git ls-files -- '*.go'`, as `file_list`.

    Args:
        analyzer_result: Markdown produced by `pprof-to-md` from the raw profile
        file_list: List of Go file paths in the repository (from `git ls-files`)
        reference_level: Profiling depth ("low", "med", or "high", default "med")

    Returns:
        Markdown prompt for LLM analysis
    """
    return build_pprof_analysis_prompt(analyzer_result, file_list, reference_level)


@server.tool()
def integrate_pprof_endpoint_tool(repo_path: str) -> str:
    """Analyze a Go service and generate pprof endpoint integration guidance.

    This tool returns a prompt for the LLM to analyze the service and generate integration code,
    not a finished artifact. The calling agent should use this prompt to reason over the
    integration strategy and generate code changes.

    Args:
        repo_path: Path to the Go repository

    Returns:
        Markdown prompt for LLM to generate pprof integration code
    """
    return integrate_pprof_endpoint(repo_path)


@server.tool()
def generate_load_test_tool(
    repo_path: str,
    tool: Literal["k6", "apache-bench", "wrk", "go"] = "k6",
) -> str:
    """Generate a load test script for a Go service.

    This tool returns a prompt for the LLM to analyze the service and generate a load test script,
    not a finished artifact. The calling agent should use this prompt to reason over the
    service endpoints and generate an appropriate load test.

    Args:
        repo_path: Path to the Go repository
        tool: Load testing tool to use ("k6", "apache-bench", "wrk", or "go", default "k6")

    Returns:
        Markdown prompt for LLM to generate load test script
    """
    return generate_load_test(repo_path, tool)


@server.tool()
def run_cpu_profile_tool(
    repo_path: str,
    port: int = 8080,
    load_cmd: str | None = None,
    duration: int = 30,
) -> str:
    """Execute CPU profiling on a Go service with optional concurrent load testing.

    This tool has side effects: it builds the service, starts it, runs profiling, and captures
    a pprof profile. The profile is written to .ai_output/cpu.prof in the target repo.

    Concurrency note: This tool is guarded by a per-repo lock within this server process.
    If a call is already running for the same repo_path, subsequent calls will immediately fail
    with error rather than attempting to run concurrently.

    Args:
        repo_path: Path to the Go repository
        port: Service port to bind to (default 8080)
        load_cmd: Optional load test command to run concurrently with profiling
        duration: Profiling duration in seconds (default 30)

    Returns:
        Profiling summary + location where profile was written
    """
    return run_cpu_profile(repo_path, port=port, load_cmd=load_cmd, duration=duration)


async def main():
    """Run the MCP server with stdio transport."""
    await server.run_stdio_async()


# Export server for use in other transports (HTTP, etc.)
__all__ = ["server", "main"]


if __name__ == "__main__":
    asyncio.run(main())
