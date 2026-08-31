# MCP Server: pprof-analyzer

An MCP (Model Context Protocol) server that exposes the four pprof-analyzer skills as tools, making them available to Claude Code, Claude Desktop, Cline, Cursor, and other MCP-native AI agents.

## What is this?

This MCP server wraps the four existing skills (`.claude/skills/`) without modification, exposing them as MCP tools:

1. **analyze_pprof_profile** — Analyze Go pprof CPU profiles and generate optimization patches
2. **integrate_pprof_endpoint** — Add pprof endpoint integration guidance to a Go service
3. **generate_load_test** — Generate load test scripts for Go services
4. **run_cpu_profile** — Execute CPU profiling with concurrent load testing

Unlike the GitHub Action (which makes external LLM API calls) or the Claude Code Skill (which is Claude Code-only), the MCP server works with any MCP-compatible agent host, including Claude Desktop, Cline, Cursor, and others.

## Installation

### Prerequisites

- Python 3.10+ (required by MCP v2.x)
- `pprof-to-md` npm binary in PATH (for profile conversion)
- `git` CLI available
- Go toolchain (for `run_cpu_profile` tool only)

### Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r mcp_tools/requirements.txt
```

## Testing Locally

Run the test suite:

```bash
pytest mcp_tools/tests/ -v
```

Launch MCP Inspector for manual testing:

```bash
mcp dev mcp_tools/main.py
```

This opens an interactive MCP Inspector where you can call tools directly.

## Registration

### Claude Code

Register the server with the local project:

```bash
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_tools/main.py
```

Tools will appear as:
- `mcp__pprof-analyzer__analyze_pprof_profile`
- `mcp__pprof-analyzer__integrate_pprof_endpoint`
- `mcp__pprof-analyzer__generate_load_test`
- `mcp__pprof-analyzer__run_cpu_profile`

**Important:** Increase the timeout in `.claude/settings.json` for `run_cpu_profile`:

```json
{
  "permissions": {
    "mcp__pprof-analyzer__run_cpu_profile": {
      "timeout": 300000
    }
  }
}
```

### Claude Desktop

Edit `~/.claude_desktop/claude_desktop_config.json` (or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "command": "python3",
      "args": ["/absolute/path/to/pprof-analyzer/mcp_tools/main.py"]
    }
  }
}
```

Restart Claude Desktop to load the server.

### Cline (VSCode Extension)

Create `.cline_mcp_settings.json` in your project root:

```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "command": "python3",
      "args": ["/absolute/path/to/pprof-analyzer/mcp_tools/main.py"]
    }
  }
}
```

## Tool Reference

| Tool | Parameters | Returns | Notes |
|------|-----------|---------|-------|
| `analyze_pprof_profile` | `profile_path: str`, `repo_path: str`, `reference_level: str = "med"` | Analysis prompt for LLM | Returns markdown prompt; LLM generates patches |
| `integrate_pprof_endpoint` | `repo_path: str` | Integration guidance prompt | Returns prompt for pprof endpoint setup |
| `generate_load_test` | `repo_path: str`, `tool: str = "k6"` | Load test generation prompt | Tool choices: `k6`, `apache-bench`, `wrk`, `go` |
| `run_cpu_profile` | `repo_path: str`, `port: int = 8080`, `load_cmd: str \| None`, `duration: int = 30` | Profile location + summary | ~30s typical latency, up to 120s+ for slow builds |

## Concurrency Behavior

The `run_cpu_profile` tool is guarded by a per-repo concurrency lock within a single server process:

- Only one call per `repo_path` can run at a time
- Overlapping calls for the same repo raise `RuntimeError` immediately
- Different repos can run concurrently (different locks)
- Lock is per-server-process (cross-process concurrency is not protected)

## Troubleshooting

**"Module not found" error:**
Ensure skills path is in `sys.path`. The server adds `.claude/skills/` automatically.

**`run_cpu_profile` timeouts:**
Increase the timeout in your agent's configuration (e.g., 300 seconds for Claude Code).

**Profile location issues:**
Profiles are written to `.ai_output/cpu.prof` relative to the repo path, not the MCP server's working directory.

## Development

### Running Tests

```bash
pytest mcp/tests/ -v
```

All tests are mocked (no real skill scripts are called).

### Adding a New Tool

1. Create a wrapper function in the skill file (`skill/<name>/`)
2. Create a tool module in `mcp_tools/tools/<name>.py`
3. Import it in `mcp_tools/main.py` via the tools loading loop
4. Add test cases in `mcp_tools/tests/test_<name>.py`

## Related

- [Root README](../README.md) — Overview of three implementations
- [AGENTS.md](../AGENTS.md) — Architecture and design decisions
- [Skills documentation](../.claude/skills/) — Individual skill descriptions
