# AGENTS.md

Guidance for AI agents (e.g. Claude Code, Cline, Copilot) working in this repository.

## Project overview

**pprof-analyzer** has three implementations:

### 1. GitHub Action (action/scripts/analyzer.py)
A reusable GitHub Action that:
1. Triggers a pprof analyzer service (or loads a raw pprof profile from a file).
2. Converts the raw profile to LLM-friendly markdown via `pprof-to-md`.
3. Lists repository files and feeds the analyzer result + file list to an LLM (OpenAI-compatible endpoint).
4. The LLM uses a `read_file` tool to request specific files/line ranges as needed (agent loop).
5. Extracts a unified-diff patch from the LLM response and applies it with `git apply`.
6. Creates a branch, commits, pushes, and opens a Pull Request via `gh`.

### 2. Claude Code Skill (skill/pprof-analyzer/)
A Claude Code skill that analyzes pprof profiles locally:
1. Reads pprof profile from file.
2. Converts the raw profile to LLM-friendly markdown via `pprof-to-md`.
3. Intelligently selects relevant Go source files (hotspot files + imports).
4. Reads all source code upfront (no agent loop needed).
5. Constructs a comprehensive prompt with all context.
6. Claude analyzes the prompt and generates SUMMARY + PATCH (single turn, no API calls).
7. Extracts patch, validates with `git apply --check`.
8. Writes artifacts to `.ai_output/` for user review.

Key difference: **Skill uses Claude's built-in capabilities; Action uses external LLM API.**

### 3. MCP Server (mcp_tools/)

An MCP (Model Context Protocol) server that exposes all four skills as tools via stdio transport:

1. Wraps the four skill scripts (`skill/`) without modification
2. Registers them as MCP tools: `analyze_pprof_profile`, `integrate_pprof_endpoint`, `generate_load_test`, `run_cpu_profile`
3. Communicates via MCP stdio protocol (works with Claude Desktop, Cline, Cursor, etc.)
4. Each tool call invokes the corresponding skill wrapper function and returns the result
5. Includes per-repo concurrency guard for `run_cpu_profile` (only one concurrent call per repo)

Key difference: **MCP server enables any MCP-compatible agent host to use these tools without modification.**

See [`README.md`](README.md) for feature comparison and [`mcp_tools/README.md`](mcp_tools/README.md) for setup instructions.

## Key files & structure

**Skill implementations** live in `skill/<name>/` directories with underscores (e.g., `pprof_analyzer/`, `load_test_generator/`), each with a `SKILL.md` definition and Python implementation files. The **GitHub Action** code is in `action/scripts/analyzer.py`, with test fixtures in `action/scripts/tests/`. The **MCP Server** code is in `mcp_tools/` with tool wrappers in `mcp_tools/tools/` and tests in `mcp_tools/tests/`. See [README.md](README.md) for the entry point, [action/README.md](action/README.md) for GitHub Action documentation, and [mcp_tools/README.md](mcp_tools/README.md) for MCP Server setup.

## Implementation Flows

### GitHub Action Flow (action/scripts/analyzer.py)

The action runs these steps in sequence:

1. **1a** — `POST /runs` to SERVICE_URL to trigger analyzer execution. Returns `run_id`.
2. **1b** — Poll SERVICE_URL every 15s (timeout: 10 min) until status = "completed". Decode base64 profile, convert to markdown via `pprof-to-md`.
3. **1c** — Verify git checkout is on requested branch/tag.
4. **1d** — Generate list of Go files in repo (for agent loop file access).
5. **1e** — Construct prompt from template + pprof markdown + file list + reference level.
6. **1f** — Call LLM (OpenAI-compatible endpoint) with tool-use enabled. LLM can call `read_file` tool to request specific files/lines.
7. **1g** — Extract SUMMARY section and unified-diff PATCH from LLM response.
8. **1h** — Apply patch with `git apply --whitespace=fix`.
9. **1i** — Write artifacts (`patch.diff`, `llm_result.txt`, `analyzer_result.md`, `raw_profile.pb.gz`) to `./artifacts/`.
10. **1j** — Create branch `pprof/fix-{run_id}`, commit, push, and open PR via `gh`.
11. **1k** — `POST /runs/{run_id}/submit` to SERVICE_URL to flag execution as done.

**If any step 1b–1j fails:** Call step **2a** to `POST /runs/{run_id}/error` to SERVICE_URL.

**When `analyzer_result_file` is set (file mode):** Skip steps 1a, 1b (service polling), 1k, and 2a (no service interaction). Load profile from file instead. Generate local `run_id` (form: `local-<timestamp>`).

### Claude Code Skill Flow (skill/pprof-analyzer/analyzer.py)

The skill runs these steps locally (simplified, single-turn analysis):

1. **Validate inputs** — Check profile file, repo path, reference level (no external API keys needed).
2. **Convert pprof** — Run `pprof-to-md --format detailed` to convert raw profile to markdown (`gather_local_context()`).
3. **Find Go files** — Use `git ls-files` to enumerate all Go files in repo (`gather_local_context()`).
4. **Build prompt** — Combine reference level instructions + pprof markdown + the file list (not file content) in the prompt template (`build_analysis_prompt()`), matching `prompts/prompt_template.txt`'s `{file_list}` contract.
5. **Return for analysis** — Return prompt + context to Claude (Claude Code will handle the analysis call).
6. **Extract SUMMARY & PATCH** — Parse Claude's response for `### SUMMARY` and `### PATCH` sections.
7. **Validate patch** — Run `git apply --check` to dry-run the patch.
8. **Write artifacts** — Save to `.ai_output/`:
    - `summary.md` — Analysis table + explanation
    - `patch.diff` — Unified diff patch
    - `analyzer_result.md` — Pprof analysis
    - `prompt.txt` — Full prompt sent to Claude

`gather_local_context(profile_path, repo_path)` (steps 2-3) and `build_analysis_prompt(analyzer_result, file_list, reference_level)` (step 4) are split so the latter can run without any access to the caller's profile/repo — see `mcp_tools/tools/pprof_analyzer.py::build_pprof_analysis_prompt` and [MCP_SETUP.md](MCP_SETUP.md#team-collaboration-httpsse) for the remote-MCP use of this split.

**Key differences from Action:**
- ✅ No external LLM API calls (uses Claude's built-in capabilities in Claude Code)
- ✅ No custom `read_file` tool-call loop in Python — Claude's own native `Read` tool serves the same purpose against the local repo, given just the file list (same idea as the Action's loop, different mechanism)
- ✅ No PR creation (user applies patch manually)
- ✅ No SERVICE_URL interaction or polling
- ✅ No credentials/API keys needed (uses Claude Code's native integration)
- ✅ Simpler, faster execution (no network delays)

**Implementation notes:**
- Skill takes CLI args: `profile_path`, `repo_path`, `reference_level` (low/med/high)
- No EnvConfig class (no external API configuration needed)
- No network calls or polling logic
- No custom Python agent-loop/tool-use framework — relies on Claude Code's native `Read` tool instead
- Focuses solely on context gathering and prompt construction
- Claude (in Claude Code context) performs the actual analysis

### Supporting Skills: Complete End-to-End Workflow

Three additional Claude Code skills support the main `pprof-analyzer` skill by handling prerequisites:

#### 1. pprof-integrator (`skill/pprof-integrator/`)

**Purpose:** Integrate Go `net/http/pprof` endpoint into a Go service using the guidance from `action/pprof_integration.md`.

**Workflow:**
1. Detect Go framework in use (net/http, gin, echo, fiber, chi, gRPC, controller-runtime, etc.)
2. Read `action/pprof_integration.md` to understand integration patterns
3. Generate code changes for pprof integration
4. User reviews and applies changes manually (default Claude Code behavior)

**Usage:** `/pprof-integrator /path/to/repo`

**Output:** Go code changes (pprofserver.go, main() modifications) with environment variables `PPROF_PORT`, `PPROF_BIND_ADDR`, `ENABLE_PPROF`.

#### 2. load-test-generator (`skill/load-test-generator/`)

**Purpose:** Analyze a Go service and generate a load test script to drive realistic traffic during profiling.

**Workflow:**
1. Analyze Go service code to identify HTTP endpoints and handlers
2. Extract request patterns, payloads, typical API usage
3. Generate load test script (k6, Apache Bench, wrk, or custom Go)
4. User reviews and runs the load test script

**Usage:** `/load-test-generator /path/to/repo [--tool k6|apache-bench|wrk|go]`

**Output:** Load test script file (e.g., `load_test.js` for k6) that generates sustained load for 30-second profiling window.

#### 3. profiler-executor (`skill/profiler-executor/`)

**Purpose:** Execute Go CPU profiling with concurrent load testing to capture realistic performance data.

**Workflow:**
1. Build the service
2. Start the service (must have pprof endpoint integrated)
3. Run profiler and load test in parallel:
   - **Profiler:** `go tool pprof -text localhost:9987/debug/pprof/profile?seconds=30 > cpu.prof`
   - **Load test:** Execute provided load test command
4. Capture `cpu.prof` to `.ai_output/` (ready for `pprof-analyzer`)
5. Stop the service

**Usage:** `/profiler-executor /path/to/repo [--port 8080] [--load-cmd "k6 run load_test.js"] [--duration 30]`

**Output:** `cpu.prof` file in `.ai_output/` (binary pprof profile)

#### Complete Workflow

```
User starts with a raw Go service:

1. /pprof-integrator ./my-service
   ↓ (integrate pprof endpoint)
   ↓ (user commits changes)

2. /load-test-generator ./my-service
   ↓ (generate load_test.js)
   ↓ (user reviews script)

3. /profiler-executor ./my-service --load-cmd "k6 run load_test.js"
   ↓ (capture cpu.prof with realistic load)
   ↓ (profile saved to .ai_output/cpu.prof)

4. /pprof-analyzer ./my-service --profile .ai_output/cpu.prof --reference med
   ↓ (analyze profile, generate performance fixes)
   ↓ (patch + summary in .ai_output/)

5. User reviews patch and creates PR
```

**Prerequisites:**
- Service repository with `go.mod`
- Go 1.11+ installed
- `pprof-to-md` available in PATH (installed via action/package.json)
- Load testing tool for step 2 (k6, wrk, Apache Bench, etc.)

## Synchronization between Action and Skill implementations

The two implementations ([action/scripts/analyzer.py](action/scripts/analyzer.py) and [skill/pprof-analyzer/analyzer.py](skill/pprof-analyzer/analyzer.py)) are **intentionally different** but share some common logic and patterns. This section clarifies when changes in one should be reflected in the other.

### Intentional design differences

**GitHub Action (action/scripts/analyzer.py):**
- Full orchestration: steps 1a–1k, 2a (1140 lines)
- Calls external LLM endpoint with tool-use enabled
- Agent loop: LLM can call `read_file` tool to request files/lines as needed
- Applies patches, creates branches, commits, pushes, opens PRs
- Handles polling, error flagging, step status tracking
- Requires: `litellm`, `requests`, `GitPython`

**Claude Code Skill (skill/pprof-analyzer/analyzer.py):**
- Local context gathering only (~350 lines)
- No external LLM API calls
- Gathers a bare Go file list via `gather_local_context()` (matches the template's `{file_list}` contract — no source content is read or inlined by this file)
- Returns prompt for Claude (in Claude Code context) to analyze; Claude's own `Read` tool pulls specific files on demand, same idea as the Action's `read_file` loop
- No patch application or PR creation
- Requires: `GitPython` only (stdlib for everything else)

### Shared components (keep in sync)

These elements appear in both files and should stay synchronized:

1. **Regex patterns** — For parsing LLM responses:
   - `PATCH_FENCE_PATTERN = r"```(?:diff[a-z-]*)?\n(.*?)```"`
   - `SUMMARY_PATTERN = r"###\s*SUMMARY\s*\n(.*?)(?:###\s*PATCH|\Z)"`
   - Location: `Config.PATCH_FENCE_PATTERN` (action/scripts/analyzer.py), same in `skill/pprof-analyzer/analyzer.py`
   - Reason: Both parse SUMMARY/PATCH structure from LLM responses; must match exactly

2. **Reference levels** — Valid values for profiling depth:
   - `VALID_REFERENCES = {"low", "med", "high"}`
   - Location: `Config.VALID_REFERENCES` (action), `SkillConfig.VALID_REFERENCES` (skill)
   - Reason: Both accept same reference level inputs

3. **Timeout constants** — For reliability:
   - `PPROF_TO_MD_TIMEOUT`: 60 seconds
   - `GIT_OPERATIONS_TIMEOUT`: 120 seconds
   - Reason: Both run same pprof-to-md and git apply operations

4. **Parameter Choices** — Enum-like values for tool parameters:
   - `reference_level` choices: `{"low", "med", "high"}` (used in `pprof_analyzer`)
   - `--tool` choices for load test: `{"k6", "apache-bench", "wrk", "go"}` (used in `load_test_generator`)
   - Location: `SkillConfig.VALID_REFERENCES` (skill CLI), `Literal[...]` type hints (MCP tools)
   - Reason: Skill CLI validates via argparse `choices=`, MCP tools validate via type hints; both must stay synchronized
   - Update strategy: When adding/removing a valid choice, update both skill argparse and MCP tool type hints

5. **GitPython Dependency Pin** — For compatibility:
   - `GitPython~=3.1.59` 
   - Location: `skill/pprof_analyzer/requirements.txt` (skill), `mcp_tools/requirements.txt` (MCP server)
   - Reason: Both invoke `analyzer.py` which imports `GitPython`; MCP server runs it via the same interpreter
   - Update strategy: If skill upgrades `GitPython`, update MCP pin to match

### When to sync changes

**Always sync (change implementations that use it):**
- ✅ Update `PATCH_FENCE_PATTERN` or `SUMMARY_PATTERN` — If LLM response format changes (Action + Skill)
- ✅ Add new reference level to `VALID_REFERENCES` — If profiling depth options expand (Skill CLI + MCP tool type hints)
- ✅ Add load-test tool choice — If new tool is added (Skill CLI + MCP tool type hints)
- ✅ Update `prompt_template.txt` — If prompt structure changes (used by Action + Skill)
- ✅ Update pprof-to-md invocation — If command arguments change (used by all three)

**Note:** `skill/pprof_analyzer/analyzer.py`'s `build_prompt()`/`build_analysis_prompt()` now format the file list into the template's `{file_list}` placeholder (matching `action/scripts/analyzer.py::construct_prompt()`'s `file_list` parameter). Previously it inlined full source into a `source_code` kwarg that the template never defined, which raised `KeyError` on every real invocation — fixed as part of enabling remote MCP use (see [MCP_SETUP.md](MCP_SETUP.md#team-collaboration-httpsse)).

**Action-only changes (no sync needed):**
- ❌ Changes to `read_file_context()`, `_execute_read_file_tool()`, `call_llm()` — Skill doesn't use agent loop
- ❌ Changes to `apply_patch()`, `create_pull_request()` — Skill doesn't apply patches
- ❌ Changes to SERVICE_URL interaction (steps 1a, 1k, 2a) — Skill has no service integration
- ❌ Changes to GitHub Actions step tracking and annotations

**Skill-only changes (no sync needed):**
- ❌ Changes to `gather_local_context()`, `build_analysis_prompt()` — Action gathers/formats its file list differently (`list_repo_files()`)
- ❌ Changes to artifact output location (`.ai_output/` vs `artifacts/`) — Directories differ by design

**MCP-only changes (no sync needed):**
- ❌ Changes to concurrency lock logic in `profiler_executor.py` — MCP-specific requirement for tool safeguarding
- ❌ Changes to tool docstrings — MCP uses them to describe tools to agent hosts (Action/Skill don't need them)

**Prompt template (single source of truth):**
- **Location**: [prompts/prompt_template.txt](prompts/prompt_template.txt) at the repository root — the canonical version used by all implementations.
- **Access across implementations**:
  - **Skill** ([skill/pprof_analyzer/analyzer.py](skill/pprof_analyzer/analyzer.py)): Reads from `../../prompts/prompt_template.txt`
  - **Action** ([action/scripts/analyzer.py](action/scripts/analyzer.py)): Reads from `../../../prompts/prompt_template.txt`
  - **MCP Server** ([mcp_tools/](mcp_tools/)): Reads from `../../prompts/prompt_template.txt`
- **Container/distribution**: The [Dockerfile](Dockerfile) and [skill/build-zip.sh](skill/build-zip.sh) both include `prompts/` so it's available in containerized and standalone distributed environments.
- **Workflow**: When updating the prompt template:
  1. Edit [prompts/prompt_template.txt](prompts/prompt_template.txt) only
  2. Commit the change — all three implementations will automatically use the updated version
  3. Test action, skill, and MCP server with sample profiles

### Regenerating the skill ZIP file

The [skill/pprof-analyzer-skill.zip](skill/pprof-analyzer-skill.zip) is a distributable package for sharing the skill outside the repository.

**When to regenerate:**
- After changes to any `skill/<name>/` implementation files
- After changes to `skill/<name>/SKILL.md` skill definitions
- After changes to shared files like `action/pprof_integration.md`

**How to regenerate:**
```bash
skill/build-zip.sh
```

This script ([skill/build-zip.sh](skill/build-zip.sh)) packages:
- All skill definitions and implementations (`skill/`)
- Integration guide (`action/pprof_integration.md`)
- Distribution documentation (`skill/*.md`)

Into a single distributable ZIP with compression. It runs from the repository root and updates `skill/pprof-analyzer-skill.zip` in place.

## Output convention — generated markdown goes in `.ai_output/`

> **Any markdown file that you (the LLM/agent) are asked to generate — analysis reports, summaries, plans, notes, review documents, etc. — must be written to the `.ai_output/` folder.**

The folder itself is tracked in git (via a `.gitkeep` placeholder), but its **contents are git-ignored** (see `.gitignore`), so generated markdown is never accidentally committed or pushed.

**This rule applies only to generated markdown.** You are still free to create, edit, and update source code files (`.py`, `.yml`, `.txt`, `.go`, etc.) in the normal tracked paths when implementing features, fixing bugs, or refactoring.

### Why?

- Generated markdown is typically intermediate output (analysis, explanations, plans) that should not pollute the repository history.
- Keeping it in a single git-ignored folder makes it easy to find, review locally, and clean up.
- Source code changes, on the other hand, are the actual deliverable and must go through normal review via Pull Requests.

## Development conventions

- **Python**: See `action/scripts/requirements.txt` and `action/scripts/requirements-dev.txt` for runtime and dev dependencies.
- **Tests**: run with `pytest` from the repo root. Test files live in `action/scripts/tests/`.
- **Node tooling**: `pprof-to-md` is pinned in `action/package.json`. Use `npm ci` for reproducible installs; Dependabot tracks `action/package-lock.json`.
- **Code style**: follow existing conventions in the file you are editing. The Python code uses `from __future__ import annotations`, type hints, and docstrings.
- **Commits**: when making a commit, append `Co-Authored-By: Cline SR` to the commit message. If your environment specifies a different attribution (e.g., from harness settings), use that instead.

## Common workflows

### Adding a feature
1. **Start with tests** — Write a test case first (or add to `test_analyzer.py`). Understand the expected behavior.
2. **Implement incrementally** — Reuse existing patterns from `analyzer.py` or utility scripts before writing new code.
3. **Verify end-to-end** — Run the full test suite with `pytest`. If the feature involves LLM output, validate that the response format matches `prompt_template.txt` expectations.
4. **Test with example workflow** — Ensure `examples/workflow.yml` still works correctly.

### Fixing a bug
1. **Root cause first** — Read error messages, logs, and related code before implementing a fix.
2. **Minimal fix** — Target the specific issue; don't refactor surrounding code unless necessary.
3. **Add a regression test** — Write a test that would have caught this bug before committing.
4. **Document the why** — If the fix is non-obvious, explain the root cause in the commit message.

### Refactoring
1. **Preserve behavior** — All tests must pass before and after. If behavior changes, discuss with the owner first.
2. **Run the full test suite** — `pytest` locally and ensure the GitHub Actions test workflow passes.
3. **Update AGENTS.md if patterns change** — If you reorganize code significantly, reflect those changes here.
4. **One refactor per PR** — Don't mix refactors with feature additions or bug fixes.

### Updating the LLM prompt
1. **Locate the prompt** — See `action/scripts/prompts/prompt_template.txt`.
2. **Test with sample profiles** — Run `action/scripts/analyzer.py` locally with a test pprof profile to validate the prompt.
3. **Validate output format** — Ensure the LLM still responds with a valid unified-diff patch that can be parsed by `git apply`.
4. **Run integration tests** — Execute the full action workflow to confirm end-to-end behavior.

### Adding or updating tests
1. **Follow existing structure** — Use fixtures from `action/scripts/tests/conftest.py`.
2. **Name tests clearly** — Test names should describe the scenario, not just the function (e.g., `test_analyzer_handles_malformed_profile` not `test_analyzer_3`).
3. **Run the full suite** — `pytest` from the repo root to ensure no regressions.
4. **Aim for coverage** — Prioritize testing the main flow, error paths, and edge cases.

## Verification checklist

Use this checklist to verify your work before opening a pull request.

### Feature additions
- ✅ Unit tests pass: `pytest`
- ✅ Integration test passes: `pytest` with the full test suite
- ✅ Example workflow still works: `action/examples/workflow.yml` produces expected output
- ✅ LLM output format validated: If using the LLM, confirm response parses correctly
- ✅ No new dependencies outside `action/package.json` or `action/scripts/requirements.txt`

### Bug fixes
- ✅ Root cause documented in commit message
- ✅ Regression test added (test that would have failed before the fix)
- ✅ All tests pass: `pytest`
- ✅ No side effects: Verify the fix doesn't break other features
- ✅ Minimal change: Confirm only the necessary code was modified

### Refactors
- ✅ All tests pass: `pytest` before and after
- ✅ Output behavior unchanged: External behavior is identical
- ✅ No new dependencies introduced
- ✅ Code is more maintainable: Easier to read, fewer duplication points, clearer organization

### Prompt or script updates
- ✅ Tested with sample pprof profile: `python action/scripts/analyzer.py <test_profile>`
- ✅ Output validated: LLM response format is correct, patch applies cleanly
- ✅ End-to-end test passes: Full action workflow runs without errors
- ✅ All existing tests still pass: `pytest`

## API keys & LLM endpoint safety

The analyzer sends repository context and pprof profiles to an LLM endpoint. Handle credentials and data carefully.

### Credentials
- **Environment variables only** — API keys and endpoint URLs are passed via environment variables, never hardcoded in scripts or committed to the repo.
- **No credentials in logs** — When debugging, redact or omit sensitive values from logs and error messages.
- **No credentials in prompts** — Repository files and profiles may contain PII or security-sensitive information. Verify file requests via the `read_file` tool before sending to the LLM.

### Prompt injection & output validation
- **Sanitize prompt inputs** — If a prompt includes user-controlled input (file names, error messages), validate for injection patterns before passing to the LLM.
- **Validate LLM response format** — Always expect the response to be a unified-diff patch. Validate the patch format before passing to `git apply`. Refuse invalid responses.
- **Log redaction** — When logging LLM responses for debugging, redact any sensitive patterns (credentials, internal paths, PII).

### Testing with external LLM
- **Use mock LLM for unit tests** — Tests should not depend on real LLM calls. Use fixtures in `conftest.py` to mock responses.
- **Manual end-to-end testing** — When testing with a real LLM endpoint, use a safe test repository (not production code).
- **Monitor action runs** — After deploying, monitor the GitHub Actions workflow logs for unexpected behavior or LLM failures.

## Decision philosophy

When making changes, prioritize these principles:

### Minimalism
Fix the specific problem; don't rewrite the module. A bug in error handling doesn't justify refactoring the entire analyzer. If you find issues in adjacent code, note them in a comment and move on — the owner can address them separately.

### Pattern reuse
Before writing new code, grep the codebase for existing patterns. If `analyzer.py` already has a function that does what you need, use it. Avoid duplicating logic across files. Small copy-paste is better than a premature abstraction.

### Abstraction threshold
Extract functions or classes only when:
- The pattern repeats 3+ times in the codebase, OR
- The task explicitly requires it (e.g., "refactor to improve maintainability"), OR
- The resulting code is significantly simpler and easier to test in isolation.

Single-use helper functions are rarely worth the indirection.

### Test-driven for new features, trust for refactors
- **New features**: Write tests first to define the expected behavior, then implement.
- **Refactors**: Run the full test suite before and after. If all tests pass, the behavior is preserved — trust the tests.
- **Bug fixes**: Add a regression test that would have caught the bug.

### Prefer explicit over clever
Code clarity matters more than brevity. A straightforward 10-line function is better than a 2-liner with nested comprehensions that requires a mental model to understand. Avoid tricks; use clear variable names and simple control flow.

## Anti-patterns to avoid

### Don't modify `action.yml` lightly
**Principle:** `action.yml` is the public contract with users. Changes to inputs, outputs, or behavior can break downstream workflows.

**What to do instead:**
- Before modifying `action.yml`, discuss the change with the repository owner.
- If you must change inputs/outputs, write migration notes and bump the version.
- Changes to internal action steps are lower-risk but still warrant a comment in the PR.

### Don't vendor or pin dependencies outside `action/package.json` / `action/scripts/requirements.txt`
**Principle:** Dependabot tracks and auto-updates dependencies via `action/package.json` and `action/scripts/requirements*.txt` files. Hardcoding versions in scripts bypasses security updates and creates maintenance debt.

**What to do instead:**
- Always declare dependencies in `action/scripts/requirements.txt` (runtime) or `action/scripts/requirements-dev.txt` (dev).
- Use `npm ci` to install pinned versions from `action/package-lock.json`.
- Let Dependabot auto-update; version bumps should go through PRs for review.

### Don't add error handling for impossible scenarios
**Principle:** Adding try-catch blocks or null checks for situations that can't happen based on framework guarantees makes code harder to read and suggests the code is fragile when it isn't.

**What to do instead:**
- Trust framework guarantees. If a dependency promises it never returns null, don't null-check.
- Only add error handling at system boundaries: user input, file I/O, external API calls.
- Add assertions or comments to document why a scenario is impossible, if it's not obvious.

### Don't commit generated markdown to main repository paths
**Principle:** Generated markdown (analysis, reports, summaries) shouldn't clutter the repository history or main branches.

**What to do instead:**
- Use `.ai_output/` for all generated markdown. The folder is git-ignored but tracked at the root level via `.gitkeep`, so you can find files locally.
- Commit source code changes (`.py`, `.yml`, `.txt`) normally; they are the actual deliverable.

### Don't skip tests as a shortcut
**Principle:** Skipping tests (e.g., `@pytest.mark.skip`) is a code smell. If a test is failing, fix it or remove it; don't silence it.

**What to do instead:**
- If a test is broken, investigate and fix the root cause.
- If a test is obsolete, delete it entirely.
- If a test is slow, optimize it; don't skip it.
- If a test needs setup that doesn't exist, build the setup rather than skipping.

## Autonomy & escalation

Use this guide to decide when to proceed independently vs. ask the owner first.

### Ask the owner first

Stop and request guidance or approval for:

- **Changes to `action.yml`** — Input/output signatures or behavior changes that affect callers.
- **Breaking API changes** — Removing functions, changing parameter types, or altering existing behavior.
- **Dependency changes** — Adding new dependencies, removing old ones, or pinning versions outside `action/scripts/requirements.txt` / `action/package.json`.
- **Security decisions** — If a change involves credentials, auth, or how sensitive data is handled, discuss first.
- **Large refactors** — Significant reorganization of `analyzer.py` or restructuring of directories.
- **When you're uncertain** — If you're unsure whether a change is in scope, ask. Better to clarify upfront than to spend time on a PR that gets rejected.

### Ask for verification if you can't test locally

- **Real LLM endpoint testing** — If the change requires testing with an actual LLM service and you don't have access, mention it in the PR and ask the owner to test.
- **External service integration** — Changes that depend on GitHub Actions environment, `git`, or system binaries that may not be available locally.

### Proceed autonomously for

- **Bug fixes** — Root cause identified, fix is minimal, regression test added, all tests pass.
- **Feature additions within scope** — New functions, new test cases, new utility scripts that don't affect the action's public interface.
- **Test additions and improvements** — New test cases, better fixtures, improved test coverage.
- **Documentation and comments** — Updating README, AGENTS.md, inline code comments, docstrings.
- **Code style cleanup** — Reformatting, renaming private variables for clarity, removing dead code (if confident it's unused).
- **Dependency updates** — Accept Dependabot PRs, test the changes, and merge if tests pass.

---

**Summary:** This document is a guide, not a rigid rulebook. When in doubt, err on the side of asking; the owner will appreciate clarity over assumptions.
