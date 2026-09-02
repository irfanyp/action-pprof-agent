# pprof-analyzer Claude Skill

Analyze Go pprof profiles and generate performance optimization patches in Claude Code.

This is a **standalone Claude skill** version of the [pprof-analyzer GitHub Action](https://github.com/irfanyusupramono/pprof-analyzer), designed to work locally without requiring GitHub Actions or a remote analyzer service.

> **Important: Source Repository vs Distributed Form**
>
> **If you're reading this in the source repository (GitHub):**
> - Skill directories use underscores: `skill/pprof_analyzer/`, `skill/load_test_generator/`, etc.
> - Setup scripts are at `skill/build-zip.sh`, `skill/SETUP.sh`
> - Tests run from `skill/<name>/tests/`
>
> **If you've extracted the distributed ZIP:**
> - Directories use hyphens: `~/.claude/skills/pprof-analyzer/`, etc.
> - Directories are installed to `~/.claude/skills/`
>
> **Note on folder naming:** The distributed ZIP uses hyphenated names (e.g., `pprof-analyzer`, `load-test-generator`) for backward compatibility. In the source repository, skill directories use underscores (e.g., `pprof_analyzer`, `load_test_generator`) to enable Python imports in the MCP server and other integrations.

## Quick Start

### Complete End-to-End Workflow (Recommended)

Starting with a raw Go service? Use the **complete workflow** with all four skills:

```bash
# 1. Integrate pprof endpoint into your service
/pprof-integrator ./my-service
   # (Review code changes, commit them)

# 2. Generate a load test script
/load-test-generator ./my-service --tool k6
   # (Review load_test.js)

# 3. Execute profiling with load test (captures cpu.prof)
/profiler-executor ./my-service --load-cmd "k6 run load_test.js"
   # (cpu.prof saved to .ai_output/)

# 4. Analyze the profile and generate fixes
/pprof-analyzer ./my-service --profile .ai_output/cpu.prof --reference med
   # (patch + summary in .ai_output/)

# 5. Review and apply the patch
git apply .ai_output/patch.diff
git commit -m "perf: optimize based on profile analysis"
```

### Quick Start (Already Have a Profile?)

If you already have a pprof profile (`.pb.gz`, `.prof`, or `.pprof`):

```bash
# 1. Analyze it with Claude (no API keys needed!)
/pprof-analyzer cpu.prof ./ med

# 2. Review the results
cat .ai_output/summary.md
cat .ai_output/patch.diff

# 3. Apply the patch
git apply .ai_output/patch.diff
```

### Install (Automatic) — From Distributed ZIP

If you have the distributed `pprof-analyzer-skill.zip`:

```bash
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
./SETUP.sh install
```

This automatically installs:
- ✅ Skill files to `~/.claude/skills/`
- ✅ Python modules (GitPython)
- ✅ Node modules (pprof-to-md)

### Install (From Source Repository)

If you're in the source repository, use the build script:

```bash
cd /path/to/pprof-analyzer
skill/build-zip.sh          # Generates pprof-analyzer-skill.zip
unzip skill/pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
./SETUP.sh install
```

## The Four Skills

This repository includes **four complementary Claude Code skills** that work together:

| Skill | Purpose | Output |
|-------|---------|--------|
| **pprof-integrator** | Integrate pprof endpoint into Go service | Code changes (pprofserver.go) |
| **load-test-generator** | Analyze service and generate load test | Load test script (k6, Apache Bench, etc.) |
| **profiler-executor** | Run profiling with load test in parallel | `cpu.prof` profile file |
| **pprof-analyzer** | Analyze profile and generate fixes | Performance optimization patch |

**Use Case:** Starting with a bare Go service? Use all four in order. Already have a profile? Skip to pprof-analyzer.

## What pprof-analyzer Does

The **pprof-analyzer** skill (the core analysis tool):

1. **Converts** your pprof profile (CPU, memory, goroutine) to detailed markdown
2. **Lists** the Go source files in the repository (via `git ls-files`)
3. **Passes** the profile markdown + file list to Claude, which reads specific files on demand with its own `Read` tool
4. **Generates** a unified diff patch with performance analysis
5. **Validates** the patch before writing it to disk
6. **Saves artifacts** to `.ai_output/` for review and debugging

## Key Features

- ✅ **No external LLM calls** — Claude Code's own model does the analysis; no agent-loop Python code to call an API
- ✅ **File-list based** — The analyzer never inlines source; Claude reads exactly the files it needs via its native `Read` tool
- ✅ **Full transparency** — All prompts and responses saved to `.ai_output/`
- ✅ **Patch validation** — Ensures generated patches apply cleanly before writing
- ✅ **Reference levels** — Control analysis depth (low/med/high)
- ✅ **Portable** — Easy to share and install across teams

## How It Works

### Unlike the GitHub Action

The full GitHub Action drives a **custom multi-turn loop against an external LLM API**:
- Calls an OpenAI-compatible endpoint with the profile + a bare file list
- LLM uses a `read_file` tool call; Action's Python code intercepts it and returns the file
- Repeat up to 10 times, then the LLM returns SUMMARY + PATCH

This skill relies on **Claude Code's own agentic capabilities** instead of custom orchestration:
- Gathers the profile markdown + file list locally (no source content read at this stage)
- Hands both to Claude in one prompt
- Claude — already running inside Claude Code, with its own `Read` tool — pulls whichever files it needs directly from the local repo, no custom tool-call interception required
- Gets back SUMMARY + PATCH, validates, and saves

**Benefits:**
- Simpler — No custom tool-use loop or external API client to maintain
- No credentials — Uses Claude Code's built-in model, not an external LLM endpoint
- Deterministic file access — Claude reads exactly what it asks for, nothing pre-selected or truncated by a size cap

## Installation

### Quick Install

```bash
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
./SETUP.sh install
```

### Manual Install

See [INSTALL.md](INSTALL.md) for detailed step-by-step instructions.

## Usage

### Basic Command

```bash
/pprof-analyze <profile_path> <repo_path> <reference_level>
```

### Arguments

- `profile_path`: Path to pprof file (`.pb.gz`, `.prof`, `.pprof`)
- `repo_path`: Path to Go repository root
- `reference_level`: `low`, `med`, or `high`

### Examples

```bash
# Analyze a CPU profile with medium depth
/pprof-analyze cpu.prof ./ med

# Analyze memory profile in a different repo
/pprof-analyze /var/tmp/mem.prof ~/myproject high

# Conservative analysis (single hotspot)
/pprof-analyze profile.pb.gz ./ low
```

### Output

All artifacts go to `.ai_output/`:

```
.ai_output/
├── summary.md           # Analysis table and explanation (use for PR description)
├── patch.diff           # Unified diff patch (apply with: git apply)
├── analyzer_result.md   # Detailed pprof analysis
└── prompt.txt           # Full prompt sent to Claude (for debugging)
```

### Applying the Patch

```bash
# 1. Review the summary
cat .ai_output/summary.md

# 2. Review the patch
cat .ai_output/patch.diff

# 3. Apply if satisfied
git apply .ai_output/patch.diff

# 4. Test
go test ./...
go run . -benchmark  # or your perf test

# 5. Commit
git add -A
git commit -m "perf: optimize hotspots per pprof analysis

Based on analysis in .ai_output/summary.md
"
```

## Supporting Skills in Detail

### 1. pprof-integrator — Add pprof to Your Service

**Purpose:** Integrate `net/http/pprof` endpoint into a Go service using the [action/pprof_integration.md](../action/pprof_integration.md) guide.

**Usage:**
```bash
/pprof-integrator ./my-service
```

**What it does:**
1. Detects your Go framework (gin, echo, fiber, chi, net/http, etc.)
2. Reads the pprof integration guide
3. Generates code changes to add pprof endpoint
4. You review and commit the changes

**Output:** Code changes (pprofserver.go, main() modifications) to start a dedicated pprof server on port 9987.

---

### 2. load-test-generator — Create a Load Test Script

**Purpose:** Analyze your Go service and generate a load test script to drive realistic traffic during profiling.

**Usage:**
```bash
/load-test-generator ./my-service --tool k6
```

**What it does:**
1. Analyzes your service code for HTTP endpoints
2. Extracts typical request patterns
3. Generates a load test script in your preferred tool (k6, Apache Bench, wrk, custom Go)
4. You review and run the script during profiling

**Output:** Load test script (e.g., `load_test.js` for k6) ready to run.

---

### 3. profiler-executor — Capture Profiling Data

**Purpose:** Run Go CPU profiling with concurrent load testing to capture realistic performance data.

**Usage:**
```bash
/profiler-executor ./my-service --load-cmd "k6 run load_test.js" --duration 30
```

**What it does:**
1. Builds your service
2. Starts it (must have pprof endpoint integrated)
3. Runs profiler and load test in parallel:
   - Profiler: `go tool pprof ... > cpu.prof`
   - Load test: Your load test command
4. Captures `cpu.prof` to `.ai_output/`
5. Stops the service

**Output:** `cpu.prof` binary profile file ready for analysis.

---

### Complete Workflow Example

```bash
# Step 1: Integrate pprof
/pprof-integrator ./my-service
# Review and commit code changes

# Step 2: Generate load test
/load-test-generator ./my-service --tool k6
# Review load_test.js

# Step 3: Capture profile
/profiler-executor ./my-service --load-cmd "k6 run load_test.js"
# .ai_output/cpu.prof now exists

# Step 4: Analyze and generate fixes
/pprof-analyzer ./my-service --profile .ai_output/cpu.prof --reference med
# Review .ai_output/summary.md and .ai_output/patch.diff

# Step 5: Apply patch and test
git apply .ai_output/patch.diff
go test ./...
go run . -benchmark
git commit -m "perf: optimize based on pprof analysis"
```

## Reference Levels

### `low` — Single Hotspot, Low-Effort Fixes

Best for: Conservative optimization, quick analysis

- Fix only the #1 highest-impact hotspot
- Only low-effort changes (pre-allocate, hoist invariants, avoid redundant work)
- Minimal code changes
- Single file typically

### `med` — Top Hotspots, Medium-Effort Fixes

Best for: Balanced optimization, typical use case

- Address top 3-5 hotspots
- Allow low or medium-effort fixes (algorithm changes within function/package)
- Multiple files OK
- Good return on investment

### `high` — All Significant Hotspots, Comprehensive Fixes

Best for: Deep optimization, architectural changes allowed

- Analyze every significant hotspot
- Allow low, medium, and high-effort fixes (including architecture changes)
- Larger refactors OK (if justified by profile data)
- Deepest analysis

## Example Workflow

```bash
# 1. Generate a CPU profile for your Go service (or use profiler-executor skill)
curl http://localhost:9987/debug/pprof/profile?seconds=30 > cpu.prof

# 2. Run the skill (no API keys needed - uses Claude's built-in capabilities!)
/pprof-analyzer cpu.prof ./ med

# 3. Review results
cat .ai_output/summary.md

# Sample output:
# | ID | File | Function | Self % | Reduction | Confidence | Priority |
# |---|---|---|---|---|---|---|
# | 1 | main.go | parseRequest | 12.5% | 12.5% | High (n=5000) | 1 |
# | 2 | cache/cache.go | Get | 8.2% | 8.2% | High (n=5000) | 2 |

# 4. Review the patch
cat .ai_output/patch.diff

# 5. Test locally
git apply .ai_output/patch.diff
go test ./...
go run . -benchtime=10s

# 6. If satisfied, commit
git add -A
git commit -m "perf: optimize request parsing and caching"
git push

# 7. Re-profile to measure improvement
curl http://localhost:6060/debug/pprof/profile?seconds=30 > cpu-after.prof
```

## Troubleshooting

### "pprof-to-md not found"

```bash
npm install -g pprof-to-md
```

### Patch doesn't apply cleanly

1. Check the prompt: `cat .ai_output/prompt.txt`
2. Try a different reference level: `/pprof-analyze profile.prof ./ low`
3. Try a different model: `/pprof-analyze --model gpt-4o profile.prof ./ med`

See [INSTALL.md](INSTALL.md) for more troubleshooting.

## How Hotspots Are Analyzed

The skill automatically:

1. **Converts** the pprof binary with `pprof-to-md --format detailed`
2. **Lists** the repository's Go files with `git ls-files`
3. **Passes** the profile markdown + file list to Claude

Claude then reads whichever files it actually needs with its own `Read` tool — no manual file specification, and no fixed size cap on what it can inspect.

## Creating a Profile

### Automated: Use profiler-executor

**Recommended:** Use the `profiler-executor` skill to automatically capture profiles with load testing:

```bash
/profiler-executor ./my-service --load-cmd "k6 run load_test.js" --duration 30
```

This runs profiling with realistic load, capturing to `.ai_output/cpu.prof`.

### Manual: Extract Profile from Running Service

If you already have pprof integrated (via `pprof-integrator` or manually), you can extract profiles manually:

#### CPU Profile (30 seconds)

```bash
curl http://localhost:9987/debug/pprof/profile?seconds=30 > cpu.prof
```

#### Memory Profile

```bash
curl http://localhost:9987/debug/pprof/heap > mem.prof
```

#### Goroutine Profile

```bash
curl http://localhost:9987/debug/pprof/goroutine > goroutines.prof
```

#### Using pprof CLI

```bash
# Generate profile
go tool pprof http://localhost:9987/debug/pprof/profile

# Save to file (inside pprof interactive)
(pprof) save /tmp/cpu.prof
```

See [action/pprof_integration.md](../action/pprof_integration.md) for how to integrate pprof into your Go service, or use `pprof-integrator` skill for automated integration.

## No API Keys Required

Unlike the GitHub Action, the Claude Code skill:
- ✅ Uses Claude's built-in capabilities (no external API calls)
- ✅ No API keys or endpoint configuration needed
- ✅ Works entirely within Claude Code
- ✅ Zero credentials to manage

The GitHub Action variant (if using external LLM services) would have API costs, but the Claude Code skill version is included with your Claude Code subscription.

## Sharing the Skill

The entire skill is portable and can be shared with teammates:

```bash
# Share the pre-built zip file (skill/pprof-analyzer-skill.zip)
# Each teammate can extract and install:
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
./SETUP.sh install
```

To rebuild the ZIP after making changes, run from the repository root:

```bash
skill/build-zip.sh
```

## Development

### Running Tests

For developers working in the source repository:

```bash
pip install pytest
pytest skill/pprof_analyzer/tests/
```

To run all skill tests:

```bash
pytest skill/*/tests/
```

**Note:** Skill directories use underscores in the source repository (e.g., `pprof_analyzer`) to support Python imports. In the distributed ZIP package, they use hyphens (e.g., `pprof-analyzer`) for backward compatibility.

### Adding Features

The skill is designed to be minimal and focused. Any major changes should be discussed before implementing.

### Reporting Issues

Include:
1. `.ai_output/prompt.txt` (what was sent to Claude)
2. `.ai_output/patch.diff` (what Claude returned)
3. Claude/OpenAI API error messages (if any)

## License

Same as the pprof-analyzer action.

## See Also

- [pprof_integration.md](pprof_integration.md) — How to add pprof endpoints to your Go service
- [INSTALL.md](INSTALL.md) — Detailed installation guide
- [examples/](examples/) — Example profiles and expected outputs

---

**Questions?** Check [INSTALL.md](INSTALL.md) for detailed setup, or review `.ai_output/prompt.txt` after running the skill to see exactly what Claude received.
