# Installation Guide — pprof-analyzer Skills

Complete installation instructions for the four Claude Code skills.

## Prerequisites

- **Claude Code** (latest version)
- **Python 3.12+**
- **Git**
- **Node.js 22+** (for `pprof-to-md`)

## Quick Install (Recommended)

```bash
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
./SETUP.sh install     # installs skills to ~/.claude/skills/, plus GitPython + pprof-to-md
./SETUP.sh verify
```

## Manual Installation

### 1. Extract and copy skill files

```bash
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/

mkdir -p ~/.claude/skills
cp -r pprof-analyzer/ pprof-integrator/ load-test-generator/ profiler-executor/ ~/.claude/skills/

# Copy shared prompt files (read by pprof-analyzer/pprof-integrator at runtime)
mkdir -p ~/.claude/prompts
cp -r prompts/. ~/.claude/prompts/
```

### 2. Install dependencies

```bash
pip3 install -r ~/.claude/skills/pprof-analyzer/requirements.txt
npm install -g pprof-to-md
```

### 3. Verify

```bash
python3 -c "import git; print('✓ GitPython installed')"
pprof-to-md --version
ls ~/.claude/skills/    # should show pprof-analyzer/, pprof-integrator/, etc.
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `pprof-to-md not found` | `npm install -g pprof-to-md` |
| `GitPython not installed` | `pip3 install GitPython` |
| Permission denied on SETUP.sh | `chmod +x SETUP.sh && ./SETUP.sh install` |
| Skills not found in Claude Code | Run `./SETUP.sh verify`, then restart Claude Code. Check: `ls ~/.claude/skills/` should show skill directories with `SKILL.md` inside. |

## Uninstall

```bash
./SETUP.sh uninstall
```

Or manually:
```bash
rm -rf ~/.claude/skills/{pprof-analyzer,pprof-integrator,load-test-generator,profiler-executor}/
rm -rf ~/.claude/prompts/
```

## Usage After Installation

```bash
/pprof-integrator ./my-service
/load-test-generator ./my-service --tool k6
/profiler-executor ./my-service --load-cmd "k6 run load_test.js"
/pprof-analyzer cpu.prof ./ med
```

## Installation Locations

```
~/.claude/skills/
├── pprof-analyzer/          # analyzer.py, requirements.txt, SKILL.md, tests/
├── pprof-integrator/        # coordinator.py, SKILL.md
├── load-test-generator/     # coordinator.py, SKILL.md
└── profiler-executor/       # profiler.py, SKILL.md

~/.claude/prompts/
├── prompt_template.txt
└── pprof_integration.md
```

## Support

1. Check [README.md](README.md) for usage and design details.
2. Run `./SETUP.sh verify` for diagnostics.
