# AGENTS.md

Guidance for AI agents (e.g. Claude Code, Cline, Copilot) working in this repository.

## Project overview

**pprof-analyzer** is a reusable GitHub Action that:

1. Triggers a pprof analyzer service (or loads a raw pprof profile from a file).
2. Converts the raw profile to LLM-friendly markdown via `pprof-to-md`.
3. Generates an XML snapshot of the repository with `repomix`.
4. Feeds the analyzer result + repo context to an LLM (OpenAI-compatible endpoint).
5. Extracts a unified-diff patch from the LLM response and applies it with `git apply`.
6. Creates a branch, commits, pushes, and opens a Pull Request via `gh`.

See [`README.md`](README.md) for the full flow, inputs, and outputs.

## Key files & structure

```
pprof-analyzer/
├── action.yml                       # Composite action definition
├── package.json                     # Pinned npm tooling (repomix, pprof-to-md)
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

This folder is git-ignored (see `.gitignore`), so generated markdown is never accidentally committed or pushed.

**This rule applies only to generated markdown.** You are still free to create, edit, and update source code files (`.py`, `.yml`, `.txt`, `.go`, etc.) in the normal tracked paths when implementing features, fixing bugs, or refactoring.

### Why?

- Generated markdown is typically intermediate output (analysis, explanations, plans) that should not pollute the repository history.
- Keeping it in a single git-ignored folder makes it easy to find, review locally, and clean up.
- Source code changes, on the other hand, are the actual deliverable and must go through normal review via Pull Requests.

## Development conventions

- **Python**: 3.11+. Runtime deps in `scripts/requirements.txt`, dev/test deps in `scripts/requirements-dev.txt`.
- **Tests**: run with `pytest` from the repo root. Test files live in `scripts/tests/`.
- **Node tooling**: `repomix` and `pprof-to-md` are pinned in `package.json` and installed via `npm ci`. Do not use global installs — Dependabot tracks versions via `package-lock.json`.
- **Code style**: follow existing conventions in the file you are editing. The Python code uses `from __future__ import annotations`, type hints, and docstrings.
- **Commits**: when making a commit, append `Co-Authored-By: Cline SR` to the commit message.
