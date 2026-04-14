# Skill Evolution Framework (DSPy + GEPA)

Offline optimization framework for Copilot CLI skills.

## Quick Start

```bash
# Install deps (one-time)
pip install dspy gepa rich click

# Evolve a skill with synthetic eval data
python -m evolution.evolve_skill --skill self-learning --iterations 10

# Use real session history from our SQLite store
python -m evolution.evolve_skill --skill self-learning --eval-source sessiondb

# Dry run — validate setup without running optimization
python -m evolution.evolve_skill --skill adr-creator --dry-run

# Specify models
python -m evolution.evolve_skill --skill self-learning \
  --optimizer-model openai/gpt-4.1 \
  --eval-model openai/gpt-4.1-mini \
  --iterations 15
```

## How It Works

```
SKILL.md ──► Dataset (synthetic / sessiondb / golden)
                │
                ▼
          GEPA Optimizer ◄── Execution traces + text feedback
                │
           Constraint gates (size, growth, structure, tests)
                │
                ▼
          Evolved SKILL.md + metrics.json
```

## Eval Data Sources

| Source | Flag | Description |
|--------|------|------------|
| Synthetic | `--eval-source synthetic` | LLM reads skill, generates test cases |
| Session DB | `--eval-source sessiondb` | Mines `~/.copilot/self-learning/memory.db` via FTS5 |
| Golden | `--eval-source golden --dataset-path datasets/<skill>/` | Hand-curated JSONL |

## Skill Search Paths

1. `.github/skills/<name>/SKILL.md` (repo-level)
2. `~/.copilot/skills/<name>/SKILL.md` (user-level)

## Cost

~$2-10 per optimization run (10 iterations, GPT-4.1 reflector).
No GPU required — API-only.
