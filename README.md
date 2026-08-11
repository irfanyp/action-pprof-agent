# pprof-analyzer

A reusable GitHub Action that runs a pprof analyzer, feeds the result (together with repository context) to an LLM, applies the generated git patch, and opens a Pull Request.

## Usage

```yaml
- name: pprof analyzer
  id: pprof
  uses: <this-module-repo>@<this-module-version>
  with:
    token: ${{ secrets.GITHUB_TOKEN }}
    ai_endpoint: ${{ secrets.AI_ENDPOINT }}
    ai_key: ${{ secrets.AI_KEY }}
    ai_model: gamma4
    reference: ${{ inputs.reference }}
    tags: ${{ inputs.tags }}
```

See [`examples/workflow.yml`](examples/workflow.yml) for a complete `workflow_dispatch` workflow.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `token` | yes | — | GitHub token used for checkout and creating the Pull Request. |
| `ai_endpoint` | yes | — | OpenAI-compatible endpoint URL for the LLM. |
| `ai_key` | yes | — | API key for the LLM endpoint. Also used as the bearer token for `SERVICE_URL` authentication. |
| `ai_model` | no | `gamma4` | LLM model name to use. |
| `reference` | yes | — | User reference option: `low`, `med`, or `high`. Controls analysis depth/strictness. Expected to come from a `workflow_dispatch` input. |
| `tags` | yes | — | Repository checkout branch/tag (git ref) to analyze. Expected to come from a `workflow_dispatch` input. |
| `analyzer_result_file` | no | `""` | Optional path to a raw pprof profile file (e.g. `pprof.pprof-dummy-go.samples.cpu.001.pb.gz`). When set, the action skips the `SERVICE_URL` trigger/poll/submit steps (1a, 1b, 1k) and loads the raw pprof profile from this file instead. The profile is then converted to markdown via `pprof-to-md`. Intended for testing. |
| `use_test` | no | `false` | If `true`, runs `go test -cpuprofile=cpu.prof ./...` to generate a CPU profile before analysis. Only applies when both `service_url` and `analyzer_result_file` are at their default values. Useful for local testing without an external analyzer service. |



## Outputs

| Output | Description |
|---|---|
| `run_id` | The analyzer run identifier returned by the service. |
| `pr_url` | URL of the created Pull Request (empty if none was created). |
| `pr_number` | Number of the created Pull Request (empty if none was created). |

## Flow

The action runs a Python orchestration script (`scripts/analyzer.py`) that performs the following steps:

| Step | Description |
|---|---|
| **1a** | `POST {SERVICE_URL}/runs` — authenticate and trigger the analyzer execution. Returns a `run_id`. |
| **1b** | `GET {SERVICE_URL}/runs/{run_id}` — poll periodically (every 15s, timeout 10 min) until the analyzer result is ready. The completed response carries a base64-encoded raw pprof profile (e.g. `*.pb.gz`) in the `result` field. The profile is decoded and converted to LLM-friendly markdown via `pprof-to-md`. |
| **1c** | Verify the git checkout is on the requested branch/tag. |
| **1d** | Run `repomix --style xml` to generate an LLM-compatible XML of the repository. |
| **1e** | Construct the prompt from the template, analyzer result (markdown), repomix XML, and reference level. |
| **1f** | Feed the prompt to the LLM via the OpenAI-compatible endpoint. |
| **1g** | Extract the `git patch` (unified diff) and summary from the LLM result. |
| **1h** | Apply the patch with `git apply`. |
| **1i** | Write artifacts (`patch.diff`, `llm_result.txt`, `repomix_result.xml`, `analyzer_result.md`, `raw_profile.pb.gz`) to `./artifacts/`; the composite action uploads them as workflow artifacts. |
| **1j** | Create a new branch, commit, push, and open a Pull Request via `gh pr create`. The PR description is derived from the LLM summary. |
| **1k** | `POST {SERVICE_URL}/runs/{run_id}/submit` — flag the execution as done/submitted. |


### Error handling

If any step **1b–1j** fails, the script calls `POST {SERVICE_URL}/runs/{run_id}/error` with the failing step and error message (spec step 2a), then exits with a non-zero code so the workflow fails.

## Testing / local mode

### Option 1: File-based raw pprof profile

For testing, you can bypass the `SERVICE_URL` analyzer service and supply a raw pprof profile directly. Set the `analyzer_result_file` input to the path of a raw pprof profile file (e.g. `*.pb.gz`):

```yaml
- name: pprof analyzer
  id: pprof
  uses: <this-module-repo>@<this-module-version>
  with:
    token: ${{ secrets.GITHUB_TOKEN }}
    ai_endpoint: ${{ secrets.AI_ENDPOINT }}
    ai_key: ${{ secrets.AI_KEY }}
    ai_model: gamma4
    reference: ${{ inputs.reference }}
    tags: ${{ inputs.tags }}
    analyzer_result_file: ./test-data/pprof.pprof-dummy-go.samples.cpu.001.pb.gz
```

When `analyzer_result_file` is set:

- Steps **1a** (trigger) and **1b** (poll) are skipped; the raw pprof profile is loaded from the given file.
- The raw profile is converted to LLM-friendly markdown via `pprof-to-md` (same as the `SERVICE_URL` flow).
- Step **1k** (submit) and the **2a** error-flag call are skipped (no run is registered with the service).
- A local `run_id` of the form `local-<timestamp>` is generated so branch naming and outputs still work.
- All remaining steps (1c–1j) run as normal.

### Option 2: Generated CPU profile via `go test`

Alternatively, you can generate a CPU profile on-the-fly by running `go test` with CPU profiling enabled. Set the `use_test` input to `true`:

```yaml
- name: pprof analyzer
  id: pprof
  uses: <this-module-repo>@<this-module-version>
  with:
    token: ${{ secrets.GITHUB_TOKEN }}
    ai_endpoint: ${{ secrets.AI_ENDPOINT }}
    ai_key: ${{ secrets.AI_KEY }}
    ai_model: gamma4
    reference: ${{ inputs.reference }}
    tags: ${{ inputs.tags }}
    use_test: true
```

When `use_test` is `true` (and both `service_url` and `analyzer_result_file` are at their default values):

- The action runs `go test -cpuprofile=cpu.prof ./...` to generate a CPU profile from your test suite.
- The generated `cpu.prof` is automatically used as the `analyzer_result_file`.
- All remaining steps (1b–1j) proceed as with Option 1 (file-based profiling).
- This is useful for local testing without needing an external analyzer service.

When `use_test` is unset or `false` (the default), the normal `SERVICE_URL` flow is used unchanged.



## SERVICE_URL REST contract

`SERVICE_URL` is hardcoded in `scripts/analyzer.py` (default: `https://analyzer.internal/api/v1`). Authentication uses `Authorization: Bearer <ai_key>`.

| Step | Method & Path | Request body | Response |
|---|---|---|---|
| 1a trigger | `POST /runs` | `{"reference":"low","tags":"main","repository":"owner/repo"}` | `{"run_id":"...","status":"pending"}` |
| 1b poll | `GET /runs/{run_id}` | — | `{"run_id":"...","status":"completed","result":"<base64-encoded .pb.gz>"}` |
| 1k submit | `POST /runs/{run_id}/submit` | `{"pr_url":"...","pr_number":123}` | `{"status":"submitted"}` |
| 2a error | `POST /runs/{run_id}/error` | `{"step":"1f","error":"..."}` | `{"status":"error"}` |


Polling statuses: `pending` → `running` → `completed` | `error`.

## GitHub Enterprise Server support

The action auto-detects the GitHub instance it runs on via the built-in
[`github.server_url`](https://docs.github.com/actions/learn-github-actions/contexts#github-context)
context (exposed to the script as `GITHUB_SERVER_URL`). No extra input is required.

- **Commit author email** is derived from the instance host
  (e.g. `pprof-analyzer[bot]@github.example.com` on GHES) instead of being
  hardcoded to `noreply.github.com`.
- **PR creation** uses the `gh` CLI, which resolves the host from the `origin`
  remote configured by `actions/checkout` and authenticates with `GITHUB_TOKEN`,
  so it works against any GitHub instance out of the box.

On public `github.com` the behavior is unchanged.

## Prerequisites for the target service

The Go service being analyzed must expose a **pprof-enabled endpoint** so the analyzer can collect CPU, memory, and goroutine profiles. Concretely:

- The service must import `net/http/pprof` and serve the profiling handlers (e.g. `/debug/pprof/`) on a **dedicated, isolated port** (default `9987`), not on the main application port.
- The pprof server should bind to `127.0.0.1` by default and be reachable from the analyzer service.
- If the service does not yet expose pprof — or exposes it on the main app port — follow the integration guide below to wire it up correctly before running this action.

> 📖 See [`pprof_integration.md`](pprof_integration.md) for a complete, framework-aware integration guide. It can be handed directly to a coding agent (e.g. Claude Code) or followed manually phase-by-phase. It covers:
> - **Framework detection** — auto-detects net/http, gorilla/mux, chi, httprouter, echo, gin, fiber, httprequest, go-restful.
> - **Fresh install** — adds an isolated `net/http/pprof` server on port `9987` (configurable via `PPROF_PORT`).
> - **Port relocation** — moves an already-isolated pprof server to the priority port with a minimal diff.
> - **Security fix** — removes pprof exposure from the main app router/port and re-isolates it.
> - **Validation checklist** and a **ready-to-paste agent prompt**.

## Pre-requisites

The composite action installs everything it needs:

- **repomix** — pinned in `package.json` and installed reproducibly via `npm ci` from `package-lock.json`. Versions are kept up to date automatically by Dependabot (npm ecosystem).
- **pprof-to-md** — pinned in `package.json` and installed reproducibly via `npm ci` from `package-lock.json`. Converts raw pprof profiles (`.pb.gz`) to LLM-friendly markdown. Versions are kept up to date automatically by Dependabot (npm ecosystem).
- **Python 3.11** — via `actions/setup-python`; dependencies (`openai`, `GitPython`, `requests`) installed from `scripts/requirements.txt`.
- **git** — available on GitHub runners; the action configures a bot identity for commits.
- **gh CLI** — pre-installed on GitHub-hosted runners, used for PR creation.


## Cleanup

A `post`-style cleanup step (runs with `if: always()`) removes temporary artifacts (`./artifacts`, `./repomix-output`), deletes any leftover local `pprof/fix-*` branches that were not turned into a PR, and scrubs secret environment variables (`AI_KEY`, `GITHUB_TOKEN`) from the job environment.

## Repository structure

```
pprof-analyzer/
├── action.yml                       # Composite action definition
├── package.json                     # Pinned npm tooling (repomix, pprof-to-md)
├── package-lock.json                # Reproducible npm installs (npm ci)
├── .github/
│   └── dependabot.yml               # Auto-updates: github-actions, pip, npm
├── scripts/
│   ├── analyzer.py                  # Main orchestration script
│   ├── requirements.txt             # Python dependencies
│   └── prompts/
│       └── prompt_template.txt       # LLM prompt template
├── examples/
│   └── workflow.yml                 # Example caller workflow
├── pprof_integration.md             # Guide for integrating net/http/pprof into target Go services
└── README.md
```
