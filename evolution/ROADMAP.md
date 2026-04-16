# Self-Learning Plugin Roadmap

Living document. Ordered by dependency and impact, not priority.

---

## Phase 1: Foundation (done)

What we built in the first session:

- [x] GEPA integration with `optimize_anything` API
- [x] Azure OpenAI backend (compat mode + standard)
- [x] LLM-judge fitness function (correctness/procedure/conciseness)
- [x] Golden dataset (15 hand-curated test cases)
- [x] Copilot CLI batch runner harness (real agent evaluation)
- [x] Two-tier eval: cheap inner loop + expensive holdout
- [x] Experiment tracking with batch structure

**Result:** First successful evolution run (+39.7% on holdout with gpt-5.4).
Proved the pipeline works. Identified dataset coverage as the key bottleneck.

---

## Phase 2: Session ingestion pipeline

**Problem:** Golden test cases are hand-curated. That doesn't scale and biases
what GEPA optimizes for. Real usage patterns are the best source of evaluation
data — but they're trapped in session transcripts.

**Design:**

```
daily copilot usage
  → session transcripts (already stored by the plugin)
  → ingestion pipeline extracts (task, behavior, outcome) triples
  → filters for self-learning-relevant sessions
  → appends to golden.jsonl with source: "ingested"
  → periodic GEPA runs use the expanded dataset
```

**Key decisions:**
- **What counts as a good example?** Sessions where the skill triggered AND the
  user didn't correct the behavior. Positive signal from absence of friction.
- **What counts as a bad example?** Sessions where the user explicitly overrode
  skill behavior ("no, don't store that", "I said npm not pnpm"). These become
  regression tests.
- **Dedup:** Hash task_input to avoid near-duplicates inflating the dataset.
- **Human-in-the-loop:** Flag ingested examples for optional review before they
  enter the training split. `auto_approved: false` field.

**Implementation:**
- `evolution/ingest.py` — reads session transcripts, extracts triples via LLM
- Cron or manual: `python evolve_skill.py --ingest` before evolution runs
- New golden.jsonl fields: `source` (hand-curated | ingested), `session_id`,
  `auto_approved`

---

## Phase 3: Session-end hook for auto-reflection (in progress)

**Problem:** The plugin's learning capabilities (memory storage, preference
detection, skill creation) only trigger when explicitly invoked or when the
agent happens to notice an opportunity. Most learning moments are missed because
the session ends before reflection happens.

**Design:**

A `sessionEnd` hook that runs automatically when a session ends:

```
session ends
  → stop hook fires
  → lightweight LLM pass reviews the session transcript
  → extracts:
      - facts worth remembering (→ store-memory)
      - preferences expressed (→ store-pref)
      - complex workflows that could be skills (→ flag for skill creation)
      - tool ordering patterns (→ store for future analysis)
  → stores silently, no user interruption
```

**Key decisions:**
- **Latency budget:** Must complete in <10s or users will notice the delay.
  Use gpt-4o-mini for speed — reflection doesn't need frontier reasoning.
- **Confidence threshold:** Only store memories/prefs above 0.8 confidence.
  False positives (storing wrong things) erode trust faster than false negatives
  (missing something).
- **Dedup:** Check existing memories before storing. Don't re-store "this repo
  uses pnpm" every session.
- **Opt-out:** Respect a `auto_reflect: false` preference if the user sets it.

**Implementation:**
- Hook scripts in `hooks/session-end.{sh,ps1}` — registered via `hooks.json`
- `resources/reflect.py` — takes session transcript, returns structured actions
- Reuses `evolution/llm_client.py` for OpenAI + Azure OpenAI support
- Direct SQLite reads for dedup, CLI writes via `memory_cli.py`
- Integrates with existing `memory_cli.py` commands

**Status:** `sessionEnd` hook confirmed available in Copilot CLI. Initial
implementation in `feature/session-end-reflection` branch.

---

## Phase 4: Closed-loop dataset expansion

**Problem:** GEPA optimizes what the dataset covers and drops what it doesn't.
We identified this in batch-001 (Cap 4-5 detail lost). Manual test curation
doesn't scale.

**Design (Hermes's insight):**

```
GEPA evolution
  → diff analyzer: compare baseline vs evolved
  → identify deleted/weakened sections
  → cross-reference against golden.jsonl
  → sections with no covering test case = blind spots
  → auto-generate targeted test cases for blind spots
  → re-run GEPA with expanded dataset
```

**Implementation:**
- `evolution/diff_analyzer.py` — LLM-powered section-level diff
- `evolution/test_generator.py` — generates golden test cases from uncovered
  sections
- `evolve_skill.py --auto-expand-dataset` flag
- Safety: auto-generated tests go into a `pending_review/` split, not directly
  into training

---

## Phase 5: Confidence-gated auto-deployment

**Problem:** Currently the evolved skill sits in `experiments/` and requires
manual review + merge. For the system to be truly self-improving, good
evolutions should deploy themselves.

**Design:**

```
evolution run completes
  → holdout score > threshold (e.g., +15% over baseline)
  → harness validation passes (no regressions on critical tests)
  → diff analysis confirms no unintended content loss
  → auto-deploy: copy evolved skill to ~/.copilot/skills/
  → keep baseline as rollback
  → notify user: "Skill evolved. Run 'rollback' to revert."
```

**Key decisions:**
- **Threshold:** Must be high enough that noise doesn't trigger deployment.
  With current holdout size (5 examples), +15% is within noise range. Need
  8+ holdout examples first.
- **Critical test subset:** Some golden tests are "must not regress" (e.g.,
  guard-conditions, preference-conflict). Failing any = block deployment.
- **Rollback:** `evolve_skill.py --rollback` restores the previous version.
  Keep a version chain, not just one backup.
- **Rate limit:** At most one auto-deployment per week. Don't churn.

---

## Phase 6: Multi-skill evolution

**Problem:** The evolution engine is hardcoded to the self-learning skill. Other
skills in `~/.copilot/skills/` could benefit too.

**Design:**
- Generalize `evolve_skill.py` to accept any skill path
- Dataset builder generates golden tests from skill description + usage history
- Batch evolution: `evolve_skill.py --all` evolves each skill independently

**Prerequisite:** Phases 2 + 4 (ingestion + auto-expansion). Without them,
there's no dataset for skills that weren't hand-curated.

---

## Phase 7: Skill interaction graph

**Problem:** Skills can conflict (concurrent-skills test case). As the skill
library grows, interactions become combinatorial.

**Design:**
- Build a skill interaction matrix: which skills co-trigger on the same prompts?
- Test cases that exercise skill pairs, not just individual skills
- Evolution can optimize for graceful handoff between skills

**This is speculative.** Only worth pursuing after 5+ skills exist and conflicts
are observed in practice.

---

## Open questions

1. ~~**sessionStop hook support**~~ — **Resolved.** Copilot CLI fires `sessionEnd`
   hooks on session termination. Implemented in Phase 3.
2. **GEPA inner loop with harness** — is the cost ($50-100/run) justified by
   better evolved skills? Needs an experiment (batch-002).
3. **Judge/reflector decoupling** — does using different models reduce the
   feedback-loop over-optimization? Also needs an experiment.
4. **Dataset saturation** — at what point do more golden tests stop improving
   evolution quality? Unknown until we run it.

---

## Principles

- **Honest evaluation over inflated metrics.** We'd rather know a skill didn't
  improve than falsely believe it did.
- **Human-in-the-loop by default, automation by opt-in.** Auto-reflection and
  auto-deployment are earned through demonstrated reliability.
- **Infrastructure over results.** A reusable pipeline that produces mediocre
  v1 results is more valuable than a one-off hack that produces great results.
- **Small dataset, deep analysis.** 15 well-understood test cases with honest
  failure analysis beats 1000 synthetic examples with no insight.
