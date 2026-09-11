# Go Performance Optimization: Developer Guideline

Optimize your Go application's CPU performance with LLM-powered analysis — manually with any chat-based LLM, or through this repo's integrated agent workflows (Claude Code, MCP, GitHub Actions).

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
2. **Node.js** (18+) — run the `pprof-to-md` utility.
3. **Python** (3.12+) — only for automated local scripts/MCP server.

---

## Approach 1: Direct-Edit Mode (LLM Agents with File Access)

*For agents with native file editing (Claude Code, Cline, Gemini Code Assist, Cursor, Codex). For chat-only interfaces (ChatGPT, Claude.ai), paste the profile and source files as text and request a patch.*

### Step 1: Integrate the `pprof` Endpoint
1. Follow the [pprof Integration Guide](./prompts/pprof_integration.md) for your router or framework (Gin, Echo, Fiber, Chi, or standard `net/http`).
2. Verify the server launches. Standard Go HTTP exposes pprof on `/debug/pprof/` by default.

### Step 2: Deploy & Collect a CPU Profile
Capture a profile under **realistic load** — an idle server produces nothing useful.

1. Deploy your service locally or to staging.
2. Run a load-test script for ~30 seconds.
3. While the load runs, fetch the CPU profile:
   ```bash
   curl -o cpu.prof "http://localhost:8080/debug/pprof/profile?seconds=30"
   ```
   *(Replace `localhost:8080` with your service's address/port.)*

### Step 3: Convert the Profile via `pprof-to-md`
LLMs can't read binary `.prof` files. Convert to markdown:

1. **Install globally:**
   ```bash
   make install-pprof-to-md
   ```
2. **Convert:**
   ```bash
   pprof-to-md --format detailed cpu.prof -o cpu_profile_analysis.md
   ```
   This produces `cpu_profile_analysis.md` with hot path functions, call trees, and line-level execution costs.

### Step 4: Prompt Your LLM (Direct-Edit Mode)
Use an LLM agent with file access and the direct-edit prompt template: [prompts/prompt_template_direct.txt](./prompts/prompt_template_direct.txt). It reads the profile, locates relevant Go source with its native tools, and edits your repo directly — no patch file is produced.

**Invoke by:**
- Pasting the template content into your prompt, then attaching/referencing `cpu_profile_analysis.md`.
- Pointing the agent at the file in one message:
  ```
  please execute this prompts/prompt_template_direct.txt where the reference_level is high and analyzer_result is @cpu_profile_analysis.md
  ```

Both accept optional parameters: **reference level** (`low`/`med`/`high`, default `med`) and **analyzer_result** (default: searches `.ai_output/analyzer_result.md`, then `analyzer_result.md` in repo root, asks if neither found).

**The agent then:** classifies each hotspot as application vs. non-application code (only application-code hotspots are fixable), inspects and edits relevant files, and replies with a `### SUMMARY` — an Executive Summary Table (measured cost, Amdahl's-law upper bound, confidence, priority per hotspot) plus a root-cause note per fix.

> Chat-only interfaces (ChatGPT, Claude.ai without file access): paste the profile markdown and relevant source files, then request a unified diff patch to apply manually.

### Step 5: Review the AI Code Changes
The agent edits source files directly. Review with git:
```bash
git status
git diff

# Revert an unwanted file
git checkout -- path/to/file.go
```
Go is sensitive to formatting — verify before committing:
```bash
gofmt -l .
```
*(Any listed file needs `gofmt -w <file>`.)*

### Step 6: Validate & Verify the Improvements
Empirically prove that CPU usage decreased.

1. Re-compile and **re-deploy** your updated service.
2. Run the **exact same load-test** under the same conditions.
3. Capture a second CPU profile:
   ```bash
   curl -o cpu_optimized.prof "http://localhost:8080/debug/pprof/profile?seconds=30"
   ```
4. **Compare both profiles:**
   ```bash
   go tool pprof -diff_base cpu.prof -http=0.0.0.0:8081 cpu_optimized.prof
   ```
5. Open `http://localhost:8081` in your browser:
   * **Red nodes**: regressions (CPU increased).
   * **Blue nodes**: improvements (CPU decreased).
   * **Node sizes**: absolute savings. Target hotspots should be solid blue.

---

## Approach 2: Guided & Automated Workflows

*Three integrations automate the manual loop: local Claude Code skills (Option A), an MCP server for any MCP-compatible host (Option B), and a GitHub Action for CI/CD (Option C). See [README.md](./README.md) for a feature comparison.*

### Option A: Local Claude Code Skills
Use the pre-packaged skills in `skill/` to automate integration, load generation, profiling, and patching.

#### 1. Installation
```bash
make install-claude-skill
```
This registers four commands in your local Claude Code CLI.

#### 2. E2E Execution inside Claude Code
```bash
# 1. Integrate pprof endpoint
/pprof-integrator ./my-go-service

# 2. Generate load-testing scripts
/load-test-generator ./my-go-service --tool k6

# 3. Compile, run load test, profile, and capture .prof
/profiler-executor ./my-go-service --duration 30

# 4. Convert profile, analyze codebase, output code patches
/pprof-analyzer ./my-go-service --profile .ai_output/cpu.prof --reference med
```

---

### Option B: Model Context Protocol (MCP) Server
Expose profiling and analysis capabilities as MCP Tools for agent hosts like **Claude Code, Claude Desktop, Cursor, Cline, or Codex**.

#### 1. Local Stdio Transport (Single User)
```bash
make mcp-stdio-run
```
**Claude Code** registration:
```bash
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_server.py
```
**Claude Desktop / Cursor** (`claude_desktop_config.json`) or **Cline** (`.cline_mcp_settings.json`):
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "command": "python3",
      "args": ["/absolute/path/to/pprof-analyzer/mcp_server.py"]
    }
  }
}
```

#### 2. Shared HTTP/SSE Transport (Team Collaboration)
Run a centralized MCP server so multiple developers can connect simultaneously:
```bash
export MCP_API_KEY="your-highly-secure-mcp-key"  # Required
export MCP_ENABLE_CPU_PROFILE=1                  # Optional: allow local profiling

python3 mcp_server_http.py --port 8000
```
Connect agents to the SSE endpoint: `http://localhost:8000/sse` with header `X-API-Key: your-highly-secure-mcp-key`.

---

### Option C: Production GitHub Action (CI/CD Pipeline)
Automatically optimize your Go service on pull requests or manual triggers.

Create a workflow file (e.g., `.github/workflows/perf-optimize.yml`):
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
        uses: <this-repo>@<version>  # e.g. your-org/pprof-analyzer@v1
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          ai_endpoint: ${{ secrets.AI_ENDPOINT }}
          ai_key: ${{ secrets.AI_KEY }}
          ai_model: 'anthropic/claude-3-5-sonnet-20241022'  # or a self-hosted model name
          tags: ${{ github.event.inputs.tags }}
          reference: ${{ github.event.inputs.reference }}
```
**Expected behavior:** triggers a remote profiling service, fetches and analyzes the profile, inspects files via a multi-turn agent loop, validates edits apply cleanly, then commits and opens a PR.

---

## Pro-Tips for Optimization

1. **Reference Levels Matter:**
   * `low`: Safe micro-optimizations (pre-allocating slice capacity, avoiding runtime type casting).
   * `med`: Algorithm optimizations within a single package (e.g., O(N²) → O(N) map lookups).
   * `high`: Structural or package-wide refactorings (e.g., adding an in-memory cache, swapping a costly dependency).
2. **Beware of Noisy Samples:** If total sample count is very low (<20), the profile is background noise — don't make complex structural changes based on it.
3. **Indentation and Whitespace:** Match tabs and spaces exactly when applying patches. Go is sensitive to formatting; diff engines fail on mismatched indentation.
