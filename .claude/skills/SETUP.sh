#!/bin/bash
# Setup script for pprof-analyzer skills
# Installs Claude Code skills and dependencies

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_INSTALL_DIR="${HOME}/.claude/skills"
ZIP_FILE="${SCRIPT_DIR}/pprof-analyzer-skill.zip"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_usage() {
    cat << EOF
Usage: $0 <command>

Commands:
  install    Install skills to ~/.claude/skills/
  uninstall  Remove installed skills
  verify     Verify installation
  help       Show this help message

Examples:
  $0 install
  $0 verify
  $0 uninstall

EOF
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required but not installed"
        return 1
    fi
    log_info "✓ Python 3 found: $(python3 --version)"

    # Check pip
    if ! command -v pip3 &> /dev/null; then
        log_error "pip3 is required but not installed"
        return 1
    fi
    log_info "✓ pip3 found"

    # Check git
    if ! command -v git &> /dev/null; then
        log_error "git is required but not installed"
        return 1
    fi
    log_info "✓ git found"

    # Check unzip
    if ! command -v unzip &> /dev/null; then
        log_warn "unzip not found, will try Python zipfile module"
    else
        log_info "✓ unzip found"
    fi

    return 0
}

install_skills() {
    log_info "Installing pprof-analyzer skills..."

    # Check if zip file exists
    if [ ! -f "$ZIP_FILE" ]; then
        log_error "ZIP file not found: $ZIP_FILE"
        return 1
    fi

    # Create skills directory if it doesn't exist
    mkdir -p "$SKILLS_INSTALL_DIR"
    log_info "✓ Created/verified skills directory: $SKILLS_INSTALL_DIR"

    # Extract ZIP file
    log_info "Extracting skills from ZIP..."
    if command -v unzip &> /dev/null; then
        unzip -q -o "$ZIP_FILE" -d "$SKILLS_INSTALL_DIR"
    else
        python3 << 'PYTHON_EOF'
import zipfile
import sys
from pathlib import Path

zip_path = sys.argv[1]
extract_dir = sys.argv[2]

try:
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(extract_dir)
    print(f"Extracted to {extract_dir}")
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_EOF
        python3 -c "
import zipfile
from pathlib import Path
with zipfile.ZipFile('$ZIP_FILE', 'r') as zf:
    zf.extractall('$SKILLS_INSTALL_DIR')
"
    fi
    log_info "✓ Skills extracted to $SKILLS_INSTALL_DIR"

    # Install Python dependencies
    log_info "Installing Python dependencies..."

    # Install pprof-analyzer skill dependencies
    if [ -f "$SKILLS_INSTALL_DIR/_impl_pprof_analyzer/requirements.txt" ]; then
        pip3 install -q -r "$SKILLS_INSTALL_DIR/_impl_pprof_analyzer/requirements.txt" 2>/dev/null || true
        log_info "✓ Installed pprof-analyzer dependencies"
    fi

    # Install other skills (minimal dependencies)
    for skill_dir in "$SKILLS_INSTALL_DIR"/_impl_*/; do
        if [ -f "$skill_dir/requirements.txt" ]; then
            skill_name=$(basename "$skill_dir")
            pip3 install -q -r "$skill_dir/requirements.txt" 2>/dev/null || true
        fi
    done
    log_info "✓ Installed skill dependencies"

    # Install npm dependencies for pprof-to-md
    if command -v npm &> /dev/null; then
        if [ -f "$SKILLS_INSTALL_DIR/_impl_pprof_analyzer/package.json" ]; then
            log_info "Installing npm dependencies (pprof-to-md)..."
            npm install -g pprof-to-md > /dev/null 2>&1 || {
                log_warn "Failed to install pprof-to-md globally"
                log_warn "Try: npm install -g pprof-to-md"
            }
        fi
    else
        log_warn "npm not found - cannot install pprof-to-md"
        log_warn "Install Node.js or run: npm install -g pprof-to-md"
    fi

    log_info "✓ Skills installed successfully to $SKILLS_INSTALL_DIR"
    return 0
}

uninstall_skills() {
    log_info "Uninstalling pprof-analyzer skills..."

    if [ ! -d "$SKILLS_INSTALL_DIR" ]; then
        log_warn "Skills directory not found: $SKILLS_INSTALL_DIR"
        return 0
    fi

    # Remove skill definition files
    for skill in pprof-analyzer pprof-integrator load-test-generator profiler-executor; do
        rm -f "$SKILLS_INSTALL_DIR/${skill}.md"
    done

    # Remove implementation directories
    rm -rf "$SKILLS_INSTALL_DIR/_impl_pprof_analyzer"
    rm -rf "$SKILLS_INSTALL_DIR/_impl_pprof_integrator"
    rm -rf "$SKILLS_INSTALL_DIR/_impl_load_test_generator"
    rm -rf "$SKILLS_INSTALL_DIR/_impl_profiler_executor"

    log_info "✓ Skills uninstalled from $SKILLS_INSTALL_DIR"
    return 0
}

verify_installation() {
    log_info "Verifying pprof-analyzer skills installation..."

    if [ ! -d "$SKILLS_INSTALL_DIR" ]; then
        log_error "Skills directory not found: $SKILLS_INSTALL_DIR"
        return 1
    fi

    # Check skill definitions
    local skill_count=0
    for skill in pprof-analyzer pprof-integrator load-test-generator profiler-executor; do
        if [ -f "$SKILLS_INSTALL_DIR/${skill}.md" ]; then
            log_info "✓ Found skill: ${skill}"
            skill_count=$((skill_count + 1))
        else
            log_warn "Missing skill: ${skill}"
        fi
    done

    # Check implementations
    local impl_count=0
    for impl in _impl_pprof_analyzer _impl_pprof_integrator _impl_load_test_generator _impl_profiler_executor; do
        if [ -d "$SKILLS_INSTALL_DIR/$impl" ]; then
            log_info "✓ Found implementation: ${impl}"
            impl_count=$((impl_count + 1))
        else
            log_warn "Missing implementation: ${impl}"
        fi
    done

    # Check Python dependencies
    python3 -c "import git" 2>/dev/null && {
        log_info "✓ GitPython installed"
    } || {
        log_warn "GitPython not installed (required for analyzer)"
    }

    # Check pprof-to-md
    if command -v pprof-to-md &> /dev/null; then
        log_info "✓ pprof-to-md installed: $(pprof-to-md --version 2>/dev/null || echo 'version unknown')"
    else
        log_warn "pprof-to-md not installed (required for analyzer)"
        log_warn "Install with: npm install -g pprof-to-md"
    fi

    if [ $skill_count -eq 4 ] && [ $impl_count -eq 4 ]; then
        log_info "✓ All 4 skills installed and verified"
        return 0
    else
        log_error "Installation incomplete (found $skill_count skills, $impl_count implementations)"
        return 1
    fi
}

# Main
main() {
    local command="${1:-help}"

    case "$command" in
        install)
            check_prerequisites || exit 1
            install_skills || exit 1
            log_info ""
            log_info "Installation complete! ✅"
            log_info ""
            log_info "Next steps:"
            log_info "1. Verify installation: $0 verify"
            log_info "2. Use skills in Claude Code:"
            log_info "   - /pprof-integrator <repo_path>"
            log_info "   - /load-test-generator <repo_path>"
            log_info "   - /profiler-executor <repo_path>"
            log_info "   - /pprof-analyzer <profile> <repo> <level>"
            log_info ""
            ;;
        uninstall)
            uninstall_skills
            log_info "Uninstall complete"
            ;;
        verify)
            verify_installation
            ;;
        help)
            show_usage
            ;;
        *)
            log_error "Unknown command: $command"
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
