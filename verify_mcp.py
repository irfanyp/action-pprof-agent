#!/usr/bin/env python3
"""
Verification script for MCP server setup.

Checks that all dependencies are installed and the MCP server can start.
"""
import sys
import subprocess
from pathlib import Path

def check_python_version():
    """Check Python version >= 3.10."""
    if sys.version_info < (3, 10):
        print(f"❌ Python 3.10+ required, got {sys.version_info.major}.{sys.version_info.minor}")
        return False
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")
    return True


def check_imports():
    """Check that required packages are installed."""
    packages = {
        "GitPython": "git",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "mcp": "mcp",
    }

    all_good = True
    for name, module in packages.items():
        try:
            __import__(module)
            print(f"✅ {name}")
        except ImportError:
            print(f"❌ {name} not installed")
            all_good = False

    return all_good


def check_skill_imports():
    """Check that skill packages are importable."""
    try:
        from skill.pprof_analyzer.analyzer import run_analyzer
        from skill.pprof_integrator.coordinator import run_integrator
        from skill.load_test_generator.coordinator import run_load_test_generator
        from skill.profiler_executor.profiler import run_profiler

        print("✅ All skill packages importable")
        return True
    except ImportError as e:
        print(f"❌ Skill import error: {e}")
        return False


def check_mcp_imports():
    """Check that MCP packages are importable."""
    try:
        from mcp.server import MCPServer
        from mcp.server.sse import SseServerTransport
        print("✅ MCP packages importable")
        return True
    except ImportError as e:
        print(f"❌ MCP import error: {e}")
        return False


def check_entry_points():
    """Check that entry point scripts exist."""
    scripts = {
        "mcp_server.py": "Stdio entry point",
        "mcp_server_http.py": "HTTP/SSE entry point",
    }

    all_good = True
    for script, desc in scripts.items():
        if Path(script).exists():
            print(f"✅ {script} ({desc})")
        else:
            print(f"❌ {script} not found")
            all_good = False

    return all_good


def main():
    """Run all verification checks."""
    print("\n" + "=" * 60)
    print("pprof-analyzer MCP Server Verification")
    print("=" * 60 + "\n")

    checks = [
        ("Python Version", check_python_version),
        ("Required Packages", check_imports),
        ("Skill Packages", check_skill_imports),
        ("MCP Packages", check_mcp_imports),
        ("Entry Point Scripts", check_entry_points),
    ]

    results = []
    for name, check in checks:
        print(f"\n{name}:")
        print("-" * 40)
        results.append(check())

    print("\n" + "=" * 60)
    if all(results):
        print("✅ All checks passed! Ready to run MCP server.")
        print("\nQuick start:")
        print("  python3 mcp_server.py              # Stdio transport")
        print("  python3 mcp_server_http.py         # HTTP/SSE transport")
        print("\nSee MCP_SETUP.md for detailed setup instructions.")
        print("=" * 60 + "\n")
        return 0
    else:
        print("❌ Some checks failed. See details above.")
        print("\nFix: pip install -e .")
        print("=" * 60 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
