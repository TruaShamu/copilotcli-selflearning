# Evaluation Protocol

How to test whether the self-learning system actually works.

For system internals, see [ARCHITECTURE.md](ARCHITECTURE.md).
For user setup, see [README.md](README.md).

---

## Overview

The core claim is: **Copilot CLI gets measurably better at your workflows over
time when using self-learning.** Proving that requires four experiments, each
targeting a different subsystem.

| Experiment | Tests | Minimum for workshop paper |
|------------|-------|---------------------------|
| [1. Before/After Task Performance](#1-beforeafter-task-performance) | End-to-end system value | ✅ Required |
| [2. Skill Evolution Quality](#2-skill-evolution-quality) | DSPy+GEPA optimizer | Nice to have |
| [3. N-gram Mining Precision](#3-n-gram-mining-precision) | Tool sequence analysis | ✅ Required (most novel) |
| [4. Memory Relevance](#4-memory-relevance) | Preference/memory retrieval | Nice to have |

**Target scale for a workshop/demo paper:** 5–10 tasks, 30–50 sessions, 3–5
skills evolved. A main conference paper would need 20+ tasks, 100+ sessions,
and comparison against at least one baseline.

---

## 1. Before/After Task Performance

> Does the self-learning system make Copilot measurably better over time?

### Setup

1. Define **10 realistic tasks** spanning different workflows:
   - Bug fix from issue description
   - Add a feature with tests
   - Refactor + update docs
   - Debug a failing CI pipeline
   - Set up a new project from scratch
   - Write a migration script
   - Review and improve existing code
   - Create an API endpoint end-to-end
   - Write integration tests for existing code
   - Optimize a slow database query

2. Create a **fresh repo** (or use a template) for each task with the problem
   already set up (failing test, slow query, etc.).

### Protocol

```
Phase A — Baseline (no self-learning)
──────────────────────────────────────
1. Uninstall hooks: python uninstall-hooks.py
2. Delete or rename ~/.copilot/self-learning/memory.db
3. Run each task with vanilla Copilot CLI
4. Record metrics (see below)

Phase B — Cold start (self-learning enabled, empty memory)
──────────────────────────────────────────────────────────
1. Install hooks: bash install-hooks.sh
2. Start with fresh memory.db
3. Run the SAME 10 tasks in order
4. Record metrics after each task

Phase C — Warm system (after 30+ sessions)
──────────────────────────────────────────
1. Use the memory.db from Phase B (now populated)
2. Run the same 10 tasks again
3. Record metrics — this is the "learned" condition
```

### Metrics

Collect per-task:

| Metric | How to measure | Why it matters |
|--------|---------------|----------------|
| **Tool calls** | `python memory_cli.py stats` → `tool_usage_entries` per session | Fewer calls = more efficient |
| **Turns to completion** | Count `session_turns` for the session | Fewer turns = less back-and-forth |
| **Task success** | Manual binary: did Copilot complete the task? (1/0) | Core correctness |
| **Error rate** | Count tool calls with `success=0` in `tool_usage` | Fewer errors = learned from mistakes |
| **Wall-clock time** | `sessions.ended_at - sessions.started_at` | Real-world speed |
| **Preference hits** | Count prefs loaded by `sessionStart` hook | System is actually using memory |

### Analysis

```bash
# Export per-session metrics
python resources/memory_cli.py stats

# Tool efficiency over time
python resources/memory_cli.py query-tool-sequences --patterns --window-size 3

# Compare Phase A vs Phase C
# (you'll need to save stats snapshots between phases)
```

**Expected result:** Phase C should show fewer tool calls, fewer errors, and
faster completion than Phase A. Phase B should be roughly equal to Phase A
(cold start hasn't learned yet) but should improve across the 10 tasks.

---

## 2. Skill Evolution Quality

> Does DSPy+GEPA actually improve skills over N optimization rounds?

### Setup

Pick 3–5 skills to evolve. Good candidates:
- `self-learning` (this project's own skill — meta!)
- A code review skill
- A testing workflow skill
- A documentation skill
- A debugging skill

### Protocol

```bash
# 1. Create eval data (synthetic or from session history)
python -m evolution.dataset_builder --skill <name> --source synthetic --count 50
# or
python -m evolution.dataset_builder --skill <name> --source sessiondb --count 50

# 2. Run evolution, saving metrics at each round
python -m evolution.evolve_skill --skill <name> \
    --iterations 10 \
    --eval-source synthetic

# 3. Repeat with golden (hand-curated) eval data if available
python -m evolution.evolve_skill --skill <name> \
    --eval-source golden
```

### Metrics

| Metric | Source | Per round |
|--------|--------|-----------|
| **Fitness score** | `evolution/metrics.json` | Should trend upward |
| **Skill size** | `wc -c` on SKILL.md | Should stay within constraint bounds |
| **Holdout score** | Run evolved skill on held-out eval set | Generalization check |

### Analysis

Plot fitness score vs. optimization round for each skill. Expected: monotonic
improvement with diminishing returns after round 5–8.

Compare round-0 skill (original) vs round-N skill (evolved) on the holdout set.
The delta is your improvement signal.

### Pitfalls

- **Overfitting to synthetic data**: If synthetic-trained skills score high on
  synthetic eval but low on golden eval, the generator and evaluator are
  colluding. Use different models for generation vs. evaluation.
- **Fitness metric gaming**: Bag-of-words overlap can be cheated by verbose
  skills. Check that evolved skills aren't just getting longer. The constraint
  gates in `evolution/constraints.py` should catch this.

---

## 3. N-gram Mining Precision

> Do the tool sequence patterns actually identify real reusable workflows?

This is the **most novel contribution** and the strongest angle for a paper.
No existing Copilot CLI tool does automated workflow discovery from tool traces.

### Setup

Collect tool usage data from **50+ real sessions** across multiple repos.
The `postToolUse` hook logs every tool call automatically.

### Protocol

```bash
# 1. After 50+ sessions, extract patterns
python resources/memory_cli.py query-tool-sequences \
    --patterns \
    --window-size 3 \
    --limit 50

# 2. Also try window sizes 2, 4, 5 for comparison
python resources/memory_cli.py query-tool-sequences --patterns --window-size 2
python resources/memory_cli.py query-tool-sequences --patterns --window-size 4
python resources/memory_cli.py query-tool-sequences --patterns --window-size 5

# 3. Export results for labeling
# (pipe to JSON, add to a spreadsheet)
```

### Labeling

For each discovered pattern (top-K by frequency), a human labels:

| Pattern | Frequency | Useful workflow? | Notes |
|---------|-----------|-----------------|-------|
| `grep → read_file → edit` | 14 sessions | ✅ Yes | Find-and-fix pattern |
| `read_file → read_file → read_file` | 23 sessions | ❌ No | Just browsing |
| `bash → grep → edit → bash` | 8 sessions | ✅ Yes | Test-driven fix |
| `edit → bash → edit` | 11 sessions | ✅ Yes | Edit-run-fix cycle |

### Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| **Precision@K** | (useful patterns in top K) / K | > 50% for K=10 |
| **Cross-session frequency** | Patterns appearing in 2+ sessions | Higher = more generalizable |
| **Window size sensitivity** | Precision@10 per window size | Find optimal N |

### Analysis

Report a **precision-recall curve** across window sizes. Smaller windows (2)
will have higher recall but lower precision (more noise). Larger windows (4–5)
will have higher precision but miss shorter patterns.

**Expected result:** Window size 3 is the sweet spot. Precision@10 should be
>50% (more than half of the top patterns are real workflows).

### Stretch: Automated skill generation from patterns

If a pattern has high frequency AND is labeled as a useful workflow, test
whether the system can auto-generate a skill from it:

```bash
python resources/memory_cli.py query-learnings --candidates-only
```

Compare auto-generated skills against hand-written ones for the same workflow.

---

## 4. Memory Relevance

> Are stored preferences and memories actually useful when retrieved?

### Setup

After 30+ sessions, dump the full memory state.

### Protocol

```bash
# 1. Export all active preferences
python resources/memory_cli.py query-prefs

# 2. Export all memories
python resources/memory_cli.py query-memory

# 3. For each of the next 10 sessions, record:
#    a. What prefs were loaded by sessionStart hook
#    b. Whether those prefs were relevant to the task
#    c. Whether any stored memory would have been useful but wasn't loaded
```

### Labeling

For each preference/memory, label:

| Fact | Still accurate? | Used in session? | Would have helped? |
|------|----------------|------------------|--------------------|
| "User prefers tabs over spaces" | ✅ | ✅ (code task) | Yes |
| "Project X uses PostgreSQL" | ✅ | ❌ (wrong project) | No |
| "Build command is `make test`" | ❌ (changed) | ❌ | Harmful if used |

### Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| **Accuracy** | (still-accurate facts) / (total facts) | > 80% |
| **Relevance** | (useful-in-session facts) / (loaded facts) | > 60% |
| **Staleness rate** | (outdated facts) / (total facts) | < 15% |
| **Supersede chain health** | (properly superseded) / (changed facts) | > 90% |

The `superseded_by` chain in the `preferences` table should catch most staleness.
If the staleness rate is high, the supersede mechanism isn't triggering often enough.

---

## Running the Full Eval

### Prerequisites

```bash
pip install -r requirements.txt
# For evolution experiments:
pip install dspy gepa rich click
```

### Recommended order

1. **N-gram mining first** (Experiment 3) — only needs existing session data,
   no new sessions required. Quick win, strongest paper angle.
2. **Before/after** (Experiment 1) — most effort but most convincing result.
3. **Evolution** (Experiment 2) — can run in parallel with Experiment 1.
4. **Memory relevance** (Experiment 4) — piggyback on sessions from Experiment 1.

### Data hygiene

- **Separate repos per task** in Experiment 1 to avoid cross-contamination
- **Seed the RNG** in evolution experiments for reproducibility
- **Save memory.db snapshots** between phases: `cp memory.db memory-phase-A.db`
- **Record Copilot CLI version** — hook behavior may change between versions

### Output artifacts

After running the full eval, you should have:

```
eval/
├── phase-a-baseline/          # Experiment 1: vanilla metrics
│   └── stats-per-task.json
├── phase-b-cold/              # Experiment 1: cold start metrics
│   └── stats-per-task.json
├── phase-c-warm/              # Experiment 1: learned metrics
│   └── stats-per-task.json
├── evolution/                 # Experiment 2: per-skill metrics
│   ├── self-learning/
│   │   └── metrics.json
│   └── code-review/
│       └── metrics.json
├── ngram-analysis/            # Experiment 3: pattern mining
│   ├── patterns-w2.json
│   ├── patterns-w3.json
│   ├── patterns-w4.json
│   └── labels.csv            # Human labels
├── memory-audit/              # Experiment 4: relevance labels
│   └── relevance-labels.csv
└── memory-snapshots/          # DB snapshots between phases
    ├── memory-phase-a.db
    ├── memory-phase-b.db
    └── memory-phase-c.db
```

---

## Paper Framing

**Workshop/demo paper (4–6 pages):**
- Title: "Self-Learning CLI Agents: Automated Workflow Discovery from Tool Traces"
- Focus on Experiment 3 (n-gram mining) + Experiment 1 (before/after)
- Position: tool/demo paper at an SE or AI agents workshop

**Full conference paper (8–10 pages):**
- All four experiments
- Comparison baseline: vanilla Copilot CLI + static skills (no evolution)
- Second baseline: Copilot CLI + hand-written skills (human ceiling)
- Venues: ICSE (tool track), FSE (ideas track), NeurIPS (agents workshop),
  EMNLP (tool-augmented LLMs)

---

## Revision History

- 2026-04-14: Initial evaluation protocol — four experiments, metrics, analysis plan
