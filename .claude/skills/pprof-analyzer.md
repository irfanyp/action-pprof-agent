# pprof-analyzer

Analyze Go pprof profiles and generate performance optimization patches using Claude's analysis.

## Input

- `profile_path` (required) — Path to pprof profile file (`.pb.gz`, `.prof`, `.pprof`)
- `repo_path` (required) — Path to the Go repository
- `reference_level` (required) — Analysis depth: `low`, `med`, or `high`

## Workflow

1. Validates inputs and converts pprof profile to markdown via `pprof-to-md`
2. Intelligently selects relevant Go source files from hotspots (capped at ~75KB)
3. Reads all source code upfront
4. Constructs comprehensive prompt with profile + source code + reference level instructions
5. Sends to Claude for single-turn analysis
6. Extracts SUMMARY and PATCH sections from response
7. Validates patch with `git apply --check`
8. Writes artifacts to `.ai_output/` for review

## Output

Artifacts saved to `.ai_output/`:
- `summary.md` — Analysis table and explanation (ready for PR description)
- `patch.diff` — Unified diff patch (apply with `git apply`)
- `analyzer_result.md` — Detailed pprof analysis
- `prompt.txt` — Full prompt sent to Claude (for debugging)

## Usage

```
/pprof-analyzer <profile_path> <repo_path> <reference_level>
```

## Example

```
/pprof-analyzer cpu.prof ./ med
```

Analyzes the CPU profile at medium depth (top 3-5 hotspots, medium-effort fixes).

## Reference Levels

- **low** — Single hotspot, low-effort fixes (pre-allocate, hoist invariants)
- **med** — Top hotspots, medium-effort fixes (algorithm changes within function/package)
- **high** — All significant hotspots, comprehensive fixes (including architectural changes)

## Key Features

✅ Single-turn analysis — No agent loops, all context upfront  
✅ Smart file selection — Only includes relevant source code  
✅ Full transparency — Complete prompt/response saved for debugging  
✅ Patch validation — Ensures patches apply cleanly  
✅ Zero credentials needed — Uses Claude Code's built-in Claude  

## Prerequisites

- Go repository with `go.mod`
- `pprof-to-md` available (auto-installed with skill)
- Existing pprof profile file

## Related Skills

For complete end-to-end workflow starting from raw service:

1. **pprof-integrator** — Add pprof endpoint to your service
2. **load-test-generator** — Generate load test script
3. **profiler-executor** — Capture cpu.prof with realistic load
4. **pprof-analyzer** (this skill) — Analyze and generate fixes
