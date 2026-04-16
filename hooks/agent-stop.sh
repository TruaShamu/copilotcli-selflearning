#!/usr/bin/env bash  
# Hook: agentStop — force self-reflection on complex sessions.
# Blocks the agent if it completed a complex workflow without a skill.
# Zero LLM cost — all local SQLite queries.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_CLI="$SCRIPT_DIR/../resources/memory_cli.py"
STATE_DIR="${HOME}/.copilot/self-learning"

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

if [[ "$session_id" == "unknown" ]]; then
  exit 0
fi

# Check if we already reflected this session (once per session)
reflect_flag="$STATE_DIR/.reflected_${session_id}"
if [[ -f "$reflect_flag" ]]; then
  exit 0
fi

# Get session stats
stats=$(python3 "$MEMORY_CLI" session-stats "$session_id" 2>/dev/null || echo '{}')

is_complex=$(echo "$stats" | python3 -c "
import sys, json
s = json.load(sys.stdin)
# Complex = 5+ tool calls AND no skill used
print('1' if s.get('complex_session', False) else '0')
" 2>/dev/null || echo "0")

if [[ "$is_complex" == "1" ]]; then
  # Mark as reflected so we don't block again
  mkdir -p "$STATE_DIR"
  touch "$reflect_flag"
  
  tool_count=$(echo "$stats" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_count', 0))" 2>/dev/null || echo "0")
  unique_tools=$(echo "$stats" | python3 -c "
import sys, json
tools = json.load(sys.stdin).get('unique_tools', [])
print(', '.join(tools[:10]))
" 2>/dev/null || echo "")

  cat <<EOF
{
  "decision": "block",
  "reason": "Self-reflection checkpoint: You just completed a complex workflow ($tool_count tool calls using: $unique_tools) with no matching skill.\n\nBefore finishing, please:\n1. Store any new facts you learned: python3 $MEMORY_CLI store-memory <subject> <fact>\n2. Store any user preferences you noticed: python3 $MEMORY_CLI store-pref <category> <fact>\n3. If this workflow is reusable, create a skill file in skills/<name>/SKILL.md\n\nThen continue with your response."
}
EOF
  exit 0
fi
