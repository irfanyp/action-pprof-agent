# Go Performance Optimization: Developer Guideline

Optimize your Go application's CPU performance with LLM-powered analysis — manually or through this repo's integrated workflows (Claude Code, MCP, GitHub Actions).

---

## The Core Optimization Loop

```
[Expose pprof Endpoint] ──> [Deploy & Stress Test] ──> [Capture cpu.prof]
                                                               │
                                                               v
[Verify with pprof -diff_base] <── [Apply Patch] <── [AI Analysis (pprof-to-md)]
```

---

## Prerequisites

1. **Go** (1.20+) — compile, run, and analyze profiles.
2. **Node.js** (22+) — run the `pprof-to-md` utility.
3. **Python** (3.12+) — only for automated local scripts/MCP server.

---

## Approach 1: Direct-Edit Mode (LLM Agents with File Access)

*For agents with native file editing (Claude Code, Cline, Cursor, Codex). For chat-only interfaces, paste the profile and source files as text and request a patch.*

### Step 1: Integrate the `pprof` Endpoint
Follow the [pprof Integration Guide](./prompts/pprof_integration.md) for your framework (Gin, Echo, Fiber, Chi, or standard `net/http`). Standard Go HTTP exposes pprof on `/debug/pprof/` by default.

### Step 2: Deploy & Collect a CPU Profile
Capture a profile under **realistic load** — an idle server produces nothing useful.

```bash
curl -o cpu.prof "http://localhost:8080/debug/pprof/profile?seconds=30"
```
*(Replace `localhost:8080` with your service's address/port.)*

### Step 3: Convert the Profile via `pprof-to-md`
LLMs can't read binary `.prof` files. Convert to markdown:

```bash
make install-pprof-to-md
pprof-to-md --format detailed cpu.prof -o cpu_profile_analysis.md
```

### Step 4: Prompt Your LLM
Use the direct-edit prompt template: [prompts/prompt_template_direct.txt](./prompts/prompt_template_direct.txt). The agent reads the profile, locates relevant Go source with its native tools, and edits your repo directly.

**Invoke by:**
```
please execute this prompts/prompt_template_direct.txt where the reference_level is high and analyzer_result is @cpu_profile_analysis.md
```

Parameters: **reference level** (`low`/`med`/`high`, default `med`) and **analyzer_result** (default: searches `.ai_output/analyzer_result.md`, then `analyzer_result.md` in repo root).

The agent classifies each hotspot as application vs. non-application code (only application-code hotspots are fixable), edits relevant files, and replies with a `### SUMMARY` — an Executive Summary Table (measured cost, Amdahl's-law upper bound, confidence, priority) plus a root-cause note per fix.

> Chat-only interfaces: paste the profile markdown and source files, then request a unified diff patch to apply manually.

### Step 5: Review the AI Code Changes
```bash
git status
git diff
git checkout -- path/to/file.go   # revert an unwanted file
gofmt -l .                         # check formatting (fix with: gofmt -w <file>)
```

### Step 6: Validate & Verify the Improvements
1. Re-compile and re-deploy your updated service.
2. Run the **exact same load-test** under the same conditions.
3. Capture a second CPU profile:
   ```bash
   curl -o cpu_optimized.prof "http://localhost:8080/debug/pprof/profile?seconds=30"
   ```
4. Compare both profiles:
   ```bash
   go tool pprof -diff_base cpu.prof -http=0.0.0.0:8081 cpu_optimized.prof
   ```
5. Open `http://localhost:8081` — **red nodes** are regressions, **blue nodes** are improvements. Target hotspots should be solid blue.

---

## Approach 2: Guided & Automated Workflows

*Three integrations automate the manual loop: local Claude Code skills (Option A), an MCP server (Option B), and a GitHub Action (Option C). See [README.md](./README.md) for a feature comparison.*

### Option A: Local Claude Code Skills

```bash
make install-claude-skill    # registers four commands in Claude Code
```

```bash
# 1. Integrate pprof endpoint
/pprof-integrator ./my-go-service

# 2. Generate load-testing scripts
/load-test-generator ./my-go-service --tool k6

# 3. Compile, run load test, profile, and capture .prof
/profiler-executor ./my-go-service --duration 30

# 4. Convert profile, analyze codebase, output code patches
/pprof-analyzer .ai_output/cpu.prof ./my-go-service med
```

### Option B: MCP Server

Expose profiling and analysis as MCP tools for **Claude Code, Claude Desktop, Cursor, Cline, or Codex**.

**Stdio (single user):**
```bash
make mcp-stdio-run
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_server.py
```

**HTTP/SSE (team collaboration):**
```bash
export MCP_API_KEY="your-secure-key"
python3 mcp_server_http.py --port 8000
```
Connect agents to `http://localhost:8000/sse` with header `X-API-Key: <key>`.

See [MCP_SETUP.md](./MCP_SETUP.md) for Docker deployment and remote usage.

### Option C: GitHub Action (CI/CD)

```yaml
name: Performance Optimizer
on:
  workflow_dispatch:
    inputs:
      tags:
        description: 'Branch/Tag to analyze'
        required: true
        default: 'main'
      reference:
        description: 'Analysis Depth (low | med | high)'
        required: true
        default: 'med'

jobs:
  optimize:
    runs-on: ubuntu-latest
    steps:
      - name: Auto-Optimize and Open Pull Request
        uses: <this-repo>@<version>
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          ai_endpoint: ${{ secrets.AI_ENDPOINT }}
          ai_key: ${{ secrets.AI_KEY }}
          ai_model: 'anthropic/claude-3-5-sonnet-20241022'
          tags: ${{ github.event.inputs.tags }}
          reference: ${{ github.event.inputs.reference }}
```

Triggers a remote profiling service, analyzes the profile, inspects files via a multi-turn agent loop, then commits and opens a PR.

---

## Pro-Tips

1. **Reference levels:** `low` = single hotspot, micro-optimizations. `med` = top 3-5 hotspots, algorithm changes within a package. `high` = all hotspots, structural refactors allowed.
2. **Noisy samples:** If total sample count is very low (<20), the profile is background noise — don't make complex changes based on it.
3. **Whitespace:** Match tabs and spaces exactly when applying patches. Go is sensitive to formatting.
