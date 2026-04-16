# Hook: sessionEnd — auto-reflect on the completed session.
# Extracts memories, preferences, and skill candidates via a lightweight LLM pass.

$ErrorActionPreference = "SilentlyContinue"

$reflectScript = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\resources\reflect.py"

if (-not (Test-Path $reflectScript)) {
    exit 0
}

# Read the hook event from stdin
$event = $input | Out-String
if (-not $event) { exit 0 }

try {
    $parsed = $event | ConvertFrom-Json
} catch {
    exit 0
}

# Extract session ID and cwd from the event JSON
$sessionId = if ($parsed.sessionId) { $parsed.sessionId } elseif ($parsed.session_id) { $parsed.session_id } else { "" }
$cwd = if ($parsed.cwd) { $parsed.cwd } else { "" }

# Build args — prefer session ID, fall back to cwd, then --latest
$args = @()
if ($sessionId) {
    $args += "--session-id", $sessionId
} elseif ($cwd) {
    $args += "--cwd", $cwd
} else {
    $args += "--latest"
}

# Run reflection (fire-and-forget, never block the CLI)
python $reflectScript @args 2>$null
