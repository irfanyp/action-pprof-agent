# load-test-generator

Analyzes a Go service and generates a load test script to drive realistic traffic during profiling.

## Input

- `repo_path` (required) — Path to the Go repository to analyze for endpoints
- `load_tool` (optional) — Preferred load testing tool: `k6`, `apache-bench`, `wrk`, or `go` (custom Go binary). Defaults to `k6`.

## Workflow

1. Analyzes the Go service code to identify HTTP endpoints and handlers
2. Extracts request patterns, typical payloads, and URL structures
3. Generates a load test script tailored to the service
4. Provides instructions for running the load test

## Output

Load test script file (user reviews and runs manually). Formats:
- **k6** (default) — `load_test.js` JavaScript script (run with `k6 run load_test.js`)
- **apache-bench** — Shell script with `ab` commands
- **wrk** — Lua script with request patterns
- **go** — Go binary source that can be compiled and run

## Usage

```
/load-test-generator /path/to/repo [--tool k6|apache-bench|wrk|go]
```

## Example

```
/load-test-generator ./my-go-service --tool k6
```

Generates `load_test.js` with realistic traffic patterns for the detected endpoints.
