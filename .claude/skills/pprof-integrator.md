# pprof-integrator

Integrates Go `net/http/pprof` profiling endpoint into a service using the guidance from `action/pprof_integration.md`.

## Input

- `repo_path` (required) — Path to the Go repository to integrate pprof into

## Workflow

1. Detects the Go framework in use (net/http, gin, echo, fiber, chi, gRPC, controller-runtime, etc.)
2. Reads `action/pprof_integration.md` to understand integration patterns
3. Applies the appropriate integration based on detected framework
4. Generates code changes for user review (no automatic PR)

## Output

Code changes directly to the repository (user reviews and commits manually). Changes include:
- `pprofserver.go` or `internal/debug/pprof.go` — Self-contained pprof server starter
- Updates to `main()` to wire in the pprof server
- Environment variable configuration for `PPROF_PORT`, `PPROF_BIND_ADDR`, `ENABLE_PPROF`

## Usage

```
/pprof-integrator /path/to/repo
```

## Example

```
/pprof-integrator ./my-go-service
```

Will detect the framework, read the integration guide, and apply pprof integration code.
