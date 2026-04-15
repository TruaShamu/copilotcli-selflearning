# Experiment Log: GEPA Skill Evolution

## Experiment 001 — gpt-4o-mini baseline (synthetic data)

**Date:** 2026-04-14
**Model:** espresso-gpt-4o-mini (Azure, both judge + reflector)
**Dataset:** 18 synthetic test cases
**Max metric calls:** 30
**Harness:** No (LLM-judge only, `agent_output=""`)

### Results

| Metric | Value |
|---|---|
| Baseline score | 0.412 |
| Evolved score | 0.412 |
| Improvement | 0.0% |
| Evolved = baseline? | **Yes (identical text)** |
| Elapsed | 254.7s (first run), 6.8s (resumed) |

### Analysis

GEPA ran 47/50 rollouts but returned the seed candidate unchanged. Two root
causes:

1. **Judge noise drowns signal.** gpt-4o-mini scores the *same text* anywhere
   from 0.19 to 0.67 across runs (±0.27 variance observed). GEPA can't
   distinguish real improvements from noise, so no candidate survives the
   Pareto frontier.

2. **No agent output.** The evaluator scores skill text in isolation
   (`agent_output=""`). The judge is answering "does this skill *read* well?"
   not "does this skill *work* well?" This is a weak signal for a 17K doc
   where phrasing differences are subtle.

3. **Model too weak for reflection.** gpt-4o-mini as the reflector can't
   meaningfully critique and rewrite a 17K skill. Its proposed mutations are
   either trivial rewording or structural damage that scores worse.

### Conclusion

gpt-4o-mini is insufficient for both judge and reflector roles on a complex
skill. Need a stronger model.

---

## Experiment 002 — gpt-4o-mini with golden data

**Date:** 2026-04-14
**Model:** espresso-gpt-4o-mini (Azure, both judge + reflector)
**Dataset:** 10 golden test cases (hand-curated)
**Max metric calls:** 50
**Harness:** No

### Results

| Metric | Value |
|---|---|
| Baseline score | 0.673 |
| Evolved score | 0.407 |
| Improvement | -39.6% (regression) |
| Evolved = baseline? | **Yes (identical text)** |
| Elapsed | 525.2s |

### Analysis

GEPA again returned the seed unchanged. The holdout score *dropped* from 0.673
to 0.407 — on the same text. This is pure judge variance. With 3 holdout
examples and a noisy judge, scores are essentially random within ±0.3.

The golden test cases themselves are better quality (specific expected behaviors,
real-world categories), but the judge can't exploit that specificity at
gpt-4o-mini level.

### Key observation

**Judge variance >> any real signal.** With ±0.27 noise on 3 holdout examples,
you'd need a >0.27 improvement to be statistically detectable. That's a 40%+
gain — unlikely from prompt rewording alone. The evaluation is noise-dominated.

---

## Experiment 003 — gpt-5.4 with golden data + harness

**Date:** 2026-04-15
**Model:** gpt-5.4 (Azure Foundry, both judge + reflector)
**Dataset:** 15 golden test cases (expanded)
**Max metric calls:** 50
**Harness:** Yes (Copilot CLI, holdout only, 120s timeout)
**Split:** 7 train / 3 val / 5 holdout

### Results

| Metric | Value |
|---|---|
| Baseline score | 0.418 |
| Evolved score | **0.584** |
| **Improvement** | **+39.7%** |
| Evolved = baseline? | **No — real structural changes** |
| Baseline size | 17,491 chars |
| Evolved size | 12,820 chars (-26.7%) |
| Elapsed | 486.6s GEPA + ~554s harness holdout |
| Harness runs | 8/10 succeeded, 2 timed out (120s) |

### What GEPA changed

The evolved skill made real structural improvements:

**Added (good):**
- "Core Rules" section with explicit priority hierarchy
  - "Explicit user instructions always win" (addresses preference-conflict)
  - "Be lightweight by default" (addresses guard-conditions)
  - "Use only the local memory CLI" (addresses the session_store_sql bug)
  - "Do not store secrets, tokens, credentials"
- "Fast Decision Table" — 5-row lookup for common intents
- "Direct Recall Flow" — structured memory-first → session-fallback with
  explicit insufficiency criteria and response templates
- "Fast Paths" section for store-pref and store-memory (no review overhead)
- Revision history appended

**Removed (concerning):**
- Capability 4 (Cross-Session Recall) lost FTS5 query syntax detail, subagent
  delegation pattern, and the `explore` agent strategy
- Capability 5 (Preference Model) lost the signal types table and `preToolUse`
  hook explanation
- Skill auto-creation template lost "Learned From" metadata
- "5 capabilities" overview table removed (less context for the agent)

**Bugs:**
- Duplicate frontmatter — old `---` block followed by new `---` block
- Some markdown formatting collapsed (missing blank lines between sections)

### Analysis

**Why the score improved:**

The golden test cases are biased toward **decision-making and priority
resolution** — 6 of 15 cases test guard conditions, preference conflicts,
recall ordering, or concurrent skill handling. The evolved skill's "Core Rules"
and "Direct Recall Flow" directly address these. The judge sees clear structure
mapping to expected behaviors.

**Why detail was lost:**

The inner loop evaluator never runs the agent. It asks gpt-5.4 "does this
skill text cover the expected behavior?" For Capability 4's FTS5 detail, the
judge doesn't test whether the agent actually uses FTS5 syntax — it tests
whether the skill *mentions* it. Since the golden tests don't specifically ask
"use FTS5 prefix queries" or "delegate to explore subagent", the judge doesn't
penalize removing that detail.

**This is dataset coverage bias.** The test cases dictate what GEPA optimizes
for. Missing test cases = missing optimization pressure = lost content.

### What would fix it

1. **More golden tests for capabilities 4-5.** Add cases like:
   - "Search for sessions about deploying to AWS using prefix matching"
     (expected: use FTS5 `deploy*` syntax)
   - "I have 50 session matches — summarize them without blowing up context"
     (expected: delegate to `explore` subagent)
   - "How does the preference model know not to use the built-in store_memory?"
     (expected: explain `preToolUse` hook blocking)

2. **Holdout size.** 5 holdout examples with 2 timeouts = effectively 3 scored
   pairs. Need 8-10 for stable comparison.

3. **Separate judge and reflector models.** Using the same model for both means
   the reflector's "improvements" align perfectly with what the judge rewards —
   creating a feedback loop that over-optimizes for judge preference rather
   than actual agent behavior.

4. **Run harness in inner loop (expensive).** The agent_output="" placeholder
   means GEPA optimizes for "reads well" not "works well." The harness proved
   the evolved skill produces more tool calls (6-7 vs 3-5 per holdout) and
   different behavior. This signal should feed back into optimization.

---

## Cross-experiment comparison

| | Exp 001 | Exp 002 | Exp 003 |
|---|---|---|---|
| Model | gpt-4o-mini | gpt-4o-mini | gpt-5.4 |
| Dataset | 18 synthetic | 10 golden | 15 golden |
| Harness | No | No | Yes (holdout) |
| Improvement | 0.0% | 0.0% | **+39.7%** |
| Skill changed? | No | No | **Yes** |
| Real improvement? | N/A | N/A | Mixed |

### Key takeaways

1. **Model quality is the #1 lever.** gpt-4o-mini → gpt-5.4 was the difference
   between "returns seed unchanged" and "makes real structural improvements."
   The reflector needs to be strong enough to reason about a 17K skill.

2. **Golden test cases shape what gets optimized.** GEPA improves what the
   tests measure and drops what they don't. This is both a feature (focused
   optimization) and a risk (content loss). Test coverage = optimization scope.

3. **The harness validates but doesn't train.** The two-tier architecture
   (LLM-judge inner loop, harness holdout) works but means GEPA never sees
   real agent behavior during optimization. The +39.7% is "looks better to
   gpt-5.4" not necessarily "works better in practice."

4. **Small holdout is noisy.** Even with gpt-5.4, 3 effective holdout pairs
   (2 timed out) is too few. The 0.418 → 0.584 delta could include ±0.1 of
   variance. Need 8+ holdout examples with longer timeouts.

5. **The evolved skill is a useful draft, not a deployment candidate.** The
   structural additions (Core Rules, Decision Table, Recall Flow) are genuine
   improvements worth cherry-picking. The content losses (Cap 4-5 detail) mean
   it shouldn't replace the original wholesale.

---

## Next experiments

### Exp 004 (planned): More golden tests + merged skill

- Add 5-8 golden tests specifically for capabilities 4-5 detail
- Manually merge best of evolved (Core Rules, Decision Table) with baseline
  (Cap 4-5 detail) as the new seed
- Re-run GEPA on the merged seed — does it maintain both?

### Exp 005 (planned): Harness in inner loop

- Run a small experiment with harness in the GEPA evaluator (not just holdout)
- Max 20 metric calls × 3 train examples = 60 copilot sessions
- Compare: does real agent output produce a different evolved skill?

### Exp 006 (planned): Separate judge and reflector

- Use gpt-5.4 as reflector, gpt-4o as judge (or vice versa)
- Test whether decoupling reduces the feedback-loop over-optimization
