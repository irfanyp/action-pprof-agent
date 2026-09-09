# Go Performance Optimization: Developer Guideline

This guideline provides a comprehensive end-to-end framework to optimize your Go application's CPU and memory performance using LLM-powered analysis. Whether you choose a manual approach using any general LLM (ChatGPT, Claude, Gemini, DeepSeek, etc.) or run our integrated AI agent workflows (Claude Code, Cline, Gemini Code Assist, Codex, or GitHub Actions), this document outlines how to safely and empirically optimize your services.

---

## 🗺️ The Core Optimization Loop

Every optimization cycle follows this foundational engineering loop:

```
[Expose pprof Endpoint] ──> [Deploy & Stress Test] ──> [Capture cpu.prof]
                                                               │
                                                               v
[Verify with pprof -diff_base] <── [Apply Patch] <── [AI Analysis (pprof-to-md)]
```

---

## 📋 Prerequisites

Before you begin, ensure you have the following installed on your machine:

1.  **Go** (1.20 or higher) — for compiling, running, and analyzing profiles.
2.  **Node.js** (18 or higher) — required to run the `pprof-to-md` utility.
3.  **Python** (3.12 or higher) — only required if using the automated local scripts/MCP server.

---

## 🚀 Approach 1: Direct-Edit Mode (LLM Agents with File Access)
*Use this approach if you are using **agent tools with native file editing** like Claude Code, Cline, Gemini Code Assist, Cursor, or Codex. For chat-only interfaces (ChatGPT, Claude.ai without file access), paste the profile and source files as text and ask for a patch.*

### Step 1: Integrate the `pprof` Endpoint
Your Go application must expose Go's native profiling endpoint. 
1. Refer to the [pprof Integration Guide](./action/pprof_integration.md) inside this repository to understand the best integration pattern for your router or framework (e.g., Gin, Echo, Fiber, Chi, or standard `net/http`).
2. Implement and verify that the server launches. By default, standard Go HTTP exposes pprof on `/debug/pprof/`.

### Step 2: Deploy & Collect a CPU Profile
You must capture a profile while your application is under **realistic load**. Running a profile on an idle server will capture nothing of value.

1. Deploy your service locally or to a staging environment.
2. Run a load-test script (or perform manual load generation) for about 30 seconds.
3. While the load is running, fetch the 30-second CPU profile using standard curl/wget:
   ```bash
   # Captures CPU profiling data for 30 seconds and saves it locally
   curl -o cpu.prof "http://localhost:8080/debug/pprof/profile?seconds=30"
   ```
   *(Replace `localhost:8080` with your service's address and port).*

### Step 3: Convert the Profile via `pprof-to-md`
Raw `.prof` files are binary protocol buffers. LLMs cannot read them directly. You must convert the profile to LLM-friendly markdown.

1. **Install `pprof-to-md` globally via npm**:
   ```bash
   npm install -g pprof-to-md
   ```
2. **Convert your binary profile to markdown**:
   ```bash
   pprof-to-md --format detailed cpu.prof -o cpu_profile_analysis.md
   ```
   This generates `cpu_profile_analysis.md`, which contains the detailed hot path functions and call trees alongside their exact line-level execution cost.

### Step 4: Prompt Your Preferred LLM (Direct-Edit Mode)
Use an LLM agent with file access (Cline SR, Claude Code, Gemini Code Assist, Codex, etc.) together with the direct-edit prompt template in this project: [prompts/prompt_template_direct.txt](./prompts/prompt_template_direct.txt). The agent reads the profile, locates the relevant Go source files with its native tools, and applies fixes directly to your repository — no patch file is produced.

There are two ways to invoke the template:

**Scenario A — Copy-paste the template content:**
1. Open your LLM agent of choice.
2. Copy the content of the template into your prompt: [prompts/prompt_template_direct.txt](./prompts/prompt_template_direct.txt).
3. Attach or reference the converted profile markdown (`cpu_profile_analysis.md`). If you don't, the agent will look for it in the common locations (`.ai_output/analyzer_result.md`, then `analyzer_result.md` in the repo root) and ask you if it cannot find it.
4. Optionally specify the **reference level** (`low`, `med`, or `high`) — it defaults to `med` if unspecified.

**Scenario B — Reference the template by path (no copy-paste):**
Instead of pasting the template content, point the agent at the template file and pass your parameters in a single message:
```
please execute this prompts/prompt_template_direct.txt where the reference_level is high and analyzer_result is @cpu_profile_analysis.md
```
The agent reads the template itself, picks up `reference_level` and `analyzer_result` from your message, and proceeds exactly as in Scenario A. If you omit `reference_level`, it defaults to `med`; if you omit `analyzer_result`, the agent searches the common locations and asks you if it cannot find it.

**What the agent will do:** determine the reference level, classify each hotspot as application vs. non-application code (only application-code hotspots are fixable), use its native file-reading/search/editing tools to locate and inspect the relevant Go source files, apply fixes directly to the repository, and respond with a `### SUMMARY` section containing an **Executive Summary Table** (per-hotspot measured cost, Amdahl's-law upper bound, confidence, priority) plus a concise root-cause explanation of each fix.

> **Note:** Chat-only web interfaces (e.g. ChatGPT or Claude.ai without file access) cannot use the direct-edit flow. In that case, paste the profile markdown and the relevant source files into the conversation and ask for a unified diff patch to apply manually.

### Step 5: Review the AI Code Changes
Since the agent edits your source files directly (no patch file is generated), review and manage the changes with git:
```bash
# See which files were changed and what changed
git status
git diff

# Revert any unwanted file
git checkout -- path/to/file.go
```
Go is highly sensitive to formatting, so verify the edited files are properly formatted before committing:
```bash
gofmt -l .
```
(Any file listed by `gofmt -l .` needs reformatting — run `gofmt -w <file>` on it.)

### Step 6: Validate & Verify the Improvements (Crucial!)
Never trust an optimization blindly. You must empirically prove that the CPU usage decreased.

1. Re-compile and **re-deploy** your updated service.
2. Run the **exact same load-test** under the same conditions.
3. Capture a second CPU profile during the load:
   ```bash
   curl -o cpu_optimized.prof "http://localhost:8080/debug/pprof/profile?seconds=30"
   ```
4. **Compare the two profiles** using Go's built-in comparative visualization:
   ```bash
   go tool pprof -diff_base cpu.prof -http=0.0.0.0:8081 cpu_optimized.prof
   ```
5. Open your web browser at `http://localhost:8081`. The visualization will color-code functions:
   *   **Red nodes**: Performance regressions (CPU consumption increased).
   *   **Blue nodes**: Performance improvements (CPU consumption decreased).
   *   **Node sizes**: Highlight absolute savings. Ensure your target hotspots are solid blue.

---

## 🤖 Approach 2: Guided & Automated Workflows
*This repository ships three native integrations that automate the manual loop above: local Claude Code skills (Option A), an MCP server for any MCP-compatible agent host (Option B), and a GitHub Action for CI/CD (Option C). See [README.md](./README.md) for a full feature comparison.*

### Option A: Local Claude Code Skills
If you run **Claude Code**, you can leverage the pre-packaged skills in the `skill/` folder to automate integration, load generation, profiling, and patching.

#### 1. Installation
Run the automated skill installer:
```bash
cd skill/
chmod +x SETUP.sh
./SETUP.sh install
```
This registers four commands directly inside your local Claude Code CLI.

#### 2. E2E Execution inside Claude Code
```bash
# 1. Integrate pprof endpoint
/pprof-integrator ./my-go-service

# 2. Automatically generate load-testing scripts
/load-test-generator ./my-go-service --tool k6

# 3. Compile, run load test, profile, and capture .prof automatically
/profiler-executor ./my-go-service --duration 30

# 4. Convert profile, analyze codebase, and output code patches
/pprof-analyzer ./my-go-service --profile .ai_output/cpu.prof --reference med
```

---

### Option B: Model Context Protocol (MCP) Server
If you use agent hosts like **Claude Code, Claude Desktop, Cursor, Cline, or Codex**, you can expose these profiling and analysis capabilities as MCP Tools.

#### 1. Local Stdio Transport (Single User)
Start the MCP server using Python:
```bash
python3 mcp_server.py
```
**Claude Code** can register it directly:
```bash
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_server.py
```
**Claude Desktop / Cursor** (`claude_desktop_config.json`) or **Cline** (`.cline_mcp_settings.json`) — add the following block:
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
You can run a centralized MCP server over HTTP so multiple developers can connect simultaneously:
```bash
# Set an API Key for security (Required)
export MCP_API_KEY="your-highly-secure-mcp-key"
# Permit the server to run profiles locally (Optional)
export MCP_ENABLE_CPU_PROFILE=1

python3 mcp_server_http.py --port 8000
```
Connect your agents/tools to the SSE endpoint: `http://localhost:8000/sse` sending the `X-API-Key: your-highly-secure-mcp-key` header.

---

### Option C: Production GitHub Action (CI/CD Pipeline)
To automatically optimize your Go service upon pull requests or manual triggers, configure the composite GitHub Action in your workflow.

Create a GitHub workflow file (e.g., `.github/workflows/perf-optimize.yml`):
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
          ai_model: 'anthropic/claude-3-5-sonnet-20241022'  # or a self-hosted model name, e.g. 'gamma4'
          tags: ${{ github.event.inputs.tags }}
          reference: ${{ github.event.inputs.reference }}
```
**Expected Behavior:** This action will trigger a remote profiling service, fetch the raw profile, run the analysis, utilize a multi-turn agent loop to inspect your files, validate that code edits apply cleanly, and automatically commit and open a PR with the suggested optimizations.

---

## 💡 Pro-Tips for Optimization

1.  **Reference Levels Matter:**
    *   `low`: Best for safe, micro-optimizations (pre-allocating slice capacity `make([]T, 0, cap)`, avoiding runtime type casting).
    *   `med`: Confined algorithm optimizations (e.g., swapping O(N²) loops to O(N) map lookups inside a single package).
    *   `high`: Structural or package-wide refactorings (e.g., adding an in-memory cache, swapping a costly third-party package).
2.  **Beware of Noisy Samples:** If the total sample count in your converted profile is very low (e.g. less than 20 samples), the profile represents background noise, not a true hotspot. Do not attempt complex structural code modifications based on low-sample profiles.
3.  **Indentation and Whitespace:** When manually applying LLM-generated patches, make sure tabs and spaces match exactly. Go is highly sensitive to formatting, and diff engines will fail if indentation mismatches.
