#!/usr/bin/env python3
"""
Self-learning memory CLI — local SQLite store for personal preferences,
memories, skill usage tracking, and learning logs.

Usage:
  python memory_cli.py store-pref <category> <fact> [--confidence 0.8] [--source "..."]
  python memory_cli.py store-memory <subject> <fact> [--repo "..."] [--citations "..."]
  python memory_cli.py log-skill <name> <outcome> [--friction "..."] [--repo "..."]
  python memory_cli.py log-learning <intent> <phases> <tool_count> [--candidate] [--repo "..."]
  python memory_cli.py query-prefs [--category <cat>]
  python memory_cli.py query-memory [--subject <sub>] [--search <text>]
  python memory_cli.py query-skills [--name <name>]
  python memory_cli.py query-learnings [--candidates-only]
  python memory_cli.py supersede-pref <old_id> <new_fact> [--confidence 0.9]
  python memory_cli.py decay-report [--dormant-only]
  python memory_cli.py stats

DB location: ~/.copilot/self-learning/memory.db
"""

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

DB_DIR = os.path.expanduser("~/.copilot/self-learning")
DB_PATH = os.path.join(DB_DIR, "memory.db")

# Copilot CLI's native session store (read-only, may not exist)
NATIVE_SESSION_STORE = os.path.expanduser("~/.copilot/session-store.db")

# FTS5 hyphen escaping — the default tokenizer treats unquoted hyphens as
# column prefix operators ("no such column" errors). Wrap hyphenated words
# in double-quotes to treat them as literal terms.
_FTS5_HYPHEN_RE = re.compile(r'(?<!")(\b\w+-\w+(?:-\w+)*\b)(?!")')


def fts5_escape(query: str) -> str:
    """Escape a query string for safe use with FTS5 MATCH."""
    return _FTS5_HYPHEN_RE.sub(r'"\1"', query)

# Stopwords to filter from search queries
_STOPWORDS = frozenset('the a an is are was were be been being have has had do does did will would shall should may might can could i me my we our you your he she it they them this that these those at by for from in of on to with and or not'.split())


@contextmanager
def native_conn():
    """Context manager for read-only access to Copilot CLI's native session store.

    Yields a sqlite3.Connection or None if the store doesn't exist.
    """
    if not os.path.exists(NATIVE_SESSION_STORE):
        yield None
        return
    conn = sqlite3.connect(f"file:{NATIVE_SESSION_STORE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_conn():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        fact TEXT NOT NULL,
        confidence REAL DEFAULT 0.7,
        source TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        superseded_by INTEGER REFERENCES preferences(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS personal_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        fact TEXT NOT NULL,
        citations TEXT,
        repo TEXT,
        session_id TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS skill_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_name TEXT NOT NULL,
        repo TEXT,
        session_id TEXT,
        outcome TEXT CHECK(outcome IN ('success', 'partial', 'failure', 'skipped')),
        friction_notes TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS learning_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        repo TEXT,
        session_id TEXT,
        intent TEXT,
        workflow_phases TEXT,
        tool_count INTEGER,
        skill_candidate INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    # Tool usage log — captures every tool call per session for sequence analysis
    c.execute("""CREATE TABLE IF NOT EXISTS tool_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        seq_index INTEGER NOT NULL,
        success INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    # Schema migration: add decay columns if missing
    _migrate_decay_columns(conn)
    # FTS5 virtual tables for fast full-text search
    _ensure_fts_tables(conn)


def _ensure_fts_tables(conn):
    """Create FTS5 virtual tables and sync triggers."""
    c = conn.cursor()
    # FTS5 indexes for fast full-text search across memories and preferences
    c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
        subject, fact, content='personal_memory', content_rowid='id',
        tokenize='porter unicode61'
    )""")
    c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS prefs_fts USING fts5(
        category, fact, content='preferences', content_rowid='id',
        tokenize='porter unicode61'
    )""")

    # Triggers to keep FTS5 in sync
    # personal_memory triggers
    c.execute("""CREATE TRIGGER IF NOT EXISTS personal_memory_ai AFTER INSERT ON personal_memory BEGIN
        INSERT INTO memory_fts(rowid, subject, fact) VALUES (new.id, new.subject, new.fact);
    END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS personal_memory_ad AFTER DELETE ON personal_memory BEGIN
        INSERT INTO memory_fts(memory_fts, rowid, subject, fact) VALUES('delete', old.id, old.subject, old.fact);
    END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS personal_memory_au AFTER UPDATE ON personal_memory BEGIN
        INSERT INTO memory_fts(memory_fts, rowid, subject, fact) VALUES('delete', old.id, old.subject, old.fact);
        INSERT INTO memory_fts(rowid, subject, fact) VALUES (new.id, new.subject, new.fact);
    END""")

    # preferences triggers
    c.execute("""CREATE TRIGGER IF NOT EXISTS preferences_ai AFTER INSERT ON preferences BEGIN
        INSERT INTO prefs_fts(rowid, category, fact) VALUES (new.id, new.category, new.fact);
    END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS preferences_ad AFTER DELETE ON preferences BEGIN
        INSERT INTO prefs_fts(prefs_fts, rowid, category, fact) VALUES('delete', old.id, old.category, old.fact);
    END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS preferences_au AFTER UPDATE ON preferences BEGIN
        INSERT INTO prefs_fts(prefs_fts, rowid, category, fact) VALUES('delete', old.id, old.category, old.fact);
        INSERT INTO prefs_fts(rowid, category, fact) VALUES (new.id, new.category, new.fact);
    END""")

    conn.commit()
    _rebuild_fts(conn)


def _rebuild_fts(conn):
    """Rebuild FTS5 indexes from source tables. Safe to call repeatedly."""
    try:
        conn.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")
    except Exception:
        pass
    try:
        conn.execute("INSERT INTO prefs_fts(prefs_fts) VALUES('rebuild')")
    except Exception:
        pass
    conn.commit()


# ---------------------------------------------------------------------------
# Decay / relevance scoring
# ---------------------------------------------------------------------------

# Half-life ~23 days: after 23 days with no access, relevance drops to 50%.
_DECAY_LAMBDA = 0.03
# Minimum relevance to include in session context
_DECAY_THRESHOLD = 0.1
# Max preferences to inject at session start
_MAX_PREFS_LOADED = 20


def _migrate_decay_columns(conn):
    """Add last_accessed_at and access_count columns for memory decay.

    Safe to run repeatedly — checks column existence first.
    """
    for table in ("preferences", "personal_memory"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "last_accessed_at" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN last_accessed_at TEXT")
        if "access_count" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN access_count INTEGER DEFAULT 0")
    conn.commit()


def _relevance_score(confidence, created_at, last_accessed_at, access_count):
    """Compute relevance = confidence × recency × access_boost.

    - recency:      exp(-λ × days_since_last_access)   λ=0.03, half-life ~23 days
    - access_boost: min(2.0, 1.0 + 0.1 × access_count)
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC for DB compat
    ref_time = last_accessed_at or created_at or now.isoformat()
    try:
        ref_dt = datetime.fromisoformat(ref_time).replace(tzinfo=None)
    except (ValueError, TypeError):
        ref_dt = now
    days_elapsed = max(0, (now - ref_dt).total_seconds() / 86400)

    recency = math.exp(-_DECAY_LAMBDA * days_elapsed)
    access_boost = min(2.0, 1.0 + 0.1 * (access_count or 0))
    return (confidence or 0.7) * recency * access_boost


def _is_duplicate(conn, fts_table, text, threshold=0.7):
    """Check if text is semantically duplicate of existing entries using FTS5 + word overlap."""
    words = set(re.findall(r'\w+', text.lower())) - _STOPWORDS
    if not words:
        return False

    fts_query = ' OR '.join(fts5_escape(w) for w in list(words)[:10])
    try:
        col_name = 'fact'  # both tables have 'fact' column
        rows = conn.execute(
            f"SELECT {col_name} FROM {fts_table} WHERE {fts_table} MATCH ? LIMIT 5",
            (fts_query,)
        ).fetchall()
    except Exception:
        return False

    for row in rows:
        existing_words = set(re.findall(r'\w+', row[0].lower())) - _STOPWORDS
        if not existing_words:
            continue
        # Jaccard similarity
        intersection = words & existing_words
        union = words | existing_words
        if union and len(intersection) / len(union) >= threshold:
            return True
    return False


def cmd_store_pref(args):
    conn = get_conn()
    conn.execute(
        "INSERT INTO preferences (category, fact, confidence, source) VALUES (?,?,?,?)",
        (args.category, args.fact, args.confidence, args.source),
    )
    conn.commit()
    print(json.dumps({"status": "stored", "table": "preferences", "category": args.category}))


def cmd_store_memory(args):
    conn = get_conn()
    conn.execute(
        "INSERT INTO personal_memory (subject, fact, citations, repo) VALUES (?,?,?,?)",
        (args.subject, args.fact, args.citations, args.repo),
    )
    conn.commit()
    print(json.dumps({"status": "stored", "table": "personal_memory", "subject": args.subject}))


def cmd_log_skill(args):
    conn = get_conn()
    conn.execute(
        "INSERT INTO skill_usage (skill_name, repo, outcome, friction_notes) VALUES (?,?,?,?)",
        (args.name, args.repo, args.outcome, args.friction),
    )
    conn.commit()
    print(json.dumps({"status": "logged", "table": "skill_usage", "skill": args.name}))


def cmd_log_learning(args):
    conn = get_conn()
    conn.execute(
        "INSERT INTO learning_log (repo, intent, workflow_phases, tool_count, skill_candidate) VALUES (?,?,?,?,?)",
        (args.repo, args.intent, args.phases, args.tool_count, 1 if args.candidate else 0),
    )
    conn.commit()
    print(json.dumps({"status": "logged", "table": "learning_log", "candidate": args.candidate}))


def cmd_query_prefs(args):
    conn = get_conn()
    q = """SELECT id, category, fact, confidence, source, created_at,
                  last_accessed_at, access_count
           FROM preferences WHERE superseded_by IS NULL"""
    params = []
    if args.category:
        q += " AND category = ?"
        params.append(args.category)
    q += " ORDER BY confidence DESC, created_at DESC"
    rows = [dict(r) for r in conn.execute(q, params)]

    if args.with_decay:
        # Score each preference and filter/sort by relevance
        for row in rows:
            row["relevance"] = round(_relevance_score(
                row["confidence"], row["created_at"],
                row["last_accessed_at"], row["access_count"],
            ), 4)
        rows = [r for r in rows if r["relevance"] >= _DECAY_THRESHOLD]
        rows.sort(key=lambda r: r["relevance"], reverse=True)
        rows = rows[:_MAX_PREFS_LOADED]

        # Bump access counts for loaded prefs
        loaded_ids = [r["id"] for r in rows]
        if loaded_ids:
            placeholders = ",".join("?" for _ in loaded_ids)
            conn.execute(
                f"""UPDATE preferences
                    SET last_accessed_at = datetime('now'),
                        access_count = COALESCE(access_count, 0) + 1
                    WHERE id IN ({placeholders})""",
                loaded_ids,
            )
            conn.commit()

    print(json.dumps(rows, indent=2))


def cmd_query_memory(args):
    conn = get_conn()

    # Summary mode: group by subject, one line per group
    if args.summary:
        rows = [dict(r) for r in conn.execute(
            """SELECT id, subject, fact, created_at, last_accessed_at, access_count
               FROM personal_memory ORDER BY subject, created_at DESC"""
        )]
        if args.with_decay:
            for r in rows:
                r["relevance"] = round(_relevance_score(
                    r.get("confidence") or 0.7, r["created_at"],
                    r["last_accessed_at"], r["access_count"],
                ), 4)
            rows = [r for r in rows if r["relevance"] >= _DECAY_THRESHOLD]

            # Bump access counts
            loaded_ids = [r["id"] for r in rows]
            if loaded_ids:
                placeholders = ",".join("?" for _ in loaded_ids)
                conn.execute(
                    f"""UPDATE personal_memory
                        SET last_accessed_at = datetime('now'),
                            access_count = COALESCE(access_count, 0) + 1
                        WHERE id IN ({placeholders})""",
                    loaded_ids,
                )
                conn.commit()

        # Group by subject
        groups = {}
        for r in rows:
            subj = r["subject"] or "general"
            groups.setdefault(subj, []).append(r["fact"])

        summary = {subj: {"count": len(facts), "facts": facts}
                   for subj, facts in groups.items()}
        print(json.dumps(summary, indent=2))
        return

    q = """SELECT id, subject, fact, citations, repo, created_at,
                  last_accessed_at, access_count
           FROM personal_memory WHERE 1=1"""
    params = []
    if args.subject:
        q += " AND subject = ?"
        params.append(args.subject)
    if args.search:
        q += " AND fact LIKE ?"
        params.append(f"%{args.search}%")
    q += " ORDER BY created_at DESC LIMIT 20"
    rows = [dict(r) for r in conn.execute(q, params)]

    if args.with_decay:
        for row in rows:
            row["relevance"] = round(_relevance_score(
                row.get("confidence") or 0.7, row["created_at"],
                row["last_accessed_at"], row["access_count"],
            ), 4)
        rows = [r for r in rows if r["relevance"] >= _DECAY_THRESHOLD]
        rows.sort(key=lambda r: r["relevance"], reverse=True)
        rows = rows[:_MAX_PREFS_LOADED]

        # Bump access counts for loaded memories
        loaded_ids = [r["id"] for r in rows]
        if loaded_ids:
            placeholders = ",".join("?" for _ in loaded_ids)
            conn.execute(
                f"""UPDATE personal_memory
                    SET last_accessed_at = datetime('now'),
                        access_count = COALESCE(access_count, 0) + 1
                    WHERE id IN ({placeholders})""",
                loaded_ids,
            )
            conn.commit()

    print(json.dumps(rows, indent=2))


def cmd_query_skills(args):
    conn = get_conn()
    q = "SELECT skill_name, outcome, friction_notes, created_at FROM skill_usage WHERE 1=1"
    params = []
    if args.name:
        q += " AND skill_name = ?"
        params.append(args.name)
    q += " ORDER BY created_at DESC LIMIT 20"
    rows = [dict(r) for r in conn.execute(q, params)]
    print(json.dumps(rows, indent=2))


def cmd_query_learnings(args):
    conn = get_conn()
    q = "SELECT intent, workflow_phases, tool_count, skill_candidate, created_at FROM learning_log WHERE 1=1"
    params = []
    if args.candidates_only:
        q += " AND skill_candidate = 1"
    q += " ORDER BY created_at DESC LIMIT 20"
    rows = [dict(r) for r in conn.execute(q, params)]
    print(json.dumps(rows, indent=2))


def cmd_supersede_pref(args):
    conn = get_conn()
    old = conn.execute("SELECT * FROM preferences WHERE id = ?", (args.old_id,)).fetchone()
    if not old:
        print(json.dumps({"error": f"Preference {args.old_id} not found"}))
        sys.exit(1)
    c = conn.cursor()
    c.execute(
        "INSERT INTO preferences (category, fact, confidence, source) VALUES (?,?,?,?)",
        (old["category"], args.new_fact, args.confidence, f"supersedes #{args.old_id}"),
    )
    new_id = c.lastrowid
    c.execute("UPDATE preferences SET superseded_by = ? WHERE id = ?", (new_id, args.old_id))
    conn.commit()
    print(json.dumps({"status": "superseded", "old_id": args.old_id, "new_id": new_id}))


def cmd_stats(args):
    conn = get_conn()
    stats = {}
    stats["preferences"] = conn.execute("SELECT COUNT(*) FROM preferences WHERE superseded_by IS NULL").fetchone()[0]
    stats["personal_memories"] = conn.execute("SELECT COUNT(*) FROM personal_memory").fetchone()[0]
    stats["skill_usages"] = conn.execute("SELECT COUNT(*) FROM skill_usage").fetchone()[0]
    stats["learning_logs"] = conn.execute("SELECT COUNT(*) FROM learning_log").fetchone()[0]
    stats["skill_candidates"] = conn.execute("SELECT COUNT(*) FROM learning_log WHERE skill_candidate=1").fetchone()[0]
    stats["tool_usage_entries"] = conn.execute("SELECT COUNT(*) FROM tool_usage").fetchone()[0]
    stats["db_path"] = DB_PATH
    stats["db_size_kb"] = round(os.path.getsize(DB_PATH) / 1024, 1)

    # Native session store (session-store.db)
    with native_conn() as nconn:
        if nconn:
            try:
                stats["native_store_path"] = NATIVE_SESSION_STORE
                stats["native_store_size_kb"] = round(os.path.getsize(NATIVE_SESSION_STORE) / 1024, 1)
                stats["native_sessions"] = nconn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                stats["native_turns"] = nconn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
                stats["native_search_index"] = nconn.execute("SELECT COUNT(*) FROM search_index").fetchone()[0]
            except Exception:
                pass

    print(json.dumps(stats, indent=2))


def cmd_decay_report(args):
    """Show all preferences scored by relevance, flagging dormant ones."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, category, fact, confidence, source, created_at,
                  last_accessed_at, access_count
           FROM preferences WHERE superseded_by IS NULL
           ORDER BY created_at DESC""",
    ).fetchall()

    scored = []
    for row in rows:
        r = dict(row)
        r["relevance"] = round(_relevance_score(
            r["confidence"], r["created_at"],
            r["last_accessed_at"], r["access_count"],
        ), 4)
        r["status"] = "active" if r["relevance"] >= _DECAY_THRESHOLD else "dormant"
        scored.append(r)

    scored.sort(key=lambda r: r["relevance"], reverse=True)

    active = [r for r in scored if r["status"] == "active"]
    dormant = [r for r in scored if r["status"] == "dormant"]

    report = {
        "total_preferences": len(scored),
        "active": len(active),
        "dormant": len(dormant),
        "threshold": _DECAY_THRESHOLD,
        "max_loaded": _MAX_PREFS_LOADED,
        "decay_half_life_days": round(math.log(2) / _DECAY_LAMBDA, 1),
        "preferences": scored,
    }

    if args.dormant_only:
        report["preferences"] = dormant

    print(json.dumps(report, indent=2))


# ---------------------------------------------------------------------------
# Session transcript storage & FTS5 search
# ---------------------------------------------------------------------------

def cmd_log_tool(args):
    """Log a single tool invocation for a session."""
    conn = get_conn()
    # Auto-increment seq_index per session
    row = conn.execute(
        "SELECT COALESCE(MAX(seq_index), -1) + 1 FROM tool_usage WHERE session_id = ?",
        (args.session_id,),
    ).fetchone()
    seq_index = row[0]
    conn.execute(
        "INSERT INTO tool_usage (session_id, tool_name, seq_index, success) VALUES (?,?,?,?)",
        (args.session_id, args.tool_name, seq_index, 0 if args.failed else 1),
    )
    conn.commit()
    print(json.dumps({"status": "logged", "session_id": args.session_id, "tool": args.tool_name, "seq": seq_index}))


def cmd_query_tool_sequences(args):
    """Query tool usage sequences, optionally grouped by session.

    With --patterns, finds recurring subsequences across sessions.
    """
    conn = get_conn()

    if args.patterns:
        # Find repeated tool sequences (window of args.window_size) across sessions
        rows = conn.execute(
            """SELECT session_id, seq_index, tool_name
               FROM tool_usage ORDER BY session_id, seq_index""",
        ).fetchall()

        # Build per-session sequences
        sessions = {}
        for r in rows:
            sid = r["session_id"]
            if sid not in sessions:
                sessions[sid] = []
            sessions[sid].append(r["tool_name"])

        # Extract n-grams and count
        from collections import Counter
        ngram_counts = Counter()
        window = args.window_size
        for sid, tools in sessions.items():
            if len(tools) < window:
                continue
            for i in range(len(tools) - window + 1):
                ngram = tuple(tools[i:i + window])
                ngram_counts[ngram] += 1

        # Filter to patterns seen in 2+ sessions
        patterns = [
            {"sequence": list(k), "count": v}
            for k, v in ngram_counts.most_common(args.limit)
            if v >= 2
        ]
        print(json.dumps({"patterns": patterns, "window_size": window}, indent=2))
        return

    # Default: show sequences for a specific session or recent sessions
    q = "SELECT session_id, seq_index, tool_name, success, created_at FROM tool_usage"
    params = []
    if args.session_id:
        q += " WHERE session_id = ?"
        params.append(args.session_id)
    q += " ORDER BY session_id, seq_index"
    if not args.session_id:
        q += " LIMIT ?"
        params.append(args.limit)

    rows = [dict(r) for r in conn.execute(q, params)]

    # Group by session
    sessions = {}
    for r in rows:
        sid = r["session_id"]
        if sid not in sessions:
            sessions[sid] = []
        sessions[sid].append(r["tool_name"])

    print(json.dumps({
        "sessions": {sid: tools for sid, tools in sessions.items()},
        "count": len(sessions),
    }, indent=2))



def cmd_search_sessions(args):
    """FTS5 full-text search across Copilot CLI's native session store.

    Queries ~/.copilot/session-store.db which has FTS5-indexed data
    across all past Copilot CLI sessions.
    """
    with native_conn() as nconn:
        if not nconn:
            print(json.dumps({
                "error": "Native session store not found at " + NATIVE_SESSION_STORE,
                "hint": "Cross-session search requires Copilot CLI's local session-store.db",
            }))
            return

        safe_query = fts5_escape(args.query)

        sql = """
            SELECT
                si.session_id,
                si.source_type,
                si.content,
                s.summary,
                s.repository AS repo,
                s.branch,
                s.created_at AS started_at,
                rank
            FROM search_index si
            JOIN sessions s ON si.session_id = s.id
            WHERE search_index MATCH ?
            ORDER BY rank
            LIMIT ?
        """

        try:
            rows = nconn.execute(sql, (safe_query, args.limit)).fetchall()
        except Exception as e:
            print(json.dumps({"error": f"FTS5 query failed: {e}", "query": args.query}))
            return

        if not rows:
            print(json.dumps({"query": args.query, "results": [], "count": 0}))
            return

        # Group by session
        sessions = {}
        for row in rows:
            sid = row["session_id"]
            if sid not in sessions:
                sessions[sid] = {
                    "session_id": sid,
                    "summary": row["summary"],
                    "repo": row["repo"],
                    "branch": row["branch"],
                    "started_at": row["started_at"],
                    "matches": [],
                }
            sessions[sid]["matches"].append({
                "source_type": row["source_type"],
                "content": row["content"][:500],
                "rank": row["rank"],
            })

        # Load surrounding turns for context
        if args.context > 0:
            for sid, sdata in sessions.items():
                context_rows = nconn.execute(
                    """SELECT turn_index, user_message, assistant_response
                       FROM turns
                       WHERE session_id = ?
                       ORDER BY turn_index
                       LIMIT ?""",
                    (sid, args.context * 2),
                ).fetchall()
                sdata["context_window"] = []
                for r in context_rows:
                    if r["user_message"]:
                        sdata["context_window"].append({
                            "turn_index": r["turn_index"],
                            "role": "user",
                            "content": r["user_message"][:2000],
                        })
                    if r["assistant_response"]:
                        sdata["context_window"].append({
                            "turn_index": r["turn_index"],
                            "role": "assistant",
                            "content": r["assistant_response"][:2000],
                        })

        result = {
            "query": args.query,
            "results": list(sessions.values()),
            "count": len(sessions),
            "total_matches": len(rows),
        }
        print(json.dumps(result, indent=2))


def cmd_recent_sessions(args):
    """List recent sessions from Copilot CLI's native session store."""
    with native_conn() as nconn:
        if not nconn:
            print(json.dumps({"error": "Native session store not found at " + NATIVE_SESSION_STORE}))
            return

        rows = nconn.execute(
            """SELECT s.id, s.repository AS repo, s.branch, s.summary,
                      s.created_at AS started_at, s.updated_at AS ended_at,
                      COUNT(t.id) AS turn_count
               FROM sessions s
               LEFT JOIN turns t ON s.id = t.session_id
               GROUP BY s.id
               ORDER BY s.created_at DESC
               LIMIT ?""",
            (args.limit,),
        ).fetchall()
        result = [dict(r) for r in rows]
        print(json.dumps(result, indent=2))



def cmd_search_context(args):
    """Search memories and preferences by prompt keywords. Zero LLM cost."""
    conn = get_conn()
    prompt = args.prompt

    # Extract significant words
    words = [w for w in re.findall(r'\w+', prompt.lower()) if w not in _STOPWORDS and len(w) > 2]
    if not words:
        print(json.dumps({"matches": [], "query": prompt}))
        return

    # Build FTS5 query: OR between words for broad recall
    fts_query = ' OR '.join(fts5_escape(w) for w in words[:10])  # cap at 10 keywords

    results = []

    # Search memories
    try:
        mem_rows = conn.execute(
            """SELECT m.id, m.subject, m.fact, m.repo, m.created_at, m.last_accessed_at, m.access_count,
                      rank
               FROM memory_fts f
               JOIN personal_memory m ON f.rowid = m.id
               WHERE memory_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, args.limit)
        ).fetchall()
        for r in mem_rows:
            row = dict(r)
            row['type'] = 'memory'
            row['relevance'] = round(_relevance_score(
                0.7, row['created_at'], row['last_accessed_at'], row['access_count']
            ), 4)
            results.append(row)
    except Exception:
        pass  # FTS table might not have data yet

    # Search preferences
    try:
        pref_rows = conn.execute(
            """SELECT p.id, p.category, p.fact, p.confidence, p.created_at, p.last_accessed_at, p.access_count,
                      rank
               FROM prefs_fts f
               JOIN preferences p ON f.rowid = p.id
               WHERE prefs_fts MATCH ?
               AND p.superseded_by IS NULL
               ORDER BY rank
               LIMIT ?""",
            (fts_query, args.limit)
        ).fetchall()
        for r in pref_rows:
            row = dict(r)
            row['type'] = 'preference'
            row['relevance'] = round(_relevance_score(
                row['confidence'], row['created_at'], row['last_accessed_at'], row['access_count']
            ), 4)
            results.append(row)
    except Exception:
        pass

    # Sort by relevance, take top N
    results.sort(key=lambda r: r['relevance'], reverse=True)
    results = results[:args.limit]

    # Bump access counts for returned items
    mem_ids = [r['id'] for r in results if r['type'] == 'memory']
    pref_ids = [r['id'] for r in results if r['type'] == 'preference']
    if mem_ids:
        ph = ','.join('?' for _ in mem_ids)
        conn.execute(f"""UPDATE personal_memory SET last_accessed_at = datetime('now'),
                         access_count = COALESCE(access_count, 0) + 1 WHERE id IN ({ph})""", mem_ids)
    if pref_ids:
        ph = ','.join('?' for _ in pref_ids)
        conn.execute(f"""UPDATE preferences SET last_accessed_at = datetime('now'),
                         access_count = COALESCE(access_count, 0) + 1 WHERE id IN ({ph})""", pref_ids)
    if mem_ids or pref_ids:
        conn.commit()

    print(json.dumps({"matches": results, "query": prompt, "keywords": words}, indent=2))


def cmd_session_stats(args):
    """Get session statistics for reflection decisions. Zero LLM cost."""
    conn = get_conn()

    tool_rows = conn.execute(
        "SELECT tool_name, success FROM tool_usage WHERE session_id = ? ORDER BY seq_index",
        (args.session_id,)
    ).fetchall()

    tool_count = len(tool_rows)
    unique_tools = list(set(r['tool_name'] for r in tool_rows))
    error_count = sum(1 for r in tool_rows if not r['success'])
    tool_sequence = [r['tool_name'] for r in tool_rows]

    # Check if any skill was used this session
    skill_rows = conn.execute(
        "SELECT skill_name, outcome FROM skill_usage WHERE session_id = ?",
        (args.session_id,)
    ).fetchall()
    skills_used = [dict(r) for r in skill_rows]

    stats = {
        'session_id': args.session_id,
        'tool_count': tool_count,
        'unique_tools': unique_tools,
        'error_count': error_count,
        'tool_sequence': tool_sequence,
        'skills_used': skills_used,
        'has_skill': len(skills_used) > 0,
        'complex_session': tool_count >= 5 and not skills_used,
    }
    print(json.dumps(stats, indent=2))


def cmd_extract_session(args):
    """Extract memories, preferences, and skill candidates from a session transcript.

    Reads from Copilot CLI's native session-store.db, sends to LLM for extraction,
    deduplicates against existing DB entries, and stores new items.
    """
    import subprocess

    # 1. Load transcript from native session store
    with native_conn() as nconn:
        if not nconn:
            print(json.dumps({'error': 'Native session store not found', 'path': NATIVE_SESSION_STORE}))
            return

        turns = nconn.execute(
            """SELECT turn_index, user_message, assistant_response
               FROM turns WHERE session_id = ? ORDER BY turn_index""",
            (args.session_id,)
        ).fetchall()

        if not turns:
            print(json.dumps({'error': 'No turns found', 'session_id': args.session_id}))
            return

        # Get session metadata
        session = nconn.execute(
            "SELECT repository, branch, summary FROM sessions WHERE id = ?",
            (args.session_id,)
        ).fetchone()

    # Build transcript text
    transcript_lines = []
    if session:
        transcript_lines.append(f"Repo: {session['repository'] or 'unknown'}")
        transcript_lines.append(f"Branch: {session['branch'] or 'unknown'}")
        if session['summary']:
            transcript_lines.append(f"Summary: {session['summary']}")
        transcript_lines.append('')

    for turn in turns:
        if turn['user_message']:
            transcript_lines.append(f"User: {turn['user_message'][:2000]}")
        if turn['assistant_response']:
            transcript_lines.append(f"Assistant: {turn['assistant_response'][:2000]}")

    transcript = '\n'.join(transcript_lines)

    # Cap transcript size for LLM
    if len(transcript) > 30000:
        transcript = transcript[:30000] + '\n[...truncated]'

    # 2. Call LLM for extraction
    extraction_prompt = f"""Analyze this coding session transcript and extract:

1. **memories**: Factual things learned about the codebase, tools, environment, or user workflows.
   Each memory has a "subject" (topic) and "fact" (the actual information).

2. **preferences**: User preferences about coding style, tools, workflows, communication.
   Each preference has a "category" (e.g., "coding-style", "tools", "workflow") and "fact" (the preference).
   Include a "confidence" score 0.0-1.0 (how certain this is a real preference vs one-time choice).

3. **skill_candidates**: Complex multi-step workflows that could be reusable.
   Each has a "name" (short identifier), "intent" (what it accomplishes), and "workflow" (step summary).
   Only include if the workflow had 3+ distinct steps and seems reusable.

Return ONLY valid JSON (no markdown, no explanation):
{{
  "memories": [{{"subject": "...", "fact": "..."}}],
  "preferences": [{{"category": "...", "fact": "...", "confidence": 0.7}}],
  "skill_candidates": [{{"name": "...", "intent": "...", "workflow": "..."}}]
}}

If nothing noteworthy was learned, return empty arrays.
Be selective — only extract genuinely useful, non-obvious information.

Transcript:
{transcript}"""

    # Call LLM via environment-configured endpoint
    model = os.environ.get('SELF_LEARNING_MODEL', 'gpt-4o-mini')
    api_key = os.environ.get('OPENAI_API_KEY', '')
    api_base = os.environ.get('OPENAI_API_BASE', 'https://api.openai.com/v1')

    if not api_key:
        print(json.dumps({'error': 'OPENAI_API_KEY not set, cannot extract session'}))
        return

    import urllib.request
    import urllib.error

    req_body = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': extraction_prompt}],
        'temperature': 0.3,
        'max_tokens': 2000,
    })

    req = urllib.request.Request(
        f'{api_base}/chat/completions',
        data=req_body.encode(),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read())
            content = resp_data['choices'][0]['message']['content']
    except Exception as e:
        print(json.dumps({'error': f'LLM call failed: {e}'}))
        return

    # Parse LLM response
    try:
        # Strip markdown fences if present
        content = content.strip()
        if content.startswith('```'):
            content = content.split('\n', 1)[1].rsplit('```', 1)[0]
        extracted = json.loads(content)
    except json.JSONDecodeError as e:
        print(json.dumps({'error': f'Failed to parse LLM response: {e}', 'raw': content[:500]}))
        return

    if args.dry_run:
        print(json.dumps({'dry_run': True, 'extracted': extracted}, indent=2))
        return

    # 3. Dedup and store
    conn = get_conn()
    stored = {'memories': 0, 'preferences': 0, 'skill_candidates': 0, 'skipped_dupes': 0}

    repo = session['repository'] if session else None

    for mem in extracted.get('memories', []):
        if not mem.get('subject') or not mem.get('fact'):
            continue
        if _is_duplicate(conn, 'memory_fts', f"{mem['subject']} {mem['fact']}"):
            stored['skipped_dupes'] += 1
            continue
        conn.execute(
            "INSERT INTO personal_memory (subject, fact, repo, session_id) VALUES (?,?,?,?)",
            (mem['subject'], mem['fact'], repo, args.session_id)
        )
        stored['memories'] += 1

    for pref in extracted.get('preferences', []):
        if not pref.get('category') or not pref.get('fact'):
            continue
        if _is_duplicate(conn, 'prefs_fts', f"{pref['category']} {pref['fact']}"):
            stored['skipped_dupes'] += 1
            continue
        conn.execute(
            "INSERT INTO preferences (category, fact, confidence, source) VALUES (?,?,?,?)",
            (pref['category'], pref['fact'], pref.get('confidence', 0.7), f'session:{args.session_id}')
        )
        stored['preferences'] += 1

    for skill in extracted.get('skill_candidates', []):
        if not skill.get('name') or not skill.get('intent'):
            continue
        conn.execute(
            "INSERT INTO learning_log (repo, session_id, intent, workflow_phases, tool_count, skill_candidate) VALUES (?,?,?,?,?,1)",
            (repo, args.session_id, skill['intent'], skill.get('workflow', ''), 0)
        )
        stored['skill_candidates'] += 1

    conn.commit()
    stored['session_id'] = args.session_id
    print(json.dumps(stored, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Self-learning local memory store")
    sub = parser.add_subparsers(dest="command", required=True)

    # store-pref
    p = sub.add_parser("store-pref")
    p.add_argument("category")
    p.add_argument("fact")
    p.add_argument("--confidence", type=float, default=0.7)
    p.add_argument("--source", default=None)

    # store-memory
    p = sub.add_parser("store-memory")
    p.add_argument("subject")
    p.add_argument("fact")
    p.add_argument("--citations", default=None)
    p.add_argument("--repo", default=None)

    # log-skill
    p = sub.add_parser("log-skill")
    p.add_argument("name")
    p.add_argument("outcome", choices=["success", "partial", "failure", "skipped"])
    p.add_argument("--friction", default=None)
    p.add_argument("--repo", default=None)

    # log-learning
    p = sub.add_parser("log-learning")
    p.add_argument("intent")
    p.add_argument("phases")
    p.add_argument("tool_count", type=int)
    p.add_argument("--candidate", action="store_true")
    p.add_argument("--repo", default=None)

    # query-prefs
    p = sub.add_parser("query-prefs")
    p.add_argument("--category", default=None)
    p.add_argument("--with-decay", action="store_true",
                   help="Apply relevance decay: score, filter, sort, and cap results. "
                        "NOTE: bumps access counts for loaded prefs (mutates DB).")

    # query-memory
    p = sub.add_parser("query-memory")
    p.add_argument("--subject", default=None)
    p.add_argument("--search", default=None)
    p.add_argument("--summary", action="store_true",
                   help="Group memories by subject with counts. Compact output for session start.")
    p.add_argument("--with-decay", action="store_true",
                   help="Apply relevance decay: score, filter, sort, and cap results. "
                        "NOTE: bumps access counts for loaded memories (mutates DB).")

    # query-skills
    p = sub.add_parser("query-skills")
    p.add_argument("--name", default=None)

    # query-learnings
    p = sub.add_parser("query-learnings")
    p.add_argument("--candidates-only", action="store_true")

    # supersede-pref
    p = sub.add_parser("supersede-pref")
    p.add_argument("old_id", type=int)
    p.add_argument("new_fact")
    p.add_argument("--confidence", type=float, default=0.9)

    # stats
    sub.add_parser("stats")

    # decay-report
    p = sub.add_parser("decay-report",
                       help="Show all preferences scored by relevance decay")
    p.add_argument("--dormant-only", action="store_true",
                   help="Show only dormant (below-threshold) preferences")

    # log-tool (single tool invocation)
    p = sub.add_parser("log-tool")
    p.add_argument("session_id")
    p.add_argument("tool_name")
    p.add_argument("--failed", action="store_true", help="Mark as failed invocation")

    # query-tool-sequences
    p = sub.add_parser("query-tool-sequences")
    p.add_argument("--session-id", default=None, help="Filter to a specific session")
    p.add_argument("--patterns", action="store_true", help="Find recurring tool subsequences across sessions")
    p.add_argument("--window-size", type=int, default=3, help="N-gram window size for pattern detection")
    p.add_argument("--limit", type=int, default=20, help="Max results to return")

    # search-sessions (FTS5)
    p = sub.add_parser("search-sessions")
    p.add_argument("query", help="FTS5 query: keywords, phrases, OR/AND/NOT, prefix*")
    p.add_argument("--limit", type=int, default=30, help="Max matches to return")
    p.add_argument("--context", type=int, default=3, help="Surrounding turns to include per match")

    # recent-sessions
    p = sub.add_parser("recent-sessions")
    p.add_argument("--limit", type=int, default=10)

    # search-context (hook: userPromptSubmitted)
    p = sub.add_parser("search-context", help="Search memories+prefs by prompt keywords (for hooks)")
    p.add_argument("prompt", help="User prompt text to search for")
    p.add_argument("--limit", type=int, default=5)

    # session-stats (hook: agentStop)
    p = sub.add_parser("session-stats", help="Session statistics for agentStop reflection")
    p.add_argument("session_id")

    # extract-session (hook: sessionEnd)
    p = sub.add_parser("extract-session", help="Extract memories/prefs/skills from session transcript via LLM")
    p.add_argument("session_id")
    p.add_argument("--dry-run", action="store_true", help="Show extraction without storing")

    args = parser.parse_args()
    handlers = {
        "store-pref": cmd_store_pref,
        "store-memory": cmd_store_memory,
        "log-skill": cmd_log_skill,
        "log-learning": cmd_log_learning,
        "query-prefs": cmd_query_prefs,
        "query-memory": cmd_query_memory,
        "query-skills": cmd_query_skills,
        "query-learnings": cmd_query_learnings,
        "supersede-pref": cmd_supersede_pref,
        "stats": cmd_stats,
        "decay-report": cmd_decay_report,
        "log-tool": cmd_log_tool,
        "query-tool-sequences": cmd_query_tool_sequences,
        "search-sessions": cmd_search_sessions,
        "recent-sessions": cmd_recent_sessions,
        "search-context": cmd_search_context,
        "session-stats": cmd_session_stats,
        "extract-session": cmd_extract_session,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
