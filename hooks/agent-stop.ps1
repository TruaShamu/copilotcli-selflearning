# Hook: agentStop — force self-reflection on complex sessions.
# Blocks the agent if it completed a complex workflow without a skill.
# Zero LLM cost — all local SQLite queries.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MemoryCli = Join-Path $ScriptDir "..\resources\memory_cli.py"
$StateDir = Join-Path $env:USERPROFILE ".copilot\self-learning"

if (-not (Test-Path $MemoryCli)) {
    exit 0
}

# Read event from stdin
$event = $input | Out-String
try {
    $sessionId = $event | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('sessionId', e.get('session_id', 'unknown')))
"
} catch {
    $sessionId = "unknown"
}

if ($sessionId -eq "unknown") {
    exit 0
}

# Check if we already reflected this session (once per session)
$reflectFlag = Join-Path $StateDir ".reflected_$sessionId"
if (Test-Path $reflectFlag) {
    exit 0
}

# Get session stats
try {
    $stats = python3 $MemoryCli session-stats $sessionId 2>$null
} catch {
    $stats = "{}"
}

try {
    $isComplex = $stats | python3 -c "
import sys, json
s = json.load(sys.stdin)
print('1' if s.get('complex_session', False) else '0')
"
} catch {
    $isComplex = "0"
}

if ($isComplex -eq "1") {
    # Mark as reflected so we don't block again
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    New-Item -ItemType File -Path $reflectFlag -Force | Out-Null

    try {
        $toolCount = $stats | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_count', 0))"
    } catch {
        $toolCount = "0"
    }

    try {
        $uniqueTools = $stats | python3 -c "
import sys, json
tools = json.load(sys.stdin).get('unique_tools', [])
print(', '.join(tools[:10]))
"
    } catch {
        $uniqueTools = ""
    }

    @"
{
  "decision": "block",
  "reason": "Self-reflection checkpoint: You just completed a complex workflow ($toolCount tool calls using: $uniqueTools) with no matching skill.\n\nBefore finishing, please:\n1. Store any new facts you learned: python3 $MemoryCli store-memory <subject> <fact>\n2. Store any user preferences you noticed: python3 $MemoryCli store-pref <category> <fact>\n3. If this workflow is reusable, ASK THE USER if they'd like to save it as a skill before creating one. Only create .github/skills/<name>/SKILL.md if the user confirms. (Frontmatter: name, description, user-invocable only — NO version or trigger fields)\n\nThen continue with your response."
}
"@
    exit 0
}
