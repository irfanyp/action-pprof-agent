# pprof-analyzer

Analyze Go pprof profiles and generate performance optimization patches using LLM-powered analysis.

**Two implementations — choose your path:**

---

## 🚀 Quick Navigation

### For Local Analysis (Claude Code)
**👉 [`skill/README.md`](skill/README.md)**

- ⚡ Zero configuration
- ⏱️ 15-35 seconds per analysis  
- 🧠 Uses Claude Code's built-in Claude
- 💻 Single-turn analysis (no agent loop)
- 📦 Easy to share with teammates

```bash
unzip pprof-analyzer-skill.zip
./SETUP.sh install
/pprof-analyze cpu.prof ./ med
```

**Best for:** Developers optimizing code locally

---

### For CI/CD Automation (GitHub Action)
**👉 [`action/README.md`](action/README.md)**

- 🤖 Automated PR creation
- 🔄 Multi-turn agent loop
- 🔌 Service-based profiling
- 🎯 Integrated in GitHub workflows
- 📊 Deep analysis capabilities

```yaml
- uses: <repo>@<version>
  with:
    token: ${{ secrets.GITHUB_TOKEN }}
    ai_endpoint: ${{ secrets.AI_ENDPOINT }}
    ai_key: ${{ secrets.AI_KEY }}
    reference: med
    tags: main
```

**Best for:** Production automation & CI/CD pipelines

---

## 📊 Skill vs. Action Comparison

| Feature | Claude Code Skill | GitHub Action |
|---------|------------------|----------------|
| **Invocation** | `/pprof-analyze` in Claude Code | Workflow trigger in GitHub |
| **Setup Time** | 10 seconds | 5 minutes |
| **Analysis Speed** | 15-35 seconds | 2-5 minutes |
| **Requires API Keys** | No | Yes |
| **PR Creation** | Manual | Automatic |
| **LLM Loop** | Single-turn | Multi-turn (agent loop) |
| **Use Case** | Interactive local analysis | Production automation |

---

## 📚 Documentation

- **[AGENTS.md](AGENTS.md)** — Developer reference (both implementations)
- **[skill/SIMPLIFIED_DESIGN.md](skill/SIMPLIFIED_DESIGN.md)** — Why we simplified the skill
- **[skill/SKILL_DISTRIBUTION.md](skill/SKILL_DISTRIBUTION.md)** — How to use & share the skill
- **[skill/IMPLEMENTATION_SUMMARY.md](skill/IMPLEMENTATION_SUMMARY.md)** — Technical details
- **[action/pprof_integration.md](action/pprof_integration.md)** — How to add pprof to your Go service

---

## 🔧 For Developers

See [AGENTS.md](AGENTS.md) for:
- Complete flow documentation (both implementations)
- Development conventions
- Contribution guidelines
- Decision philosophy

---

For detailed setup and usage, choose your implementation above.
