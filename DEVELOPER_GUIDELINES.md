# Go Performance Optimization: Developer Guideline

This guide covers optimizing your Go application's CPU performance with LLM-powered analysis — manually with any chat-based LLM, or through this repo's integrated agent workflows (Claude Code, MCP, GitHub Actions).

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
Use an LLM agent with file access (Claude Code, Cline, Gemini Code Assist, Codex, etc.) with the direct-edit prompt template: [prompts/prompt_template_direct.txt](./prompts/prompt_template_direct.txt). The agent reads the profile, locates the relevant Go source with its native tools, and edits your repository directly — no patch file is produced.

**Invoke it either by:**
- Pasting the template's content into your prompt, then attaching/referencing `cpu_profile_analysis.md`.
- Pointing the agent at the file by path in one message, e.g.:
  ```
  please execute this prompts/prompt_template_direct.txt where the reference_level is high and analyzer_result is @cpu_profile_analysis.md
  ```

Both take two optional parameters: **reference level** (`low`/`med`/`high`, defaults to `med`) and **analyzer_result** (defaults to searching `.ai_output/analyzer_result.md`, then `analyzer_result.md` in the repo root, and asks you if neither is found).

**The agent will:** classify each hotspot as application vs. non-application code (only application-code hotspots are fixable), inspect and edit the relevant files, then reply with a `### SUMMARY` — an Executive Summary Table (measured cost, Amdahl's-law upper bound, confidence, priority per hotspot) plus a root-cause note for each fix.

> Chat-only interfaces (e.g. ChatGPT or Claude.ai without file access) can't use this flow — paste the profile markdown and relevant source files into the conversation instead, and ask for a unified diff patch to apply manually.

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
**Expected behavior:** triggers a remote profiling service, fetches and analyzes the profile, inspects your files via a multi-turn agent loop, validates the edits apply cleanly, then commits and opens a PR.

---

## 💡 Pro-Tips for Optimization

1.  **Reference Levels Matter:**
    *   `low`: Best for safe, micro-optimizations (pre-allocating slice capacity `make([]T, 0, cap)`, avoiding runtime type casting).
    *   `med`: Confined algorithm optimizations (e.g., swapping O(N²) loops to O(N) map lookups inside a single package).
    *   `high`: Structural or package-wide refactorings (e.g., adding an in-memory cache, swapping a costly third-party package).
2.  **Beware of Noisy Samples:** If the total sample count in your converted profile is very low (e.g. less than 20 samples), the profile represents background noise, not a true hotspot. Do not attempt complex structural code modifications based on low-sample profiles.
3.  **Indentation and Whitespace:** When manually applying LLM-generated patches, make sure tabs and spaces match exactly. Go is highly sensitive to formatting, and diff engines will fail if indentation mismatches.
