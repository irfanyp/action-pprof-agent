---
name: pprof-analyzer
description: Analyze Go pprof profiles and generate performance optimization patches
command: python3 analyzer.py
---

# pprof-analyzer

Analyze Go pprof profiles and generate performance optimization patches using Claude's analysis.

## Input

- `profile_path` (required) — Path to pprof profile file (`.pb.gz`, `.prof`, `.pprof`)
- `repo_path` (required) — Path to the Go repository
- `reference_level` (required) — Analysis depth: `low`, `med`, or `high`

## Workflow

1. Validates inputs and converts pprof profile to markdown via `pprof-to-md`
2. Lists the repository's Go files (via `git ls-files`)
3. Constructs a prompt with the profile markdown + file list + reference level instructions
4. Sends to Claude, which uses its own `Read` tool to pull specific files as needed while writing the patch
5. Extracts SUMMARY and PATCH sections from Claude's response
6. Validates patch with `git apply --check`
7. Writes artifacts to `.ai_output/` for review

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

✅ File-list based — Claude reads specific files on demand via its own `Read` tool, not a bulk upfront dump  
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
