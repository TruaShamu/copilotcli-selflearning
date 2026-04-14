# Install self-learning hooks to the user-level ~/.copilot/hooks/ directory.
# Run once after cloning the repo.

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$hooksSrc = Join-Path $scriptDir "hooks"
$hooksDest = Join-Path $HOME ".copilot\hooks"
$configPath = Join-Path $HOME ".copilot\config.json"

Write-Host "=== Self-Learning Hooks Installer ===" -ForegroundColor Cyan
Write-Host ""

# 1. Copy hook scripts
New-Item -ItemType Directory -Force -Path $hooksDest | Out-Null
foreach ($f in Get-ChildItem "$hooksSrc\*" -Include "*.sh","*.ps1") {
    $dest = Join-Path $hooksDest "self-learning-$($f.Name)"
    Copy-Item $f.FullName $dest -Force
    Write-Host "  ✓ Installed $dest" -ForegroundColor Green
}

# 2. Update config.json with hooks
if (-not (Test-Path $configPath)) {
    '{}' | Set-Content $configPath
}

python -c @"
import json

config_path = r'$configPath'
with open(config_path) as f:
    config = json.load(f)

# Copilot CLI expands ~ in hook paths per the config spec.
# See: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference
hooks_dir = '~/.copilot/hooks'

self_learning_hooks = {
    'sessionStart': [{
        'type': 'command',
        'bash': f'{hooks_dir}/self-learning-session-start.sh',
        'powershell': f'powershell -ExecutionPolicy Bypass -File {hooks_dir}/self-learning-session-start.ps1',
        'timeoutSec': 15
    }],
    'preToolUse': [{
        'type': 'command',
        'bash': f'{hooks_dir}/self-learning-pre-tool-use.sh',
        'powershell': f'powershell -ExecutionPolicy Bypass -File {hooks_dir}/self-learning-pre-tool-use.ps1',
        'timeoutSec': 10
    }],
    'postToolUse': [{
        'type': 'command',
        'bash': f'{hooks_dir}/self-learning-post-tool-use.sh',
        'powershell': f'powershell -ExecutionPolicy Bypass -File {hooks_dir}/self-learning-post-tool-use.ps1',
        'timeoutSec': 10
    }]
}

existing_hooks = config.get('hooks', {})
for event, hook_list in self_learning_hooks.items():
    if event not in existing_hooks:
        existing_hooks[event] = []
    existing_hooks[event] = [
        h for h in existing_hooks[event]
        if 'self-learning' not in h.get('bash', '')
    ]
    existing_hooks[event].extend(hook_list)

config['hooks'] = existing_hooks

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print('  \u2713 Updated ~/.copilot/config.json')
"@

Write-Host ""
Write-Host "Done! Self-learning hooks are now active globally." -ForegroundColor Green
Write-Host "Hooks will apply to all Copilot CLI sessions across all repos."
Write-Host ""
Write-Host "To uninstall: python $(Join-Path $scriptDir 'uninstall-hooks.py')"
