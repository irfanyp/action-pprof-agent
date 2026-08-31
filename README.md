# pprof-analyzer

Analyze Go pprof profiles and generate performance optimization patches using LLM-powered analysis.

**Three implementations — choose your path:**

---

## 🚀 Quick Navigation

### For Local Analysis (Claude Code Skills)
**👉 [`skill/README.md`](skill/README.md)**

**Four complementary Claude Code skills for end-to-end performance optimization:**

1. **`pprof-integrator`** — Integrate pprof endpoint into your Go service
2. **`load-test-generator`** — Generate load test script for realistic profiling
3. **`profiler-executor`** — Run profiling with concurrent load testing
4. **`pprof-analyzer`** — Analyze profile and generate performance fixes

```bash
# Complete workflow (starting from scratch)
/pprof-integrator ./my-service          # Add pprof endpoint
/load-test-generator ./my-service       # Generate load test
/profiler-executor ./my-service         # Capture cpu.prof
/pprof-analyzer ./my-service --profile .ai_output/cpu.prof --reference med

# Or just analyze an existing profile
/pprof-analyzer cpu.prof ./ med
```

**Features:**
- ⚡ Zero configuration for analyzer (uses Claude's built-in capabilities)
- ⏱️ 15-35 seconds per analysis  
- 🧠 Complete workflow from integration to optimization
- 💻 Single-turn analysis (no agent loop)
- 📦 Easy to share with teammates

**Best for:** Developers optimizing code locally

---

### For CI/CD Automation (GitHub Action)
**👉 [`action/README.md`](action/README.md)**

- 🤖 Automated PR creation
- 🔄 Multi-turn agent loop
- 🔌 Service-based profiling
- 🎯 Integrated in GitHub workflows
- 📊 Deep analysis capabilities

```yaml
- uses: <repo>@<version>
  with:
    token: ${{ secrets.GITHUB_TOKEN }}
    ai_endpoint: ${{ secrets.AI_ENDPOINT }}
    ai_key: ${{ secrets.AI_KEY }}
    reference: med
    tags: main
```

**Best for:** Production automation & CI/CD pipelines

---

### For AI Agents via MCP (Claude Desktop, Cline, Cursor, etc.)
**👉 [`mcp/README.md`](mcp/README.md)**

- 🌐 Works with any MCP-compatible AI agent host
- 🔧 Same four skills wrapped as MCP tools
- ⚡ Instant integration (no agent setup needed)
- 🤝 Share across teams and tools
- 📱 Claude Desktop, Cline, Cursor support

```bash
# Register locally
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp/main.py
```

**Best for:** Teams using multiple AI agents, sharing analysis across tools

---

## 📊 Implementation Comparison

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

---

## 📚 Documentation

- **[AGENTS.md](AGENTS.md)** — Developer reference (both implementations)
- **[skill/SIMPLIFIED_DESIGN.md](skill/SIMPLIFIED_DESIGN.md)** — Why we simplified the skill
- **[skill/SKILL_DISTRIBUTION.md](skill/SKILL_DISTRIBUTION.md)** — How to use & share the skill
- **[skill/IMPLEMENTATION_SUMMARY.md](skill/IMPLEMENTATION_SUMMARY.md)** — Technical details
- **[action/pprof_integration.md](action/pprof_integration.md)** — How to add pprof to your Go service

---

## 🔧 For Developers

See [AGENTS.md](AGENTS.md) for:
- Complete flow documentation (both implementations)
- Development conventions
- Contribution guidelines
- Decision philosophy

---

For detailed setup and usage, choose your implementation above.
