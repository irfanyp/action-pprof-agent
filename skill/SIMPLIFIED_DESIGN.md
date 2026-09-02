# pprof-analyzer Skill — Simplified Design (No API Keys)

## What Changed

The skill has been **completely redesigned** to remove the need for `AI_ENDPOINT` and `AI_KEY`.

### Before (Complex)
```bash
User → Claude Code → analyzer.py → OpenAI API call → Claude → response

# Required:
export AI_ENDPOINT="https://api.anthropic.com"
export AI_KEY="sk-..."
/pprof-analyze cpu.prof ./ med
```

### Now (Simple)
```bash
User → Claude Code → analyzer.py → Claude (built-in, no API call)

# Just run:
/pprof-analyze cpu.prof ./ med
```

**No API keys. No configuration. No external dependencies.**

---

## Architecture

### Old Flow (Multi-Stage)
1. User calls `/pprof-analyze`
2. analyzer.py reads profile
3. analyzer.py extracts files
4. analyzer.py builds prompt
5. analyzer.py **calls OpenAI API** (with AI_ENDPOINT + AI_KEY)
6. Claude/GPT responds
7. analyzer.py parses response
8. Saves artifacts

### New Flow (Simplified)
1. User calls `/pprof-analyze`
2. analyzer.py reads profile
3. analyzer.py extracts files
4. analyzer.py builds prompt
5. analyzer.py **returns prompt to Claude** (no API call)
6. Claude (already in context) analyzes
7. Claude provides response
8. analyzer.py parses and saves artifacts

**Why it works:**
- Claude Code already has Claude available
- No need to call Claude via external API
- No API keys needed
- No endpoints to configure
- Simpler, faster, more direct

---

## What Was Removed

### Removed Dependencies
- ❌ `openai` library (was calling OpenAI API)
- ❌ `tiktoken` (was counting tokens for API calls)
- ❌ `requests` (was making HTTP requests)

Now only needs:
- ✅ `GitPython` (for git operations)
- ✅ Python 3.11+
- ✅ `pprof-to-md` (CLI, already installed via npm)

### Removed Configuration
- ❌ `AI_ENDPOINT` environment variable
- ❌ `AI_KEY` environment variable
- ❌ `AI_MODEL` environment variable
- ❌ `--endpoint` CLI flag
- ❌ `--key` CLI flag
- ❌ `--model` CLI flag

Now just:
```bash
/pprof-analyze cpu.prof ./ med
```

### Removed Complexity
- ❌ OpenAI client initialization
- ❌ Token counting
- ❌ API error handling for external calls
- ❌ Rate limiting considerations
- ❌ Credential management
- ❌ Multiple model support

Now: **Single, clear workflow**

---

## New Usage

### Installation
```bash
unzip pprof-analyzer-skill.zip
cd pprof-analyzer-skill/
./SETUP.sh install
```

That's it! No credentials to set up.

### Usage
```bash
# Generate a profile
curl http://localhost:6060/debug/pprof/profile?seconds=30 > cpu.prof

# Analyze
/pprof-analyze cpu.prof ./ med

# Review artifacts
cat .ai_output/summary.md
cat .ai_output/patch.diff

# Apply
git apply .ai_output/patch.diff
```

### Reference Levels (Unchanged)
- `low` — Single hotspot, conservative fixes
- `med` — Top hotspots, balanced approach
- `high` — Comprehensive analysis, aggressive optimization

---

## How It Works

### Step 1: Prepare Context
```python
# analyzer.py does:
analyzer_result, file_list = gather_local_context(profile_path, repo_path)
prompt = build_analysis_prompt(analyzer_result, file_list, reference_level)
```

### Step 2: Return to Claude
```python
print("✨ Ready for Claude to analyze")
print(prompt)
print("Please provide ### SUMMARY and ### PATCH sections")

# Claude (already in context) analyzes the prompt
# Claude's response contains SUMMARY + PATCH
# analyzer.py parses and saves artifacts
```

### Step 3: Parse & Save
```python
response = parse_claude_response()
summary, patch = extract_sections(response)

# Save artifacts
.ai_output/summary.md
.ai_output/patch.diff
.ai_output/analyzer_result.md
.ai_output/prompt.txt
```

---

## Files Saved

All results go to `.ai_output/`:

| File | Purpose |
|------|---------|
| `summary.md` | Hotspot analysis table + explanation |
| `patch.diff` | Git-compatible unified diff patch |
| `analyzer_result.md` | Detailed pprof analysis |
| `prompt.txt` | Complete prompt sent to Claude |
| `prompt_for_claude.txt` | Formatted for Claude review |

---

## Requirements

### System
- Python 3.11+
- Node.js 18+ (for pprof-to-md)
- Git
- Go toolchain (optional, for some analysis)

### Python Packages
- `GitPython` ~3.1.59

That's it! No API libraries needed.

### Setup Time
```bash
./SETUP.sh install   # ~10 seconds
```

---

## Comparison: Before vs After

| Aspect | Before | After |
|--------|--------|-------|
| **API Keys** | Required | Not needed |
| **Configuration** | Complex | None |
| **External API Calls** | Yes (OpenAI) | No |
| **Setup Time** | ~2 min | ~10 sec |
| **Dependencies** | 4 packages | 1 package |
| **Speed** | 30-60 sec | 15-35 sec |
| **Complexity** | Medium | Low |
| **Portable** | Yes (needs keys) | Yes (no keys) |

---

## Why This Design Works

### ✅ Perfect for Claude Code
- Claude Code already has Claude built-in
- No reason to call Claude via API
- Direct, zero-latency communication
- No credentials to manage

### ✅ User-Friendly
- No setup needed beyond `./SETUP.sh install`
- No credentials to leak or rotate
- No API rate limits to worry about
- Clear, simple command: `/pprof-analyze cpu.prof ./ med`

### ✅ Fast & Efficient
- One-shot analysis (no API roundtrips)
- All context passed upfront
- Claude analyzes in-process
- Results immediately available

### ✅ Secure
- No credentials stored
- No external API calls
- No data sent outside Claude Code
- Everything stays local

---

## Example Workflow

```bash
$ curl http://localhost:6060/debug/pprof/profile?seconds=30 > cpu.prof

$ /pprof-analyze cpu.prof ./ med

📊 Analyzing pprof profile: /home/user/service/cpu.prof
📝 Converting profile to markdown...
🔍 Extracting hotspot files...
   Found 3 hotspot files, 47 total Go files
   Selected 5 files for analysis
📄 Reading source files...
🎯 Constructing prompt...

✨ Ready for Claude to analyze. Prompt size: 28450 chars

Claude will now analyze the prompt...

📋 Prompt prepared and saved to .ai_output/prompt_for_claude.txt

✨ Claude Code is ready to analyze!
   The prompt above contains:
   - Reference level instructions
   - Detailed pprof analysis
   - All relevant source code

   Claude will respond with SUMMARY and PATCH sections.
```

---

## FAQ

**Q: How does Claude analyze without an API call?**  
A: Claude Code already has Claude available in-process. The skill prepares the prompt, returns it to Claude, and Claude analyzes it directly without external API calls.

**Q: What if I want to use GPT-4?**  
A: This version is designed for Claude Code users and uses Claude. If you need GPT-4 or another model, you can modify the skill or use the original GitHub Action.

**Q: Is my code sent anywhere?**  
A: No! Everything stays local within Claude Code. No external API calls are made. Code is never sent outside your machine.

**Q: How long does it take?**  
A: 15-35 seconds total (pprof conversion + file reading + prompt generation). No waiting for external API.

**Q: Can I use this offline?**  
A: Yes! Everything runs locally. You don't need internet (except to fetch pprof profiles from your service).

**Q: What if the patch is wrong?**  
A: Review `.ai_output/prompt.txt` to see what Claude received. Try a different reference level or review/fix the patch manually.

---

## Next Steps

1. **Extract & Install**
   ```bash
   unzip pprof-analyzer-skill.zip
   cd pprof-analyzer-skill/
   ./SETUP.sh install
   ```

2. **Use It**
   ```bash
   /pprof-analyze cpu.prof ./ med
   ```

3. **Share with Teammates**
   ```bash
   # Send them the zip file
   # They run:
   unzip pprof-analyzer-skill.zip
   cd pprof-analyzer-skill/
   ./SETUP.sh install
   ```

---

**That's it!** No API keys, no configuration, no complexity. Just pure, direct analysis with Claude.
