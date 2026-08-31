"""
Central registry for skill wrapper functions.

Handles sys.path setup for the skill/ directory, exposing skill wrapper
functions cleanly without requiring type: ignore comments throughout the codebase.
"""
import sys
from pathlib import Path

# Add skill directory to path (one time at module load)
skill_path = Path(__file__).parent / "skill"
if str(skill_path) not in sys.path:
    sys.path.insert(0, str(skill_path))

# Import skill wrapper functions - clean, type-checkable imports
from pprof_analyzer.analyzer import run_analyzer
from pprof_integrator.coordinator import run_integrator
from load_test_generator.coordinator import run_load_test_generator
from profiler_executor.profiler import run_profiler

__all__ = [
    "run_analyzer",
    "run_integrator",
    "run_load_test_generator",
    "run_profiler",
]
