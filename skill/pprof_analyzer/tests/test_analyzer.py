"""Tests for skill/pprof_analyzer/analyzer.py (the Claude Code Skill implementation).

Not to be confused with action/scripts/tests/test_analyzer.py, which tests the
separate GitHub Action implementation.
"""

from __future__ import annotations

from pathlib import Path

import git
import pytest

from skill.pprof_analyzer.analyzer import (
    build_analysis_prompt,
    build_prompt,
    find_all_go_files,
    gather_local_context,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A real git repo with a couple of tracked Go files (for find_all_go_files)."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.go").write_text("package main\n\nfunc main() {}\n")
    (repo_dir / "util.go").write_text("package main\n\nfunc helper() {}\n")
    (repo_dir / "README.md").write_text("not a go file\n")

    repo = git.Repo.init(repo_dir)
    repo.index.add(["main.go", "util.go", "README.md"])
    return repo_dir


@pytest.fixture
def real_template_path() -> Path:
    return Path(__file__).resolve().parents[3] / "prompts" / "prompt_template.txt"


class TestFindAllGoFiles:
    def test_lists_only_go_files(self, git_repo):
        repo = git.Repo(git_repo)
        files = find_all_go_files(repo)
        assert files == {"main.go", "util.go"}


class TestGatherLocalContext:
    def test_raises_on_missing_profile(self, git_repo, tmp_path):
        with pytest.raises(FileNotFoundError):
            gather_local_context(tmp_path / "missing.prof", git_repo)

    def test_raises_on_missing_repo(self, tmp_path):
        profile = tmp_path / "cpu.prof"
        profile.write_bytes(b"fake profile bytes")
        with pytest.raises(FileNotFoundError):
            gather_local_context(profile, tmp_path / "missing_repo")

    def test_raises_on_non_git_repo(self, monkeypatch, tmp_path):
        profile = tmp_path / "cpu.prof"
        profile.write_bytes(b"fake profile bytes")
        not_a_repo = tmp_path / "not_a_repo"
        not_a_repo.mkdir()

        import skill.pprof_analyzer.analyzer as analyzer_module

        monkeypatch.setattr(analyzer_module, "convert_pprof_to_markdown", lambda p: "## hotspot")

        with pytest.raises(ValueError, match="Not a git repository"):
            gather_local_context(profile, not_a_repo)

    def test_returns_markdown_and_sorted_file_list(self, monkeypatch, git_repo, tmp_path):
        profile = tmp_path / "cpu.prof"
        profile.write_bytes(b"fake profile bytes")

        import skill.pprof_analyzer.analyzer as analyzer_module

        monkeypatch.setattr(analyzer_module, "convert_pprof_to_markdown", lambda p: "## hotspot\nmain.go:10")

        analyzer_result, file_list = gather_local_context(profile, git_repo)

        assert analyzer_result == "## hotspot\nmain.go:10"
        assert file_list == ["main.go", "util.go"]


class TestBuildAnalysisPrompt:
    """These exercise the REAL prompts/prompt_template.txt — the regression test
    for the bug where build_prompt() was called with a `source_code` kwarg that
    didn't match the template's actual `{file_list}` placeholder (KeyError)."""

    def test_builds_prompt_against_real_template(self):
        prompt = build_analysis_prompt(
            analyzer_result="## Hotspot\nmain.go:10 (50% self)",
            file_list=["util.go", "main.go"],
            reference_level="med",
        )

        assert "## Hotspot" in prompt
        assert "main.go:10" in prompt
        assert "- `main.go`" in prompt
        assert "- `util.go`" in prompt
        # file_list must be sorted regardless of input order
        assert prompt.index("- `main.go`") < prompt.index("- `util.go`")

    def test_rejects_invalid_reference_level(self):
        with pytest.raises(ValueError, match="Invalid reference level"):
            build_analysis_prompt("analyzer result", ["main.go"], "invalid")

    def test_reference_level_is_case_insensitive(self):
        prompt = build_analysis_prompt("analyzer result", ["main.go"], "MED")
        assert prompt  # did not raise


class TestBuildPrompt:
    def test_uses_file_list_kwarg_against_real_template(self, real_template_path):
        prompt = build_prompt(
            real_template_path,
            reference="low",
            analyzer_result="analyzer markdown",
            file_list="- `main.go`",
        )

        assert "analyzer markdown" in prompt
        assert "- `main.go`" in prompt

    def test_fallback_template_used_when_template_missing(self, tmp_path):
        prompt = build_prompt(
            tmp_path / "does_not_exist.txt",
            reference="low",
            analyzer_result="analyzer markdown",
            file_list="- `main.go`",
        )

        assert "analyzer markdown" in prompt
        assert "- `main.go`" in prompt
