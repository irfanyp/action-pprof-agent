#!/bin/bash
# Setup script for pprof-analyzer skills
# Installs Claude Code skills and dependencies from the extracted skill package.
#
# This script lives inside the extracted pprof-analyzer-skill/ directory and
# copies the skill files (definitions + implementations) to ~/.claude/skills/.
# It does NOT depend on a ZIP file — all source files are alongside it.
#
# Usage (from inside the extracted pprof-analyzer-skill/ directory):
#   ./SETUP.sh install
#   ./SETUP.sh verify
#   ./SETUP.sh uninstall

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_INSTALL_DIR="${HOME}/.claude/skills"

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

    return 0
}

install_skills() {
    log_info "Installing pprof-analyzer skills..."

    # Verify the source skill files exist alongside this script
    local skill_md_count=0
    for skill in pprof-analyzer pprof-integrator load-test-generator profiler-executor; do
        if [ -f "$SCRIPT_DIR/${skill}.md" ]; then
            skill_md_count=$((skill_md_count + 1))
        fi
    done
    if [ $skill_md_count -lt 1 ]; then
        log_error "No skill definition files (*.md) found in: $SCRIPT_DIR"
        log_error "Make sure you are running this script from inside the extracted pprof-analyzer-skill/ directory."
        return 1
    fi

    # Create skills directory if it doesn't exist
    mkdir -p "$SKILLS_INSTALL_DIR"
    log_info "✓ Created/verified skills directory: $SKILLS_INSTALL_DIR"

    # Copy skill definition files
    log_info "Copying skill definitions..."
    for skill in pprof-analyzer pprof-integrator load-test-generator profiler-executor; do
        if [ -f "$SCRIPT_DIR/${skill}.md" ]; then
            cp "$SCRIPT_DIR/${skill}.md" "$SKILLS_INSTALL_DIR/"
            log_info "  ✓ ${skill}.md"
        fi
    done

    # Copy implementation directories
    log_info "Copying skill implementations..."
    for impl in _impl_pprof_analyzer _impl_pprof_integrator _impl_load_test_generator _impl_profiler_executor; do
        if [ -d "$SCRIPT_DIR/$impl" ]; then
            rm -rf "$SKILLS_INSTALL_DIR/$impl"
            cp -r "$SCRIPT_DIR/$impl" "$SKILLS_INSTALL_DIR/"
            log_info "  ✓ ${impl}/"
        fi
    done

    # Copy pprof_integration.md (referenced by pprof-integrator skill)
    if [ -f "$SCRIPT_DIR/pprof_integration.md" ]; then
        mkdir -p "$SKILLS_INSTALL_DIR/_impl_pprof_integrator"
        cp "$SCRIPT_DIR/pprof_integration.md" "$SKILLS_INSTALL_DIR/_impl_pprof_integrator/"
        log_info "  ✓ pprof_integration.md"
    fi

    log_info "✓ All skill files copied to $SKILLS_INSTALL_DIR"

    # Install Python dependencies
    log_info "Installing Python dependencies..."

    for skill_dir in "$SKILLS_INSTALL_DIR"/_impl_*/; do
        if [ -f "$skill_dir/requirements.txt" ]; then
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
