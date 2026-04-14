#!/usr/bin/env bash
# Hook: sessionStart — load user preferences and inject them as context.
# Copilot CLI pipes a JSON event on stdin; we read it, then query memory.

set -euo pipefail

MEMORY_CLI="$HOME/.copilot/skills/self-learning/resources/memory_cli.py"

# Only run if the memory CLI exists
if [[ ! -f "$MEMORY_CLI" ]]; then
  exit 0
fi

# Load active preferences and emit them as copilot-readable context
prefs=$(python3 "$MEMORY_CLI" query-prefs 2>/dev/null || echo "[]")
pref_count=$(echo "$prefs" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

if [[ "$pref_count" -gt 0 ]]; then
  cat <<EOF
{
  "message": "Self-learning: loaded $pref_count user preferences from memory.",
  "context": $prefs
}
EOF
fi
