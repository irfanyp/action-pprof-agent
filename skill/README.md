# pprof-analyzer Claude Skill

Analyze Go pprof profiles and generate performance optimization patches in Claude Code.

This is a **standalone Claude skill** version of the [pprof-analyzer GitHub Action](https://github.com/irfanyusupramono/pprof-analyzer), designed to work locally without requiring GitHub Actions or a remote analyzer service.

## Quick Start

### Step 1: Install (Automatic)

```bash
./SETUP.sh install
```

This automatically installs:
- ✅ Skill files to `~/.claude/skills/`
- ✅ Python modules (GitPython)
- ✅ Node modules (pprof-to-md)

**No manual module installation needed!**

### Step 2-5: Analyze

```bash
# 2. Generate a pprof profile
curl http://localhost:6060/debug/pprof/profile?seconds=30 > cpu.prof

# 3. Analyze it with Claude (no API keys needed!)
/pprof-analyze cpu.prof ./ med

# 4. Claude analyzes and generates a patch
# Review the results
cat .ai_output/summary.md
cat .ai_output/patch.diff

# 5. Apply the patch
git apply .ai_output/patch.diff
```

## What It Does

1. **Converts** your pprof profile (CPU, memory, goroutine) to detailed markdown
2. **Extracts** the Go source files mentioned in the hotspots
3. **Passes all context** to Claude upfront (no back-and-forth tool calls)
4. **Generates** a unified diff patch with performance analysis
5. **Validates** the patch before writing it to disk
6. **Saves artifacts** to `.ai_output/` for review and debugging

## Key Features

- ✅ **Single-turn analysis** — No agent loops, just one Claude call with all context
- ✅ **Smart file selection** — Automatically finds relevant source files from hotspots
- ✅ **Full transparency** — All prompts and responses saved to `.ai_output/`
- ✅ **Patch validation** — Ensures generated patches apply cleanly before writing
- ✅ **Reference levels** — Control analysis depth (low/med/high)
- ✅ **Portable** — Easy to share and install across teams

## How It Works

### Unlike the GitHub Action

The full GitHub Action uses a **multi-turn agent loop**:
- Sends profile to LLM
- LLM uses `read_file` tool to request specific source files
- Action provides them
- LLM refines analysis
- Repeat up to 10 times

This skill uses a **single-turn approach**:
- Collects all relevant source files upfront (~50-75KB of code)
- Sends everything to Claude in one prompt
- Gets back SUMMARY + PATCH
- Validates and saves

**Benefits:**
- Simpler — No tool-use loop complexity
- Faster — Single API call instead of 10+
- Deterministic — No retries or edge cases

**Trade-off:**
- We include more source code upfront (but smart-selected)
- Works well for most Go services (hotspots are usually in a few key files)

## Installation

### Quick Install

```bash
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

## Configuration

### Environment Variables

```bash
AI_ENDPOINT="https://api.openai.com/v1"  # LLM endpoint (required)
AI_KEY="sk-..."                          # API key (required)
AI_MODEL="claude-opus-5"                 # Model (optional, default shown)
```

### CLI Flags (Override Env Vars)

```bash
/pprof-analyze \
  --endpoint https://api.openai.com/v1 \
  --key sk-... \
  --model gpt-4o \
  profile.prof ./ med
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
# 1. Generate a CPU profile for your Go service
curl http://localhost:6060/debug/pprof/profile?seconds=30 > cpu.prof

# 2. Run the skill
export AI_ENDPOINT="https://api.anthropic.com"
export AI_KEY="your-key"
/pprof-analyze cpu.prof ./ med

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

### "AI endpoint not configured"

```bash
export AI_ENDPOINT="https://api.openai.com/v1"
export AI_KEY="sk-..."
```

### Patch doesn't apply cleanly

1. Check the prompt: `cat .ai_output/prompt.txt`
2. Try a different reference level: `/pprof-analyze profile.prof ./ low`
3. Try a different model: `/pprof-analyze --model gpt-4o profile.prof ./ med`

See [INSTALL.md](INSTALL.md) for more troubleshooting.

## How Hotspots Are Extracted

The skill automatically:

1. **Converts** the pprof binary with `pprof-to-md --format detailed`
2. **Parses** the output to find file paths (e.g., `main.go`, `utils/cache.go`)
3. **Includes** those files + their direct imports
4. **Caps** total code at ~75KB to stay within Claude's context window
5. **Passes** everything to Claude upfront

This "smart selection" means you get all the context Claude needs without manual setup.

## Creating a Profile

### CPU Profile (30 seconds)

```bash
curl http://localhost:6060/debug/pprof/profile?seconds=30 > cpu.prof
```

### Memory Profile

```bash
curl http://localhost:6060/debug/pprof/heap > mem.prof
```

### Goroutine Profile

```bash
curl http://localhost:6060/debug/pprof/goroutine > goroutines.prof
```

### Using pprof CLI

```bash
# Generate profile
go tool pprof http://localhost:6060/debug/pprof/profile

# Save to file (inside pprof interactive)
(pprof) save /tmp/cpu.prof
```

See [pprof_integration.md](pprof_integration.md) for how to integrate pprof into your Go service.

## Cost Estimation

The skill makes a single API call to Claude. Cost depends on:

- **Input tokens**: ~5,000-15,000 (profile + source code)
- **Output tokens**: ~1,000-4,000 (SUMMARY + PATCH)

For typical usage:
- Claude Opus: ~$0.05-0.15 per analysis
- GPT-4o: ~$0.05-0.20 per analysis

Much cheaper than the GitHub Action (which polls a service for minutes).

## Sharing the Skill

The entire skill is portable and can be shared with teammates:

```bash
# Create a distribution package
zip -r pprof-analyzer-skill.zip \
  .claude/skills/pprof-analyzer.md \
  .claude/skills/_impl_pprof_analyzer/ \
  examples/ \
  INSTALL.md \
  README.md \
  SETUP.sh

# Share the zip file
# Each teammate can extract and run: ./SETUP.sh install
```

## Development

### Running Tests

```bash
pip install pytest
pytest .claude/skills/_impl_pprof_analyzer/tests/
```

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
