"""Tests for pprof_integrator tool."""

from __future__ import annotations

import pytest


class TestIntegratePprofEndpoint:
    """Test suite for integrate_pprof_endpoint tool."""

    def test_calls_run_integrator_with_correct_args(self, tmp_repo_path, mock_run_integrator, load_tools):
        """Test that integrate_pprof_endpoint calls run_integrator with repo_path."""
        integrate_pprof_endpoint = load_tools["pprof_integrator"].integrate_pprof_endpoint
        repo_path = str(tmp_repo_path)
        result = integrate_pprof_endpoint(repo_path)

        mock_run_integrator.assert_called_once_with(repo_path)
        assert result == "Mocked integrator prompt"

    def test_returns_integrator_output(self, tmp_repo_path, mock_run_integrator, load_tools):
        """Test that output from run_integrator is returned as-is."""
        integrate_pprof_endpoint = load_tools["pprof_integrator"].integrate_pprof_endpoint
        expected_output = "Integration guide and analysis"
        mock_run_integrator.return_value = expected_output

        result = integrate_pprof_endpoint(str(tmp_repo_path))

        assert result == expected_output

    def test_raises_on_invalid_repo(self, tmp_path, mock_run_integrator, load_tools):
        """Test that FileNotFoundError is raised for non-existent repo."""
        integrate_pprof_endpoint = load_tools["pprof_integrator"].integrate_pprof_endpoint
        repo_path = str(tmp_path / "nonexistent")
        mock_run_integrator.side_effect = FileNotFoundError("Repository not found")

        with pytest.raises(FileNotFoundError):
            integrate_pprof_endpoint(repo_path)

    def test_raises_on_missing_go_mod(self, tmp_path, mock_run_integrator, load_tools):
        """Test that ValueError is raised if go.mod missing."""
        integrate_pprof_endpoint = load_tools["pprof_integrator"].integrate_pprof_endpoint
        repo = tmp_path / "repo"
        repo.mkdir()
        mock_run_integrator.side_effect = ValueError("Not a Go module")

        with pytest.raises(ValueError):
            integrate_pprof_endpoint(str(repo))
