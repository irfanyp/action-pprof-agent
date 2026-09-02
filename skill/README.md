# pprof-analyzer Claude Skill

Analyze Go pprof profiles and generate performance optimization patches in Claude Code — no API keys, no external LLM calls, no agent-loop code to maintain. This is the standalone Claude Code skill form of the [pprof-analyzer GitHub Action](https://github.com/irfanyusupramono/pprof-analyzer); it runs entirely locally.

> **Source repo vs. distributed ZIP:** in this repository, skill directories use underscores (`skill/pprof_analyzer/`, `skill/load_test_generator/`, …) so they can be imported as Python modules by the MCP server. The distributed ZIP renames them to hyphens (`pprof-analyzer/`, …) and installs them to `~/.claude/skills/`, for backward compatibility with the original distribution format.

## The Four Skills

| Skill | Purpose | Output |
|---|---|---|
| **pprof-integrator** | Integrate a pprof endpoint into a Go service | Code changes (pprofserver.go) |
| **load-test-generator** | Analyze a service and generate a load test | Load test script (k6, Apache Bench, …) |
| **profiler-executor** | Run profiling with load test in parallel | `cpu.prof` profile file |
| **pprof-analyzer** | Analyze a profile and generate fixes | Performance optimization patch |

Starting from a bare Go service? Run all four in order. Already have a profile? Skip straight to pprof-analyzer.

## Quick Start

Already have a profile (`.pb.gz`, `.prof`, `.pprof`)?

```bash
/pprof-analyzer cpu.prof ./ med
cat .ai_output/summary.md      # review analysis
cat .ai_output/patch.diff      # review patch
git apply .ai_output/patch.diff
```

Starting from a raw service with no pprof endpoint yet?

```bash
/pprof-integrator ./my-service                                        # integrate pprof endpoint, then commit
/load-test-generator ./my-service --tool k6                           # generate load_test.js
/profiler-executor ./my-service --load-cmd "k6 run load_test.js"      # capture .ai_output/cpu.prof
/pprof-analyzer ./my-service --profile .ai_output/cpu.prof --reference med
git apply .ai_output/patch.diff && git commit -m "perf: optimize based on profile analysis"
```

## Installation

**From the distributed ZIP:**
```bash
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
./SETUP.sh install     # installs skill files to ~/.claude/skills/, plus GitPython + pprof-to-md
./SETUP.sh verify
```

**From this source repository:**
```bash
skill/build-zip.sh
unzip skill/pprof-analyzer-skill.zip
cd pprof-analyzer-skill/ && ./SETUP.sh install
```

The ZIP extracts into a single flat `pprof-analyzer-skill/` directory:
```
pprof-analyzer-skill/
├── SETUP.sh                  # install / verify / uninstall
├── README.md, INSTALL.md     # docs
├── pprof-analyzer/           # analyzer.py, prompts/, requirements.txt, SKILL.md, tests/
├── pprof-integrator/
├── load-test-generator/
└── profiler-executor/
```
See [INSTALL.md](INSTALL.md) for manual installation and detailed prerequisites.

## How It Works

The GitHub Action drives a **custom multi-turn agent loop against an external LLM API**: it sends the profile plus a bare file list, the LLM calls a `read_file` tool, the Action's Python code intercepts that call and returns the file, and this repeats (up to ~10 times) until the LLM returns a patch.

This skill relies on **Claude Code's own agentic capabilities** instead:
1. Convert the pprof profile to markdown (`pprof-to-md`) and list the repo's Go files (`git ls-files`) — no source content is read at this stage.
2. Hand both to Claude in a single prompt.
3. Claude — already running inside Claude Code, with its own native `Read` tool — pulls whichever files it needs directly from the local repo. No custom tool-call interception, no external API client.
4. Claude returns `### SUMMARY` + `### PATCH`; the skill validates the patch with `git apply --check` and writes artifacts.

|  | GitHub Action | Skill |
|---|---|---|
| LLM calls | External API, multi-turn | Claude Code's built-in model, single turn |
| File access | Custom `read_file` tool-call loop | Claude's native `Read` tool, on demand |
| API keys | Required | None |
| Speed | 2-5 min | 15-35 sec |
| Output | Opens a PR | Artifacts in `.ai_output/` (user applies/commits) |

This means no external API calls, no credentials to manage, and no fixed cap on what Claude can inspect — it reads exactly what it asks for.

## Usage

```bash
/pprof-analyzer <profile_path> <repo_path> <reference_level>
```

- `profile_path` — path to a pprof file (`.pb.gz`, `.prof`, `.pprof`)
- `repo_path` — path to the Go repository root
- `reference_level` — `low`, `med`, or `high` (analysis depth; see below)

```bash
/pprof-analyzer cpu.prof ./ med                    # medium-depth CPU profile analysis
/pprof-analyzer /var/tmp/mem.prof ~/myproject high # comprehensive memory profile analysis
/pprof-analyzer profile.pb.gz ./ low               # conservative, single-hotspot fix
```

All artifacts go to `.ai_output/`:
```
.ai_output/
├── summary.md           # analysis table + explanation (use for PR description)
├── patch.diff           # unified diff (apply with: git apply)
├── analyzer_result.md   # detailed pprof analysis
└── prompt.txt           # full prompt sent to Claude (for debugging)
```

```bash
cat .ai_output/summary.md && cat .ai_output/patch.diff   # review
git apply .ai_output/patch.diff                           # apply
go test ./...                                             # verify
git commit -m "perf: optimize hotspots per pprof analysis"
```

### Reference levels

- **`low`** — fix only the #1 hotspot; low-effort changes only (pre-allocate, hoist invariants); typically a single file.
- **`med`** — address the top 3-5 hotspots; low- or medium-effort fixes (algorithm changes within a function/package); good default.
- **`high`** — analyze every significant hotspot; low/medium/high-effort fixes including architectural changes; larger refactors allowed if the profile justifies them.

## Supporting Skills

**pprof-integrator** — integrates `net/http/pprof` using the [action/pprof_integration.md](../action/pprof_integration.md) guide. Detects your framework (gin, echo, fiber, chi, net/http, …) and generates a dedicated pprof server on port 9987.
```bash
/pprof-integrator ./my-service
```

**load-test-generator** — analyzes your service's HTTP endpoints and request patterns, then generates a load test script (k6, Apache Bench, wrk, or custom Go) to drive traffic during profiling.
```bash
/load-test-generator ./my-service --tool k6
```

**profiler-executor** — builds and starts your service, runs `go tool pprof .../profile?seconds=30` and your load test in parallel, captures `cpu.prof` to `.ai_output/`, then stops the service.
```bash
/profiler-executor ./my-service --load-cmd "k6 run load_test.js" --duration 30
```

### Creating a profile manually

If pprof is already integrated, you can skip profiler-executor and pull profiles directly:
```bash
curl http://localhost:9987/debug/pprof/profile?seconds=30 > cpu.prof   # CPU
curl http://localhost:9987/debug/pprof/heap > mem.prof                 # memory
curl http://localhost:9987/debug/pprof/goroutine > goroutines.prof     # goroutines
```

## Troubleshooting

- **"pprof-to-md not found"** — `npm install -g pprof-to-md`
- **Patch doesn't apply cleanly** — inspect `.ai_output/prompt.txt` to see exactly what Claude received, then retry with a different `reference_level` (e.g. `low` for a smaller, safer patch)
- More detail: [INSTALL.md](INSTALL.md)

## Development

```bash
pytest skill/pprof_analyzer/tests/   # one skill's tests
pytest skill/*/tests/                # all skill tests
```

- **Prompt**: edit [prompts/prompt_template.txt](../prompts/prompt_template.txt) (shared with the Action and MCP server — see [AGENTS.md](../AGENTS.md) for the sync rules) — key placeholders are `{reference_level}`, `{analyzer_result}`, `{file_list}`.
- **File listing**: `gather_local_context()` in `skill/pprof_analyzer/analyzer.py`.
- **Rebuild the distributed ZIP** after any change under `skill/` or to `action/pprof_integration.md`: `skill/build-zip.sh`.

The skill is designed to be minimal — discuss any major change before implementing (see [AGENTS.md](../AGENTS.md)).

### Known limitations

- No iterative refinement: if Claude's patch is wrong, there's no automatic retry — try a different `reference_level` instead.
- No PR creation: the skill only writes artifacts; you apply the patch and open the PR yourself.

## FAQ

**Why not use a custom agent loop like the Action?** Claude Code already gives Claude a native `Read` tool — no need to reimplement a `read_file` request/response loop in Python.

**Can I add more files to the analysis?** No cap to change — Claude reads whatever it decides it needs.

**How much does it cost?** Nothing extra — it uses Claude Code's built-in model, no external API calls.

**Can I use a different LLM?** Not with this skill; it's built for Claude Code. The GitHub Action supports OpenAI-compatible endpoints if you need that.

**Does it work on Windows?** Yes, via WSL2 or Python 3.11+ with Git Bash (`SETUP.sh` is bash).

## Reporting issues

Include `.ai_output/prompt.txt` (what was sent to Claude) and `.ai_output/patch.diff` (what came back).

## License

Same as the pprof-analyzer action.

## See Also

- [action/pprof_integration.md](../action/pprof_integration.md) — how to add pprof endpoints to a Go service
- [INSTALL.md](INSTALL.md) — detailed installation guide
- [AGENTS.md](../AGENTS.md) — architecture and sync rules across Action/Skill/MCP implementations
