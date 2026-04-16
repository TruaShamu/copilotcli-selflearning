# Hook: sessionEnd — extract memories, preferences, and skill candidates from
# the completed session transcript using LLM analysis.
# This is fire-and-forget (output is ignored by Copilot CLI).

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MemoryCli = Join-Path $ScriptDir "..\resources\memory_cli.py"

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

try {
    $exitReason = $event | python3 -c "
import sys, json
e = json.load(sys.stdin)
print(e.get('exitReason', e.get('reason', 'unknown')))
"
} catch {
    $exitReason = "unknown"
}

if ($sessionId -eq "unknown") {
    exit 0
}

# Skip aborted/error sessions — not worth extracting
if ($exitReason -eq "abort" -or $exitReason -eq "error") {
    exit 0
}

# Run extraction (calls LLM, deduplicates, stores)
try {
    python3 $MemoryCli extract-session $sessionId 2>$null
} catch {
    # Fire and forget
}

# Clean up reflection flag files older than 1 day
$selfLearningDir = Join-Path $env:USERPROFILE ".copilot\self-learning"
if (Test-Path $selfLearningDir) {
    Get-ChildItem -Path $selfLearningDir -Filter ".reflected_*" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-1) } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}
