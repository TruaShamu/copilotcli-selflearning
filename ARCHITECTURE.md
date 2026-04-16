# Architecture

Developer reference for the self-learning system internals.

For user-facing setup, see [README.md](README.md).
For LLM skill instructions, see [skills/self-learning/SKILL.md](skills/self-learning/SKILL.md).

## System Overview

Hook-driven autonomous learning. The agent never needs to voluntarily manage memory — hooks handle all reads, writes, and searches automatically.

> **Design principle**: *The agent is a goldfish. Hooks are its brain.*

Six hooks form a complete lifecycle around every session: context loading, semantic search, tool governance, usage logging, forced reflection, and LLM-powered extraction. The agent operates naturally; the hook system silently maintains continuity across sessions.

## Hook Architecture

All hooks live in `hooks/` with bash + PowerShell variants. They resolve `memory_cli.py` relative to their own location (`dirname $0/../resources/`) so they work from any install path.

| Hook | Purpose | LLM? | Blocks? |
|------|---------|------|---------|
| `sessionStart` | Load prefs + memories → inject context | No | No |
| `userPromptSubmitted` | FTS5 search on prompt → inject relevant matches | No | No |
| `preToolUse` | Block `store_memory` (enforce local SQLite) | No | Yes (deny) |
| `postToolUse` | Log tool calls + skill invocations | No | No |
| `agentStop` | Force reflection on complex sessions (5+ tools, no skill) | No | Yes (block) |
| `sessionEnd` | LLM extracts memories/prefs/skill candidates from transcript | Yes (`gpt-4o-mini`) | No |

### Hook details

- **sessionStart**: Queries active preferences (`WHERE superseded_by IS NULL`) and recent memories, formats them as context injection. Output goes to system prompt.
- **userPromptSubmitted**: Runs FTS5 search against `memory_fts` and `prefs_fts` using the user's prompt as query. Injects matching memories/prefs as additional context.
- **preToolUse**: Only hook with actionable output. Returns `deny` for `store_memory` calls to enforce that all memory writes go through the local SQLite pipeline, not Copilot's native store.
- **postToolUse**: Logs every tool invocation to `tool_usage` (name, sequence index, success/failure). Logs skill invocations to `skill_usage`.
- **agentStop**: Inspects session metrics. If 5+ tool calls and no skill was invoked, blocks the stop and forces the agent to reflect on whether the workflow should become a skill.
- **sessionEnd**: Calls `gpt-4o-mini` to analyze the full session transcript. Extracts new memories, preference updates, and skill candidates. Writes directly to SQLite tables.

> **Important**: Per the [official docs](https://docs.github.com/en/copilot/reference/hooks-configuration), only `preToolUse` can return allow/deny. `agentStop` can block by returning non-zero exit. Other hooks have output injected as context or discarded depending on type.

## Data Flow

```
sessionStart
  → prefs + memories injected into context
    → userPromptSubmitted
      → FTS5 search on prompt → relevant memories injected
        → agent works (tool calls, edits, etc.)
          → postToolUse logs each tool call
            → agentStop checks: 5+ tools & no skill? → force reflection
              → sessionEnd: gpt-4o-mini extracts memories/prefs/skill candidates
```

## Database Schema

All data lives in `~/.copilot/self-learning/memory.db` (SQLite, WAL mode).

### preferences

User workflow and style preferences with confidence scoring and supersede chain.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| category | TEXT NOT NULL | e.g. "code-style", "workflow", "tool-preferences" |
| fact | TEXT NOT NULL | The preference statement |
| confidence | REAL | 0.0–1.0, default 0.7 |
| source | TEXT | Where this was observed |
| created_at | TEXT | ISO datetime |
| updated_at | TEXT | ISO datetime |
| superseded_by | INTEGER FK | Points to newer preference (self-referential) |

**Supersede chain**: When a preference is updated, the old row gets `superseded_by` set
to the new row's id. Queries filter `WHERE superseded_by IS NULL` to get active prefs.

### personal_memory

Facts, conventions, gotchas, and commands discovered during sessions.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| subject | TEXT NOT NULL | Topic key (e.g. "build-system", "auth") |
| fact | TEXT NOT NULL | The memory content |
| citations | TEXT | Source references |
| repo | TEXT | owner/repo if repo-specific |
| session_id | TEXT | Which session discovered this |
| created_at | TEXT | ISO datetime |

### skill_usage

Tracks skill invocations and outcomes. Fed by `postToolUse` hook (success/failure)
and manual `log-skill` calls (partial/skipped).

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| skill_name | TEXT NOT NULL | Skill identifier |
| repo | TEXT | Context repo |
| session_id | TEXT | Session that used the skill |
| outcome | TEXT | CHECK: success, partial, failure, skipped |
| friction_notes | TEXT | What went wrong (manual only) |
| created_at | TEXT | ISO datetime |

### learning_log

Session workflows flagged as potential skill auto-creation candidates.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| repo | TEXT | Context repo |
| session_id | TEXT | Source session |
| intent | TEXT | What the user was trying to do |
| workflow_phases | TEXT | Comma-separated phases |
| tool_count | INTEGER | Number of tool calls |
| skill_candidate | INTEGER | 1 if flagged as candidate |
| created_at | TEXT | ISO datetime |

### tool_usage

Every tool invocation per session, for sequence pattern analysis.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| session_id | TEXT NOT NULL | Session identifier |
| tool_name | TEXT NOT NULL | e.g. "grep", "edit", "bash", "skill" |
| seq_index | INTEGER NOT NULL | 0-based order within session |
| success | INTEGER | 1 = success (default), 0 = failure |
| created_at | TEXT | ISO datetime |

**Pattern detection**: Use `query-tool-sequences --patterns --window-size 3`
to find recurring n-gram tool sequences across sessions. Sequences appearing
in 2+ sessions are potential skill candidates.

### FTS5 Virtual Tables

| Table | Source | Purpose |
|-------|--------|---------|
| `memory_fts` | `personal_memory` | Full-text search on subject + fact columns |
| `prefs_fts` | `preferences` | Full-text search on category + fact columns |

Used by `userPromptSubmitted` hook and `search-context` CLI command. Content-sync triggers keep FTS tables in sync with source tables on INSERT/UPDATE/DELETE.

**FTS5 query syntax**: `keywords` (AND), `word1 OR word2`, `"exact phrase"`, `prefix*`, `word1 NOT word2`.

### Cross-session search (native store)

Session transcripts are stored in Copilot CLI's native `~/.copilot/session-store.db`.
This is a separate SQLite database managed by Copilot CLI itself — the self-learning
system reads it in read-only mode for cross-session search and evolution data mining.

**Native store schema** (read-only, managed by Copilot CLI):
- `sessions` — id, repository, branch, summary, created_at, updated_at
- `turns` — session_id, turn_index, user_message, assistant_response, timestamp
- `search_index` — FTS5 virtual table (content, session_id, source_type)
- `checkpoints`, `session_files`, `session_refs` — additional metadata

## CLI Commands

### New commands (supporting hooks)

| Command | Purpose | Used by |
|---------|---------|---------|
| `search-context` | FTS5 search across memory_fts + prefs_fts | `userPromptSubmitted` hook |
| `session-stats` | Session metrics (tool count, skill usage, complexity) | `agentStop` hook |
| `extract-session` | LLM-powered extraction of memories/prefs/skill candidates from transcript | `sessionEnd` hook |

### Existing commands

See `memory_cli.py --help` for the full list: `store-memory`, `recall`, `set-preference`, `get-preferences`, `log-skill`, `query-tool-sequences`, etc.

## Evolution Engine

See [evolution/README.md](evolution/README.md) for the DSPy + GEPA optimization
framework. Key design decisions:

- **GEPA optimizes CoT reasoning**, not skill text directly. The skill body is
  passed as an InputField on each forward pass; the evolution loop in
  `evolve_skill.py` handles skill text mutation between optimization runs.
- **Fitness metric** uses bag-of-words overlap (with stopword filtering) as a
  fast proxy during optimization. Full LLM-as-judge scoring is used on the
  holdout set.
- **Three eval data sources**: synthetic (LLM-generated), sessiondb (mined from
  Copilot CLI's native session-store.db via FTS5), golden (hand-curated JSONL).
