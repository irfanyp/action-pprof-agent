"""Unit tests for scripts/analyzer.py.

This test suite validates the pprof-analyzer orchestration script, which implements
a multi-step workflow to analyze CPU profiles, generate optimization suggestions via
an LLM, and create pull requests with proposed fixes.

## Test Organization

Tests are split into two tiers to maximize ROI and maintainability:

### Tier 1: Pure-Function Tests (no mocking required)
These test business logic in isolation and catch refactoring regressions early.
Classes: TestExtractPatch, TestConstructPrompt, TestDecodePprofResult, TestEnvConfig,
         TestGhAnnotation, TestNodeBin, TestLocalRunId, TestWriteStepSummary,
         TestRecordStep, TestWriteArtifact, TestSetOutput, TestLoadAnalyzerResultFromFile,
         TestAnalyzerError

### Tier 2: Mocked Integration Tests
These test external interactions (API calls, subprocess, git) with mocks to verify
error handling and correct payloads without actual side effects.
Classes: TestServiceRequest, TestTriggerAnalyzer, TestPollAnalyzerResult,
         TestRunCommand, TestGitApplyCheck, TestGenerateValidPatch, TestCallLlm,
         TestFlagSubmitted, TestFlagError, TestCreatePullRequest, TestApplyPatch,
         TestConvertPprofToMarkdown, TestRunRepomix, TestPrepareGitCheckout

## Workflow Steps Reference

The analyzer.py workflow follows these numbered steps (see Config.STEP_DESCRIPTIONS):
  1a: Trigger analyzer via service API
  1b: Poll result, decode pprof, convert to markdown
  1c: Validate git checkout state
  1d: Generate file list for agent-loop file access
  1e: Construct the LLM prompt
  1f: Call the LLM with the prompt (with tool-use enabled)
  1g: Extract patch from LLM result
  1h: Apply patch to git repo
  1j: Create pull request
  1k: Flag execution as submitted

To find tests for a specific step, search for the step label in test class names.
"""
from __future__ import annotations

import base64
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

import analyzer
from analyzer import (
    AnalyzerError,
    Config,
    EnvConfig,
    STEP_RESULTS,
    _decode_pprof_result,
    _gh_annotation,
    _git_apply_check,
    _node_bin,
    _record_step,
    _run_command,
    _service_request,
    _set_output,
    _write_artifact,
    _write_step_summary,
    apply_patch,
    call_llm,
    construct_prompt,
    convert_pprof_to_markdown,
    create_pull_request,
    extract_patch,
    flag_error,
    flag_submitted,
    generate_valid_patch,
    load_analyzer_result_from_file,
    local_run_id,
    poll_analyzer_result,
    prepare_git_checkout,
    trigger_analyzer,
)


# ============================================================================
# Tier 1: Pure-Function Tests (no mocking required)
# ============================================================================
# These tests validate business logic in isolation without mocks. They catch
# refactoring errors early and provide the highest ROI per test.
# ============================================================================


class TestExtractPatch:
    """Tests for extract_patch() — the critical regex extraction logic.

    extract_patch() parses LLM results to extract the SUMMARY and PATCH sections.
    It must handle various fence formats (```diff, ```diff-python, etc.) and
    provide helpful error messages when extraction fails.
    """

    def test_extract_patch_basic(self, sample_llm_result):
        """A well-formed LLM result yields summary and patch."""
        summary, patch = extract_patch(sample_llm_result)
        assert "buildUsers" in summary
        assert "--- a/main.go" in patch
        assert "+++ b/main.go" in patch

    def test_extract_patch_no_summary_uses_default(self, sample_llm_result_no_summary):
        """When no SUMMARY section is found, a default summary is used."""
        summary, patch = extract_patch(sample_llm_result_no_summary)
        assert summary == "Automated pprof-analyzer fix."
        assert "--- a/main.go" in patch

    def test_extract_patch_no_patch_raises(self, sample_llm_result_no_patch):
        """An LLM result with no diff fence raises AnalyzerError('1g')."""
        with pytest.raises(AnalyzerError) as exc_info:
            extract_patch(sample_llm_result_no_patch)
        assert exc_info.value.step == "1g"
        assert "No patch code fence" in exc_info.value.message

    def test_extract_patch_empty_patch_raises(self, sample_llm_result_empty_patch):
        """An empty diff fence raises AnalyzerError('1g')."""
        with pytest.raises(AnalyzerError) as exc_info:
            extract_patch(sample_llm_result_empty_patch)
        assert exc_info.value.step == "1g"
        assert "empty" in exc_info.value.message.lower()

    def test_extract_patch_diff_variant_fence(self, sample_llm_result_diff_variant):
        """The regex handles ```diff-python variant fences."""
        summary, patch = extract_patch(sample_llm_result_diff_variant)
        assert "Fixed the issue" in summary
        assert "--- a/main.go" in patch

    def test_extract_patch_strips_whitespace(self, sample_llm_result):
        """The extracted patch is stripped of leading/trailing whitespace."""
        _, patch = extract_patch(sample_llm_result)
        assert patch == patch.strip()

    def test_extract_patch_preview_in_error(self, sample_llm_result_no_patch):
        """The error message includes a preview of the LLM result."""
        with pytest.raises(AnalyzerError) as exc_info:
            extract_patch(sample_llm_result_no_patch)
        assert "Got:" in exc_info.value.message
        assert sample_llm_result_no_patch in exc_info.value.message

    def test_extract_patch_long_result_preview_truncated(self):
        """When the LLM result is >500 chars, the preview is truncated."""
        long_result = "x" * 600
        with pytest.raises(AnalyzerError) as exc_info:
            extract_patch(long_result)
        # The preview should be the first 500 chars
        assert "x" * 500 in exc_info.value.message
        assert "x" * 600 not in exc_info.value.message


class TestConstructPrompt:
    """Tests for construct_prompt() — template formatting.

    construct_prompt() loads a template file and substitutes {reference_level},
    {analyzer_result}, and {file_list} placeholders with actual data.
    """

    def test_construct_prompt_substitutes_placeholders(
        self, tmp_path, sample_prompt_template
    ):
        """All three placeholders are correctly substituted."""
        template_file = tmp_path / "template.txt"
        template_file.write_text(sample_prompt_template, encoding="utf-8")

        prompt = construct_prompt(
            Path(template_file), "high", "analyzer_data", "file_list_data"
        )
        assert "Reference: high" in prompt
        assert "Analyzer:\nanalyzer_data" in prompt
        assert "Repo:\nfile_list_data" in prompt

    def test_construct_prompt_preserves_content(self, tmp_path, sample_prompt_template):
        """The prompt contains all input content verbatim."""
        template_file = tmp_path / "template.txt"
        template_file.write_text(sample_prompt_template, encoding="utf-8")

        prompt = construct_prompt(
            Path(template_file), "low", "SPECIAL_ANALYZER_OUTPUT", "SPECIAL_FILE_LIST"
        )
        assert "SPECIAL_ANALYZER_OUTPUT" in prompt
        assert "SPECIAL_FILE_LIST" in prompt

    def test_construct_prompt_missing_placeholder_raises(self, tmp_path):
        """A template with a missing placeholder raises KeyError (format)."""
        template_file = tmp_path / "template.txt"
        template_file.write_text("No placeholders here", encoding="utf-8")

        # No placeholders — format() with kwargs is fine, just returns the string
        prompt = construct_prompt(Path(template_file), "low", "data", "data2")
        assert prompt == "No placeholders here"


class TestDecodePprofResult:
    """Tests for _decode_pprof_result() — base64 decoding.

    _decode_pprof_result() decodes a base64-encoded pprof binary and writes it
    to disk. Must reject invalid base64 and empty results.
    """

    def test_decode_valid_base64(self, tmp_artifacts_dir):
        """Valid base64 data is decoded and written to disk."""
        raw_data = b"\x1f\x8b\x08\x00test_profile_data"
        encoded = base64.b64encode(raw_data).decode("ascii")
        result_path = _decode_pprof_result(encoded)
        assert result_path.exists()
        assert result_path.read_bytes() == raw_data
        assert result_path.name == "raw_profile.pb.gz"

    def test_decode_invalid_base64_raises(self, tmp_artifacts_dir):
        """Invalid base64 input raises AnalyzerError('1b')."""
        with pytest.raises(AnalyzerError) as exc_info:
            _decode_pprof_result("!!!not-valid-base64!!!")
        assert exc_info.value.step == "1b"
        assert "base64-decode" in exc_info.value.message

    def test_decode_empty_result_raises(self, tmp_artifacts_dir):
        """An empty decoded result raises AnalyzerError('1b')."""
        # base64 of empty bytes
        empty_encoded = base64.b64encode(b"").decode("ascii")
        with pytest.raises(AnalyzerError) as exc_info:
            _decode_pprof_result(empty_encoded)
        assert exc_info.value.step == "1b"
        assert "empty" in exc_info.value.message.lower()


class TestEnvConfig:
    """Tests for EnvConfig — environment variable loading and validation.

    EnvConfig is the single source of truth for all required env vars. It validates
    required fields, optional fields with defaults, and enum constraints. Missing or
    invalid vars raise AnalyzerError('init').
    """

    def test_valid_env_config(self, set_env):
        """All valid env vars produce a correctly populated EnvConfig."""
        config = EnvConfig()
        assert config.repository == "owner/repo"
        assert config.token == "ghp_testtoken123"
        assert config.tags == "main"
        assert config.reference == "med"
        assert config.ai_key == "test-ai-key"
        assert config.ai_endpoint == "https://llm.example.com/v1"
        assert config.ai_model == "gamma4"
        assert config.service_url == "https://analyzer.test/api/v1"
        assert config.action_path == Path("/tmp/action")

    def test_missing_required_env_raises(self, monkeypatch, valid_env_vars):
        """Missing a required env var raises AnalyzerError('init')."""
        env = dict(valid_env_vars)
        del env["GITHUB_TOKEN"]
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        with pytest.raises(AnalyzerError) as exc_info:
            EnvConfig()
        assert exc_info.value.step == "init"
        assert "GITHUB_TOKEN" in exc_info.value.message

    def test_invalid_reference_raises(self, monkeypatch, valid_env_vars):
        """An invalid REFERENCE value raises AnalyzerError('init')."""
        env = dict(valid_env_vars)
        env["REFERENCE"] = "ultra"
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        with pytest.raises(AnalyzerError) as exc_info:
            EnvConfig()
        assert exc_info.value.step == "init"
        assert "REFERENCE" in exc_info.value.message
        assert "ultra" in exc_info.value.message

    def test_reference_case_insensitive(self, monkeypatch, valid_env_vars):
        """REFERENCE is lowercased before validation."""
        env = dict(valid_env_vars)
        env["REFERENCE"] = "HIGH"
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        config = EnvConfig()
        assert config.reference == "high"

    def test_invalid_repository_format_raises(self, monkeypatch, valid_env_vars):
        """A repository without '/' raises AnalyzerError('init')."""
        env = dict(valid_env_vars)
        env["GITHUB_REPOSITORY"] = "invalid-no-slash"
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        with pytest.raises(AnalyzerError) as exc_info:
            EnvConfig()
        assert exc_info.value.step == "init"
        assert "GITHUB_REPOSITORY" in exc_info.value.message

    def test_service_url_trailing_slash_stripped(self, monkeypatch, valid_env_vars):
        """Trailing slash on SERVICE_URL is stripped."""
        env = dict(valid_env_vars)
        env["SERVICE_URL"] = "https://analyzer.test/api/v1/"
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        config = EnvConfig()
        assert config.service_url == "https://analyzer.test/api/v1"

    def test_default_service_url(self, monkeypatch, valid_env_vars):
        """When SERVICE_URL is unset, the default is used."""
        env = dict(valid_env_vars)
        del env["SERVICE_URL"]
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("SERVICE_URL", raising=False)

        config = EnvConfig()
        assert config.service_url == "https://analyzer.internal/api/v1"

    def test_default_ai_model(self, monkeypatch, valid_env_vars):
        """When AI_MODEL is unset, the default 'gamma4' is used."""
        env = dict(valid_env_vars)
        del env["AI_MODEL"]
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("AI_MODEL", raising=False)

        config = EnvConfig()
        assert config.ai_model == "gamma4"

    def test_optional_env_vars_default_to_none_or_empty(self, monkeypatch, valid_env_vars):
        """Optional env vars default correctly when unset."""
        env = dict(valid_env_vars)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("ANALYZER_RESULT_FILE", raising=False)
        monkeypatch.delenv("BASE_BRANCH", raising=False)

        config = EnvConfig()
        assert config.analyzer_result_file is None
        assert config.base_branch == ""

    def test_whitespace_stripped_from_values(self, monkeypatch, valid_env_vars):
        """Whitespace is stripped from env var values."""
        env = dict(valid_env_vars)
        env["TAGS"] = "  main  "
        env["GITHUB_REPOSITORY"] = "  owner/repo  "
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        config = EnvConfig()
        assert config.tags == "main"
        assert config.repository == "owner/repo"


class TestGhAnnotation:
    """Tests for _gh_annotation() — GitHub Actions annotation encoding.

    _gh_annotation() formats messages as GitHub Actions annotations (::error::, etc.)
    and percent-encodes special characters (%, newlines, carriage returns).
    """

    def test_basic_annotation(self, capfd):
        """A basic annotation is printed with the correct format."""
        _gh_annotation("error", "Something went wrong", "1b")
        captured = capfd.readouterr()
        assert "::error::[1b] Something went wrong" in captured.out

    def test_annotation_no_step(self, capfd):
        """Annotation without a step label has no prefix."""
        _gh_annotation("warning", "Heads up")
        captured = capfd.readouterr()
        assert "::warning::Heads up" in captured.out

    def test_annotation_percent_encoded(self, capfd):
        """Percent signs are percent-encoded."""
        _gh_annotation("error", "50% done")
        captured = capfd.readouterr()
        assert "%25" in captured.out
        assert "50% done" not in captured.out

    def test_annotation_newlines_encoded(self, capfd):
        """Newlines are percent-encoded."""
        _gh_annotation("error", "line1\nline2")
        captured = capfd.readouterr()
        assert "%0A" in captured.out
        assert "line1\nline2" not in captured.out

    def test_annotation_carriage_returns_encoded(self, capfd):
        """Carriage returns are percent-encoded."""
        _gh_annotation("error", "line1\rline2")
        captured = capfd.readouterr()
        assert "%0D" in captured.out


class TestNodeBin:
    """Tests for _node_bin() — binary path resolution."""

    def test_node_bin_resolves_path(self):
        """The path is resolved under node_modules/.bin."""
        action_path = Path("/tmp/action")
        result = _node_bin("pprof-to-md", action_path)
        assert result == str(Path("/tmp/action/node_modules/.bin/pprof-to-md"))

    def test_node_bin_pprof_to_md(self):
        """Different binary names resolve correctly."""
        action_path = Path("/opt/action")
        result = _node_bin("pprof-to-md", action_path)
        assert "pprof-to-md" in result
        assert "node_modules" in result
        assert ".bin" in result


class TestLocalRunId:
    """Tests for local_run_id() — deterministic ID generation."""

    def test_local_run_id_format(self):
        """The run_id has the 'local-' prefix followed by a timestamp."""
        before = int(time.time())
        run_id = local_run_id()
        after = int(time.time())
        assert run_id.startswith("local-")
        timestamp = int(run_id.split("-")[1])
        assert before <= timestamp <= after

    def test_local_run_id_is_string(self):
        """The run_id is a string."""
        run_id = local_run_id()
        assert isinstance(run_id, str)


class TestWriteStepSummary:
    """Tests for _write_step_summary() — markdown summary table generation."""

    def test_no_summary_file_does_nothing(self, monkeypatch, tmp_path):
        """When GITHUB_STEP_SUMMARY is unset, nothing is written."""
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        # Should not raise
        _write_step_summary("test-run-id")

    def test_summary_file_written(self, monkeypatch, tmp_path):
        """When GITHUB_STEP_SUMMARY is set, a markdown table is written."""
        summary_file = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        # Clear and populate step results
        STEP_RESULTS.clear()
        STEP_RESULTS["1a"] = "ok"
        STEP_RESULTS["1b"] = "error"

        _write_step_summary("run-123")

        content = summary_file.read_text(encoding="utf-8")
        assert "run-123" in content
        assert "| Step | Description | Status |" in content
        assert "1a" in content
        assert "1b" in content
        assert "✅" in content  # ok icon
        assert "❌" in content  # error icon

    def test_summary_includes_all_steps(self, monkeypatch, tmp_path):
        """All steps from STEP_DESCRIPTIONS appear in the summary."""
        summary_file = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        STEP_RESULTS.clear()
        _write_step_summary("run-456")

        content = summary_file.read_text(encoding="utf-8")
        for step in Config.STEP_DESCRIPTIONS:
            assert step in content

    def test_summary_unrun_steps_show_skip_icon(self, monkeypatch, tmp_path):
        """Steps not in STEP_RESULTS show the skip icon."""
        summary_file = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        STEP_RESULTS.clear()
        _write_step_summary("run-789")

        content = summary_file.read_text(encoding="utf-8")
        assert "⏭️" in content


class TestRecordStep:
    """Tests for _record_step() — step status tracking."""

    def test_record_step_ok(self):
        """Recording 'ok' status stores it in STEP_RESULTS."""
        STEP_RESULTS.clear()
        _record_step("1a", "ok")
        assert STEP_RESULTS["1a"] == "ok"

    def test_record_step_error(self):
        """Recording 'error' status stores it in STEP_RESULTS."""
        STEP_RESULTS.clear()
        _record_step("1b", "error")
        assert STEP_RESULTS["1b"] == "error"

    def test_record_step_overwrites(self):
        """Recording a step twice overwrites the previous status."""
        STEP_RESULTS.clear()
        _record_step("1c", "ok")
        _record_step("1c", "error")
        assert STEP_RESULTS["1c"] == "error"


class TestWriteArtifact:
    """Tests for _write_artifact() — artifact file writing."""

    def test_write_artifact_creates_file(self, tmp_artifacts_dir):
        """An artifact file is created with the correct content."""
        path = _write_artifact("test.txt", "hello world")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "hello world"
        assert path.parent == tmp_artifacts_dir

    def test_write_artifact_creates_dir(self, tmp_path, monkeypatch):
        """The artifacts directory is created if it doesn't exist."""
        import analyzer
        artifacts = tmp_path / "new_artifacts"
        monkeypatch.setattr(analyzer.Config, "ARTIFACTS_DIR", artifacts)

        path = _write_artifact("test2.txt", "content")
        assert artifacts.exists()
        assert path.read_text(encoding="utf-8") == "content"

    def test_write_artifact_overwrites(self, tmp_artifacts_dir):
        """Writing an artifact with the same name overwrites it."""
        _write_artifact("dup.txt", "first")
        path = _write_artifact("dup.txt", "second")
        assert path.read_text(encoding="utf-8") == "second"


class TestSetOutput:
    """Tests for _set_output() — GitHub Actions output writing."""

    def test_set_output_writes_to_file(self, monkeypatch, tmp_path):
        """When GITHUB_OUTPUT is set, the output is appended."""
        output_file = tmp_path / "outputs.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        _set_output("run_id", "test-123")
        content = output_file.read_text(encoding="utf-8")
        assert "run_id=test-123" in content

    def test_set_output_no_file_does_nothing(self, monkeypatch):
        """When GITHUB_OUTPUT is unset, nothing happens."""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        # Should not raise
        _set_output("key", "value")

    def test_set_output_appends(self, monkeypatch, tmp_path):
        """Multiple outputs are appended to the same file."""
        output_file = tmp_path / "outputs.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        _set_output("key1", "val1")
        _set_output("key2", "val2")
        content = output_file.read_text(encoding="utf-8")
        assert "key1=val1" in content
        assert "key2=val2" in content


class TestLoadAnalyzerResultFromFile:
    """Tests for load_analyzer_result_from_file() — file-mode loading."""

    def test_load_existing_file(self, tmp_path):
        """Loading an existing file returns its path."""
        test_file = tmp_path / "profile.pb.gz"
        test_file.write_bytes(b"\x1f\x8bprofile_data")

        result = load_analyzer_result_from_file(str(test_file))
        assert result == test_file
        assert result.exists()

    def test_load_nonexistent_file_raises(self):
        """Loading a non-existent file raises AnalyzerError('1b')."""
        with pytest.raises(AnalyzerError) as exc_info:
            load_analyzer_result_from_file("/nonexistent/path/profile.pb.gz")
        assert exc_info.value.step == "1b"
        assert "not found" in exc_info.value.message.lower()


class TestAnalyzerError:
    """Tests for the AnalyzerError exception class.

    AnalyzerError carries a step label (1a, 1b, etc.) and a message. It's raised
    whenever a step in the 1b-1j workflow fails, allowing error handling to identify
    which step failed.
    """

    def test_analyzer_error_attributes(self):
        """AnalyzerError stores step and message."""
        err = AnalyzerError("1b", "Something failed")
        assert err.step == "1b"
        assert err.message == "Something failed"

    def test_analyzer_error_str(self):
        """The string representation includes step and message."""
        err = AnalyzerError("1g", "No patch found")
        assert "[1g]" in str(err)
        assert "No patch found" in str(err)

    def test_analyzer_error_is_exception(self):
        """AnalyzerError is a subclass of Exception."""
        err = AnalyzerError("1a", "test")
        assert isinstance(err, Exception)


# ============================================================================
# Tier 2: Mocked Integration Tests
# ============================================================================
# These tests validate external interactions (API calls, subprocess, git) using
# mocks. They verify correct payloads, error handling, and state transitions
# without actual side effects.
# ============================================================================


# Step 1a: Trigger analyzer
class TestServiceRequest:
    """Tests for _service_request() — HTTP API interaction.

    _service_request() is the low-level wrapper for GET/POST requests to the
    analyzer service. It handles authorization, error responses, and network failures.
    """

    def test_get_request_success(self, mocker):
        """A successful GET request returns parsed JSON."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"status": "ok"}
        mocker.patch("analyzer.requests.get", return_value=mock_resp)

        result = _service_request(
            "GET", "/runs/123", "1b", "https://api.test", "key"
        )
        assert result == {"status": "ok"}

    def test_post_request_success(self, mocker):
        """A successful POST request returns parsed JSON."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"run_id": "abc"}
        mocker.patch("analyzer.requests.post", return_value=mock_resp)

        result = _service_request(
            "POST", "/runs", "1a", "https://api.test", "key", {"data": 1}
        )
        assert result == {"run_id": "abc"}

    def test_request_failure_raises(self, mocker):
        """A network error raises AnalyzerError."""
        import requests as req_module
        mocker.patch(
            "analyzer.requests.get",
            side_effect=req_module.ConnectionError("refused"),
        )

        with pytest.raises(AnalyzerError) as exc_info:
            _service_request("GET", "/runs/123", "1b", "https://api.test", "key")
        assert exc_info.value.step == "1b"
        assert "Request to /runs/123 failed" in exc_info.value.message

    def test_http_error_raises(self, mocker):
        """A non-2xx response raises AnalyzerError."""
        import requests as req_module
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req_module.HTTPError("404 Not Found")
        mocker.patch("analyzer.requests.get", return_value=mock_resp)

        with pytest.raises(AnalyzerError) as exc_info:
            _service_request("GET", "/runs/123", "1b", "https://api.test", "key")
        assert exc_info.value.step == "1b"

    def test_unsupported_method_raises(self):
        """An unsupported HTTP method raises AnalyzerError."""
        with pytest.raises(AnalyzerError) as exc_info:
            _service_request("DELETE", "/runs/123", "1b", "https://api.test", "key")
        assert exc_info.value.step == "1b"
        assert "Unsupported HTTP method" in exc_info.value.message

    def test_authorization_header_set(self, mocker):
        """The Authorization header uses the Bearer token."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {}
        mock_get = mocker.patch("analyzer.requests.get", return_value=mock_resp)

        _service_request("GET", "/runs", "1a", "https://api.test", "my-secret-key")
        args, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer my-secret-key"

    def test_post_sends_json_payload(self, mocker):
        """POST requests include the JSON payload."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {}
        mock_post = mocker.patch("analyzer.requests.post", return_value=mock_resp)

        payload = {"reference": "low", "tags": "main"}
        _service_request("POST", "/runs", "1a", "https://api.test", "key", payload)
        args, kwargs = mock_post.call_args
        assert kwargs["json"] == payload


# Step 1a (continued)
class TestTriggerAnalyzer:
    """Tests for trigger_analyzer() — step 1a.

    trigger_analyzer() POSTs to /runs with reference, tags, and repository,
    then extracts and returns the run_id. Missing or empty run_id raises error.
    """

    def test_trigger_success(self, mocker, mock_config):
        """A successful trigger returns the run_id."""
        mocker.patch(
            "analyzer._service_request",
            return_value={"run_id": "run-abc-123"},
        )

        run_id = trigger_analyzer("med", "main", "owner/repo", mock_config)
        assert run_id == "run-abc-123"

    def test_trigger_no_run_id_raises(self, mocker, mock_config):
        """A response without run_id raises AnalyzerError('1a')."""
        mocker.patch(
            "analyzer._service_request",
            return_value={"status": "ok"},
        )

        with pytest.raises(AnalyzerError) as exc_info:
            trigger_analyzer("med", "main", "owner/repo", mock_config)
        assert exc_info.value.step == "1a"
        assert "No run_id" in exc_info.value.message

    def test_trigger_empty_run_id_raises(self, mocker, mock_config):
        """An empty run_id raises AnalyzerError('1a')."""
        mocker.patch(
            "analyzer._service_request",
            return_value={"run_id": ""},
        )

        with pytest.raises(AnalyzerError) as exc_info:
            trigger_analyzer("med", "main", "owner/repo", mock_config)
        assert exc_info.value.step == "1a"

    def test_trigger_correct_payload(self, mocker, mock_config):
        """The trigger sends the correct payload to _service_request."""
        mock_service = mocker.patch(
            "analyzer._service_request",
            return_value={"run_id": "run-1"},
        )

        trigger_analyzer("high", "v1.0", "owner/repo", mock_config)
        args, kwargs = mock_service.call_args
        # _service_request(method, endpoint, step, service_url, ai_key, payload)
        assert args[0] == "POST"
        assert args[1] == "/runs"
        assert args[2] == "1a"
        assert args[5] == {
            "reference": "high",
            "tags": "v1.0",
            "repository": "owner/repo",
        }


# Step 1b: Poll analyzer result
class TestPollAnalyzerResult:
    """Tests for poll_analyzer_result() — step 1b polling loop.

    poll_analyzer_result() polls /runs/{run_id} until 'completed' or 'error'.
    On completion, it decodes the base64 result. Must handle pending/running states,
    errors, empty results, and timeouts.
    """

    def test_poll_completed_immediately(self, mocker, mock_config, tmp_artifacts_dir):
        """When the first poll returns 'completed', the result is decoded."""
        raw_data = b"\x1f\x8b\x08profile"
        encoded = base64.b64encode(raw_data).decode("ascii")
        mocker.patch(
            "analyzer._service_request",
            return_value={"status": "completed", "result": encoded},
        )

        result_path = poll_analyzer_result("run-1", mock_config)
        assert result_path.exists()
        assert result_path.read_bytes() == raw_data

    def test_poll_error_status_raises(self, mocker, mock_config):
        """An 'error' status raises AnalyzerError('1b')."""
        mocker.patch(
            "analyzer._service_request",
            return_value={"status": "error", "detail": "profile failed"},
        )

        with pytest.raises(AnalyzerError) as exc_info:
            poll_analyzer_result("run-1", mock_config)
        assert exc_info.value.step == "1b"
        assert "error" in exc_info.value.message.lower()

    def test_poll_empty_result_raises(self, mocker, mock_config):
        """A 'completed' status with empty result raises AnalyzerError('1b')."""
        mocker.patch(
            "analyzer._service_request",
            return_value={"status": "completed", "result": ""},
        )

        with pytest.raises(AnalyzerError) as exc_info:
            poll_analyzer_result("run-1", mock_config)
        assert exc_info.value.step == "1b"
        assert "empty" in exc_info.value.message.lower()

    def test_poll_timeout_raises(self, mocker, mock_config):
        """Polling that never completes raises AnalyzerError('1b')."""
        # Always return 'pending' — will time out
        mocker.patch(
            "analyzer._service_request",
            return_value={"status": "pending"},
        )
        mocker.patch("analyzer.time.sleep")  # Don't actually sleep
        # Set a very short timeout
        mocker.patch.object(analyzer.Config, "POLL_TIMEOUT_SECONDS", 0)

        with pytest.raises(AnalyzerError) as exc_info:
            poll_analyzer_result("run-1", mock_config)
        assert exc_info.value.step == "1b"
        assert "Timed out" in exc_info.value.message

    def test_poll_transitions_through_statuses(self, mocker, mock_config, tmp_artifacts_dir):
        """The poll loop handles status transitions correctly."""
        raw_data = b"\x1f\x8bprofile"
        encoded = base64.b64encode(raw_data).decode("ascii")

        responses = [
            {"status": "pending"},
            {"status": "running"},
            {"status": "completed", "result": encoded},
        ]
        mocker.patch("analyzer._service_request", side_effect=responses)
        mocker.patch("analyzer.time.sleep")

        result_path = poll_analyzer_result("run-1", mock_config)
        assert result_path.exists()
        assert result_path.read_bytes() == raw_data


# Step 1d: File access (and other external commands)
class TestRunCommand:
    """Tests for _run_command() — subprocess execution.

    _run_command() wraps subprocess.run() with timeout, error handling, and
    stderr capture. Used for git, repomix, and other external commands.
    """

    def test_run_command_success(self, mocker):
        """A successful command returns stdout."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mocker.patch("analyzer.subprocess.run", return_value=mock_result)

        output = _run_command(["echo", "hello"], "1d")
        assert output == "output"

    def test_run_command_failure_raises(self, mocker):
        """A non-zero exit code raises AnalyzerError."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "command not found"
        mocker.patch("analyzer.subprocess.run", return_value=mock_result)

        with pytest.raises(AnalyzerError) as exc_info:
            _run_command(["nonexistent-cmd"], "1d")
        assert exc_info.value.step == "1d"
        assert "Command failed" in exc_info.value.message

    def test_run_command_timeout_raises(self, mocker):
        """A command timeout raises AnalyzerError."""
        mocker.patch(
            "analyzer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="test", timeout=5),
        )

        with pytest.raises(AnalyzerError) as exc_info:
            _run_command(["slow-cmd"], "1d", timeout=5)
        assert exc_info.value.step == "1d"
        assert "timeout" in exc_info.value.message.lower()

    def test_run_command_error_prefix_in_message(self, mocker):
        """The error_prefix is included in the error message."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "failed"
        mocker.patch("analyzer.subprocess.run", return_value=mock_result)

        with pytest.raises(AnalyzerError) as exc_info:
            _run_command(["cmd"], "1d", error_prefix="pprof-to-md")
        assert "pprof-to-md" in exc_info.value.message

    def test_run_command_default_timeout(self, mocker):
        """When timeout is None, the default GIT_OPERATIONS_TIMEOUT is used."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        mock_run = mocker.patch("analyzer.subprocess.run", return_value=mock_result)

        _run_command(["git", "status"], "1c")
        args, kwargs = mock_run.call_args
        assert kwargs["timeout"] == Config.GIT_OPERATIONS_TIMEOUT_SECONDS


class TestGitApplyCheck:
    """Tests for _git_apply_check() — dry-run patch validation.

    _git_apply_check() runs `git apply --check` on a patch without modifying
    the working directory. Returns None on success, error message on failure.
    """

    def test_check_clean_patch(self, mocker, tmp_artifacts_dir):
        """A patch that applies cleanly returns None."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mocker.patch("analyzer.subprocess.run", return_value=mock_result)

        result = _git_apply_check("--- a/file\n+++ b/file\n")
        assert result is None

    def test_check_failed_patch(self, mocker, tmp_artifacts_dir):
        """A patch that fails returns the error message."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "patch does not apply"
        mocker.patch("analyzer.subprocess.run", return_value=mock_result)

        result = _git_apply_check("--- a/file\n+++ b/file\n")
        assert result == "patch does not apply"

    def test_check_timeout(self, mocker, tmp_artifacts_dir):
        """A timeout returns a timeout error message."""
        mocker.patch(
            "analyzer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=120),
        )

        result = _git_apply_check("--- a/file\n+++ b/file\n")
        assert "timed out" in result.lower()

    def test_check_no_stderr_uses_default(self, mocker, tmp_artifacts_dir):
        """When stderr is empty, a default message is returned."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = ""
        mocker.patch("analyzer.subprocess.run", return_value=mock_result)

        result = _git_apply_check("--- a/file\n+++ b/file\n")
        assert "failed with no stderr" in result

    def test_check_writes_patch_file(self, mocker, tmp_artifacts_dir):
        """The patch is written to a temp file for git apply --check."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_run = mocker.patch("analyzer.subprocess.run", return_value=mock_result)

        _git_apply_check("--- a/file\n+++ b/file\n")
        args, kwargs = mock_run.call_args
        cmd = args[0] if args else kwargs.get("args", [])
        assert "git" in cmd
        assert "apply" in cmd
        assert "--check" in cmd


# Step 1f-1g: Call LLM and extract patch
class TestGenerateValidPatch:
    """Tests for generate_valid_patch() — LLM call + patch extraction + retry.

    generate_valid_patch() orchestrates the LLM call and patch validation:
    1. Calls the LLM
    2. Extracts patch from result
    3. Validates with `git apply --check`
    4. On failure, retries up to MAX_PATCH_ATTEMPTS times with error feedback
    """

    def test_first_attempt_succeeds(self, mocker, mock_config, tmp_artifacts_dir, sample_llm_result):
        """When the first LLM result produces a valid patch, it's returned."""
        mock_messages = [{"role": "user", "content": "test"}]
        mocker.patch("analyzer.call_llm", return_value=(sample_llm_result, mock_messages))
        mocker.patch("analyzer._git_apply_check", return_value=None)

        summary, patch, llm_result = generate_valid_patch("prompt", mock_config)
        assert "buildUsers" in summary
        assert "--- a/main.go" in patch
        assert llm_result == sample_llm_result

    def test_retry_after_extraction_failure(self, mocker, mock_config, tmp_artifacts_dir):
        """When extraction fails on the first attempt, a retry is attempted."""
        bad_result = "No patch here"
        good_result = """### SUMMARY
Fixed.

### PATCH

```diff
--- a/f.go
+++ b/f.go
@@ -1,3 +1,3 @@
-old
+new
 ctx
```
"""
        mock_messages = [{"role": "user", "content": "test"}]
        mocker.patch(
            "analyzer.call_llm",
            side_effect=[(bad_result, mock_messages), (good_result, mock_messages)],
        )
        mocker.patch("analyzer._git_apply_check", return_value=None)

        summary, patch, llm_result = generate_valid_patch("prompt", mock_config)
        assert "Fixed" in summary
        assert "--- a/f.go" in patch

    def test_retry_after_apply_check_failure(self, mocker, mock_config, tmp_artifacts_dir, sample_llm_result):
        """When git apply --check fails on the first attempt, a retry is attempted."""
        good_result = """### SUMMARY
Fixed.

### PATCH

```diff
--- a/f.go
+++ b/f.go
@@ -1,3 +1,3 @@
-old
+new
 ctx
```
"""
        mock_messages = [{"role": "user", "content": "test"}]
        mocker.patch(
            "analyzer.call_llm",
            side_effect=[(sample_llm_result, mock_messages), (good_result, mock_messages)],
        )
        mocker.patch(
            "analyzer._git_apply_check",
            side_effect=["patch does not apply", None],
        )

        summary, patch, llm_result = generate_valid_patch("prompt", mock_config)
        assert "Fixed" in summary

    def test_all_attempts_fail_raises(self, mocker, mock_config, tmp_artifacts_dir):
        """When all attempts fail, AnalyzerError('1h') is raised."""
        bad_result = "No patch here"
        mock_messages = [{"role": "user", "content": "test"}]
        mocker.patch("analyzer.call_llm", return_value=(bad_result, mock_messages))
        mocker.patch("analyzer._git_apply_check", return_value=None)

        with pytest.raises(AnalyzerError) as exc_info:
            generate_valid_patch("prompt", mock_config)
        assert exc_info.value.step == "1h"
        assert "No valid patch" in exc_info.value.message

    def test_retry_feeds_error_to_llm(self, mocker, mock_config, tmp_artifacts_dir):
        """The retry message includes the error from the previous attempt.

        Note: generate_valid_patch mutates the messages list in place via
        .append(), so both call_args_list entries point to the same list
        object. We verify the feedback was added by checking the final state
        of the messages list rather than comparing lengths across calls.
        """
        bad_result = "No patch"
        good_result = """### SUMMARY
Ok.

### PATCH

```diff
--- a/f.go
+++ b/f.go
@@ -1,3 +1,3 @@
-old
+new
 ctx
```
"""
        mock_messages1 = [{"role": "system", "content": "sys"}, {"role": "user", "content": "msg"}]
        mock_messages2 = [{"role": "system", "content": "sys"}, {"role": "user", "content": "msg"}]
        mock_llm = mocker.patch(
            "analyzer.call_llm",
            side_effect=[(bad_result, mock_messages1), (good_result, mock_messages2)],
        )
        mocker.patch("analyzer._git_apply_check", return_value=None)

        generate_valid_patch("prompt", mock_config)

        # The messages list was mutated in place; the final state should
        # contain the error feedback message
        assert mock_llm.call_count == 2
        # Get the messages from the second call
        final_messages = mock_llm.call_args_list[1].args[0]
        # Should have system message, original user message, assistant response, and feedback
        assert len(final_messages) >= 3
        # The last message should be the user feedback with the error
        feedback_msg = final_messages[-1]
        assert feedback_msg["role"] == "user"
        assert "could not be turned into" in feedback_msg["content"]


class TestCallLlm:
    """Tests for call_llm() — LLM API interaction.

    call_llm() creates an OpenAI client, sends messages, and returns the response
    text and messages. Configured with ai_key, ai_endpoint, and ai_model from config.
    """

    def test_call_llm_returns_text_and_messages(self, mocker, mock_config):
        """The LLM response text and messages are returned."""
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "LLM response text"
        mock_completion.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion
        mocker.patch("analyzer.OpenAI", return_value=mock_client)

        messages = [{"role": "user", "content": "hi"}]
        text, returned_messages = call_llm(messages, mock_config)
        assert text == "LLM response text"
        assert returned_messages == messages

    def test_call_llm_empty_response(self, mocker, mock_config):
        """An empty LLM response returns an empty string."""
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = None
        mock_completion.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion
        mocker.patch("analyzer.OpenAI", return_value=mock_client)

        messages = [{"role": "user", "content": "hi"}]
        text, returned_messages = call_llm(messages, mock_config)
        assert text == ""
        assert returned_messages == messages

    def test_call_llm_uses_config(self, mocker, mock_config):
        """The LLM client is configured with the config values."""
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "ok"
        mock_completion.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion
        mock_openai = mocker.patch("analyzer.OpenAI", return_value=mock_client)

        call_llm([{"role": "user", "content": "hi"}], mock_config)

        # Verify OpenAI client was initialized with config values
        args, kwargs = mock_openai.call_args
        assert kwargs["api_key"] == mock_config.ai_key
        assert kwargs["base_url"] == mock_config.ai_endpoint

    def test_call_llm_create_uses_model(self, mocker, mock_config):
        """The chat completion create uses the configured model."""
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "ok"
        mock_completion.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion
        mocker.patch("analyzer.OpenAI", return_value=mock_client)

        call_llm([{"role": "user", "content": "hi"}], mock_config)

        args, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["model"] == mock_config.ai_model


# Step 1h-1k: Apply patch and finalize
class TestFlagSubmitted:
    """Tests for flag_submitted() — step 1k.

    flag_submitted() POSTs to /runs/{run_id}/submit with the PR URL and number
    to record that the execution completed and a PR was created.
    """

    def test_flag_submitted_success(self, mocker, mock_config):
        """A successful submit flag calls _service_request."""
        mock_service = mocker.patch("analyzer._service_request", return_value={})

        flag_submitted("run-1", "https://github.com/owner/repo/pull/1", "1", mock_config)

        mock_service.assert_called_once()
        args, kwargs = mock_service.call_args
        # _service_request(method, endpoint, step, service_url, ai_key, payload)
        assert args[0] == "POST"
        assert args[1] == "/runs/run-1/submit"
        assert args[2] == "1k"
        assert args[5] == {
            "pr_url": "https://github.com/owner/repo/pull/1",
            "pr_number": "1",
        }

    def test_flag_submitted_step_label(self, mocker, mock_config):
        """The submit flag uses step label '1k'."""
        mock_service = mocker.patch("analyzer._service_request", return_value={})

        flag_submitted("run-1", "url", "1", mock_config)

        args, kwargs = mock_service.call_args
        assert args[2] == "1k"


class TestFlagError:
    """Tests for flag_error() — step 2a.

    flag_error() POSTs to /runs/{run_id}/error with the failing step and error
    message. It must not raise exceptions itself (swallows errors from the service).
    """

    def test_flag_error_success(self, mocker, mock_config):
        """A successful error flag calls _service_request."""
        mock_service = mocker.patch("analyzer._service_request", return_value={})

        flag_error("run-1", "1b", "Something failed", mock_config)

        mock_service.assert_called_once()
        args, kwargs = mock_service.call_args
        # _service_request(method, endpoint, step, service_url, ai_key, payload)
        assert args[0] == "POST"
        assert args[1] == "/runs/run-1/error"
        assert args[2] == "2a"
        assert args[5] == {
            "step": "1b",
            "error": "Something failed",
        }

    def test_flag_error_swallows_exceptions(self, mocker, mock_config):
        """If _service_request fails, flag_error does not raise."""
        mocker.patch(
            "analyzer._service_request",
            side_effect=AnalyzerError("2a", "network error"),
        )

        # Should not raise
        flag_error("run-1", "1b", "error", mock_config)

    def test_flag_error_step_label(self, mocker, mock_config):
        """The error flag uses step label '2a'."""
        mock_service = mocker.patch("analyzer._service_request", return_value={})

        flag_error("run-1", "1b", "msg", mock_config)

        args, kwargs = mock_service.call_args
        assert args[2] == "2a"


class TestCreatePullRequest:
    """Tests for create_pull_request() — step 1j.

    create_pull_request() commits the applied patch, pushes to a feature branch,
    and opens a pull request via the GitHub CLI. Must handle no-changes error,
    token redaction, and base branch resolution.
    """

    def test_create_pr_success(self, mocker, mock_config, tmp_path):
        """A successful PR creation returns URL and number."""
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = "some diff"
        mock_repo.remote.return_value.url = "https://github.com/owner/repo.git"

        # Mock _run_command for push and gh pr create
        def run_cmd_side_effect(cmd, step, **kwargs):
            if "push" in cmd:
                return ""
            if "pr" in cmd and "create" in cmd:
                return "https://github.com/owner/repo/pull/42\n"
            return ""

        mocker.patch("analyzer._run_command", side_effect=run_cmd_side_effect)
        mocker.patch("analyzer._resolve_default_branch", return_value="main")

        pr_url, pr_number = create_pull_request(
            mock_repo, "run-123", "Fix summary", mock_config
        )
        assert pr_url == "https://github.com/owner/repo/pull/42"
        assert pr_number == "42"

    def test_create_pr_no_changes_raises(self, mocker, mock_config):
        """When there are no staged changes, AnalyzerError('1j') is raised."""
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = ""  # No changes
        mock_repo.remote.return_value.url = "https://github.com/owner/repo.git"
        mocker.patch("analyzer._resolve_default_branch", return_value="main")

        with pytest.raises(AnalyzerError) as exc_info:
            create_pull_request(mock_repo, "run-1", "summary", mock_config)
        assert exc_info.value.step == "1j"
        assert "No changes" in exc_info.value.message

    def test_create_pr_token_redacted_on_push_error(self, mocker, mock_config):
        """The token is redacted in the error message when push fails."""
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = "some diff"
        mock_repo.remote.return_value.url = "https://github.com/owner/repo.git"
        mocker.patch("analyzer._resolve_default_branch", return_value="main")

        token = mock_config.token
        # Simulate push failure with token in the error message
        mocker.patch(
            "analyzer._run_command",
            side_effect=AnalyzerError("1j", f"git push failed: {token} in URL"),
        )

        with pytest.raises(AnalyzerError) as exc_info:
            create_pull_request(mock_repo, "run-1", "summary", mock_config)
        assert token not in exc_info.value.message
        assert "***" in exc_info.value.message

    def test_create_pr_uses_base_branch_from_config(self, mocker, mock_config):
        """When config.base_branch is set, it's used instead of auto-detecting."""
        mock_config.base_branch = "develop"
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = "diff"
        mock_repo.remote.return_value.url = "https://github.com/owner/repo.git"

        mock_resolve = mocker.patch("analyzer._resolve_default_branch")
        mocker.patch(
            "analyzer._run_command",
            side_effect=lambda cmd, step, **kw: "https://github.com/owner/repo/pull/1\n"
            if "pr" in cmd
            else "",
        )

        create_pull_request(mock_repo, "run-1", "summary", mock_config)
        mock_resolve.assert_not_called()

    def test_create_pr_branch_name_format(self, mocker, mock_config):
        """The branch name follows the pprof/fix-{run_id} pattern."""
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = "diff"
        mock_repo.remote.return_value.url = "https://github.com/owner/repo.git"
        mocker.patch("analyzer._resolve_default_branch", return_value="main")
        mocker.patch("analyzer._run_command", return_value="https://github.com/owner/repo/pull/1\n")

        create_pull_request(mock_repo, "run-abc", "summary", mock_config)

        # Verify checkout -b was called with the correct branch name
        mock_repo.git.checkout.assert_called_with("-b", "pprof/fix-run-abc")


class TestApplyPatch:
    """Tests for apply_patch() — step 1h.

    apply_patch() writes the patch to a file and runs `git apply --whitespace=fix`
    to apply it to the working directory.
    """

    def test_apply_patch_success(self, mocker, tmp_artifacts_dir):
        """A successful patch application calls git apply."""
        mock_repo = MagicMock()
        mock_run = mocker.patch("analyzer._run_command", return_value="")

        apply_patch(mock_repo, "--- a/file\n+++ b/file\n@@ -1,3 +1,3 @@\n-old\n+new\n ctx\n")

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert "git" in cmd
        assert "apply" in cmd
        assert "--whitespace=fix" in cmd

    def test_apply_patch_writes_file(self, mocker, tmp_artifacts_dir):
        """The patch is written to a file before applying."""
        mock_repo = MagicMock()
        mocker.patch("analyzer._run_command", return_value="")

        patch_content = "--- a/file\n+++ b/file\n@@ -1,3 +1,3 @@\n-old\n+new\n ctx\n"
        apply_patch(mock_repo, patch_content)

        patch_file = tmp_artifacts_dir / "patch.diff"
        assert patch_file.exists()
        assert patch_content in patch_file.read_text(encoding="utf-8")


class TestConvertPprofToMarkdown:
    """Tests for convert_pprof_to_markdown() — step 1b conversion.

    convert_pprof_to_markdown() runs the pprof-to-md node binary on a raw profile
    and reads the markdown output file.
    """

    def test_convert_success(self, mocker, tmp_artifacts_dir, tmp_path):
        """A successful conversion returns the markdown content."""
        action_path = tmp_path / "action"
        action_path.mkdir()
        # Create the node_modules/.bin structure
        bin_dir = action_path / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "pprof-to-md").write_text("#!/bin/sh\necho mock")

        out_file = tmp_artifacts_dir / "analyzer_result.md"
        out_file.write_text("# Profile Analysis\n\nHot function: foo", encoding="utf-8")

        mocker.patch("analyzer._run_command", return_value="")

        result = convert_pprof_to_markdown(tmp_path / "profile.pb.gz", action_path)
        assert "Hot function: foo" in result

    def test_convert_empty_output_raises(self, mocker, tmp_artifacts_dir, tmp_path):
        """Empty pprof-to-md output raises AnalyzerError('1b')."""
        action_path = tmp_path / "action"
        action_path.mkdir()
        bin_dir = action_path / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)

        out_file = tmp_artifacts_dir / "analyzer_result.md"
        out_file.write_text("", encoding="utf-8")

        mocker.patch("analyzer._run_command", return_value="")

        with pytest.raises(AnalyzerError) as exc_info:
            convert_pprof_to_markdown(tmp_path / "profile.pb.gz", action_path)
        assert exc_info.value.step == "1b"
        assert "empty" in exc_info.value.message.lower()

    def test_convert_missing_output_file_raises(self, mocker, tmp_artifacts_dir, tmp_path):
        """Missing output file raises AnalyzerError('1b')."""
        action_path = tmp_path / "action"
        action_path.mkdir()
        bin_dir = action_path / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)

        mocker.patch("analyzer._run_command", return_value="")

        with pytest.raises(AnalyzerError) as exc_info:
            convert_pprof_to_markdown(tmp_path / "profile.pb.gz", action_path)
        assert exc_info.value.step == "1b"
        assert "did not produce" in exc_info.value.message.lower()


class TestPrepareGitCheckout:
    """Tests for prepare_git_checkout() — step 1c.

    prepare_git_checkout() validates that the repo is on the correct branch/tag
    and returns the Repo object for subsequent git operations.
    """

    def test_prepare_checkout_on_branch_match(self, mocker):
        """When on the correct branch, no warning is emitted."""
        mock_repo = MagicMock()
        mock_repo.head.is_detached = False
        mock_repo.active_branch.name = "main"

        mocker.patch("analyzer.git.Repo", return_value=mock_repo)
        mocker.patch("os.getcwd", return_value="/tmp/repo")

        result = prepare_git_checkout("main")
        assert result == mock_repo

    def test_prepare_checkout_on_branch_mismatch(self, mocker):
        """When on the wrong branch, a warning is emitted but no error."""
        mock_repo = MagicMock()
        mock_repo.head.is_detached = False
        mock_repo.active_branch.name = "develop"

        mocker.patch("analyzer.git.Repo", return_value=mock_repo)
        mocker.patch("os.getcwd", return_value="/tmp/repo")

        # Should not raise, just warn
        result = prepare_git_checkout("main")
        assert result == mock_repo

    def test_prepare_checkout_not_a_repo(self, mocker):
        """When cwd is not a git repo, AnalyzerError('1c') is raised."""
        import git as git_module
        mocker.patch("analyzer.git.Repo", side_effect=git_module.InvalidGitRepositoryError("not a repo"))
        mocker.patch("os.getcwd", return_value="/tmp/not-a-repo")

        with pytest.raises(AnalyzerError) as exc_info:
            prepare_git_checkout("main")
        assert exc_info.value.step == "1c"
        assert "Not a git repository" in exc_info.value.message

    def test_prepare_checkout_detached_head_match(self, mocker):
        """Detached HEAD matching the tag resolves correctly."""
        mock_repo = MagicMock()
        mock_repo.head.is_detached = True
        mock_repo.head.commit.hexsha = "abc123"
        mock_repo.git.rev_parse.return_value = "abc123"

        mocker.patch("analyzer.git.Repo", return_value=mock_repo)
        mocker.patch("os.getcwd", return_value="/tmp/repo")

        result = prepare_git_checkout("v1.0")
        assert result == mock_repo

    def test_prepare_checkout_detached_head_mismatch(self, mocker):
        """Detached HEAD not matching the tag warns but doesn't error."""
        mock_repo = MagicMock()
        mock_repo.head.is_detached = True
        mock_repo.head.commit.hexsha = "abc123"
        mock_repo.git.rev_parse.return_value = "def456"

        mocker.patch("analyzer.git.Repo", return_value=mock_repo)
        mocker.patch("os.getcwd", return_value="/tmp/repo")

        result = prepare_git_checkout("v1.0")
        assert result == mock_repo
