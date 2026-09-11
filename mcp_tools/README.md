# MCP Server: pprof-analyzer

An MCP server exposing the four pprof-analyzer skills as tools for Claude Code, Claude Desktop, Cline, Cursor, and other MCP-native AI agents.

## What is this?

This server wraps the four existing skills (`skill/`) as five MCP tools — `analyze_pprof_profile_tool`, `build_pprof_analysis_prompt_tool`, `integrate_pprof_endpoint_tool`, `generate_load_test_tool`, `run_cpu_profile_tool` — without modifying them. See [Tool Reference](#tool-reference) below for parameters and behavior.

Unlike the GitHub Action (external LLM API calls) or the Claude Code Skill (Claude Code-only), it works with any MCP-compatible agent host.

## Installation

### Prerequisites

- Python 3.12+ (required by MCP v2.x)
- `pprof-to-md` npm binary in PATH (for profile conversion)
- `git` CLI available
- Go toolchain (for `run_cpu_profile` tool only)

### Setup

```bash
make setup-env
```

## Testing Locally

```bash
make test-mcp                    # run the test suite
mcp dev mcp_server.py            # launch MCP Inspector for manual testing
```

## Registration

### Claude Code

```bash
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_server.py
```

Tools will appear as:
- `mcp__pprof-analyzer__analyze_pprof_profile_tool`
- `mcp__pprof-analyzer__build_pprof_analysis_prompt_tool`
- `mcp__pprof-analyzer__integrate_pprof_endpoint_tool`
- `mcp__pprof-analyzer__generate_load_test_tool`
- `mcp__pprof-analyzer__run_cpu_profile_tool`

**Important:** Increase the timeout in `.claude/settings.json` for `run_cpu_profile_tool`:

```json
{
  "permissions": {
    "mcp__pprof-analyzer__run_cpu_profile_tool": {
      "timeout": 300000
    }
  }
}
```

### Claude Desktop / Cline / Cursor

See [MCP_SETUP.md](../MCP_SETUP.md) for registration examples with `claude_desktop_config.json` and `.cline_mcp_settings.json`.

## Tool Reference

| Tool | Parameters | Returns | Notes |
|------|-----------|---------|-------|
| `analyze_pprof_profile_tool` | `profile_path: str`, `repo_path: str`, `reference_level: str = "med"` | Analysis prompt for LLM | Path-based; requires `profile_path`/`repo_path` to exist on the machine running the MCP server (local/stdio only) |
| `build_pprof_analysis_prompt_tool` | `analyzer_result: str`, `file_list: list[str]`, `reference_level: str = "med"` | Analysis prompt for LLM | Content-only, remote-safe variant of `analyze_pprof_profile_tool` — see [MCP_SETUP.md](../MCP_SETUP.md#team-collaboration-httpsse) |
| `integrate_pprof_endpoint_tool` | `repo_path: str` | Integration guidance prompt | Returns prompt for pprof endpoint setup; set `PPROF_VERIFY_LOCAL_PATHS=false` server-side for remote callers |
| `generate_load_test_tool` | `repo_path: str`, `tool: str = "k6"` | Load test generation prompt | Tool choices: `k6`, `apache-bench`, `wrk`, `go`; same `PPROF_VERIFY_LOCAL_PATHS` note as above |
| `run_cpu_profile_tool` | `repo_path: str`, `port: int = 8080`, `load_cmd: str \| None`, `duration: int = 30` | Profile location + summary | ~30s typical latency, up to 120s+ for slow builds; disabled unless `MCP_ENABLE_CPU_PROFILE=1` is set on the server |

## Concurrency Behavior

The `run_cpu_profile_tool` is guarded by a per-repo concurrency lock within a single server process:

- Only one call per `repo_path` can run at a time
- Overlapping calls for the same repo raise `RuntimeError` immediately
- Different repos can run concurrently (different locks)
- Lock is per-server-process (cross-process concurrency is not protected)

## Troubleshooting

| Problem | Fix |
|---|---|
| "Module not found" | Ensure the repository root is on `sys.path` so `skill/` and `mcp_tools/` can be imported |
| `run_cpu_profile_tool` timeouts | Increase the timeout in your agent's configuration (e.g., 300 seconds for Claude Code) |
| Profile location issues | Profiles are written to `.ai_output/cpu.prof` relative to the repo path, not the MCP server's working directory |

## Development

```bash
make test-mcp    # all tests are mocked (no real skill scripts are called)
```

### Adding a New Tool

1. Create a wrapper function in the skill file (`skill/<name>/`)
2. Create a tool module in `mcp_tools/tools/<name>.py`
3. Import it in `mcp_tools/main.py` and register it with `@server.tool()`
4. Add test cases in `mcp_tools/tests/test_<name>.py`

## Related

- [Root README](../README.md) — Overview of three implementations
- [AGENTS.md](../AGENTS.md) — Architecture and design decisions
- [MCP_SETUP.md](../MCP_SETUP.md) — Setup, Docker, and remote usage
- [Skills documentation](../skill/) — Individual skill descriptions
