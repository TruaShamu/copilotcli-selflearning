#!/usr/bin/env bash
# Hook: sessionEnd — archive the session summary into the learning memory.
# Reads the session event JSON from stdin and stores a summary turn.

set -euo pipefail

# Resolve memory_cli.py relative to this script (works for both plugin and manual installs)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_CLI="$SCRIPT_DIR/../resources/memory_cli.py"

if [[ ! -f "$MEMORY_CLI" ]]; then
  exit 0
fi

# Read the session event from stdin
event=$(cat)

session_id=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('sessionId', e.get('session_id', 'unknown')))
" 2>/dev/null || echo "unknown")

summary=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('summary', e.get('message', 'Session ended'))[:500])
" 2>/dev/null || echo "Session ended")

if [[ "$session_id" != "unknown" ]]; then
  python3 "$MEMORY_CLI" ingest-turn "$session_id" system \
    "Session ended. Summary: $summary" 2>/dev/null || true
fi
