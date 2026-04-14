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
  python memory_cli.py stats

DB location: ~/.copilot/self-learning/memory.db
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

DB_DIR = os.path.expanduser("~/.copilot/self-learning")
DB_PATH = os.path.join(DB_DIR, "memory.db")


def get_conn():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    # Session transcripts — stores conversation turns for FTS5 search
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        repo TEXT,
        branch TEXT,
        summary TEXT,
        started_at TEXT DEFAULT (datetime('now')),
        ended_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS session_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        turn_index INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    # FTS5 virtual table for full-text search over turns
    # Check if it exists first (CREATE VIRTUAL TABLE IF NOT EXISTS is supported)
    c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS session_turns_fts USING fts5(
        content, session_id UNINDEXED, role UNINDEXED,
        content_rowid='id', tokenize='porter unicode61'
    )""")
    conn.commit()


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
    q = "SELECT id, category, fact, confidence, source, created_at FROM preferences WHERE superseded_by IS NULL"
    params = []
    if args.category:
        q += " AND category = ?"
        params.append(args.category)
    q += " ORDER BY confidence DESC, created_at DESC"
    rows = [dict(r) for r in conn.execute(q, params)]
    print(json.dumps(rows, indent=2))


def cmd_query_memory(args):
    conn = get_conn()
    q = "SELECT id, subject, fact, citations, repo, created_at FROM personal_memory WHERE 1=1"
    params = []
    if args.subject:
        q += " AND subject = ?"
        params.append(args.subject)
    if args.search:
        q += " AND fact LIKE ?"
        params.append(f"%{args.search}%")
    q += " ORDER BY created_at DESC LIMIT 20"
    rows = [dict(r) for r in conn.execute(q, params)]
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
    stats["sessions"] = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    stats["session_turns"] = conn.execute("SELECT COUNT(*) FROM session_turns").fetchone()[0]
    stats["db_path"] = DB_PATH
    stats["db_size_kb"] = round(os.path.getsize(DB_PATH) / 1024, 1)
    print(json.dumps(stats, indent=2))


# ---------------------------------------------------------------------------
# Session transcript storage & FTS5 search
# ---------------------------------------------------------------------------

def cmd_ingest_session(args):
    """Ingest a session transcript from JSON (stdin or --file).

    Expected JSON format:
    {
      "session_id": "abc-123",
      "repo": "owner/repo",
      "branch": "main",
      "summary": "...",
      "turns": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
      ]
    }
    """
    conn = get_conn()
    if args.file:
        with open(args.file) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    sid = data["session_id"]
    # Upsert session metadata
    conn.execute(
        """INSERT INTO sessions (id, repo, branch, summary, started_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(id) DO UPDATE SET
             summary = COALESCE(excluded.summary, summary),
             ended_at = datetime('now')""",
        (sid, data.get("repo"), data.get("branch"), data.get("summary")),
    )

    turns = data.get("turns", [])
    for i, turn in enumerate(turns):
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        if not content.strip():
            continue
        # Insert turn
        c = conn.cursor()
        c.execute(
            "INSERT INTO session_turns (session_id, turn_index, role, content) VALUES (?,?,?,?)",
            (sid, i, role, content),
        )
        row_id = c.lastrowid
        # Index in FTS5
        c.execute(
            "INSERT INTO session_turns_fts (rowid, content, session_id, role) VALUES (?,?,?,?)",
            (row_id, content, sid, role),
        )

    conn.commit()
    print(json.dumps({
        "status": "ingested",
        "session_id": sid,
        "turns_stored": len(turns),
    }))


def cmd_search_sessions(args):
    """FTS5 full-text search across all session transcripts.

    Returns ranked matches grouped by session, with surrounding context.
    Output is designed to be fed to an LLM subagent for summarization.
    """
    conn = get_conn()
    query = args.query

    # FTS5 search with BM25 ranking
    params = [query]

    sql = """
        SELECT
            st.session_id,
            st.role,
            st.turn_index,
            st.content,
            s.summary,
            s.repo,
            s.branch,
            s.started_at,
            rank
        FROM session_turns_fts fts
        JOIN session_turns st ON fts.rowid = st.id
        JOIN sessions s ON st.session_id = s.id
        WHERE session_turns_fts MATCH ?
    """
    if args.role:
        sql += " AND role = ?"
        params.append(args.role)
    sql += " ORDER BY rank LIMIT ?"
    params.append(args.limit)

    rows = conn.execute(sql, params).fetchall()

    if not rows:
        print(json.dumps({"query": query, "results": [], "count": 0}))
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
            "role": row["role"],
            "turn_index": row["turn_index"],
            "content": row["content"][:500],  # Truncate for preview
            "rank": row["rank"],
        })

    # If --context is set, load surrounding turns for each matched session
    if args.context > 0:
        for sid, sdata in sessions.items():
            match_indices = {m["turn_index"] for m in sdata["matches"]}
            min_idx = max(0, min(match_indices) - args.context)
            max_idx = max(match_indices) + args.context
            context_rows = conn.execute(
                """SELECT turn_index, role, content FROM session_turns
                   WHERE session_id = ? AND turn_index BETWEEN ? AND ?
                   ORDER BY turn_index""",
                (sid, min_idx, max_idx),
            ).fetchall()
            sdata["context_window"] = [
                {"turn_index": r["turn_index"], "role": r["role"], "content": r["content"][:2000]}
                for r in context_rows
            ]

    result = {
        "query": query,
        "results": list(sessions.values()),
        "count": len(sessions),
        "total_matches": len(rows),
    }
    print(json.dumps(result, indent=2))


def cmd_recent_sessions(args):
    """List recent sessions with metadata (no search, no LLM)."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.id, s.repo, s.branch, s.summary, s.started_at, s.ended_at,
                  COUNT(st.id) as turn_count
           FROM sessions s
           LEFT JOIN session_turns st ON s.id = st.session_id
           GROUP BY s.id
           ORDER BY s.started_at DESC
           LIMIT ?""",
        (args.limit,),
    ).fetchall()
    print(json.dumps([dict(r) for r in rows], indent=2))


def cmd_ingest_turn(args):
    """Ingest a single turn into an existing or new session.

    Lightweight alternative to ingest-session — call once per turn
    so the agent can stream transcripts incrementally.
    """
    conn = get_conn()
    # Ensure session exists
    conn.execute(
        """INSERT INTO sessions (id, repo, branch, summary)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET ended_at = datetime('now')""",
        (args.session_id, args.repo, None, args.summary),
    )
    # Get next turn index
    row = conn.execute(
        "SELECT COALESCE(MAX(turn_index), -1) + 1 FROM session_turns WHERE session_id = ?",
        (args.session_id,),
    ).fetchone()
    turn_index = row[0]

    c = conn.cursor()
    c.execute(
        "INSERT INTO session_turns (session_id, turn_index, role, content) VALUES (?,?,?,?)",
        (args.session_id, turn_index, args.role, args.content),
    )
    row_id = c.lastrowid
    c.execute(
        "INSERT INTO session_turns_fts (rowid, content, session_id, role) VALUES (?,?,?,?)",
        (row_id, args.content, args.session_id, args.role),
    )
    conn.commit()
    print(json.dumps({"status": "stored", "session_id": args.session_id, "turn_index": turn_index}))


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

    # query-memory
    p = sub.add_parser("query-memory")
    p.add_argument("--subject", default=None)
    p.add_argument("--search", default=None)

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

    # ingest-session (bulk from JSON)
    p = sub.add_parser("ingest-session")
    p.add_argument("--file", default=None, help="JSON file path (reads stdin if omitted)")

    # ingest-turn (single turn, incremental)
    p = sub.add_parser("ingest-turn")
    p.add_argument("session_id")
    p.add_argument("role", choices=["user", "assistant", "tool", "system"])
    p.add_argument("content")
    p.add_argument("--repo", default=None)
    p.add_argument("--summary", default=None)

    # search-sessions (FTS5)
    p = sub.add_parser("search-sessions")
    p.add_argument("query", help="FTS5 query: keywords, phrases, OR/AND/NOT, prefix*")
    p.add_argument("--role", default=None, help="Filter by role (user, assistant, tool)")
    p.add_argument("--limit", type=int, default=30, help="Max matches to return")
    p.add_argument("--context", type=int, default=3, help="Surrounding turns to include per match")

    # recent-sessions
    p = sub.add_parser("recent-sessions")
    p.add_argument("--limit", type=int, default=10)

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
        "ingest-session": cmd_ingest_session,
        "ingest-turn": cmd_ingest_turn,
        "search-sessions": cmd_search_sessions,
        "recent-sessions": cmd_recent_sessions,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
