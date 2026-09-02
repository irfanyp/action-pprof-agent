# AGENTS.md

Guidance for AI agents working in this repository.

## Project overview

**pprof-analyzer** has three implementations:

1. **GitHub Action** (`action/scripts/analyzer.py`) — triggers/loads a pprof profile, converts it to markdown via `pprof-to-md`, sends it + a repo file list to an external OpenAI-compatible LLM with tool-use enabled (LLM calls a `read_file` tool in a loop to request files/lines), extracts a unified-diff patch, applies it, and opens a PR via `gh`.
2. **Claude Code Skill** (`skill/pprof_analyzer/`) — same idea, run locally, single-turn: converts the profile, lists Go files (no source read yet), builds one prompt, and returns it for Claude Code to analyze with its own native `Read` tool instead of a custom loop. No external API calls, no PR creation — writes `SUMMARY`/`PATCH` artifacts to `.ai_output/` for the user to apply.
3. **MCP Server** (`mcp_tools/`) — wraps all four skills (unmodified) as MCP tools (`analyze_pprof_profile`, `integrate_pprof_endpoint`, `generate_load_test`, `run_cpu_profile`) over stdio (or HTTP/SSE), so any MCP-compatible host can call them. Has a per-repo concurrency guard for `run_cpu_profile`.

See [README.md](README.md) for a feature comparison, [mcp_tools/README.md](mcp_tools/README.md) and [MCP_SETUP.md](MCP_SETUP.md) for MCP setup.

## Key files & structure

- **Skills**: `skill/<name>/` (underscores, e.g. `pprof_analyzer/`, `load_test_generator/`), each with `SKILL.md` + implementation. Distributed ZIP renames these to hyphens.
- **Action**: `action/scripts/analyzer.py`; tests in `action/scripts/tests/`.
- **MCP**: `mcp_tools/`, tool wrappers in `mcp_tools/tools/`, tests in `mcp_tools/tests/`.
- Docs: [README.md](README.md) (entry point), [action/README.md](action/README.md), [mcp_tools/README.md](mcp_tools/README.md), [skill/README.md](skill/README.md).

## Implementation flows

### Action (`action/scripts/analyzer.py`)

`1a` POST `/runs` → `run_id` → `1b` poll every 15s (10 min timeout), decode profile, convert via `pprof-to-md` → `1c` verify branch/tag checkout → `1d` list Go files → `1e` build prompt (template + markdown + file list + reference level) → `1f` call LLM with tool-use; LLM calls `read_file` as needed → `1g` extract `SUMMARY`/`PATCH` → `1h` `git apply --whitespace=fix` → `1i` write artifacts to `./artifacts/` → `1j` branch, commit, push, open PR → `1k` POST `/runs/{run_id}/submit`.

If `1b`–`1j` fails: `2a` POST `/runs/{run_id}/error`. In file mode (`analyzer_result_file` set): skip `1a`, `1b`, `1k`, `2a`; load the profile from disk; use a local `run_id` (`local-<timestamp>`).

### Skill (`skill/pprof_analyzer/analyzer.py`)

Validate inputs → convert pprof to markdown + list Go files via `gather_local_context()` (no source content read) → `build_analysis_prompt()` fills the template's `{file_list}` placeholder → return the prompt for Claude Code to analyze (its native `Read` tool fetches files on demand, playing the role of the Action's `read_file` loop) → extract `SUMMARY`/`PATCH` → validate with `git apply --check` → write `summary.md`, `patch.diff`, `analyzer_result.md`, `prompt.txt` to `.ai_output/`.

`gather_local_context()` and `build_analysis_prompt()` are split so the latter can run without repo/profile access — see `mcp_tools/tools/pprof_analyzer.py::build_pprof_analysis_prompt` and [MCP_SETUP.md#team-collaboration-httpsse](MCP_SETUP.md#team-collaboration-httpsse) (remote-MCP use).

Unlike the Action, the skill has: no external LLM calls, no custom `read_file` loop, no PR creation, no SERVICE_URL/polling, no credentials, and only `GitPython` as a dependency.

### Supporting skills (prerequisites for pprof-analyzer)

| Skill | Purpose | Usage | Output |
|---|---|---|---|
| `pprof-integrator` | Add `net/http/pprof` per [action/pprof_integration.md](action/pprof_integration.md) | `/pprof-integrator <repo>` | pprofserver.go + main() changes |
| `load-test-generator` | Generate load test from detected endpoints | `/load-test-generator <repo> [--tool k6\|apache-bench\|wrk\|go]` | e.g. `load_test.js` |
| `profiler-executor` | Build+run service, profile + load test in parallel | `/profiler-executor <repo> [--port] [--load-cmd] [--duration]` | `.ai_output/cpu.prof` |

Full chain: `pprof-integrator` → commit → `load-test-generator` → `profiler-executor` (produces `.ai_output/cpu.prof`) → `pprof-analyzer --profile .ai_output/cpu.prof` → review/apply patch. Requires: `go.mod` present, Go 1.11+, `pprof-to-md` on PATH, a load-test tool.

## Syncing Action ↔ Skill ↔ MCP

Action and Skill are **intentionally different** (external multi-turn LLM API + PR creation vs. local single-turn + artifacts only), but these must stay identical across the files that use them:

| Shared item | Where | Sync when |
|---|---|---|
| `PATCH_FENCE_PATTERN`, `SUMMARY_PATTERN` | `Config` in both `analyzer.py` files | LLM response format changes |
| `VALID_REFERENCES = {low, med, high}` | `Config`/`SkillConfig`, skill argparse `choices=`, MCP `Literal[...]` type hints | Adding/removing a reference level |
| `--tool` choices `{k6, apache-bench, wrk, go}` | skill argparse, MCP type hints | Adding a load-test tool |
| `PPROF_TO_MD_TIMEOUT` (60s), `GIT_OPERATIONS_TIMEOUT` (120s) | both `analyzer.py` files | Rarely |
| `GitPython~=3.1.59` pin | `skill/pprof_analyzer/requirements.txt`, `mcp_tools/requirements.txt` | Skill upgrades GitPython |
| [prompts/prompt_template.txt](prompts/prompt_template.txt) (single source of truth, repo root) | Action reads `../../../prompts/...`, Skill/MCP read `../../prompts/...`; also bundled by [Dockerfile](Dockerfile) and [skill/build-zip.sh](skill/build-zip.sh) | Prompt structure changes — edit once, all three pick it up |

**No sync needed:** Action-only (`read_file_context`, `call_llm`, `apply_patch`, `create_pull_request`, SERVICE_URL steps, step-tracking) — Skill has no agent loop or patch/PR logic. Skill-only (`gather_local_context`, `build_analysis_prompt`, `.ai_output/` location) — Action's `list_repo_files()` and `./artifacts/` differ by design. MCP-only (concurrency lock in `profiler_executor.py`, tool docstrings).

**Rebuild the distributed ZIP** (`skill/build-zip.sh`, output `skill/pprof-analyzer-skill.zip`, git-ignored) after changing any `skill/<name>/` file, a `SKILL.md`, or `action/pprof_integration.md`.

## Generated markdown → `.ai_output/`

Any markdown you generate (analysis, summaries, plans, review notes) goes in `.ai_output/` — tracked via `.gitkeep`, contents git-ignored, so it never lands in a commit. Source code changes (`.py`, `.yml`, `.txt`, `.go`, …) are committed normally.

## Development conventions

- Python deps: `action/scripts/requirements.txt` (runtime), `requirements-dev.txt` (dev). Tests: `pytest` from repo root (`action/scripts/tests/`, `skill/*/tests/`, `mcp_tools/tests/`).
- Node: `pprof-to-md` pinned in `action/package.json`; use `npm ci`.
- Style: match the file you're editing — `from __future__ import annotations`, type hints, docstrings.
- Commits: append `Co-Authored-By: Cline SR` (or whatever your harness settings specify instead).

## Common workflows

- **Feature**: write/extend a test first, reuse existing patterns, run `pytest`, check `examples/workflow.yml` still works.
- **Bug fix**: find root cause, minimal targeted fix, add a regression test, explain the "why" in the commit message.
- **Refactor**: behavior must be identical before/after (`pytest` both times); one refactor per PR; update this file if patterns change.
- **Prompt change**: edit [prompts/prompt_template.txt](prompts/prompt_template.txt) only, test against a real profile, confirm the response still parses and `git apply`s cleanly.

Before opening a PR: tests pass, the change is minimal and scoped, no new dependencies snuck in outside the pinned requirement files, and (for prompt/LLM changes) a real sample profile still produces a valid, applicable patch.

## LLM/prompt safety

- API keys and endpoint URLs: env vars only, never hardcoded or logged.
- Don't forward file contents to the LLM without going through `read_file`/the skill's file list — repo content may contain PII or secrets.
- Treat LLM output as untrusted: validate it's actually a unified-diff patch before `git apply`; redact credentials/PII when logging responses.
- Unit tests mock the LLM (fixtures in `conftest.py`); only test against a real endpoint manually, against a non-production repo.

## Repo-specific anti-patterns

- **`action.yml`** is the public contract — don't change inputs/outputs/behavior without discussing it and bumping the version first.
- **Dependencies** belong only in `action/scripts/requirements*.txt` / `action/package.json` (Dependabot tracks these) — no ad hoc version pins elsewhere.
- **Abstraction threshold**: only extract a shared function/class when a pattern repeats 3+ times, the task explicitly asks for it, or it's clearly simpler to test in isolation.

## Autonomy & escalation

**Ask first:** `action.yml` changes, breaking API changes, dependency changes, anything touching credentials/auth, large refactors of `analyzer.py` or directory structure, or whenever you're unsure if something is in scope. If a change needs a real LLM endpoint or GitHub Actions environment you don't have access to, say so and ask the owner to test it.

**Proceed autonomously:** root-caused bug fixes with a regression test, in-scope feature/test additions that don't touch the public interface, docs/comments, code-style cleanup, and Dependabot updates that pass tests.

---
This is a guide, not a rulebook — when in doubt, ask rather than assume.
