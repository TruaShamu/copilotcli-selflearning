#!/usr/bin/env bash
# Hook: postToolUse — track skill invocations in the learning log.
# Fires after every tool use. We filter to only log skill-related tools.

set -euo pipefail

MEMORY_CLI="$HOME/.copilot/skills/self-learning/resources/memory_cli.py"

if [[ ! -f "$MEMORY_CLI" ]]; then
  exit 0
fi

# Read the tool event from stdin
event=$(cat)

tool_name=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('toolName', e.get('tool_name', '')))
" 2>/dev/null || echo "")

# Only track skill invocations (the skill tool calls)
if [[ "$tool_name" != "skill" ]]; then
  exit 0
fi

skill_name=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
args = e.get('arguments', e.get('toolInput', {}))
if isinstance(args, str):
    import json as j
    args = j.loads(args)
print(args.get('skill', 'unknown'))
" 2>/dev/null || echo "unknown")

success=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
# Check for error indicators
if e.get('error') or e.get('toolResult', {}).get('isError'):
    print('failure')
else:
    print('success')
" 2>/dev/null || echo "success")

if [[ -n "$skill_name" && "$skill_name" != "unknown" ]]; then
  python3 "$MEMORY_CLI" log-skill "$skill_name" "$success" 2>/dev/null || true
fi
