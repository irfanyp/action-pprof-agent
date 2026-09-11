# pprof-analyzer GitHub Action

A reusable GitHub Action that runs a pprof analyzer, feeds the result to an LLM, applies the generated git patch, and opens a Pull Request.

## Usage

```yaml
- name: pprof analyzer
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
| `ai_endpoint` | yes | — | Endpoint URL for the LLM. Passed to litellm as `api_base`. |
| `ai_key` | yes | — | API key for the LLM endpoint. Also used as the bearer token for `SERVICE_URL` authentication. |
| `ai_model` | no | `gamma4` | LLM model name. Unprefixed values target the self-hosted OpenAI-compatible endpoint at `ai_endpoint`; prefix with a litellm provider (e.g. `anthropic/...`) to target a native provider — see [below](#ai_model-provider-prefixes). |
| `reference` | yes | — | Analysis depth: `low`, `med`, or `high`. |
| `tags` | yes | — | Repository checkout branch/tag (git ref) to analyze. |
| `analyzer_result_file` | no | `""` | Optional path to a raw pprof profile file for testing (file mode). Skips SERVICE_URL trigger/poll/submit steps. |
| `service_url` | no | `https://analyzer.internal/api/v1` | Base URL of the pprof analyzer service API. |
| `base_branch` | no | `""` | Branch to open the Pull Request against. When unset, targets the repository's default branch. |

## Outputs

| Output | Description |
|---|---|
| `run_id` | The analyzer run identifier returned by the service. |
| `pr_url` | URL of the created Pull Request (empty if none was created). |
| `pr_number` | Number of the created Pull Request (empty if none was created). |

## Flow

1. **1a** — Trigger analyzer execution via SERVICE_URL. Returns a `run_id`.
2. **1b** — Poll SERVICE_URL for the analyzer result. Convert raw pprof to markdown via `pprof-to-md`.
3. **1c** — Verify git checkout is on the requested branch/tag.
4. **1d** — Generate a list of Go files in the repository.
5. **1e** — Construct the prompt from template + analyzer result + file list + reference level.
6. **1f** — Feed the prompt to the LLM via `litellm.completion()` with tool-use enabled.
7. **1g** — Extract the git patch and summary from the LLM result.
8. **1h** — Apply the patch with `git apply`.
9. **1i** — Write artifacts to `./artifacts/`.
10. **1j** — Create a new branch, commit, push, and open a Pull Request via `gh pr create`.
11. **1k** — Flag the execution as submitted via SERVICE_URL.

If any step 1b–1j fails, step 2a flags the execution as error via SERVICE_URL.

## AI_MODEL provider prefixes

The LLM call goes through [litellm](https://github.com/BerriAI/litellm), which routes on a `provider/model` string convention. Unprefixed values are auto-prefixed with `openai/` and target `AI_ENDPOINT`.

| `AI_MODEL` | Routes to |
|---|---|
| `gamma4` (unprefixed) | `AI_ENDPOINT`, OpenAI-compatible (default) |
| `anthropic/claude-3-5-sonnet-20241022` | Anthropic Messages API |
| `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0` | AWS Bedrock |
| `vertex_ai/gemini-1.5-pro` | Google Vertex AI |

`ai_endpoint` and `ai_key` are always required. For providers that don't use them (e.g. Anthropic with its own SDK credentials), set them to any non-empty placeholder.

## Testing / Local Mode

Use the `analyzer_result_file` input to bypass the SERVICE_URL analyzer service and supply a raw pprof profile directly.

See [`pprof_integration.md`](../prompts/pprof_integration.md) for integrating pprof into your Go services.

## Prerequisites

The composite action installs everything it needs: **pprof-to-md**, **Python 3.12**, **git**, and **gh CLI**.

## See Also

[`README.md`](../README.md) (project overview) · [`AGENTS.md`](../AGENTS.md) (developer/architecture guide) · [`skill/README.md`](../skill/README.md) (local skill alternative)
