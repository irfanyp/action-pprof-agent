"""Shared pytest fixtures for pprof-analyzer tests."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make the scripts/ directory importable so we can `import analyzer`.
# This is needed because pytest discovers tests from scripts/tests/ but
# analyzer.py lives directly in scripts/.
import sys
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


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
    """Set all valid env vars via monkeypatch."""
    for key, val in valid_env_vars.items():
        monkeypatch.setenv(key, val)
    return valid_env_vars


@pytest.fixture
def tmp_artifacts_dir(tmp_path, monkeypatch):
    """Redirect Config.ARTIFACTS_DIR to a temp directory."""
    import analyzer
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(analyzer.Config, "ARTIFACTS_DIR", artifacts)
    return artifacts


@pytest.fixture
def sample_llm_result() -> str:
    """A realistic LLM result with SUMMARY and PATCH sections."""
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
    """An LLM result with a patch but no SUMMARY section."""
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
    """An LLM result with no diff code fence at all."""
    return "I couldn't find any issues to fix. Everything looks good!"


@pytest.fixture
def sample_llm_result_empty_patch() -> str:
    """An LLM result with an empty diff fence."""
    return """### SUMMARY

No fix needed.

### PATCH

```diff
```
"""


@pytest.fixture
def sample_llm_result_diff_variant() -> str:
    """An LLM result using ```diff-python variant fence."""
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


@pytest.fixture
def sample_prompt_template() -> str:
    """A minimal prompt template with the expected placeholders."""
    return (
        "Reference: {reference_level}\n"
        "Analyzer:\n{analyzer_result}\n"
        "Repo:\n{repomix_result}\n"
    )


@pytest.fixture
def mock_config():
    """A mock EnvConfig for tests that don't need real env validation."""
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
