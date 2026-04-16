#!/usr/bin/env bash
# Hook: userPromptSubmitted — search memory for relevant context on every prompt.
# Zero LLM cost — pure FTS5 search.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_CLI="$SCRIPT_DIR/../resources/memory_cli.py"

if [[ ! -f "$MEMORY_CLI" ]]; then
  exit 0
fi

# Read the event to get the user's prompt
event=$(cat)
prompt=$(echo "$event" | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('userPrompt', e.get('prompt', '')))
" 2>/dev/null || echo "")

# Skip very short prompts (< 10 chars) — not enough signal
if [[ ${#prompt} -lt 10 ]]; then
  exit 0
fi

# Search memories + preferences for anything relevant
result=$(python3 "$MEMORY_CLI" search-context "$prompt" --limit 5 2>/dev/null || echo '{"matches": []}')
match_count=$(echo "$result" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('matches',[])))" 2>/dev/null || echo "0")

if [[ "$match_count" -gt 0 ]]; then
  # Format matches as readable context
  context=$(echo "$result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
lines = ['Relevant context from memory:']
for m in data.get('matches', []):
    mtype = m.get('type', 'unknown')
    if mtype == 'memory':
        lines.append(f\"  - [{m.get('subject', '?')}] {m['fact']}\")
    elif mtype == 'preference':
        lines.append(f\"  - [pref:{m.get('category', '?')}] {m['fact']}\")
print(json.dumps('\\n'.join(lines)))
" 2>/dev/null || echo '""')

  cat <<EOF
{
  "additionalContext": $context
}
EOF
fi
