"""Tests for load_test_generator tool."""

from __future__ import annotations

import pytest


class TestGenerateLoadTest:
    """Test suite for generate_load_test tool."""

    def test_calls_run_load_test_generator_with_correct_args(
        self, tmp_repo_path, mock_run_load_test_generator, load_tools
    ):
        """Test that generate_load_test calls run_load_test_generator correctly."""
        generate_load_test = load_tools["load_test_generator"].generate_load_test
        repo_path = str(tmp_repo_path)
        tool = "k6"

        result = generate_load_test(repo_path, tool)

        mock_run_load_test_generator.assert_called_once_with(repo_path, tool)
        assert result == "Mocked load test prompt"

    def test_uses_default_tool(self, tmp_repo_path, mock_run_load_test_generator, load_tools):
        """Test that default tool is 'k6'."""
        generate_load_test = load_tools["load_test_generator"].generate_load_test
        repo_path = str(tmp_repo_path)
        generate_load_test(repo_path)

        args = mock_run_load_test_generator.call_args[0]
        assert args[1] == "k6"

    def test_returns_generator_output(self, tmp_repo_path, mock_run_load_test_generator, load_tools):
        """Test that output is returned as-is."""
        generate_load_test = load_tools["load_test_generator"].generate_load_test
        expected_output = "Load test script generation prompt"
        mock_run_load_test_generator.return_value = expected_output

        result = generate_load_test(str(tmp_repo_path))

        assert result == expected_output

    def test_all_tool_choices_accepted(self, tmp_repo_path, mock_run_load_test_generator, load_tools):
        """Test that all valid tool choices are accepted."""
        generate_load_test = load_tools["load_test_generator"].generate_load_test
        repo_path = str(tmp_repo_path)

        for tool in ["k6", "apache-bench", "wrk", "go"]:
            generate_load_test(repo_path, tool)
            args = mock_run_load_test_generator.call_args[0]
            assert args[1] == tool

    def test_raises_on_invalid_repo(self, tmp_path, mock_run_load_test_generator, load_tools):
        """Test that FileNotFoundError is raised for non-existent repo."""
        generate_load_test = load_tools["load_test_generator"].generate_load_test
        repo_path = str(tmp_path / "nonexistent")
        mock_run_load_test_generator.side_effect = FileNotFoundError("Repository not found")

        with pytest.raises(FileNotFoundError):
            generate_load_test(repo_path)

    def test_raises_on_missing_go_mod(self, tmp_path, mock_run_load_test_generator, load_tools):
        """Test that ValueError is raised if go.mod missing."""
        generate_load_test = load_tools["load_test_generator"].generate_load_test
        repo = tmp_path / "repo"
        repo.mkdir()
        mock_run_load_test_generator.side_effect = ValueError("Not a Go module")

        with pytest.raises(ValueError):
            generate_load_test(str(repo))

    def test_raises_on_invalid_tool(self, tmp_repo_path, mock_run_load_test_generator, load_tools):
        """Test that ValueError is raised for invalid tool."""
        generate_load_test = load_tools["load_test_generator"].generate_load_test
        mock_run_load_test_generator.side_effect = ValueError("Invalid tool")

        with pytest.raises(ValueError):
            generate_load_test(str(tmp_repo_path), "invalid-tool")
