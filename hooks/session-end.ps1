# Hook: sessionEnd — archive the session summary into the learning memory.
# Reads the session event JSON from stdin and stores a summary turn.

$ErrorActionPreference = "SilentlyContinue"

$memoryCli = Join-Path $HOME ".copilot\skills\self-learning\resources\memory_cli.py"

if (-not (Test-Path $memoryCli)) {
    exit 0
}

$event = $input | Out-String
if (-not $event) { exit 0 }

try {
    $parsed = $event | ConvertFrom-Json
    $sessionId = if ($parsed.sessionId) { $parsed.sessionId } elseif ($parsed.session_id) { $parsed.session_id } else { "unknown" }
    $summary = if ($parsed.summary) { $parsed.summary.Substring(0, [Math]::Min(500, $parsed.summary.Length)) } else { "Session ended" }
} catch {
    exit 0
}

if ($sessionId -ne "unknown") {
    python $memoryCli ingest-turn $sessionId system "Session ended. Summary: $summary" 2>$null
}
