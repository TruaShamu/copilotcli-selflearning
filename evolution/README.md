# Skill Evolution Framework (GEPA optimize_anything)

Offline optimization framework for Copilot CLI skills.
Uses GEPA's `optimize_anything` to directly evolve SKILL.md body text
with trace-aware reflection and Pareto frontier tracking.

## Quick Start

```bash
# Install deps (one-time)
pip install gepa openai rich click

# Evolve a skill with synthetic eval data
python -m evolution.evolve_skill --skill self-learning --max-calls 100

# Use real session history from our SQLite store
python -m evolution.evolve_skill --skill self-learning --eval-source sessiondb

# Dry run — validate setup without running optimization
python -m evolution.evolve_skill --skill adr-creator --dry-run

# Resume a previous interrupted run
python -m evolution.evolve_skill --skill self-learning --resume

# Specify models
python -m evolution.evolve_skill --skill self-learning \
  --optimizer-model openai/gpt-4.1 \
  --eval-model openai/gpt-4.1-mini \
  --max-calls 200
```

## How It Works

```
SKILL.md body ──► GEPA optimize_anything
                      │
                      ├── Evaluator (LLMJudge) scores candidate skill text
                      ├── oa.log() feeds feedback as ASI to GEPA's reflector
                      ├── Reflector analyzes WHY the skill scored poorly
                      ├── Proposes targeted fixes (not random mutations)
                      └── Pareto frontier tracks diverse successful strategies
                      │
                 Constraint gates (size, growth, structure)
                      │
                      ▼
                 Evolved SKILL.md + metrics.json
```

## Eval Data Sources

| Source | Flag | Description |
|--------|------|------------|
| Synthetic | `--eval-source synthetic` | LLM reads skill, generates test cases |
| Session DB | `--eval-source sessiondb` | Mines `~/.copilot/session-store.db` via FTS5 |
| Golden | `--eval-source golden --dataset-path datasets/<skill>/` | Hand-curated JSONL |

## Skill Search Paths

1. `.github/skills/<name>/SKILL.md` (repo-level)
2. `~/.copilot/skills/<name>/SKILL.md` (user-level)

## Cost

~$5-25 per optimization run (100 metric calls, GPT-4.1 reflector + GPT-4.1-mini judge).
No GPU required — API-only.

## Architecture

- `evolve_skill.py` — CLI + orchestration, calls `optimize_anything()`
- `fitness.py` — `LLMJudge` scores skill quality, feeds feedback via `oa.log()`
- `dataset_builder.py` — Synthetic, SessionDB, and Golden eval data sources
- `constraints.py` — Size, growth, and structure validation (rejects bad candidates)
- `skill_module.py` — Utility functions: find, load, reassemble SKILL.md files
- `config.py` — All configuration in one place

## Future: Harness-based evaluation

The evaluator currently scores skill text quality via LLM-judge. The next step
is adding a harness adapter that runs Copilot CLI programmatically:

```bash
copilot -p "<prompt>" --allow-all --no-ask-user --share transcript.md -s
```

This would let GEPA reflect on actual agent execution traces, not just
simulated quality scores. See `harness/` (TODO).
