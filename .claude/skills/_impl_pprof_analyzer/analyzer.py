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
    MAX_CODE_SIZE_KB = 75
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


def extract_hotspot_files(analyzer_result: str) -> set[str]:
    """Extract file paths mentioned in hotspot analysis."""
    # Look for patterns like "main.go:12" or "pkg/utils.go:45"
    pattern = r"([a-zA-Z0-9_./\-]+\.go):(\d+)"
    matches = re.findall(pattern, analyzer_result)
    files = {match[0] for match in matches}
    log(f"✓ Extracted {len(files)} hotspot files from analysis")
    return files


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


def find_imports_in_file(file_path: str, repo: git.Repo) -> set[str]:
    """Extract import paths from a Go file."""
    try:
        content = repo.git.show(f"HEAD:{file_path}")
    except Exception:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return set()

    imports = set()
    # Simple regex for Go imports
    import_pattern = r'import\s+(?:\(([^)]+)\)|"([^"]+)")'
    for match in re.finditer(import_pattern, content, re.MULTILINE | re.DOTALL):
        group = match.group(1) or match.group(2)
        if group:
            # Extract import paths from parenthesized imports
            for line in group.split("\n"):
                line = line.strip().strip('"').strip("_")
                if line and not line.startswith("//"):
                    imports.add(line)

    return imports


def smart_select_files(
    hotspot_files: set[str], all_files: set[str], repo: git.Repo
) -> list[str]:
    """Intelligently select files to include in context.

    Strategy:
    1. Always include hotspot files
    2. Include direct imports of hotspot files
    3. Cap total size at ~75KB
    """
    selected = set()

    # Start with hotspot files
    for f in hotspot_files:
        if f in all_files:
            selected.add(f)

    # Add direct imports from hotspot files
    for f in selected.copy():
        imports = find_imports_in_file(f, repo)
        # Convert import paths to file paths (simple heuristic)
        for imp in imports:
            if imp.startswith("."):
                continue  # Skip relative imports for now
            # Try to find matching file in repo
            for repo_file in all_files:
                # Very simple matching: if filename contains import name
                if repo_file.replace("/", "").endswith(imp.replace("/", "")):
                    selected.add(repo_file)
                    break

    # Sort and apply size limit
    selected = sorted(selected)
    log(f"✓ Selected {len(selected)} files for analysis (before size cap)")

    return selected


def read_file_with_lines(file_path: str, repo: git.Repo) -> str:
    """Read a file and add line numbers (L{num}| format)."""
    try:
        try:
            content = repo.git.show(f"HEAD:{file_path}")
        except Exception:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
    except Exception:
        return f"# ERROR reading {file_path}\n"

    lines = content.splitlines()
    result = [f"L{i}| {line}" for i, line in enumerate(lines, 1)]
    return "\n".join(result)


def build_prompt(
    template_path: Path,
    reference: str,
    analyzer_result: str,
    source_code: str,
) -> str:
    """Build the prompt for Claude."""
    if not template_path.exists():
        # Fallback template if file not found
        template = """# Go Performance Optimization Task

## Reference Level
{reference_level}

## Performance Profile Analysis
{analyzer_result}

## Repository Source Code
{source_code}

## Your Task
Analyze the pprof profile and the source code. Identify the top performance hotspots and propose optimizations.

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
        source_code=source_code,
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


def main() -> int:
    """Main orchestration."""
    # Parse arguments
    if len(sys.argv) != 4:
        print(
            "Usage: python analyzer.py <profile_path> <repo_path> <reference_level>",
            file=sys.stderr,
        )
        print("Example: python analyzer.py cpu.prof ./ med", file=sys.stderr)
        return 1

    profile_path = Path(sys.argv[1])
    repo_path = Path(sys.argv[2])
    reference_level = sys.argv[3].lower()

    # Validate inputs
    if not profile_path.exists():
        error(f"Profile file not found: {profile_path}")
    if not repo_path.exists():
        error(f"Repository path not found: {repo_path}")
    if reference_level not in SkillConfig.VALID_REFERENCES:
        error(f"Invalid reference level: {reference_level}. Must be one of: {SkillConfig.VALID_REFERENCES}")

    log(f"Profile: {profile_path}")
    log(f"Repository: {repo_path}")
    log(f"Reference level: {reference_level}")

    # Step 1: Convert pprof to markdown
    analyzer_result = convert_pprof_to_markdown(profile_path)

    # Step 2: Prepare git repo
    try:
        repo = git.Repo(repo_path)
    except git.InvalidGitRepositoryError:
        error(f"Not a git repository: {repo_path}")
        return 1  # error() calls sys.exit(1); this satisfies type checkers

    # Step 3: Extract hotspot files and smart-select
    hotspot_files = extract_hotspot_files(analyzer_result)
    all_files = find_all_go_files(repo)
    selected_files = smart_select_files(hotspot_files, all_files, repo)

    log(f"✓ Selected files: {', '.join(selected_files[:5])}" + (
        f" ... and {len(selected_files) - 5} more" if len(selected_files) > 5 else ""
    ))

    # Step 4: Read source code for selected files
    source_code_parts = []
    total_size = 0
    for f in selected_files:
        if total_size > SkillConfig.MAX_CODE_SIZE_KB * 1024:
            log(f"Reached code size limit ({SkillConfig.MAX_CODE_SIZE_KB}KB), stopping", "WARN")
            break
        try:
            content = read_file_with_lines(f, repo)
            part = f"## {f}\n{content}\n\n"
            source_code_parts.append(part)
            total_size += len(content)
        except Exception as e:
            log(f"Failed to read {f}: {e}", "WARN")

    source_code = "".join(source_code_parts)
    log(f"✓ Read {len(source_code)} chars of source code")

    # Step 5: Build prompt
    template_path = Path(__file__).parent / "prompts" / "prompt_template.txt"
    prompt = build_prompt(template_path, reference_level, analyzer_result, source_code)
    log(f"✓ Built prompt ({len(prompt)} chars)")

    # Step 6: Return prompt for Claude to analyze
    # (Claude Code will handle the actual analysis call)
    log("=" * 70)
    log("PROMPT FOR CLAUDE ANALYSIS")
    log("=" * 70)
    print(prompt)
    log("=" * 70)

    # Step 7: Write artifacts for reference
    write_artifacts("", "", analyzer_result, prompt)
    log("✓ Wrote prompt to .ai_output/prompt.txt")

    return 0


if __name__ == "__main__":
    sys.exit(main())
