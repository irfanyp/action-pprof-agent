#!/bin/bash
# build-zip.sh — Regenerate the pprof-analyzer skill distribution ZIP file
#
# This script packages the Claude Code skills and supporting files into a
# distributable ZIP archive (skill/pprof-analyzer-skill.zip).
#
# Usage:
#   .claude/skills/build-zip.sh
#
# The ZIP includes:
#   - All .claude/skills/ (skill definitions and implementations)
#   - action/pprof_integration.md (integration guide)
#   - skill/*.md (distribution documentation)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZIP_PATH="$REPO_ROOT/skill/pprof-analyzer-skill.zip"

echo "Building skill ZIP: $ZIP_PATH"

cd "$REPO_ROOT"

python3 << 'PYTHON_EOF'
import zipfile
import os
from pathlib import Path

zip_path = Path('skill/pprof-analyzer-skill.zip')
root_dir = Path('.')

# Files and directories to include in the ZIP
includes = [
    '.claude/skills/',
    'action/pprof_integration.md',
    'skill/README.md',
    'skill/INSTALL.md',
    'skill/SIMPLIFIED_DESIGN.md',
    'skill/SKILL_DISTRIBUTION.md',
    'skill/IMPLEMENTATION_SUMMARY.md',
]

# Create/update the ZIP
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for include in includes:
        path = root_dir / include
        if path.is_dir():
            for root, dirs, files in os.walk(path):
                # Skip unwanted directories
                dirs[:] = [d for d in dirs if d not in {'__pycache__', '.git', '.pytest_cache'}]
                for file in files:
                    if not file.startswith('.'):
                        file_path = Path(root) / file
                        arcname = str(file_path.relative_to(root_dir))
                        zf.write(file_path, arcname)
        else:
            if path.exists():
                arcname = str(path.relative_to(root_dir))
                zf.write(path, arcname)

# Report results
file_size_kb = zip_path.stat().st_size / 1024
file_count = len(zf.namelist())

print(f"✓ Created {zip_path} ({file_size_kb:.1f} KB, {file_count} files)")

PYTHON_EOF

echo "Done!"
