# Hook: sessionStart — load user preferences and inject them as context.
# Copilot CLI pipes a JSON event on stdin; we read it, then query memory.

$ErrorActionPreference = "SilentlyContinue"

$memoryCli = Join-Path $HOME ".copilot\skills\self-learning\resources\memory_cli.py"

if (-not (Test-Path $memoryCli)) {
    exit 0
}

$prefs = python $memoryCli query-prefs 2>$null
if (-not $prefs) { exit 0 }

try {
    $parsed = $prefs | ConvertFrom-Json
    $count = $parsed.Count
} catch {
    exit 0
}

if ($count -gt 0) {
    @{
        message = "Self-learning: loaded $count user preferences from memory."
        context = $parsed
    } | ConvertTo-Json -Depth 5
}
