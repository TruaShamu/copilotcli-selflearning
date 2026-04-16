#!/usr/bin/env bash
# Hook: sessionStart — load preferences AND memories, inject as context.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_CLI="$SCRIPT_DIR/../resources/memory_cli.py"

if [[ ! -f "$MEMORY_CLI" ]]; then
  exit 0
fi

# Read event from stdin to get cwd (repo path)
event=$(cat)

# Load preferences with decay scoring
prefs=$(python3 "$MEMORY_CLI" query-prefs --with-decay 2>/dev/null || echo "[]")
pref_count=$(echo "$prefs" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

# Load memories (summary mode groups by subject)
memories=$(python3 "$MEMORY_CLI" query-memory --summary --with-decay 2>/dev/null || echo "{}")
mem_count=$(echo "$memories" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(sum(v.get('count', 0) if isinstance(v, dict) else 0 for v in d.values()))
" 2>/dev/null || echo "0")

if [[ "$pref_count" -gt 0 || "$mem_count" -gt 0 ]]; then
  # Build combined context — pipe JSON through stdin to avoid quoting issues
  context=$(printf '%s\n%s' "$prefs" "$memories" | python3 -c "
import json, sys

raw = sys.stdin.read()
parts = raw.split('\n', 1)
# First part is prefs JSON array, second is memories JSON object
# But they may be multiline, so split smarter: find the boundary
# by parsing prefs first
import io
decoder = json.JSONDecoder()
prefs, idx = decoder.raw_decode(raw)
rest = raw[idx:].lstrip()
if rest:
    memories = json.loads(rest)
else:
    memories = {}

lines = []
if prefs:
    lines.append('## User Preferences')
    for p in prefs[:20]:
        cat = p.get('category', '?')
        fact = p.get('fact', '')
        lines.append(f'- [{cat}] {fact}')
if memories:
    lines.append('')
    lines.append('## Known Facts')
    for subject, data in memories.items():
        facts = data.get('facts', []) if isinstance(data, dict) else []
        for f in facts[:5]:
            lines.append(f'- [{subject}] {f}')
print(json.dumps('\n'.join(lines)))
" 2>/dev/null || echo '""')

  # Append session store instructions to context
  context=$(echo "$context" | python3 -c "
import sys, json
ctx = json.loads(sys.stdin.read())
session_hint = '''

## Session Store Recall

You have access to your full session history via the sql tool with database:'session_store'. When starting a new task, search for relevant past context using: SELECT content FROM search_index WHERE search_index MATCH 'relevant keywords' ORDER BY rank LIMIT 5. This helps you recall past approaches, mistakes, and solutions.'''
print(json.dumps(ctx + session_hint))
" 2>/dev/null || echo "$context")

  cat <<EOF
{
  "message": "Self-learning: loaded $pref_count preferences + $mem_count memories.",
  "additionalContext": $context
}
EOF
fi
