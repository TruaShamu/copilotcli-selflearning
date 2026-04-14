# Architecture

Developer reference for the self-learning system internals.

For user-facing setup, see [README.md](README.md).
For LLM skill instructions, see [skills/self-learning/SKILL.md](skills/self-learning/SKILL.md).

## System Overview

![Architecture diagram](architecture.png)

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

**Note**: Hook-sourced entries only have `success`/`failure` outcomes.
`partial` and `skipped` require manual `log-skill` invocation.

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

### sessions

Session metadata for transcript storage.

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | Session identifier |
| repo | TEXT | owner/repo |
| branch | TEXT | Git branch |
| summary | TEXT | Session summary |
| started_at | TEXT | ISO datetime |
| ended_at | TEXT | ISO datetime, set on close |

### session_turns

Individual conversation turns within a session.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| session_id | TEXT FK | References sessions(id) |
| turn_index | INTEGER NOT NULL | 0-based order within session |
| role | TEXT NOT NULL | user, assistant, tool, system |
| content | TEXT NOT NULL | Turn content |
| created_at | TEXT | ISO datetime |

### session_turns_fts

FTS5 virtual table for full-text search over session turns.

```sql
CREATE VIRTUAL TABLE session_turns_fts USING fts5(
    content,
    session_id UNINDEXED,
    role UNINDEXED,
    content_rowid='id',
    tokenize='porter unicode61'
)
```

**Design note**: This is a standalone FTS5 table (not an external content table).
It stores its own copy of content. Session turns are append-only — we never
delete or update them, so no sync triggers are needed.

**FTS5 query syntax**: `keywords` (AND), `word1 OR word2`, `"exact phrase"`,
`prefix*`, `word1 NOT word2`.

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

## Hooks

All hooks live in `hooks/` with bash + PowerShell variants. They resolve
`memory_cli.py` relative to their own location (`dirname $0/../resources/`)
so they work from any install path.

| Hook | Event | Behavior |
|------|-------|----------|
| pre-tool-use | preToolUse | Blocks `store_memory` (returns deny) |
| session-start | sessionStart | Queries prefs, emits as context |
| session-end | sessionEnd | Archives session summary via ingest-turn |
| post-tool-use | postToolUse | Logs tool to tool_usage + skill to skill_usage |

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
  FTS5 store), golden (hand-curated JSONL).
