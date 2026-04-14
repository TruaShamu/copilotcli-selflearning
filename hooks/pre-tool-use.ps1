# Hook: preToolUse — block repo-scoped store_memory calls.
#
# This project keeps all memory in local SQLite. The built-in store_memory
# tool writes to repo-scoped storage visible to all collaborators. This hook
# enforces the local-only policy by denying store_memory at the tool level.

$ErrorActionPreference = "SilentlyContinue"

$event = $input | Out-String
if (-not $event) { exit 0 }

try {
    $parsed = $event | ConvertFrom-Json
} catch {
    exit 0
}

$toolName = if ($parsed.toolName) { $parsed.toolName } elseif ($parsed.tool_name) { $parsed.tool_name } else { "" }

if ($toolName -eq "store_memory") {
    @{
        permissionDecision       = "deny"
        permissionDecisionReason = "Blocked by self-learning policy: all memory must stay in local SQLite (~/.copilot/self-learning/memory.db). Use memory_cli.py store-memory instead of repo-scoped store_memory."
    } | ConvertTo-Json -Compress
    exit 0
}
