#!/usr/bin/env python3
"""
Claude Code Skill: pprof-analyzer

Simplified analyzer for local Claude Code use (no external API calls).
Single-turn analysis: reads all context upfront, returns prompt to Claude.

Usage:
  python analyzer.py <profile_path> <repo_path> <reference_level>

Example:
  python analyzer.py cpu.prof ./ med
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import git
except ImportError:
    print("ERROR: GitPython not installed. Run: pip install GitPython")
    sys.exit(1)


class SkillConfig:
    """Configuration constants for the skill."""
    PPROF_TO_MD_TIMEOUT = 60
    GIT_OPERATIONS_TIMEOUT = 120
    VALID_REFERENCES = {"low", "med", "high"}
    ARTIFACTS_DIR = Path(".ai_output")
    PATCH_FENCE_PATTERN = r"```(?:diff[a-z-]*)?\n(.*?)```"
    SUMMARY_PATTERN = r"###\s*SUMMARY\s*\n(.*?)(?:###\s*PATCH|\Z)"


def log(message: str, level: str = "INFO") -> None:
    """Print a log message."""
    print(f"[{level}] {message}")


def error(message: str) -> None:
    """Print an error and exit."""
    log(message, "ERROR")
    sys.exit(1)


def find_node_bin(name: str) -> str:
    """Find a node_modules binary (pprof-to-md)."""
    candidates = [
        Path.cwd() / "node_modules" / ".bin" / name,
        Path.home() / ".local" / "bin" / name,
        Path("/usr/local/bin") / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    # Fallback: assume it's in PATH
    return name


def convert_pprof_to_markdown(pprof_path: Path) -> str:
    """Convert raw pprof profile to markdown via pprof-to-md."""
    if not pprof_path.exists():
        error(f"Profile file not found: {pprof_path}")

    SkillConfig.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = SkillConfig.ARTIFACTS_DIR / "analyzer_result.md"

    pprof_to_md = find_node_bin("pprof-to-md")
    cmd = [pprof_to_md, "--format", "detailed", str(pprof_path), "-o", str(out_file)]

    log(f"Converting pprof to markdown: {' '.join(cmd[:3])}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SkillConfig.PPROF_TO_MD_TIMEOUT,
        )
        if result.returncode != 0:
            error(f"pprof-to-md failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        error(f"pprof-to-md timed out after {SkillConfig.PPROF_TO_MD_TIMEOUT}s")
    except FileNotFoundError:
        error(
            "pprof-to-md not found. Install with: npm install -g pprof-to-md "
            "or npm ci in action/ folder"
        )

    if not out_file.exists():
        error(f"pprof-to-md did not produce output: {out_file}")

    markdown = out_file.read_text(encoding="utf-8")
    if not markdown.strip():
        error("pprof-to-md produced empty output")

    log(f"✓ pprof-to-md produced {len(markdown)} chars")
    return markdown


def find_all_go_files(repo: git.Repo) -> set[str]:
    """Find all Go files in the repository."""
    files = set()
    try:
        for item in repo.git.ls_files().split("\n"):
            if item.endswith(".go"):
                files.add(item)
    except Exception:
        # Fallback to filesystem walk
        for root, dirs, filenames in os.walk("."):
            dirs[:] = [
                d
                for d in dirs
                if d not in {".git", "vendor", "node_modules", ".github", "build"}
            ]
            for f in filenames:
                if f.endswith(".go"):
                    path = os.path.join(root, f).lstrip("./")
                    files.add(path)

    log(f"✓ Found {len(files)} Go files in repository")
    return files


def build_prompt(
    template_path: Path,
    reference: str,
    analyzer_result: str,
    file_list: str,
) -> str:
    """Build the prompt for Claude."""
    if not template_path.exists():
        # Fallback template if file not found
        template = """# Go Performance Optimization Task

## Reference Level
{reference_level}

## Performance Profile Analysis
{analyzer_result}

## Repository Files
{file_list}

## Your Task
Analyze the pprof profile and the file list. Use the read_file tool to inspect any files you need. Identify the top performance hotspots and propose optimizations.

Generate your response with:
1. A SUMMARY section with:
   - Analysis table (hotspot, function, % time, proposed fix, confidence)
   - Brief explanation of findings
2. A PATCH section with:
   - Unified diff format
   - Only the minimal changes needed
   - Clear, production-ready code

Format your response exactly as:

### SUMMARY
[Analysis table and explanation]

### PATCH
```diff
[unified diff patch here]
```
"""
    else:
        template = template_path.read_text(encoding="utf-8")

    prompt = template.format(
        reference_level=reference,
        analyzer_result=analyzer_result,
        file_list=file_list,
    )
    return prompt


def extract_patch_and_summary(llm_response: str) -> tuple[str, str]:
    """Extract SUMMARY and PATCH sections from Claude's response."""
    # Extract SUMMARY
    summary_match = re.search(SkillConfig.SUMMARY_PATTERN, llm_response, re.DOTALL | re.IGNORECASE)
    if summary_match:
        summary = summary_match.group(1).strip()
    else:
        summary = "Performance optimization analysis (auto-generated)"

    # Extract PATCH
    patch_match = re.search(SkillConfig.PATCH_FENCE_PATTERN, llm_response, re.DOTALL)
    if not patch_match:
        log("WARNING: No patch code fence found in response", "WARN")
        return summary, ""

    patch = patch_match.group(1).strip()
    return summary, patch


def validate_patch(patch: str) -> bool:
    """Validate patch with git apply --check."""
    if not patch.strip():
        log("WARNING: Patch is empty", "WARN")
        return False

    SkillConfig.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    patch_file = SkillConfig.ARTIFACTS_DIR / "patch_check.diff"
    patch_file.write_text(patch + "\n", encoding="utf-8")

    try:
        result = subprocess.run(
            ["git", "apply", "--check", "--whitespace=fix", str(patch_file)],
            capture_output=True,
            text=True,
            timeout=SkillConfig.GIT_OPERATIONS_TIMEOUT,
        )
        if result.returncode != 0:
            log(f"Patch validation failed: {result.stderr}", "WARN")
            return False
        return True
    except subprocess.TimeoutExpired:
        log("Patch validation timed out", "WARN")
        return False
    except Exception as e:
        log(f"Patch validation error: {e}", "WARN")
        return False


def write_artifacts(
    summary: str, patch: str, analyzer_result: str, prompt: str
) -> None:
    """Write analysis artifacts to .ai_output/."""
    SkillConfig.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "summary.md": summary,
        "patch.diff": patch + "\n" if patch else "# No patch generated\n",
        "analyzer_result.md": analyzer_result,
        "prompt.txt": prompt,
    }

    for name, content in artifacts.items():
        path = SkillConfig.ARTIFACTS_DIR / name
        path.write_text(content, encoding="utf-8")
        log(f"✓ Wrote {name}")


def run_analyzer(profile_path: str | Path, repo_path: str | Path, reference_level: str) -> str:
    """Run analyzer and return prompt (importable wrapper for MCP).

    Args:
        profile_path: Path to pprof profile file
        repo_path: Path to repository
        reference_level: One of "low", "med", "high"

    Returns:
        Markdown prompt for Claude analysis

    Raises:
        ValueError: If inputs are invalid
        FileNotFoundError: If profile or repo not found
    """
    prompt, _analyzer_result = _run_analyzer(profile_path, repo_path, reference_level)
    return prompt


def gather_local_context(profile_path: str | Path, repo_path: str | Path) -> tuple[str, list[str]]:
    """Gather everything that requires access to the caller's actual profile/repo.

    Must run on whatever machine has the real profile file and repo checkout —
    converts the raw pprof profile to markdown and lists the repo's Go files.
    Returns (analyzer_result_markdown, sorted_go_file_list).
    """
    profile_path = Path(profile_path)
    repo_path = Path(repo_path)

    if not profile_path.exists():
        raise FileNotFoundError(f"Profile file not found: {profile_path}")
    if not repo_path.exists():
        raise FileNotFoundError(f"Repository path not found: {repo_path}")

    analyzer_result = convert_pprof_to_markdown(profile_path)

    try:
        repo = git.Repo(repo_path)
    except git.InvalidGitRepositoryError:
        raise ValueError(f"Not a git repository: {repo_path}") from None

    file_list = sorted(find_all_go_files(repo))
    return analyzer_result, file_list


def build_analysis_prompt(analyzer_result: str, file_list: list[str], reference_level: str) -> str:
    """Build the final prompt from already-gathered content.

    Pure text templating — touches no caller-supplied filesystem path, so it's
    safe to run anywhere (including a shared remote server) once the caller has
    gathered `analyzer_result`/`file_list` locally via gather_local_context().
    """
    reference_level = reference_level.lower()
    if reference_level not in SkillConfig.VALID_REFERENCES:
        raise ValueError(f"Invalid reference level: {reference_level}. Must be one of: {SkillConfig.VALID_REFERENCES}")

    file_list_md = "\n".join(f"- `{f}`" for f in sorted(file_list))

    # The template is part of pprof-analyzer, not the target repo being analyzed —
    # resolve it relative to this file's location instead of repo_path.
    template_path = Path(__file__).resolve().parents[2] / "prompts" / "prompt_template.txt"
    return build_prompt(template_path, reference_level, analyzer_result, file_list_md)


def _run_analyzer(profile_path: str | Path, repo_path: str | Path, reference_level: str) -> tuple[str, str]:
    """Core analyzer logic, returning both the prompt and the pprof markdown.

    Split out from run_analyzer() so main() can reuse the markdown for artifact
    writing without invoking the pprof-to-md subprocess a second time.
    """
    profile_path = Path(profile_path)
    repo_path = Path(repo_path)
    reference_level = reference_level.lower()

    # Validate reference_level up front so a typo is caught before the slow
    # pprof-to-md subprocess runs.
    if reference_level not in SkillConfig.VALID_REFERENCES:
        raise ValueError(f"Invalid reference level: {reference_level}. Must be one of: {SkillConfig.VALID_REFERENCES}")

    analyzer_result, file_list = gather_local_context(profile_path, repo_path)
    prompt = build_analysis_prompt(analyzer_result, file_list, reference_level)

    return prompt, analyzer_result


def main() -> int:
    """Main orchestration (CLI entrypoint)."""
    # Parse arguments
    if len(sys.argv) != 4:
        print(
            "Usage: python analyzer.py <profile_path> <repo_path> <reference_level>",
            file=sys.stderr,
        )
        print("Example: python analyzer.py cpu.prof ./ med", file=sys.stderr)
        return 1

    try:
        profile_path = sys.argv[1]
        repo_path = sys.argv[2]
        reference_level = sys.argv[3]

        log(f"Profile: {profile_path}")
        log(f"Repository: {repo_path}")
        log(f"Reference level: {reference_level}")

        # Run analyzer
        prompt, analyzer_result = _run_analyzer(profile_path, repo_path, reference_level)

        # Output prompt
        log("=" * 70)
        log("PROMPT FOR CLAUDE ANALYSIS")
        log("=" * 70)
        print(prompt)
        log("=" * 70)

        # Write artifacts for reference
        write_artifacts("", "", analyzer_result, prompt)
        log("✓ Wrote prompt to .ai_output/prompt.txt")

        return 0
    except (FileNotFoundError, ValueError) as e:
        error(str(e))
        return 1  # error() calls sys.exit(1), but return for type checking


if __name__ == "__main__":
    sys.exit(main())
