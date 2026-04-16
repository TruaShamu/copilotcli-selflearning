#!/usr/bin/env bash
# Hook: sessionEnd — auto-reflect on the completed session.
# Extracts memories, preferences, and skill candidates via a lightweight LLM pass.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REFLECT="$SCRIPT_DIR/../resources/reflect.py"

if [[ ! -f "$REFLECT" ]]; then
  exit 0
fi

# Read the hook event from stdin
event=$(cat)

# Extract session ID and cwd from the event JSON
session_id=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('sessionId', e.get('session_id', '')))
" 2>/dev/null || echo "")

cwd=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('cwd', ''))
" 2>/dev/null || echo "")

# Build args — prefer session ID, fall back to cwd, then --latest
args=()
if [[ -n "$session_id" ]]; then
  args+=(--session-id "$session_id")
elif [[ -n "$cwd" ]]; then
  args+=(--cwd "$cwd")
else
  args+=(--latest)
fi

# Run reflection (fire-and-forget, never block the CLI)
python3 "$REFLECT" "${args[@]}" 2>/dev/null || true
