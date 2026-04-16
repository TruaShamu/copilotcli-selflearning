#!/usr/bin/env python3
"""Session-end reflection — extracts memories, preferences, and skill candidates
from a completed session transcript using a lightweight LLM pass.

Called by the sessionEnd hook. Reads the session transcript from Copilot CLI's
native session store, sends it through an LLM for structured extraction, deduplicates
against existing knowledge, and stores new findings via memory_cli.py.

Usage:
    python reflect.py --session-id <uuid>
    python reflect.py --latest --cwd /path/to/project

Environment:
    Requires OPENAI_API_KEY or AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY.
    Falls back gracefully (exit 0) if no LLM credentials are configured.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NATIVE_SESSION_STORE = os.path.expanduser("~/.copilot/session-store.db")
MEMORY_DB = os.path.expanduser("~/.copilot/self-learning/memory.db")
MEMORY_CLI = str(Path(__file__).parent / "memory_cli.py")

# Reflection model — fast and cheap, reflection is extraction not reasoning
REFLECT_MODEL = os.environ.get("REFLECT_MODEL", "gpt-4o-mini")

# Only store items above this confidence
CONFIDENCE_THRESHOLD = 0.8

# Skip sessions shorter than this many turns
MIN_TURNS = 3

# Max turns to include in the transcript (to stay within token budget)
MAX_TURNS = 30

# Max characters per turn message
MAX_CHARS_PER_TURN = 2000

# ---------------------------------------------------------------------------
# Session transcript loading
# ---------------------------------------------------------------------------


def _open_session_store():
    """Open the native session store read-only. Returns None if missing."""
    if not os.path.exists(NATIVE_SESSION_STORE):
        return None
    conn = sqlite3.connect(f"file:{NATIVE_SESSION_STORE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_transcript(session_id: str | None, cwd: str | None) -> dict | None:
    """Load a session transcript from the native store.

    If session_id is provided, load that session directly.
    Otherwise, find the most recent session matching cwd.
    Returns {session_id, repository, branch, turns: [{role, content}]} or None.
    """
    conn = _open_session_store()
    if not conn:
        return None

    try:
        if session_id:
            session = conn.execute(
                "SELECT id, repository, branch, cwd FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        elif cwd:
            session = conn.execute(
                "SELECT id, repository, branch, cwd FROM sessions "
                "WHERE cwd = ? ORDER BY updated_at DESC LIMIT 1",
                (cwd,),
            ).fetchone()
        else:
            session = conn.execute(
                "SELECT id, repository, branch, cwd FROM sessions "
                "ORDER BY updated_at DESC LIMIT 1",
            ).fetchone()

        if not session:
            return None

        rows = conn.execute(
            "SELECT turn_index, user_message, assistant_response "
            "FROM turns WHERE session_id = ? ORDER BY turn_index",
            (session["id"],),
        ).fetchall()

        if len(rows) < MIN_TURNS:
            return None

        # Build turn list, truncating if needed
        turns = []
        selected_rows = rows
        if len(rows) > MAX_TURNS:
            # Keep first 3 turns (intent) + last (MAX_TURNS - 3) turns (outcome)
            selected_rows = list(rows[:3]) + list(rows[-(MAX_TURNS - 3):])

        for row in selected_rows:
            if row["user_message"]:
                turns.append({
                    "role": "user",
                    "content": row["user_message"][:MAX_CHARS_PER_TURN],
                })
            if row["assistant_response"]:
                turns.append({
                    "role": "assistant",
                    "content": row["assistant_response"][:MAX_CHARS_PER_TURN],
                })

        return {
            "session_id": session["id"],
            "repository": session["repository"],
            "branch": session["branch"],
            "turns": turns,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dedup — check existing knowledge via direct SQLite reads
# ---------------------------------------------------------------------------


def _open_memory_db():
    """Open the self-learning memory DB read-only for dedup checks."""
    if not os.path.exists(MEMORY_DB):
        return None
    conn = sqlite3.connect(f"file:{MEMORY_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _existing_memory_facts() -> set[str]:
    """Return a set of existing memory facts (lowercased) for dedup."""
    conn = _open_memory_db()
    if not conn:
        return set()
    try:
        rows = conn.execute("SELECT fact FROM personal_memory").fetchall()
        return {row["fact"].lower().strip() for row in rows}
    finally:
        conn.close()


def _existing_pref_facts() -> set[str]:
    """Return a set of existing preference facts (lowercased) for dedup."""
    conn = _open_memory_db()
    if not conn:
        return set()
    try:
        rows = conn.execute(
            "SELECT fact FROM preferences WHERE superseded_by IS NULL"
        ).fetchall()
        return {row["fact"].lower().strip() for row in rows}
    finally:
        conn.close()


def is_duplicate_memory(fact: str, existing: set[str]) -> bool:
    """Check if a memory fact is substantially similar to an existing one."""
    normalized = fact.lower().strip()
    if normalized in existing:
        return True
    # Substring match — catches "repo uses pnpm" vs "this repo uses pnpm"
    for ex in existing:
        if normalized in ex or ex in normalized:
            return True
    return False


# ---------------------------------------------------------------------------
# Opt-out check
# ---------------------------------------------------------------------------


def is_reflection_disabled() -> bool:
    """Check if the user has disabled auto-reflection via a preference."""
    conn = _open_memory_db()
    if not conn:
        return False
    try:
        rows = conn.execute(
            "SELECT fact FROM preferences "
            "WHERE category = 'plugin-setting' AND superseded_by IS NULL"
        ).fetchall()
        for row in rows:
            if "auto_reflect" in row["fact"].lower() and "false" in row["fact"].lower():
                return True
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# LLM reflection
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a reflection engine for a developer's coding assistant. You analyze a
completed session transcript and extract structured learnings.

Extract ONLY things that would be useful in FUTURE sessions:
- Project facts: repo conventions, tool versions, gotchas, architecture decisions
- User preferences: code style, workflow habits, tool choices
- Skill candidates: multi-step workflows (3+ phases) that could be automated

Rules:
- Only extract facts with high confidence (you are very sure they are true)
- Do NOT extract ephemeral information (today's bug, a one-time task)
- Do NOT extract things obvious from code (language, framework) unless there's
  a non-obvious convention
- Prefer specific, actionable facts over vague observations
- For preferences, distinguish explicit statements ("I prefer X") from implicit
  patterns (consistently doing X)
"""

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Topic category (e.g., 'git-workflow', 'testing', 'deploy')"},
                    "fact": {"type": "string", "description": "The specific fact to remember"},
                    "confidence": {"type": "number", "description": "0.0 to 1.0"},
                },
                "required": ["subject", "fact", "confidence"],
            },
        },
        "preferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Preference category (e.g., 'code-style', 'workflow', 'tooling')"},
                    "fact": {"type": "string", "description": "The preference"},
                    "confidence": {"type": "number", "description": "0.0 to 1.0 — higher for explicit statements"},
                },
                "required": ["category", "fact", "confidence"],
            },
        },
        "skill_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short skill name"},
                    "description": {"type": "string", "description": "What the skill automates"},
                    "phases": {"type": "string", "description": "Comma-separated workflow phases"},
                },
                "required": ["name", "description", "phases"],
            },
        },
    },
    "required": ["memories", "preferences", "skill_candidates"],
}


def reflect_on_transcript(turns: list[dict]) -> dict | None:
    """Send the transcript to an LLM and extract structured learnings."""
    # Import LLM client from the evolution engine (supports OpenAI + Azure)
    sys.path.insert(0, str(Path(__file__).parent.parent / "evolution"))
    try:
        from llm_client import create_client, resolve_model
    except ImportError:
        # Fallback: try direct openai import
        try:
            from openai import OpenAI
            create_client = OpenAI
            resolve_model = lambda m: m  # noqa: E731
        except ImportError:
            return None

    try:
        client = create_client()
    except Exception:
        return None

    model = resolve_model(REFLECT_MODEL)

    # Build the transcript text
    transcript_lines = []
    for turn in turns:
        role = turn["role"].upper()
        content = turn["content"]
        transcript_lines.append(f"[{role}]: {content}")
    transcript_text = "\n\n".join(transcript_lines)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Session transcript:\n\n{transcript_text}"},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "session_reflection",
                    "strict": True,
                    "schema": EXTRACTION_SCHEMA,
                },
            },
            temperature=0.2,
            timeout=25,
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Storage — use memory_cli.py as the write interface
# ---------------------------------------------------------------------------


def _run_memory_cli(*args: str) -> bool:
    """Run a memory_cli.py command. Returns True on success."""
    try:
        subprocess.run(
            [sys.executable, MEMORY_CLI, *args],
            capture_output=True,
            timeout=10,
        )
        return True
    except Exception:
        return False


def store_results(
    results: dict,
    session_id: str,
    repository: str | None,
) -> dict:
    """Store reflection results via memory_cli.py. Returns a summary."""
    existing_memories = _existing_memory_facts()
    existing_prefs = _existing_pref_facts()

    summary = {"memories_stored": 0, "prefs_stored": 0, "skills_flagged": 0, "skipped_dup": 0}

    # Store memories
    for mem in results.get("memories", []):
        if mem.get("confidence", 0) < CONFIDENCE_THRESHOLD:
            continue
        if is_duplicate_memory(mem["fact"], existing_memories):
            summary["skipped_dup"] += 1
            continue
        cmd = ["store-memory", mem["subject"], mem["fact"]]
        if repository:
            cmd.extend(["--repo", repository])
        if _run_memory_cli(*cmd):
            summary["memories_stored"] += 1
            existing_memories.add(mem["fact"].lower().strip())

    # Store preferences
    for pref in results.get("preferences", []):
        if pref.get("confidence", 0) < CONFIDENCE_THRESHOLD:
            continue
        if is_duplicate_memory(pref["fact"], existing_prefs):
            summary["skipped_dup"] += 1
            continue
        confidence = str(pref.get("confidence", 0.8))
        cmd = [
            "store-pref", pref["category"], pref["fact"],
            "--confidence", confidence,
            "--source", f"auto-reflect:{session_id}",
        ]
        if _run_memory_cli(*cmd):
            summary["prefs_stored"] += 1
            existing_prefs.add(pref["fact"].lower().strip())

    # Flag skill candidates via learning_log
    for skill in results.get("skill_candidates", []):
        cmd = [
            "log-learning",
            skill.get("description", "unnamed workflow"),
            skill.get("phases", "unknown"),
            "0",
            "--candidate",
        ]
        if repository:
            cmd.extend(["--repo", repository])
        if _run_memory_cli(*cmd):
            summary["skills_flagged"] += 1

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Session-end reflection engine")
    parser.add_argument("--session-id", help="Session ID to reflect on")
    parser.add_argument("--cwd", help="Working directory (fallback to find most recent session)")
    parser.add_argument("--latest", action="store_true", help="Reflect on the most recent session")
    parser.add_argument("--dry-run", action="store_true", help="Extract but don't store")
    args = parser.parse_args()

    # Check opt-out
    if is_reflection_disabled():
        return

    # Check LLM credentials
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_azure = bool(
        os.environ.get("AZURE_OPENAI_ENDPOINT")
        and os.environ.get("AZURE_OPENAI_API_KEY")
    )
    if not has_openai and not has_azure:
        return

    # Load transcript
    session_id = args.session_id
    cwd = args.cwd if not session_id else None
    transcript = load_transcript(session_id, cwd)
    if not transcript:
        return

    # Reflect
    results = reflect_on_transcript(transcript["turns"])
    if not results:
        return

    if args.dry_run:
        print(json.dumps(results, indent=2))
        return

    # Store
    summary = store_results(
        results,
        session_id=transcript["session_id"],
        repository=transcript.get("repository"),
    )

    # Output summary for hook logging (won't be shown to user)
    if any(v > 0 for v in summary.values()):
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
