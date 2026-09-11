# pprof-analyzer

Analyze Go pprof profiles and generate performance optimization patches using LLM-powered analysis. Three implementations — pick the one that matches your workflow.

## Quick Navigation

### Local Analysis — [`skill/README.md`](skill/README.md)

Four complementary Claude Code skills covering the full workflow from pprof integration to optimization:

1. **`pprof-integrator`** — Integrate pprof endpoint into your Go service
2. **`load-test-generator`** — Generate load test script for realistic profiling
3. **`profiler-executor`** — Run profiling with concurrent load testing
4. **`pprof-analyzer`** — Analyze profile and generate performance fixes

```bash
# Complete workflow (starting from scratch)
/pprof-integrator ./my-service          # Add pprof endpoint
/load-test-generator ./my-service       # Generate load test
/profiler-executor ./my-service         # Capture cpu.prof
/pprof-analyzer .ai_output/cpu.prof ./my-service med

# Or just analyze an existing profile
/pprof-analyzer cpu.prof ./ med
```

Zero configuration, self-contained skill folder. Best for developers optimizing code locally.

### CI/CD Automation — [`action/README.md`](action/README.md)

Runs as a service-based GitHub Action step with a multi-turn LLM agent loop, opening a Pull Request automatically.

```yaml
- uses: <repo>@<version>
  with:
    token: ${{ secrets.GITHUB_TOKEN }}
    ai_endpoint: ${{ secrets.AI_ENDPOINT }}
    ai_key: ${{ secrets.AI_KEY }}
    reference: med
    tags: main
```

Best for production automation and CI/CD pipelines.

### AI Agents via MCP — [`MCP_SETUP.md`](MCP_SETUP.md) & [`mcp_tools/README.md`](mcp_tools/README.md)

Wraps the same four skills as MCP tools, usable from any MCP-compatible AI agent host. Two transport options:

**Stdio** (single user, local):
```bash
make mcp-stdio-run
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_server.py
```

**HTTP/SSE** (multiple users, team collaboration):
```bash
python3 mcp_server_http.py              # Runs on http://localhost:8000
# Multiple agents connect to: http://localhost:8000/sse
```

Best for teams sharing analysis tools across multiple AI agents.

## Implementation Comparison

| Feature | Claude Code Skill | GitHub Action | MCP Server |
|---------|------------------|----------------|-----------|
| **Invocation** | `/pprof-analyzer` in Claude Code | GitHub workflow | Any MCP agent host |
| **Supported Hosts** | Claude Code only | GitHub only | Claude Desktop, Cline, Cursor, etc. |
| **Setup Time** | 10 seconds | 5 minutes | 2 minutes (registration) |
| **Analysis Speed** | 15-35 seconds | 2-5 minutes | 15-35 seconds |
| **Requires API Keys** | No | Yes | No |
| **PR Creation** | Manual | Automatic | Via agent host |
| **LLM Loop** | Single-turn | Multi-turn | Single-turn |
| **Use Case** | Interactive local analysis | Production automation | Multi-agent teams |

## Documentation

- **[MCP_SETUP.md](MCP_SETUP.md)** — MCP server setup, Docker, and production deployment
- **[AGENTS.md](AGENTS.md)** — Developer reference: flow documentation, conventions, and contribution guidelines
- **[skill/README.md](skill/README.md)** — Claude Code skill usage, design, and distribution
- **[prompts/pprof_integration.md](prompts/pprof_integration.md)** — How to add pprof to your Go service
