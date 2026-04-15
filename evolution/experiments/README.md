# Evolution Experiments

Tracked experiments for GEPA skill evolution on the self-learning plugin.

## Structure

```
experiments/
├── batch-NNN_description/
│   ├── analysis.md                          # per-batch writeup
│   ├── YYYY-MM-DD_exp-NNN_model-desc/       # individual runs
│   │   ├── baseline_skill.md
│   │   ├── evolved_skill.md
│   │   ├── metrics.json
│   │   └── (optional) run_log.txt, candidate_tree.html
```

Each **batch** groups related experiments with a single analysis. Experiments
within a batch share a hypothesis or theme.

## Batches

| Batch | Theme | Experiments | Key finding |
|---|---|---|---|
| 001 | Baseline exploration | 3 runs | Model quality is #1 lever; gpt-5.4 achieved +39.7% but lost Cap 4-5 detail due to dataset coverage gaps |

## Convention

- Batch dirs: `batch-NNN_slug`
- Experiment dirs: `YYYY-MM-DD_exp-NNN_model-description`
- One `analysis.md` per batch (not per experiment)
- Artifacts checked in: baseline, evolved, metrics, GEPA logs when interesting
