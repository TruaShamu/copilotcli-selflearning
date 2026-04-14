#!/usr/bin/env bash
# Hook: preToolUse — block repo-scoped store_memory calls.
#
# This project keeps all memory in local SQLite. The built-in store_memory
# tool writes to repo-scoped storage visible to all collaborators. This hook
# enforces the local-only policy by denying store_memory at the tool level.

set -euo pipefail

event=$(cat)

tool_name=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('toolName', e.get('tool_name', '')))
" 2>/dev/null || echo "")

if [[ "$tool_name" == "store_memory" ]]; then
  cat <<'EOF'
{
  "permissionDecision": "deny",
  "permissionDecisionReason": "Blocked by self-learning policy: all memory must stay in local SQLite (~/.copilot/self-learning/memory.db). Use memory_cli.py store-memory instead of repo-scoped store_memory."
}
EOF
  exit 0
fi
