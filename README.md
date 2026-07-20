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
| **1b** | `GET {SERVICE_URL}/runs/{run_id}` — poll periodically (every 15s, timeout 10 min) until the analyzer result is ready. |
| **1c** | Verify the git checkout is on the requested branch/tag. |
| **1d** | Run `npx repomix --style xml` to generate an LLM-compatible XML of the repository. |
| **1e** | Construct the prompt from the template, analyzer result, repomix XML, and reference level. |
| **1f** | Feed the prompt to the LLM via the OpenAI-compatible endpoint. |
| **1g** | Extract the `git patch` (unified diff) and summary from the LLM result. |
| **1h** | Apply the patch with `git apply`. |
| **1i** | Write artifacts (`patch.diff`, `llm_result.txt`, `repomix_result.xml`, `analyzer_result.json`) to `./artifacts/`; the composite action uploads them as workflow artifacts. |
| **1j** | Create a new branch, commit, push, and open a Pull Request via `gh pr create`. The PR description is derived from the LLM summary. |
| **1k** | `POST {SERVICE_URL}/runs/{run_id}/submit` — flag the execution as done/submitted. |

### Error handling

If any step **1b–1j** fails, the script calls `POST {SERVICE_URL}/runs/{run_id}/error` with the failing step and error message (spec step 2a), then exits with a non-zero code so the workflow fails.

## SERVICE_URL REST contract

`SERVICE_URL` is hardcoded in `scripts/analyzer.py` (default: `https://analyzer.internal/api/v1`). Authentication uses `Authorization: Bearer <ai_key>`.

| Step | Method & Path | Request body | Response |
|---|---|---|---|
| 1a trigger | `POST /runs` | `{"reference":"low","tags":"main","repository":"owner/repo"}` | `{"run_id":"...","status":"pending"}` |
| 1b poll | `GET /runs/{run_id}` | — | `{"run_id":"...","status":"completed","result":{...}}` |
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

## Pre-requisites

The composite action installs everything it needs:

- **repomix** — installed globally via `npm install -g repomix`.
- **Python 3.11** — via `actions/setup-python`; dependencies (`openai`, `GitPython`, `requests`) installed from `scripts/requirements.txt`.
- **git** — available on GitHub runners; the action configures a bot identity for commits.
- **gh CLI** — pre-installed on GitHub-hosted runners, used for PR creation.

## Cleanup

A `post`-style cleanup step (runs with `if: always()`) removes temporary artifacts (`./artifacts`, `./repomix-output`), deletes any leftover local `pprof/fix-*` branches that were not turned into a PR, and scrubs secret environment variables (`AI_KEY`, `GITHUB_TOKEN`) from the job environment.

## Repository structure

```
pprof-analyzer/
├── action.yml                       # Composite action definition
├── scripts/
│   ├── analyzer.py                  # Main orchestration script
│   ├── requirements.txt             # Python dependencies
│   └── prompts/
│       └── prompt_template.txt       # LLM prompt template
├── examples/
│   └── workflow.yml                 # Example caller workflow
└── README.md
```
