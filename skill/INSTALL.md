# Installation Guide — pprof-analyzer Skills

Complete installation instructions for the four Claude Code skills.

## Prerequisites

- **Claude Code** (latest version)
- **Python 3.11+** (for the skills)
- **Git** (for repository operations)
- **npm** (for `pprof-to-md` tool)
- **Node.js 16+** (for npm)

## Quick Install (Recommended)

### Step 1: Extract the ZIP

```bash
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
```

This creates a single `pprof-analyzer-skill/` directory containing all files:

```bash
ls
# Should see: SETUP.sh, pprof-analyzer.md, pprof-integrator.md, ...
```

### Step 2: Run the Setup Script

```bash
./SETUP.sh install
```

This will:
- ✅ Create `~/.claude/skills/` directory
- ✅ Extract all skill files
- ✅ Install Python dependencies (GitPython)
- ✅ Install npm package (pprof-to-md)
- ✅ Verify installation

### Step 3: Verify Installation

```bash
./SETUP.sh verify
```

You should see:
```
[INFO] ✓ Found skill: pprof-analyzer
[INFO] ✓ Found skill: pprof-integrator
[INFO] ✓ Found skill: load-test-generator
[INFO] ✓ Found skill: profiler-executor
[INFO] ✓ All 4 skills installed and verified
```

## Manual Installation

If you prefer to install manually:

### 1. Extract the ZIP

```bash
# Extract the ZIP (creates a pprof-analyzer-skill/ directory)
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
```

### 2. Copy Skill Files to Claude Skills Directory

```bash
# Create the skills directory if it doesn't exist
mkdir -p ~/.claude/skills

# Copy skill definitions and implementations
cp *.md ~/.claude/skills/
cp -r _impl_*/ ~/.claude/skills/
cp pprof_integration.md ~/.claude/skills/_impl_pprof_integrator/

# Verify files are in place
ls ~/.claude/skills/
```

### 3. Install Python Dependencies

```bash
# Install GitPython (required for git operations)
pip3 install GitPython

# Or use the provided requirements
pip3 install -r ~/.claude/skills/_impl_pprof_analyzer/requirements.txt
```

### 4. Install npm Package

```bash
# Install pprof-to-md (required for profile conversion)
npm install -g pprof-to-md
```

### 5. Verify Installation

```bash
# Check Python module
python3 -c "import git; print('✓ GitPython installed')"

# Check npm package
pprof-to-md --version

# Check skill files
ls ~/.claude/skills/*.md
```

## Troubleshooting

### "pprof-to-md not found"

```bash
# Install via npm
npm install -g pprof-to-md

# Or verify npm installation
npm list -g pprof-to-md

# Check PATH
which pprof-to-md
```

### "GitPython not installed"

```bash
pip3 install --upgrade GitPython
```

### "Permission denied" on SETUP.sh

```bash
chmod +x SETUP.sh
./SETUP.sh install
```

### Skills not found in Claude Code

1. Verify installation completed:
   ```bash
   ./SETUP.sh verify
   ```

2. Restart Claude Code

3. Check skill directory:
   ```bash
   ls -la ~/.claude/skills/
   # Should show pprof-analyzer.md, pprof-integrator.md, etc.
   ```

## Uninstall

To remove the skills:

```bash
./SETUP.sh uninstall
```

Or manually:
```bash
rm -rf ~/.claude/skills/pprof-analyzer.md
rm -rf ~/.claude/skills/_impl_pprof_analyzer/
rm -rf ~/.claude/skills/pprof-integrator.md
rm -rf ~/.claude/skills/_impl_pprof_integrator/
rm -rf ~/.claude/skills/load-test-generator.md
rm -rf ~/.claude/skills/_impl_load_test_generator/
rm -rf ~/.claude/skills/profiler-executor.md
rm -rf ~/.claude/skills/_impl_profiler_executor/
```

## Usage After Installation

Once installed, you can use the skills in Claude Code:

### 1. Integrate pprof into Your Service

```bash
/pprof-integrator ./my-service
```

### 2. Generate Load Test

```bash
/load-test-generator ./my-service --tool k6
```

### 3. Execute Profiling

```bash
/profiler-executor ./my-service --load-cmd "k6 run load_test.js"
```

### 4. Analyze Profile

```bash
/pprof-analyzer cpu.prof ./ med
```

## System Requirements Detail

### Python 3.11+

Check version:
```bash
python3 --version
```

If not installed:
- **macOS:** `brew install python3`
- **Ubuntu/Debian:** `sudo apt-get install python3`
- **Windows:** Download from [python.org](https://www.python.org)

### Git

Check version:
```bash
git --version
```

If not installed:
- **macOS:** `brew install git`
- **Ubuntu/Debian:** `sudo apt-get install git`
- **Windows:** Download from [git-scm.com](https://git-scm.com)

### Node.js & npm

Check versions:
```bash
node --version
npm --version
```

If not installed:
- Download from [nodejs.org](https://nodejs.org)
- Installs both node and npm

## Installation Locations

After installation, skills are located at:

```
~/.claude/skills/
├── pprof-analyzer.md
├── pprof-integrator.md
├── load-test-generator.md
├── profiler-executor.md
├── _impl_pprof_analyzer/
│   ├── analyzer.py
│   ├── requirements.txt
│   ├── package.json
│   ├── prompts/
│   └── tests/
├── _impl_pprof_integrator/
├── _impl_load_test_generator/
└── _impl_profiler_executor/
```

## Support

For issues or questions:

1. Check [README.md](README.md) for usage examples
2. See [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) for technical details
3. Review [SKILL_DISTRIBUTION.md](SKILL_DISTRIBUTION.md) for sharing/distribution info
4. Check logs: `./SETUP.sh verify` shows detailed diagnostics

## Next Steps

1. ✅ Install with `./SETUP.sh install`
2. ✅ Verify with `./SETUP.sh verify`
3. ✅ Read [README.md](README.md) for usage
4. ✅ Start using skills in Claude Code!

---

**Installation complete! Happy optimizing! 🚀**
