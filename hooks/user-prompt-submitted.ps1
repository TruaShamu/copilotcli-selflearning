# Hook: userPromptSubmitted — search memory for relevant context on every prompt.
# Zero LLM cost — pure FTS5 search.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MemoryCli = Join-Path $ScriptDir "..\resources\memory_cli.py"

if (-not (Test-Path $MemoryCli)) {
    exit 0
}

# Read the event to get the user's prompt
$event = $input | Out-String
try {
    $prompt = $event | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('userPrompt', e.get('prompt', '')))
"
} catch {
    $prompt = ""
}

# Skip very short prompts (< 10 chars) — not enough signal
if ($prompt.Length -lt 10) {
    exit 0
}

# Search memories + preferences for anything relevant
try {
    $result = python3 $MemoryCli search-context $prompt --limit 5 2>$null
} catch {
    $result = '{"matches": []}'
}

try {
    $matchCount = $result | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('matches',[])))"
} catch {
    $matchCount = "0"
}

if ([int]$matchCount -gt 0) {
    # Format matches as readable context
    try {
        $context = $result | python3 -c @"
import sys, json
data = json.load(sys.stdin)
lines = ['Relevant context from memory:']
for m in data.get('matches', []):
    mtype = m.get('type', 'unknown')
    if mtype == 'memory':
        lines.append(f"  - [{m.get('subject', '?')}] {m['fact']}")
    elif mtype == 'preference':
        lines.append(f"  - [pref:{m.get('category', '?')}] {m['fact']}")
print(json.dumps('\n'.join(lines)))
"@
    } catch {
        $context = '""'
    }

    @"
{
  "additionalContext": $context
}
"@
}
