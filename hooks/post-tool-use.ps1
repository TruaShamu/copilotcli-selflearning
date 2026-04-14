# Hook: postToolUse — log every tool invocation per session for sequence analysis,
# and track skill invocations separately in skill_usage.

$ErrorActionPreference = "SilentlyContinue"

# Resolve memory_cli.py relative to this script (works for both plugin and manual installs)
$memoryCli = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\resources\memory_cli.py"

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

# Event field is 'toolName' per Copilot CLI hook schema.
# Fallback to 'tool_name' for forward-compat if the schema changes.
$toolName = if ($parsed.toolName) { $parsed.toolName } elseif ($parsed.tool_name) { $parsed.tool_name } else { "" }
$sessionId = if ($parsed.sessionId) { $parsed.sessionId } elseif ($parsed.session_id) { $parsed.session_id } else { "unknown" }

$isError = $parsed.error -or ($parsed.toolResult -and $parsed.toolResult.isError)

# Log every tool call to the sequence table
if ($toolName -and $sessionId -ne "unknown") {
    $logArgs = @($sessionId, $toolName)
    if ($isError) { $logArgs += "--failed" }
    python $memoryCli log-tool @logArgs 2>$null
}

# Additionally track skill invocations in skill_usage
if ($toolName -eq "skill") {
    $skillName = "unknown"
    try {
        $toolArgs = $parsed.arguments
        if (-not $toolArgs) { $toolArgs = $parsed.toolInput }
        if ($toolArgs -is [string]) { $toolArgs = $toolArgs | ConvertFrom-Json }
        if ($toolArgs.skill) { $skillName = $toolArgs.skill }
    } catch {}

    # Hook can only detect success/failure from the event JSON.
    # The other outcomes (partial, skipped) are only available via manual
    # invocation of memory_cli.py log-skill.
    $outcome = if ($isError) { "failure" } else { "success" }

    if ($skillName -ne "unknown") {
        python $memoryCli log-skill $skillName $outcome 2>$null
    }
}
