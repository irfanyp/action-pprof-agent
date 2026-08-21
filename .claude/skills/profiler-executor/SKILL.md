---
name: profiler-executor
description: Execute Go CPU profiling with concurrent load testing
command: python3 profiler.py
---

# profiler-executor

Executes Go CPU profiling with concurrent load testing to capture realistic performance data. Produces `cpu.prof` for analysis by `pprof-analyzer`.

## Input

- `repo_path` (required) — Path to the Go repository (must have pprof endpoint integrated)
- `service_port` (optional) — Main service port. Defaults to `:8080`
- `load_test_cmd` (optional) — Command to run load test. If omitted, uses simple request loop.
- `profile_duration` (optional) — CPU profiling duration in seconds. Defaults to `30`.

## Workflow

1. Validates service repo has pprof endpoint integrated (checks for pprof port 9987 by default)
2. Builds and starts the service in background
3. Runs profiler and load test **in parallel**:
   - **Profiler:** `go tool pprof -text localhost:9987/debug/pprof/profile?seconds=30 > cpu.prof`
   - **Load test:** Executes load test command (curl loop, k6, wrk, etc.)
4. Captures `cpu.prof` and stops the service
5. Outputs profile to `.ai_output/cpu.prof` (ready for `pprof-analyzer`)

## Output

- `cpu.prof` — Raw pprof CPU profile (binary format)
- `.ai_output/` directory with:
  - `cpu.prof` — The captured profile
  - `profiling.log` — Profiling execution log
  - `load_test.log` — Load test execution log

## Usage

```
/profiler-executor /path/to/repo [--port 8080] [--load-cmd "k6 run load_test.js"] [--duration 30]
```

## Example

```
/profiler-executor ./my-go-service --port 8080 --load-cmd "k6 run load_test.js" --duration 30
```

Executes profiling for 30 seconds while running k6 load test, captures `cpu.prof` to `.ai_output/`.

## Prerequisites

- Service must have pprof endpoint integrated (use `pprof-integrator` first if needed)
- `go` command available
- `go tool pprof` available (built-in to Go)
- Load test tool available if using custom load command (k6, wrk, etc.)

## Next Step

After profiling completes, run `pprof-analyzer` on the generated `cpu.prof`:
```
/pprof-analyzer ./my-go-service --profile .ai_output/cpu.prof --reference med
```
