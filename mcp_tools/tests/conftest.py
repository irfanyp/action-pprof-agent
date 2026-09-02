"""Pytest configuration and fixtures for MCP tools tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def tmp_repo_path(tmp_path: Path) -> Path:
    """Create a temporary directory with go.mod file (minimal Go repo)."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    (repo / "go.mod").write_text("module test-service\ngo 1.21\n")
    return repo


@pytest.fixture
def load_tools():
    """Load tool modules using importlib (same as main.py)."""
    tools = {}
    tools_dir = Path(__file__).parent.parent / "tools"

    for tool_name in ["pprof_analyzer", "pprof_integrator", "load_test_generator", "profiler_executor"]:
        spec = importlib.util.spec_from_file_location(tool_name, tools_dir / f"{tool_name}.py")
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            tools[tool_name] = module

    return tools


@pytest.fixture
def mock_run_analyzer(monkeypatch, load_tools):
    """Mock the run_analyzer skill function."""
    mock = MagicMock(return_value="Mocked analyzer prompt")
    # Patch in the pprof_analyzer tool module's namespace
    monkeypatch.setattr(load_tools["pprof_analyzer"], "run_analyzer", mock)
    return mock


@pytest.fixture
def mock_run_integrator(monkeypatch, load_tools):
    """Mock the run_integrator skill function."""
    mock = MagicMock(return_value="Mocked integrator prompt")
    monkeypatch.setattr(load_tools["pprof_integrator"], "run_integrator", mock)
    return mock


@pytest.fixture
def mock_run_load_test_generator(monkeypatch, load_tools):
    """Mock the run_load_test_generator skill function."""
    mock = MagicMock(return_value="Mocked load test prompt")
    monkeypatch.setattr(load_tools["load_test_generator"], "run_load_test_generator", mock)
    return mock


@pytest.fixture
def mock_run_profiler(monkeypatch, load_tools):
    """Mock the run_profiler skill function."""
    mock = MagicMock(return_value="Mocked profiler output")
    monkeypatch.setattr(load_tools["profiler_executor"], "run_profiler", mock)
    return mock
