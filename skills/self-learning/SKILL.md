---
name: self-learning
description: >-
  Self-learning loop for Copilot CLI. Auto-creates skills from complex sessions,
  improves existing skills after use, nudges persistent memory, recalls cross-session context,
  and builds a user preference model. Trigger with "learn", "reflect", "improve skill",
  "what do you remember", or "review session".
---

# Self-Learning Skill

A meta-skill that gives Copilot CLI a closed learning loop. It covers five
capabilities that compound over time:

| # | Capability | Description |
|---|-----------|-------------|
| 1 | **Skill auto-creation** | Distill a complex session into a reusable skill |
| 2 | **Skill self-improvement** | Revise a skill after observing its use |
| 3 | **Memory nudges** | Proactively persist important facts |
| 4 | **Cross-session recall** | Search past sessions for relevant context via FTS5 + LLM summarization |
| 5 | **User preference model** | Build a deepening model of the user's preferences and workflow |

## Requirements

- Python 3.9+ (for local SQLite memory store)

### Quick reference

```bash
# Personal preferences
python memory_cli.py store-pref <category> "<fact>" --confidence 0.8
python memory_cli.py query-prefs [--category <cat>]
python memory_cli.py supersede-pref <old_id> "<new_fact>"

# Personal memory (not repo-scoped)
python memory_cli.py store-memory <subject> "<fact>" --repo "owner/repo"
python memory_cli.py query-memory [--subject <sub>] [--search <text>]

# Skill usage tracking
python memory_cli.py log-skill <name> <success|partial|failure|skipped> --friction "..."
python memory_cli.py query-skills [--name <name>]

# Learning log (skill-creation triggers)
python memory_cli.py log-learning "<intent>" "<phases>" <tool_count> --candidate
python memory_cli.py query-learnings [--candidates-only]

# Session transcripts & FTS5 search
python memory_cli.py ingest-turn <session_id> <role> "<content>" --repo "..."
python memory_cli.py ingest-session --file session.json  # or pipe JSON to stdin
python memory_cli.py search-sessions "<query>" --context 3 --limit 30
python memory_cli.py recent-sessions --limit 10

# Overview
python memory_cli.py stats
```

## When to Use This Skill

Activate this skill when the user:

- Says "learn", "reflect", "what did you learn", or "review session"
- Says "improve skill X", "update skill", or "skill isn't working well"
- Says "what do you remember", "recall", or "search past sessions for X"
- Says "create a skill from this session" or "save this as a skill"
- Finishes a complex multi-turn task (self-trigger via AGENTS.md guidance)

---

## Lifecycle Hooks

The self-learning loop has two automatic lifecycle phases. These run without
the user explicitly invoking the skill — they're wired via AGENTS.md.

### Session Start (proactive, silent)

Run this at the **beginning** of any session before the first substantive task:

1. **Load preferences** — ✅ *Handled by `sessionStart` hook.* The hook
   queries `memory_cli.py query-prefs` and injects results automatically.
2. **Check prior art** — If the user's first message mentions a specific topic,
   file, or feature, search for related past sessions:
   ```bash
   python ~/.copilot/skills/self-learning/resources/memory_cli.py search-sessions "<topic>" --context 3 --limit 5
   ```
   If results are found, mention them briefly: "I found a related session
   from last week where you..."
3. **Load relevant memory** — Query personal memory for the topic:
   ```bash
   python ~/.copilot/skills/self-learning/resources/memory_cli.py query-memory --search "<topic>"
   ```

Steps 2-3 require LLM judgment (extracting the topic). Step 1 is deterministic
and handled by the hook — no need to repeat it.

### Post-Task (autonomous, single pass)

Run this **once** after completing any substantial task (3+ tool calls,
multi-phase work). Execute all steps in a single pass — don't wait for the
user between steps:

1. **Memory nudge** (silent) — Scan the session for 1-3 novel facts worth
   persisting. Store each via:
   ```bash
   python ~/.copilot/skills/self-learning/resources/memory_cli.py store-memory \
     "<subject>" "<fact>" --repo "<owner/repo>"
   ```
   Briefly confirm what was stored: "📝 Stored: ..."

2. **Preference observation** (silent) — If the user stated or demonstrated
   any conventions/preferences during the task, store them:
   ```bash
   python ~/.copilot/skills/self-learning/resources/memory_cli.py store-pref \
     "<category>" "<fact>" --confidence 0.8
   ```

3. **Session ingestion** — ✅ *Handled by `sessionEnd` hook.* The hook
   archives the session summary automatically via `memory_cli.py ingest-turn`.
   No need to do this manually.

4. **Skill creation check** (ask user) — If and only if the session involved
   a novel, reusable multi-step workflow (3+ distinct phases), ask:
   > "This looks like a reusable workflow. Want me to save it as a skill?"

   Use `ask_user` with choices: `["Save as skill", "Skip"]`.
   If the user approves, proceed to Capability 1.

5. **Skill improvement check** (ask user) — If a skill was used during the
   session and you encountered friction (skipped steps, added steps, wrong
   order), ask:
   > "I noticed some improvements to the <skill> skill. Apply them?"

   Use `ask_user` with choices: `["Apply improvements", "Skip"]`.
   If approved, proceed to Capability 2.

**Key rule**: Steps 1-2 require LLM judgment and always run silently. Step 3
is handled by the `sessionEnd` hook. Steps 4-5 are conditional and use
`ask_user` only when there's something worth proposing. The entire post-task
flow is a single autonomous pass — never require the user to prompt each step
separately.

### Do NOT self-trigger when:
- The task was simple Q&A or a single tool call
- The user explicitly asked you to stop learning
- You've already run the post-task flow this session

---

## Explicit Invocation Flow

When the user explicitly triggers this skill ("learn", "reflect", "review
session"), run the full suite in order:

1. **Cross-session recall** (Cap 4) — Search for related past sessions
2. **Memory nudge** (Cap 3) — Persist any novel facts from this session
3. **Preference observation** (Cap 5) — Store any preferences demonstrated
4. **Skill creation check** (Cap 1) — Propose a new skill if warranted
5. **Skill improvement check** (Cap 2) — Propose improvements if a skill was used

Present a brief summary at the end:
> "📋 Session review complete:
> - Stored 2 facts (verified build command, config file distinction)
> - Found 1 related past session (Apr 5 — runtime build fix)
> - No skill creation candidates
> - No skill improvements needed"

---

## Capability 1 — Skill Auto-Creation

**Goal**: After a complex session, distill the workflow into a new reusable
SKILL.md so the same class of task is handled better next time.

### Trigger

User says "create a skill from this" or you detect the session involved 5+
tool calls across 3+ distinct phases (exploration → implementation → validation).

### Procedure

1. **Analyze the session** — Query the current session's turns to extract:
   - What the user asked for (intent)
   - What tools were used and in what order (workflow)
   - What decision points occurred (choices)
   - What the final deliverable was (outcome)

   Use `session_store_sql` to pull recent session data:
   ```sql
   SELECT user_message, assistant_response
   FROM turns
   WHERE session_id = '<current_session>'
   ORDER BY turn_index
   ```

2. **Identify the reusable pattern** — Ask yourself:
   - Is this a one-off task or a recurring workflow?
   - What would change between invocations (parameters)?
   - What stays the same (procedure)?

   If the task is clearly one-off (e.g., "fix this specific bug"), skip skill
   creation and instead store key learnings via Capability 3 (Memory Nudge).

3. **Draft the skill** — Generate a SKILL.md following the project convention:

   ```markdown
   ---
   name: <kebab-case-name>
   description: <one-line description with trigger phrases>
   ---

   # <Skill Name>

   <Brief description of what this skill does and when to use it.>

   ## When to Use This Skill
   <Trigger conditions>

   ## Procedure
   <Step-by-step workflow distilled from the session>

   ## Parameters
   <What varies between invocations>

   ## Learned From
   - Session: <session_id>
   - Date: <date>
   - Original request: "<user's original ask>"
   ```

4. **Propose to the user** — Show the draft and ask:
   > "I've distilled this session into a reusable skill. Should I save it to
   > `.github/skills/<name>/SKILL.md`?"

   Use `ask_user` with choices: `["Save skill", "Edit first", "Skip"]`.

5. **Save** — If approved, save to the **user-level** skills directory so it
   works across all repos without touching git:

   ```
   ~/.copilot/skills/<name>/SKILL.md
   ```

   Use the `create` tool to write the file. Create the directory first:
   ```bash
   mkdir -p ~/.copilot/skills/<name>
   ```

   This keeps auto-generated skills personal and out of the repo. If the user
   wants to share a skill with the team, they can copy it to `.github/skills/`
   and commit it.

### Quality gates

- The skill must be self-contained (no references to "this session")
- The skill must have at least 3 concrete procedural steps
- Trigger phrases in `description` must be diverse (3+ variations)

---

## Capability 2 — Skill Self-Improvement

**Goal**: After a skill is used, evaluate whether it performed well and
propose targeted revisions.

### Trigger

User says "improve skill X" or "that skill didn't work well", or you
just finished executing a skill and encountered friction.

### Procedure

1. **Identify the skill** — Find the SKILL.md that was used:
   ```
   glob .github/skills/**/SKILL.md
   ```

2. **Review execution** — Compare what the skill prescribed vs what actually
   happened. Look for:
   - **Skipped steps** — steps you had to skip because they didn't apply
   - **Added steps** — things you had to do that the skill didn't mention
   - **Wrong order** — steps that worked better in a different sequence
   - **Missing tools** — tools that would have helped but weren't mentioned
   - **Outdated references** — file paths, APIs, or patterns that changed

3. **Draft a revision** — Produce a diff-style summary:
   ```
   ## Proposed Skill Improvements

   ### Added
   - Step 2b: Run typecheck before linting (catches errors earlier)

   ### Modified
   - Step 4: Changed from `pnpm test` to `pnpm --filter <pkg> test`
     (full test suite is too slow for iterative development)

   ### Removed
   - Step 6: "Check legacy bean compatibility" (bean is deprecated)
   ```

4. **Propose to the user** — Show the revision summary and ask:
   > "I noticed some improvements after using this skill. Apply them?"

   Use `ask_user` with choices: `["Apply all", "Let me review", "Skip"]`.

5. **Apply** — If approved, use `edit` to update the SKILL.md in place.
   Add a revision log entry at the bottom of the skill:
   ```markdown
   ## Revision History
   - <date>: <brief description of changes> (from session <id>)
   ```

### Self-improvement heuristics

- If a skill was used 3+ times without changes, it's probably stable — don't
  propose improvements unless something clearly broke.
- Weight user corrections heavily — if the user manually overrode a skill step,
  that's strong signal the skill is wrong.
- Never remove steps that enforce safety/validation without explicit approval.

---

## Capability 3 — Memory Nudges

**Goal**: Proactively persist important facts discovered during the session
so they're available in future sessions.

### Trigger

- End of any substantial task (3+ tool calls)
- User says "remember this" or "save this for later"
- You discover a convention, pattern, or gotcha that isn't obvious

### Procedure

1. **Scan the session for memorable facts** — Look for:
   - **Conventions**: Coding patterns, naming rules, file organization
   - **Commands**: Build/test/lint commands that were verified to work
   - **Gotchas**: Things that failed unexpectedly and required workarounds
   - **Preferences**: User choices that indicate a preference
   - **Architecture**: Structural decisions about the codebase

2. **Filter against criteria** — Each candidate fact must be:
   - Actionable in future tasks
   - Independent of the current changeset
   - Unlikely to change over time
   - Not inferrable from a small code sample
   - Free of secrets or sensitive data

3. **Check for duplicates** — Before storing, grep existing memories by
   searching `session_store_sql` for similar facts:
   ```sql
   SELECT assistant_response FROM turns
   WHERE assistant_response ILIKE '%<key_phrase>%'
   ORDER BY timestamp DESC LIMIT 5
   ```

4. **Store** — All facts go to local SQLite via the memory CLI:

   ```bash
   python ~/.copilot/skills/self-learning/resources/memory_cli.py store-memory \
     "<subject>" "<fact>" --repo "<owner/repo>" --citations "..."
   ```

5. **Confirm to the user** — Briefly mention what was stored:
   > "📝 Stored 2 facts: build command for runtime package, and the
   > local vs deployed config file distinction."

### Nudge timing

When self-triggering (not user-invoked), be conservative:
- Only nudge after tasks that produced verified, working results
- Maximum 3 facts per session to avoid noise
- Prefer facts with broad applicability over narrow ones

---

## Capability 4 — Cross-Session Recall

**Goal**: Search past sessions to find relevant context, prior approaches,
or historical decisions that inform the current task.

### Trigger

- User says "what do you remember about X", "have I done this before",
  "search past sessions", or "recall"
- You're about to start a task and want to check for prior art

### Architecture

1. **FTS5 search** finds matching turns ranked by BM25 relevance
2. **Context windows** load surrounding turns for each match
3. **Subagent summarization** sends matched context to an `explore` subagent
   for focused summarization (keeps main context clean)

### Procedure

1. **Ingest sessions** — At the end of each session, save the transcript:
   ```bash
   # Bulk ingest from JSON
   echo '{"session_id":"...","repo":"...","turns":[...]}' | \
     python ~/.copilot/skills/self-learning/resources/memory_cli.py ingest-session

   # Or incrementally per turn
   python ~/.copilot/skills/self-learning/resources/memory_cli.py ingest-turn \
     "<session_id>" "user" "<message>" --repo "<owner/repo>"
   ```

2. **Search** — FTS5 full-text search with BM25 ranking:
   ```bash
   python ~/.copilot/skills/self-learning/resources/memory_cli.py search-sessions \
     "sqlite FTS5 memory" --context 3 --limit 30
   ```

   FTS5 query syntax:
   - Keywords: `runtime build catalog` (AND by default)
   - OR: `sqlite OR memory OR preferences`
   - Phrases: `"mixin registration"`
   - Prefix: `deploy*`
   - NOT: `build NOT test`

3. **Summarize via subagent** — Send the search results to an `explore`
   subagent for focused summarization. This keeps the main context clean:

   ```
   task(
     agent_type: "explore",
     prompt: "Summarize these past session matches for the query '<query>'.
              Focus on: what was asked, what was done, key decisions, and
              outcomes. Be concise but preserve specific commands, paths,
              and error messages.

              SEARCH RESULTS:
              <paste search-sessions JSON output>"
   )
   ```

4. **Present to user** — Synthesize the subagent's summary:
   > "I found 2 relevant past sessions:
   > 1. **Apr 5** — You fixed the runtime build pipeline. The catalog is
   >    auto-generated by `pnpm --filter runtime build`. A missing mixin
   >    registration in physics/ was the root cause.
   > 2. **Mar 28** — You prototyped the self-learning loop..."

5. **Browse recent** — For "what did I work on recently":
   ```bash
   python ~/.copilot/skills/self-learning/resources/memory_cli.py recent-sessions --limit 10
   ```

### Session ingestion guidance

Session transcripts are automatically archived by the `sessionEnd` hook.

---

## Capability 5 — User Preference Model

**Goal**: Build a progressively richer model of the user's preferences,
work style, and expertise areas.

### ⚠️ Scope constraint

All memory is stored locally in `~/.copilot/self-learning/memory.db`.
The `preToolUse` hook automatically **blocks** the built-in `store_memory`
tool, enforcing the local-only policy. No manual vigilance needed.

### What to track

Store everything locally — preferences, conventions, team rules, personal style:

| Category | Example facts |
|----------|--------------|
| **Code style** | "Team uses explicit return types on exported functions" |
| **Workflow** | "Prefers plan-first: show plan before implementing" |
| **Tool preferences** | "Use Vitest for all new test files in runtime/" |
| **Review style** | "PR descriptions must include testing instructions" |

### Procedure

1. **Observe signals** — During the session, note when the user:
   - States a convention or rule → store as preference
   - Corrects your approach → store the correction
   - Expresses a preference → store with high confidence

2. **Encode via memory CLI**:
   ```bash
   python ~/.copilot/skills/self-learning/resources/memory_cli.py store-pref \
     "workflow" "Prefers plan-first: always show plan before implementing" \
     --confidence 0.9 --source "Session: <id>"
   ```

3. **Load preferences at session start** — ✅ *Handled by `sessionStart` hook.*
   Active (non-superseded) preferences are loaded automatically.

4. **Evolve the model** — If a new observation contradicts a stored fact,
   supersede it:
   ```bash
   python ~/.copilot/skills/self-learning/resources/memory_cli.py supersede-pref \
     <old_id> "Updated preference text" --confidence 0.9
   ```

### Privacy guardrails

- Never store credentials, tokens, or secrets
- `store_memory` is blocked by the `preToolUse` hook

---

## Revision History

- 2026-04-11: Initial prototype — capabilities 1-5
- 2026-04-14: Added hooks, pruned instructions handled by hooks
