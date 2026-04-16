#!/usr/bin/env bash
# Hook: postToolUse — log every tool invocation per session for sequence analysis,
# and track skill invocations separately in skill_usage.

set -euo pipefail

# Resolve memory_cli.py relative to this script (works for both plugin and manual installs)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_CLI="$SCRIPT_DIR/../resources/memory_cli.py"

if [[ ! -f "$MEMORY_CLI" ]]; then
  exit 0
fi

# Read the tool event from stdin
event=$(cat)

# Event field is 'toolName' per Copilot CLI hook schema.
# Fallback to 'tool_name' for forward-compat if the schema changes.
tool_name=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('toolName', e.get('tool_name', '')))
" 2>/dev/null || echo "")

session_id=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('sessionId', e.get('session_id', 'unknown')))
" 2>/dev/null || echo "unknown")

is_error=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
if e.get('error') or e.get('toolResult', {}).get('isError'):
    print('1')
else:
    print('0')
" 2>/dev/null || echo "0")

# Log every tool call to the sequence table
if [[ -n "$tool_name" && "$session_id" != "unknown" ]]; then
  failed_flag=""
  if [[ "$is_error" == "1" ]]; then
    failed_flag="--failed"
  fi
  python3 "$MEMORY_CLI" log-tool "$session_id" "$tool_name" $failed_flag 2>/dev/null || true
fi

# Additionally track skill invocations in skill_usage
if [[ "$tool_name" == "skill" ]]; then
  skill_name=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
args = e.get('arguments', e.get('toolInput', {}))
if isinstance(args, str):
    args = json.loads(args)
print(args.get('skill', 'unknown'))
" 2>/dev/null || echo "unknown")

  # Hook can only detect success/failure from the event JSON.
  # The other outcomes (partial, skipped) are only available via manual
  # invocation of memory_cli.py log-skill.
  outcome="success"
  if [[ "$is_error" == "1" ]]; then
    outcome="failure"
  fi

  if [[ "$skill_name" != "unknown" ]]; then
    python3 "$MEMORY_CLI" log-skill "$skill_name" "$outcome" 2>/dev/null || true
  fi
fi
