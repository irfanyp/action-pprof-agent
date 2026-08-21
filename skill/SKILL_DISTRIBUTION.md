# pprof-analyzer Claude Skill Distribution Guide

This document explains the pprof-analyzer Claude skill package and how to use it.

## What's Included

The `pprof-analyzer-skill.zip` contains a complete, ready-to-use Claude skill for analyzing Go pprof profiles and generating optimization patches.

### Package Contents

The ZIP extracts into a single flat `pprof-analyzer-skill/` directory:

```
pprof-analyzer-skill.zip
└── pprof-analyzer-skill/
    ├── SETUP.sh                       # Installation helper script (executable)
    ├── pprof-analyzer.md              # Skill definition (register in Claude Code)
    ├── pprof-integrator.md            # Skill definition
    ├── load-test-generator.md         # Skill definition
    ├── profiler-executor.md           # Skill definition
    ├── pprof_integration.md           # Go pprof integration guide
    ├── README.md                      # Complete documentation
    ├── INSTALL.md                      # Detailed installation instructions
    ├── SIMPLIFIED_DESIGN.md           # Design decisions and rationale
    ├── SKILL_DISTRIBUTION.md          # This file (sharing/distribution info)
    ├── IMPLEMENTATION_SUMMARY.md      # Technical details
    ├── pprof-analyzer/
    │   ├── analyzer.py                # Main orchestration script
    │   ├── package.json               # Node.js dependencies (pprof-to-md)
    │   ├── requirements.txt           # Python dependencies
    │   ├── SKILL.md                   # Skill metadata
    │   ├── prompts/
    │   │   └── prompt_template.txt    # Claude prompt template
    │   └── tests/
    │       └── test_analyzer.py       # Unit tests
    ├── pprof-integrator/
    │   ├── coordinator.py
    │   ├── requirements.txt
    │   └── SKILL.md
    ├── load-test-generator/
    │   ├── coordinator.py
    │   └── requirements.txt
    └── profiler-executor/
        ├── profiler.py
        └── requirements.txt
```

## Quick Start (30 seconds)

### 1. Extract

```bash
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill
```

### 2. Install

```bash
./SETUP.sh install
```

### 3. Use

In Claude Code:

```bash
/pprof-analyze cpu.prof ./ med
```

Results go to `.ai_output/`:

```bash
cat .ai_output/summary.md
git apply .ai_output/patch.diff
```

## How It Works

### Single-Turn Analysis (vs. Agent Loops)

Unlike the GitHub Action which uses a multi-turn agent loop:

```
Action Flow (multi-turn):
┌─────────────────────────────────────────┐
│ 1. Send profile to LLM                  │
├─────────────────────────────────────────┤
│ 2. LLM: "I need to read main.go"       │
│    Action: Sends main.go                │
├─────────────────────────────────────────┤
│ 3. LLM: "I need cache.go lines 50-100" │
│    Action: Sends lines 50-100           │
├─────────────────────────────────────────┤
│ 4. LLM: "Here's my patch" → Done       │
└─────────────────────────────────────────┘
```

This skill uses a simpler approach:

```
Skill Flow (single-turn):
┌──────────────────────────────────────────┐
│ 1. Extract files from hotspots (~75KB)   │
│ 2. Send EVERYTHING to Claude upfront     │
│ 3. Claude: "Here's my analysis & patch"  │
│ 4. Done!                                  │
└──────────────────────────────────────────┘
```

**Benefits:**
- ✅ Simpler (no tool-use complexity)
- ✅ Faster (single API call)
- ✅ Deterministic (no retry logic needed)

**Trade-off:**
- We include ~50-75KB of source code upfront
- Works well for most Go services

For most Go services, the hotspots are in a few key files. We include those files + their direct imports, capping at ~75KB of code. This is typically enough context for Claude to make good optimization suggestions.

## Key Features

### Smart File Selection

The skill automatically:
1. Converts pprof to markdown with `pprof-to-md`
2. Extracts file paths mentioned in hotspots
3. Includes files + their direct imports
4. Caps at ~75KB to stay within Claude's comfortable window

No manual file selection needed.

### Three Analysis Depths

- **low** — Single hotspot, low-effort fixes only
- **med** — Top hotspots, low/medium-effort fixes
- **high** — All hotspots, comprehensive analysis

Tailor the analysis to your risk tolerance.

### Full Transparency

All artifacts saved to `.ai_output/`:
- `summary.md` — Analysis results (use for PR description)
- `patch.diff` — Git-compatible patch
- `analyzer_result.md` — Detailed pprof analysis
- `prompt.txt` — Exactly what was sent to Claude (for debugging)

### Patch Validation

The skill validates patches with `git apply --check` before writing, ensuring they apply cleanly.

## Example Workflow

### Generate Profile

```bash
# Start your Go service with pprof endpoint
curl http://localhost:6060/debug/pprof/profile?seconds=30 > cpu.prof
```

### Analyze

```bash
/pprof-analyze cpu.prof ./ med
```

### Review & Apply

```bash
cat .ai_output/summary.md
cat .ai_output/patch.diff

git apply .ai_output/patch.diff
go test ./...
git commit -m "perf: optimize hotspots"
```

## Configuration

### Environment Variables

The skill uses Claude Code's built-in Claude model. **No configuration needed!**

```bash
/pprof-analyze cpu.prof ./ med
```

That's it. No API keys, no endpoints to set up.

## Sharing with Teammates

The skill is portable and self-contained:

```bash
# Share the zip file
# Each teammate extracts and installs:
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
./SETUP.sh install

# Now everyone has: /pprof-analyze
```

That's it! No additional setup needed beyond what's in `SETUP.sh install`.

## File Structure Explanation

### `pprof-analyzer.md`

The skill definition. Claude Code reads this to understand how to invoke the skill. Contains usage examples and documentation.

### `analyzer.py`

The main orchestration script. Does the heavy lifting:
1. Validates inputs
2. Converts pprof to markdown
3. Selects source files
4. Builds the prompt
5. Returns prompt to Claude
6. Extracts SUMMARY and PATCH
7. Validates patch
8. Writes artifacts

Run with: `python3 analyzer.py profile.prof ./ med`

Or via skill: `/pprof-analyze profile.prof ./ med`

### `prompt_template.txt`

The Claude prompt template. Controls how Claude analyzes the profile.

Key sections:
- Reference level instructions (low/med/high)
- Profile analysis guidance
- Output format expectations (SUMMARY + PATCH)

### `SETUP.sh`

Installation automation. Commands:
- `./SETUP.sh install` — Install skill
- `./SETUP.sh verify` — Check installation
- `./SETUP.sh uninstall` — Remove skill

### `tests/test_analyzer.py`

Unit tests for:
- SUMMARY/PATCH extraction
- File selection logic
- Hotspot extraction

Run with: `pytest pprof-analyzer/tests/`

## Advanced Usage

### Custom Output Directory

```bash
/pprof-analyze cpu.prof ./ med --output my-results/
```

### Batch Analysis

Analyze multiple profiles:

```bash
for profile in *.prof; do
  /pprof-analyze "$profile" ./ med
  # Results in .ai_output/ (overwritten each time, so save them)
  mkdir -p results/"${profile%.prof}"
  cp -r .ai_output/* results/"${profile%.prof}"/
done
```

### Integration with CI/CD

Use in your GitHub workflow:

```yaml
- name: Analyze Performance Profile
  run: |
    /pprof-analyze cpu.prof ./ med

- name: Comment on PR
  if: github.event_name == 'pull_request'
  uses: actions/github-script@v6
  with:
    script: |
      const fs = require('fs');
      const summary = fs.readFileSync('.ai_output/summary.md', 'utf8');
      github.rest.issues.createComment({
        issue_number: context.issue.number,
        owner: context.repo.owner,
        repo: context.repo.repo,
        body: '## Performance Analysis\n\n' + summary
      });
```

## Development

### Running Tests

```bash
cd pprof-analyzer
pytest tests/
```

### Modifying the Prompt

Edit `prompts/prompt_template.txt` to change how Claude analyzes profiles.

**Key placeholders:**
- `{reference_level}` — Replaced with low/med/high
- `{analyzer_result}` — Pprof markdown
- `{repository_files}` — Source code sections

### Adding New Features

The skill is designed to be minimal. For major changes:
1. Discuss in a PR
2. Maintain backward compatibility
3. Update tests
4. Update documentation

## FAQ

**Q: Why single-turn instead of agent loop?**  
A: Simpler, faster, and works well for typical Go services where hotspots are in a few key files.

**Q: Can I add more files to the analysis?**  
A: Not yet, but you can modify `analyzer.py` to change `select_files_smart()`.

**Q: What if Claude generates an invalid patch?**  
A: The skill validates with `git apply --check` and saves artifacts for debugging.

**Q: How much does it cost?**  
A: No cost! Uses Claude Code's built-in Claude. No external API calls.

**Q: Can I use my own LLM?**  
A: Not in this version. This skill is designed for Claude Code users and uses Claude directly.

**Q: Does it work on Windows?**  
A: Should work with WSL2 or native Python 3.11+. SETUP.sh is bash, so use WSL or GitBash.

## More Information

- **README.md** — Complete skill documentation
- **INSTALL.md** — Detailed setup instructions
- **examples/workflow_example.md** — Step-by-step example
- **SIMPLIFIED_DESIGN.md** — Design decisions and rationale

## License

Same as the pprof-analyzer action.

---

**Ready to start?** Extract the zip and run `./SETUP.sh install`!
