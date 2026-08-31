"""Tests for profiler_executor tool (including concurrency lock)."""

from __future__ import annotations

import os
import pytest


class TestRunCpuProfile:
    """Test suite for run_cpu_profile tool."""

    def test_calls_run_profiler_with_correct_args(self, tmp_repo_path, mock_run_profiler, load_tools):
        """Test that run_cpu_profile calls run_profiler with correct arguments."""
        run_cpu_profile = load_tools["profiler_executor"].run_cpu_profile
        repo_path = str(tmp_repo_path)
        port = 9000
        duration = 60
        load_cmd = "curl localhost:9000"

        result = run_cpu_profile(repo_path, port=port, load_cmd=load_cmd, duration=duration)

        mock_run_profiler.assert_called_once_with(
            repo_path, port=port, load_cmd=load_cmd, duration=duration
        )
        assert "cpu.prof" in result

    def test_uses_default_parameters(self, tmp_repo_path, mock_run_profiler, load_tools):
        """Test that default parameters are correct."""
        run_cpu_profile = load_tools["profiler_executor"].run_cpu_profile
        repo_path = str(tmp_repo_path)
        run_cpu_profile(repo_path)

        args = mock_run_profiler.call_args
        assert args[1]["port"] == 8080
        assert args[1]["load_cmd"] is None
        assert args[1]["duration"] == 30

    def test_returns_profiler_output_plus_location(self, tmp_repo_path, mock_run_profiler, load_tools):
        """Test that return value includes profiler output and profile location."""
        run_cpu_profile = load_tools["profiler_executor"].run_cpu_profile
        repo_path = str(tmp_repo_path)
        profiler_output = "Profiling completed successfully"
        mock_run_profiler.return_value = profiler_output

        result = run_cpu_profile(repo_path)

        assert profiler_output in result
        assert f"Profile written to: {repo_path}/.ai_output/cpu.prof" in result

    def test_raises_on_invalid_repo(self, tmp_path, mock_run_profiler, load_tools):
        """Test that RuntimeError is raised for non-existent repo."""
        run_cpu_profile = load_tools["profiler_executor"].run_cpu_profile
        repo_path = str(tmp_path / "nonexistent")
        mock_run_profiler.side_effect = RuntimeError("Repository not found")

        with pytest.raises(RuntimeError):
            run_cpu_profile(repo_path)

    def test_raises_on_missing_go_mod(self, tmp_path, mock_run_profiler, load_tools):
        """Test that ValueError is raised if go.mod missing."""
        run_cpu_profile = load_tools["profiler_executor"].run_cpu_profile
        repo = tmp_path / "repo"
        repo.mkdir()
        mock_run_profiler.side_effect = ValueError("Not a Go module")

        with pytest.raises(ValueError):
            run_cpu_profile(str(repo))

    def test_concurrency_lock_prevents_overlapping_calls(self, tmp_repo_path, mock_run_profiler, load_tools):
        """Test that concurrency lock prevents overlapping calls for same repo."""
        run_cpu_profile = load_tools["profiler_executor"].run_cpu_profile
        repo_path = str(tmp_repo_path)

        # Get access to the _get_lock function from the loaded module
        _get_lock = load_tools["profiler_executor"]._get_lock

        # Manually acquire the lock for this repo
        lock = _get_lock(repo_path)
        lock.acquire()

        try:
            # Now try to call run_cpu_profile - should fail immediately
            with pytest.raises(RuntimeError, match="already running"):
                run_cpu_profile(repo_path)
        finally:
            # Release the lock
            lock.release()

    def test_concurrency_lock_allows_different_repos(self, tmp_path, mock_run_profiler, load_tools):
        """Test that different repos can run concurrently (different locks)."""
        run_cpu_profile = load_tools["profiler_executor"].run_cpu_profile
        _get_lock = load_tools["profiler_executor"]._get_lock

        repo1 = tmp_path / "repo1"
        repo2 = tmp_path / "repo2"
        repo1.mkdir()
        repo2.mkdir()
        (repo1 / "go.mod").write_text("module test\ngo 1.21\n")
        (repo2 / "go.mod").write_text("module test\ngo 1.21\n")

        # Acquire lock for repo1
        lock1 = _get_lock(str(repo1))
        lock1.acquire()

        try:
            # repo2 should work fine (different lock)
            mock_run_profiler.return_value = "Success"
            result = run_cpu_profile(str(repo2))
            assert result is not None
        finally:
            lock1.release()

    def test_lock_is_released_after_call(self, tmp_repo_path, mock_run_profiler, load_tools):
        """Test that lock is released after successful call."""
        run_cpu_profile = load_tools["profiler_executor"].run_cpu_profile
        _get_lock = load_tools["profiler_executor"]._get_lock

        repo_path = str(tmp_repo_path)
        lock = _get_lock(repo_path)

        # Call should acquire and release the lock
        mock_run_profiler.return_value = "Success"
        run_cpu_profile(repo_path)

        # Should be able to acquire immediately (lock was released)
        assert lock.acquire(blocking=False)
        lock.release()

    def test_lock_is_released_on_error(self, tmp_repo_path, mock_run_profiler, load_tools):
        """Test that lock is released even if profiler fails."""
        run_cpu_profile = load_tools["profiler_executor"].run_cpu_profile
        _get_lock = load_tools["profiler_executor"]._get_lock

        repo_path = str(tmp_repo_path)
        lock = _get_lock(repo_path)

        # Mock profiler to raise an error
        mock_run_profiler.side_effect = RuntimeError("Profiling failed")

        # Call should raise but release lock
        with pytest.raises(RuntimeError):
            run_cpu_profile(repo_path)

        # Lock should be released
        assert lock.acquire(blocking=False)
        lock.release()
