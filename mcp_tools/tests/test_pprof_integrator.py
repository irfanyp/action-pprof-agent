"""Tests for pprof_integrator tool."""

from __future__ import annotations

import pytest

from skill.pprof_integrator.coordinator import run_integrator


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


class TestVerifyLocalPaths:
    """Test suite for the PPROF_VERIFY_LOCAL_PATHS env var (remote-deployment support).

    Exercises the real (unmocked) run_integrator(), since a repo_path from a remote
    caller never exists on this host — the mocked mcp_tools fixtures wouldn't catch
    a regression here.
    """

    def test_nonexistent_repo_fails_by_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PPROF_VERIFY_LOCAL_PATHS", raising=False)
        with pytest.raises(FileNotFoundError):
            run_integrator(str(tmp_path / "nonexistent"))

    def test_nonexistent_repo_succeeds_when_verification_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PPROF_VERIFY_LOCAL_PATHS", "false")
        repo_path = str(tmp_path / "nonexistent")

        prompt = run_integrator(repo_path)

        assert repo_path in prompt

    def test_path_is_not_resolved_when_verification_disabled(self, monkeypatch):
        monkeypatch.setenv("PPROF_VERIFY_LOCAL_PATHS", "false")
        relative_path = "some/relative/repo"

        prompt = run_integrator(relative_path)

        # Should be embedded exactly as given, not resolved against this host's cwd.
        assert relative_path in prompt
