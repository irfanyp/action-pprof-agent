"""Shared pytest fixtures for pprof-analyzer tests.

Fixtures are organized into three categories:
  1. Environment setup (valid_env_vars, set_env, tmp_artifacts_dir)
  2. Mock/dependency fixtures (mock_config)
  3. Sample data fixtures (sample_llm_result, sample_prompt_template, etc.)
"""
from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make the scripts/ directory importable so we can `import analyzer`.
# This is needed because pytest discovers tests from scripts/tests/ but
# analyzer.py lives directly in scripts/.
import sys
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


# ============================================================================
# Environment & Configuration Fixtures
# ============================================================================


@pytest.fixture
def valid_env_vars() -> dict[str, str]:
    """A complete set of valid environment variables for EnvConfig."""
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "ghp_testtoken123",
        "TAGS": "main",
        "REFERENCE": "med",
        "AI_KEY": "test-ai-key",
        "AI_ENDPOINT": "https://llm.example.com/v1",
        "AI_MODEL": "gamma4",
        "SERVICE_URL": "https://analyzer.test/api/v1",
        "ACTION_PATH": "/tmp/action",
        "GITHUB_SERVER_URL": "https://github.com",
    }


@pytest.fixture
def set_env(monkeypatch, valid_env_vars):
    """Populate all required env vars for a complete test environment.

    Intended for tests that need EnvConfig to be instantiated.
    Returns the env vars dict for reference if needed.
    """
    for key, val in valid_env_vars.items():
        monkeypatch.setenv(key, val)
    return valid_env_vars


@pytest.fixture
def tmp_artifacts_dir(tmp_path, monkeypatch):
    """Redirect Config.ARTIFACTS_DIR to a temp directory for file I/O tests.

    Isolates artifact writing tests so they don't pollute the real artifacts/
    directory and can use pytest's tmp_path for automatic cleanup.
    """
    import analyzer
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(analyzer.Config, "ARTIFACTS_DIR", artifacts)
    return artifacts


@pytest.fixture
def mock_config():
    """A mock EnvConfig for tests that don't need real env validation.

    Used when testing functions that accept a config object but don't need
    the full environment variable validation logic.
    """
    config = MagicMock()
    config.service_url = "https://analyzer.test/api/v1"
    config.ai_key = "test-ai-key"
    config.ai_endpoint = "https://llm.test/v1"
    config.ai_model = "gamma4"
    config.token = "ghp_testtoken"
    config.base_branch = ""
    config.repository = "owner/repo"
    config.tags = "main"
    config.reference = "med"
    config.action_path = Path("/tmp/action")
    config.analyzer_result_file = None
    return config



# ============================================================================
# Sample Data Fixtures: LLM Results
# ============================================================================


@pytest.fixture
def sample_llm_result() -> str:
    """A realistic, well-formed LLM result with SUMMARY and PATCH sections.

    This is the golden-path example — used by most tests. It includes:
    - A SUMMARY section with a markdown table
    - A PATCH section with a valid unified diff
    - Both sections properly delineated with ### headers
    """
    return """### SUMMARY

| ID | File Path | Function | Self % | Max Reduction | Confidence | Priority |
|---|---|---|---|---|---|---|
| 1 | `main.go` | `buildUsers` | 50.0% | 50.0% (self) | High (n=5000) | 1 |

The `buildUsers` function has an O(n²) uniqueness scan that dominates CPU time.

### PATCH

```diff
--- a/main.go
+++ b/main.go
@@ -10,7 +10,7 @@
 func buildUsers() {
-	for i := 0; i < len(users); i++ {
-		for j := 0; j < i; j++ {
-			if users[i].Name == users[j].Name {
-				users = append(users[:i], users[i+1:]...)
-			}
-		}
-	}
+	seen := make(map[string]struct{})
+	filtered := users[:0]
+	for _, u := range users {
+		if _, ok := seen[u.Name]; !ok {
+			seen[u.Name] = struct{}{}
+			filtered = append(filtered, u)
+		}
+	}
+	users = filtered
 }
```
"""


@pytest.fixture
def sample_llm_result_no_summary() -> str:
    """LLM result with a valid patch but missing the SUMMARY section.

    Tests fallback to the default summary when no SUMMARY header is found.
    """
    return """Here is the fix:

```diff
--- a/main.go
+++ b/main.go
@@ -1,3 +1,3 @@
-old line
+new line
 context
```
"""


@pytest.fixture
def sample_llm_result_no_patch() -> str:
    """LLM result with no diff code fence at all (error case).

    Tests that extraction fails gracefully when the LLM doesn't provide a patch.
    """
    return "I couldn't find any issues to fix. Everything looks good!"


@pytest.fixture
def sample_llm_result_empty_patch() -> str:
    """LLM result with a diff fence that is empty (error case).

    Tests that extraction rejects empty patches.
    """
    return """### SUMMARY

No fix needed.

### PATCH

```diff
```
"""


@pytest.fixture
def sample_llm_result_diff_variant() -> str:
    """LLM result using ```diff-python fence variant instead of just ```diff.

    Tests that the regex pattern handles fence variants correctly.
    """
    return """### SUMMARY

Fixed the issue.

### PATCH

```diff-python
--- a/main.go
+++ b/main.go
@@ -1,3 +1,3 @@
-old line
+new line
 context
```
"""


# ============================================================================
# Sample Data Fixtures: Templates and Prompts
# ============================================================================


@pytest.fixture
def sample_prompt_template() -> str:
    """A minimal prompt template with the expected {reference_level}, {analyzer_result},
    {repomix_result} placeholders.

    Used by construct_prompt() tests to verify template substitution.
    """
    return (
        "Reference: {reference_level}\n"
        "Analyzer:\n{analyzer_result}\n"
        "Repo:\n{repomix_result}\n"
    )
