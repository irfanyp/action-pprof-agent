#!/bin/bash
# build-zip.sh — Regenerate the pprof-analyzer skill distribution ZIP file
#
# This script packages the Claude Code skills and supporting files into a
# distributable ZIP archive (skill/pprof-analyzer-skill.zip).
#
# The ZIP extracts into a single flat directory: pprof-analyzer-skill/
# Users then run:
#   unzip pprof-analyzer-skill.zip
#   cd pprof-analyzer-skill/
#   ./SETUP.sh install
#
# Usage:
#   skill/build-zip.sh
#
# The ZIP includes (all under pprof-analyzer-skill/ prefix):
#   - SETUP.sh                          (installation helper, at root of zip)
#   - <skill-name>/SKILL.md + impl files (one directory per skill, Claude Code's
#                                          expected <skills-dir>/<name>/SKILL.md layout)
#   - skill/*.md                         (distribution documentation)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ZIP_PATH="$REPO_ROOT/skill/pprof-analyzer-skill.zip"

echo "Building skill ZIP: $ZIP_PATH"

cd "$REPO_ROOT"

# Sync prompt template from action (single source of truth)
echo "Syncing prompt template from action/scripts/ ..."
mkdir -p skill/pprof_analyzer/prompts
cp action/scripts/prompts/prompt_template.txt \
   skill/pprof_analyzer/prompts/prompt_template.txt

python3 << 'PYTHON_EOF'
import zipfile
import os
from pathlib import Path

zip_path = Path('skill/pprof-analyzer-skill.zip')
root_dir = Path('.')
prefix = 'pprof-analyzer-skill'  # All files go under this top-level dir in the ZIP

# Mapping of source paths to destination (relative to prefix)
# Format: (source_path, dest_path_inside_prefix)
file_map = [
    # Setup script — at the root of the zip
    ('skill/SETUP.sh', 'SETUP.sh'),
    # Distribution docs
    ('skill/README.md', 'README.md'),
    ('skill/INSTALL.md', 'INSTALL.md'),
    ('skill/SIMPLIFIED_DESIGN.md', 'SIMPLIFIED_DESIGN.md'),
    ('skill/SKILL_DISTRIBUTION.md', 'SKILL_DISTRIBUTION.md'),
    ('skill/IMPLEMENTATION_SUMMARY.md', 'IMPLEMENTATION_SUMMARY.md'),
]

# Skill directories to include (each becomes <prefix>/<skill-name>/ containing
# SKILL.md alongside its implementation files — matches the <skill-dir>/<name>/SKILL.md
# layout Claude Code expects, so `cp -r <skill-name> ~/.claude/skills/` just works)
# Note: local directories use underscores (pprof_analyzer), but ZIP uses hyphens (pprof-analyzer)
# to maintain compatibility with existing skill distribution format
dir_map = [
    ('skill/pprof_analyzer', 'pprof-analyzer'),
    ('skill/pprof_integrator', 'pprof-integrator'),
    ('skill/load_test_generator', 'load-test-generator'),
    ('skill/profiler_executor', 'profiler-executor'),
]

# Skip these files/dirs when walking implementation directories
skip_dirs = {'__pycache__', '.git', '.pytest_cache'}
skip_files_starting_with = ('.',)

# Create the ZIP
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    # Add individual files
    for src, dest in file_map:
        src_path = root_dir / src
        if src_path.exists() and src_path.is_file():
            arcname = f'{prefix}/{dest}'
            zf.write(src_path, arcname)
        else:
            print(f"  WARNING: Source file not found, skipping: {src}")

    # Add implementation directories
    for src_dir, dest_dir in dir_map:
        src_path = root_dir / src_dir
        if not src_path.exists() or not src_path.is_dir():
            print(f"  WARNING: Source dir not found, skipping: {src_dir}")
            continue
        for walk_root, dirs, files in os.walk(src_path):
            # Filter out unwanted directories in-place
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for file in files:
                if any(file.startswith(p) for p in skip_files_starting_with):
                    continue
                file_path = Path(walk_root) / file
                rel_to_src = file_path.relative_to(src_path)
                arcname = f'{prefix}/{dest_dir}/{rel_to_src}'
                zf.write(file_path, arcname)

# Report results
file_size_kb = zip_path.stat().st_size / 1024
file_count = len(zipfile.ZipFile(zip_path, 'r').namelist())

print(f"✓ Created {zip_path} ({file_size_kb:.1f} KB, {file_count} files)")
print(f"  Structure: all files under '{prefix}/' prefix")

PYTHON_EOF

echo "Done!"
