"""Tests for pprof_analyzer tool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestAnalyzePprofProfile:
    """Test suite for analyze_pprof_profile tool."""

    def test_calls_run_analyzer_with_correct_args(self, tmp_repo_path, mock_run_analyzer, load_tools):
        """Test that analyze_pprof_profile calls run_analyzer with correct arguments."""
        analyze_pprof_profile = load_tools["pprof_analyzer"].analyze_pprof_profile

        profile_path = "cpu.prof"
        repo_path = str(tmp_repo_path)
        reference_level = "med"

        result = analyze_pprof_profile(profile_path, repo_path, reference_level)

        mock_run_analyzer.assert_called_once_with(profile_path, repo_path, reference_level)
        assert result == "Mocked analyzer prompt"

    def test_uses_default_reference_level(self, tmp_repo_path, mock_run_analyzer, load_tools):
        """Test that default reference_level is 'med'."""
        analyze_pprof_profile = load_tools["pprof_analyzer"].analyze_pprof_profile

        profile_path = "cpu.prof"
        repo_path = str(tmp_repo_path)

        analyze_pprof_profile(profile_path, repo_path)

        # Check that the third argument (reference_level) is "med"
        args = mock_run_analyzer.call_args[0]
        assert args[2] == "med"

    def test_returns_analyzer_output(self, tmp_repo_path, mock_run_analyzer, load_tools):
        """Test that output from run_analyzer is returned as-is."""
        analyze_pprof_profile = load_tools["pprof_analyzer"].analyze_pprof_profile

        expected_output = "Complex analysis prompt\nwith multiple lines"
        mock_run_analyzer.return_value = expected_output

        result = analyze_pprof_profile("cpu.prof", str(tmp_repo_path))

        assert result == expected_output

    def test_raises_on_invalid_repo(self, tmp_path, mock_run_analyzer, load_tools):
        """Test that FileNotFoundError is raised for non-existent repo."""
        analyze_pprof_profile = load_tools["pprof_analyzer"].analyze_pprof_profile

        profile_path = "cpu.prof"
        repo_path = str(tmp_path / "nonexistent")

        # Mock run_analyzer to raise FileNotFoundError
        mock_run_analyzer.side_effect = FileNotFoundError("Repository not found")

        with pytest.raises(FileNotFoundError):
            analyze_pprof_profile(profile_path, repo_path)

    def test_raises_on_missing_go_mod(self, tmp_path, mock_run_analyzer, load_tools):
        """Test that ValueError is raised if go.mod missing."""
        analyze_pprof_profile = load_tools["pprof_analyzer"].analyze_pprof_profile

        repo = tmp_path / "repo"
        repo.mkdir()

        # Mock run_analyzer to raise ValueError
        mock_run_analyzer.side_effect = ValueError("Not a Go module")

        with pytest.raises(ValueError):
            analyze_pprof_profile("cpu.prof", str(repo))

    def test_accepts_all_reference_levels(self, tmp_repo_path, mock_run_analyzer, load_tools):
        """Test that all valid reference levels are accepted."""
        analyze_pprof_profile = load_tools["pprof_analyzer"].analyze_pprof_profile

        profile_path = "cpu.prof"
        repo_path = str(tmp_repo_path)

        for level in ["low", "med", "high"]:
            analyze_pprof_profile(profile_path, repo_path, level)
            args = mock_run_analyzer.call_args[0]
            assert args[2] == level


class TestBuildPprofAnalysisPrompt:
    """Test suite for build_pprof_analysis_prompt (remote-safe, content-only) tool."""

    @pytest.fixture
    def mock_build_analysis_prompt(self, monkeypatch, load_tools):
        mock = MagicMock(return_value="Mocked remote analysis prompt")
        monkeypatch.setattr(load_tools["pprof_analyzer"], "build_analysis_prompt", mock)
        return mock

    def test_calls_build_analysis_prompt_with_correct_args(self, mock_build_analysis_prompt, load_tools):
        build_pprof_analysis_prompt = load_tools["pprof_analyzer"].build_pprof_analysis_prompt

        analyzer_result = "## Hotspot\nmain.go:10"
        file_list = ["main.go", "util.go"]
        reference_level = "high"

        result = build_pprof_analysis_prompt(analyzer_result, file_list, reference_level)

        mock_build_analysis_prompt.assert_called_once_with(analyzer_result, file_list, reference_level)
        assert result == "Mocked remote analysis prompt"

    def test_uses_default_reference_level(self, mock_build_analysis_prompt, load_tools):
        build_pprof_analysis_prompt = load_tools["pprof_analyzer"].build_pprof_analysis_prompt

        build_pprof_analysis_prompt("analyzer result", ["main.go"])

        args = mock_build_analysis_prompt.call_args[0]
        assert args[2] == "med"

    def test_does_not_touch_filesystem(self, mock_build_analysis_prompt, load_tools):
        """No profile_path/repo_path params at all — nothing here can hit the server's disk."""
        build_pprof_analysis_prompt = load_tools["pprof_analyzer"].build_pprof_analysis_prompt

        import inspect
        params = inspect.signature(build_pprof_analysis_prompt).parameters
        assert set(params) == {"analyzer_result", "file_list", "reference_level"}

    def test_propagates_value_error(self, mock_build_analysis_prompt, load_tools):
        build_pprof_analysis_prompt = load_tools["pprof_analyzer"].build_pprof_analysis_prompt
        mock_build_analysis_prompt.side_effect = ValueError("Invalid reference level")

        with pytest.raises(ValueError):
            build_pprof_analysis_prompt("analyzer result", ["main.go"], "invalid")
