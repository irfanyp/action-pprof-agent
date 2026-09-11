#!/usr/bin/env python3
"""Bump the project version across all version-tracking files.

Rewrites exactly 5 fields across 4 files:
  - VERSION (root)                          — the single source of truth for the
                                              Python side (read dynamically by
                                              pyproject.toml and mcp_server_http.py)
  - action/package.json                     — "version" field
  - skill/pprof_analyzer/package.json        — "version" field
  - action/package-lock.json                — the two root-level "version" fields
                                              (top-of-file package + packages[""])

Deliberately does NOT touch git — committing, tagging, and pushing remain
manual, reviewable follow-up steps (see AGENTS.md "Release flow").

Usage:
    .venv/bin/python scripts/bump_version.py 0.1.1
    .venv/bin/python scripts/bump_version.py v0.1.1   # leading 'v' is stripped
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_FILE = REPO_ROOT / "VERSION"
ACTION_PACKAGE_JSON = REPO_ROOT / "action" / "package.json"
SKILL_PACKAGE_JSON = REPO_ROOT / "skill" / "pprof_analyzer" / "package.json"
ACTION_PACKAGE_LOCK = REPO_ROOT / "action" / "package-lock.json"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def bump_version_file(version: str) -> None:
    """Overwrite VERSION with the new version string."""
    VERSION_FILE.write_text(f"{version}\n")
    print(f"  VERSION -> {version}")


def bump_json_file(path: Path, version: str, expected_matches: int) -> None:
    """Replace the top-level "version" fields in a package manifest.

    Uses a precise regex anchored on the "version" key rather than blind
    find/replace, so a version number that happens to appear elsewhere (e.g.
    a dependency pin like "pprof-to-md": "^0.2.0") is never touched. Aborts
    loudly if the match count differs from what's expected, rather than
    silently corrupting the file or silently doing nothing.
    """
    text = path.read_text()
    pattern = re.compile(r'("version"\s*:\s*")[^"]+(")')
    # No count limit on subn: an unbounded count is what makes the exact-match
    # assertion below meaningful (it catches extra "version" fields too).
    new_text, count = pattern.subn(rf"\g<1>{version}\g<2>", text)
    if count != expected_matches:
        fail(
            f"{path.relative_to(REPO_ROOT)}: expected {expected_matches} "
            f'"version" field(s) to replace, found {count} — file format has '
            "drifted from what this script expects; aborting without writing."
        )
    path.write_text(new_text)
    print(f"  {path.relative_to(REPO_ROOT)} -> {version} ({expected_matches} field(s))")


def bump_package_lock(version: str) -> None:
    """Replace only the two root-level "version" fields in package-lock.json.

    The lockfile also contains "version" entries for every dependency under
    "node_modules/..." (e.g. pprof-to-md 0.2.0) which must never be touched.
    Splitting the file at the first "node_modules" marker and rewriting only
    the head guarantees the dependency entries are left alone.
    """
    text = ACTION_PACKAGE_LOCK.read_text()
    marker = '"node_modules'
    split_at = text.find(marker)
    if split_at == -1:
        fail(
            f"{ACTION_PACKAGE_LOCK.relative_to(REPO_ROOT)}: no "
            f'{marker}..." marker found — file format has drifted from what '
            "this script expects; aborting without writing."
        )
    head, tail = text[:split_at], text[split_at:]

    pattern = re.compile(r'("version"\s*:\s*")[^"]+(")')
    new_head, count = pattern.subn(rf"\g<1>{version}\g<2>", head)
    if count != 2:
        fail(
            f"{ACTION_PACKAGE_LOCK.relative_to(REPO_ROOT)}: expected 2 root-level "
            f'"version" fields before the first node_modules entry, found {count} — '
            "file format has drifted from what this script expects; aborting "
            "without writing."
        )
    ACTION_PACKAGE_LOCK.write_text(new_head + tail)
    print(f"  {ACTION_PACKAGE_LOCK.relative_to(REPO_ROOT)} -> {version} (2 root-level fields)")


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: scripts/bump_version.py <version>  (e.g. scripts/bump_version.py 0.1.1)")

    version = sys.argv[1].lstrip("v")
    if not SEMVER_RE.match(version):
        fail(f"'{sys.argv[1]}' is not a valid version string (expected X.Y.Z, e.g. 0.1.1)")

    print(f"Bumping project version to {version}:\n")
    bump_version_file(version)
    bump_json_file(ACTION_PACKAGE_JSON, version, expected_matches=1)
    bump_json_file(SKILL_PACKAGE_JSON, version, expected_matches=1)
    bump_package_lock(version)

    print(
        f"\nDone. pyproject.toml and mcp_server_http.py read VERSION dynamically and\n"
        "need no edits.\n"
        "\nManual next steps (this script does not touch git):\n"
        "  1. Review the diff:            git diff\n"
        f"  2. Commit:                    git add VERSION action/package.json \\\n"
        "                                   action/package-lock.json \\\n"
        "                                   skill/pprof_analyzer/package.json\n"
        f"  3. Tag:                       git tag -a v{version} -m \"v{version}\"\n"
        "  4. Push:                      git push && git push --tags\n"
        "     (pushing the tag triggers .github/workflows/release.yml, which\n"
        "      builds the skill zip and publishes a GitHub Release)"
    )


if __name__ == "__main__":
    main()
