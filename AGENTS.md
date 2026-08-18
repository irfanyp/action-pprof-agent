# AGENTS.md

Guidance for AI agents (e.g. Claude Code, Cline, Copilot) working in this repository.

## Project overview

**pprof-analyzer** is a reusable GitHub Action that:

1. Triggers a pprof analyzer service (or loads a raw pprof profile from a file).
2. Converts the raw profile to LLM-friendly markdown via `pprof-to-md`.
3. Lists repository files and feeds the analyzer result + file list to an LLM (OpenAI-compatible endpoint).
4. The LLM uses a `read_file` tool to request specific files/line ranges as needed (agent loop).
5. Extracts a unified-diff patch from the LLM response and applies it with `git apply`.
6. Creates a branch, commits, pushes, and opens a Pull Request via `gh`.

See [`README.md`](README.md) for the full flow, inputs, and outputs.

## Key files & structure

```
pprof-analyzer/
├── action.yml                       # Composite action definition
├── package.json                     # Pinned npm tooling (pprof-to-md)
├── package-lock.json                # Reproducible npm installs (npm ci)
├── .github/
│   ├── dependabot.yml               # Auto-updates: github-actions, pip, npm
│   └── workflows/test.yml           # CI test workflow
├── scripts/
│   ├── analyzer.py                  # Main orchestration script (steps 1a–1k)
│   ├── requirements.txt             # Python runtime dependencies
│   ├── requirements-dev.txt         # Python dev/test dependencies
│   ├── prompts/
│   │   └── prompt_template.txt       # LLM prompt template
│   └── tests/
│       ├── conftest.py              # Pytest fixtures
│       └── test_analyzer.py          # Unit tests
├── examples/
│   └── workflow.yml                 # Example caller workflow
├── pprof_integration.md             # Guide for integrating net/http/pprof into target Go services
└── README.md
```

## Output convention — generated markdown goes in `.ai_output/`

> **Any markdown file that you (the LLM/agent) are asked to generate — analysis reports, summaries, plans, notes, review documents, etc. — must be written to the `.ai_output/` folder.**

The folder itself is tracked in git (via a `.gitkeep` placeholder), but its **contents are git-ignored** (see `.gitignore`), so generated markdown is never accidentally committed or pushed.

**This rule applies only to generated markdown.** You are still free to create, edit, and update source code files (`.py`, `.yml`, `.txt`, `.go`, etc.) in the normal tracked paths when implementing features, fixing bugs, or refactoring.

### Why?

- Generated markdown is typically intermediate output (analysis, explanations, plans) that should not pollute the repository history.
- Keeping it in a single git-ignored folder makes it easy to find, review locally, and clean up.
- Source code changes, on the other hand, are the actual deliverable and must go through normal review via Pull Requests.

## Development conventions

- **Python**: 3.11+. Runtime deps in `scripts/requirements.txt`, dev/test deps in `scripts/requirements-dev.txt`.
- **Tests**: run with `pytest` from the repo root. Test files live in `scripts/tests/`.
- **Node tooling**: `pprof-to-md` is pinned in `package.json` and installed via `npm ci`. Do not use global installs — Dependabot tracks versions via `package-lock.json`.
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
1. **Locate the prompt** — See `scripts/prompts/prompt_template.txt`.
2. **Test with sample profiles** — Run `analyzer.py` locally with a test pprof profile to validate the prompt.
3. **Validate output format** — Ensure the LLM still responds with a valid unified-diff patch that can be parsed by `git apply`.
4. **Run integration tests** — Execute the full action workflow to confirm end-to-end behavior.

### Adding or updating tests
1. **Follow existing structure** — Use fixtures from `scripts/tests/conftest.py`.
2. **Name tests clearly** — Test names should describe the scenario, not just the function (e.g., `test_analyzer_handles_malformed_profile` not `test_analyzer_3`).
3. **Run the full suite** — `pytest` from the repo root to ensure no regressions.
4. **Aim for coverage** — Prioritize testing the main flow, error paths, and edge cases.

## Verification checklist

Use this checklist to verify your work before opening a pull request.

### Feature additions
- ✅ Unit tests pass: `pytest`
- ✅ Integration test passes: `pytest` with the full test suite
- ✅ Example workflow still works: `examples/workflow.yml` produces expected output
- ✅ LLM output format validated: If using the LLM, confirm response parses correctly
- ✅ No new dependencies outside `package.json` or `requirements.txt`

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
- ✅ Tested with sample pprof profile: `python scripts/analyzer.py <test_profile>`
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

### Don't vendor or pin dependencies outside `package.json` / `requirements.txt`
**Principle:** Dependabot tracks and auto-updates dependencies via `package.json` and `requirements*.txt` files. Hardcoding versions in scripts bypasses security updates and creates maintenance debt.

**What to do instead:**
- Always declare dependencies in `requirements.txt` (runtime) or `requirements-dev.txt` (dev).
- Use `npm ci` to install pinned versions from `package-lock.json`.
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
- **Dependency changes** — Adding new dependencies, removing old ones, or pinning versions outside `requirements.txt` / `package.json`.
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
