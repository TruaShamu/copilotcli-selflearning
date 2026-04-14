# Hook: postToolUse — track skill invocations in the learning log.
# Fires after every tool use. We filter to only log skill-related tools.

$ErrorActionPreference = "SilentlyContinue"

$memoryCli = Join-Path $HOME ".copilot\skills\self-learning\resources\memory_cli.py"

if (-not (Test-Path $memoryCli)) {
    exit 0
}

$event = $input | Out-String
if (-not $event) { exit 0 }

try {
    $parsed = $event | ConvertFrom-Json
} catch {
    exit 0
}

$toolName = if ($parsed.toolName) { $parsed.toolName } elseif ($parsed.tool_name) { $parsed.tool_name } else { "" }

# Only track skill invocations
if ($toolName -ne "skill") {
    exit 0
}

$skillName = "unknown"
try {
    $args = $parsed.arguments
    if (-not $args) { $args = $parsed.toolInput }
    if ($args -is [string]) { $args = $args | ConvertFrom-Json }
    if ($args.skill) { $skillName = $args.skill }
} catch {}

$outcome = "success"
if ($parsed.error -or ($parsed.toolResult -and $parsed.toolResult.isError)) {
    $outcome = "failure"
}

if ($skillName -ne "unknown") {
    python $memoryCli log-skill $skillName $outcome 2>$null
}
