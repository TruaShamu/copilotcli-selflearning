# Hook: sessionStart — load user preferences and inject them as context.
# Copilot CLI pipes a JSON event on stdin; we read it, then query memory.

$ErrorActionPreference = "SilentlyContinue"

# Resolve memory_cli.py relative to this script (works for both plugin and manual installs)
$memoryCli = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\resources\memory_cli.py"

if (-not (Test-Path $memoryCli)) {
    exit 0
}

# Use --with-decay to filter stale prefs, sort by relevance, cap at top 20,
# and bump access counts for loaded prefs.
$prefs = python $memoryCli query-prefs --with-decay 2>$null
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
