# 🚀 START HERE - PyPI Publishing Launcher

## Single Command to Start Everything

```bash
python .claude/launcher.py --all
```

That's it. This command will:
- ✅ Validate the environment
- ✅ Show the full execution plan
- ✅ Launch 4 sub-agents across 3 waves
- ✅ Coordinate checkpoints between waves
- ✅ Guide you through publishing perplexity-cli to PyPI

---

## What Happens

1. **Wave 1 (Parallel):** Agents 1 & 2 run simultaneously
   - Agent 1: Version sync + Build
   - Agent 2: PyPI metadata + README

2. **Checkpoint 1:** Verification before Wave 2

3. **Wave 2:** Agent 3 runs
   - CI/CD workflow + Documentation

4. **Checkpoint 2:** Verification before Wave 3

5. **Wave 3:** Agent 4 runs
   - Verification + Release to PyPI

6. **Complete:** Package is live on PyPI ✅

---

## Alternative Commands

```bash
# Show project information only
python .claude/launcher.py --info

# Validate environment
python .claude/launcher.py --validate

# Launch specific wave
python .claude/launcher.py --wave 1

# Launch specific agent
python .claude/launcher.py --agent 1
```

---

## Estimated Time

With parallel execution: **5.5-8 hours total**

- Wave 1 (parallel): 1.5-2 hours
- Wave 2: 2-3 hours
- Wave 3: 2-3 hours

---

## Success Looks Like

When complete, you'll see:

```
🎉 PROJECT COMPLETE ✅

Package: perplexity-cli 0.3.0
Location: https://pypi.org/project/perplexity-cli/
Installation: pip install perplexity-cli
              uvx perplexity-cli
```

---

## Ready?

```bash
python .claude/launcher.py --all
```

🚀 Let it run!
