#!/usr/bin/env bash
# Hook: sessionEnd — extract memories, preferences, and skill candidates from
# the completed session transcript using LLM analysis.
# This is fire-and-forget (output is ignored by Copilot CLI).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_CLI="$SCRIPT_DIR/../resources/memory_cli.py"

if [[ ! -f "$MEMORY_CLI" ]]; then
  exit 0
fi

# Read event
event=$(cat)
session_id=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('sessionId', e.get('session_id', 'unknown')))
" 2>/dev/null || echo "unknown")

exit_reason=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('exitReason', e.get('reason', 'unknown')))
" 2>/dev/null || echo "unknown")

if [[ "$session_id" == "unknown" ]]; then
  exit 0
fi

# Skip aborted/error sessions — not worth extracting
if [[ "$exit_reason" == "abort" || "$exit_reason" == "error" ]]; then
  exit 0
fi

# Run extraction (calls LLM, deduplicates, stores)
python3 "$MEMORY_CLI" extract-session "$session_id" 2>/dev/null || true

# Clean up reflection flag files older than 1 day
find "${HOME}/.copilot/self-learning/" -name '.reflected_*' -mtime +1 -delete 2>/dev/null || true
