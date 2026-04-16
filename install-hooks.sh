#!/usr/bin/env bash
# Install self-learning hooks to the user-level ~/.copilot/ directory.
# Handles: hook script copying, config.json hook registration, SESSION_STORE flag.
# Run once after cloning the repo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOKS_SRC="$SCRIPT_DIR/hooks"
HOOKS_DEST="$HOME/.copilot/hooks"
CONFIG="$HOME/.copilot/config.json"
GITHUB_HOOKS_DIR="$SCRIPT_DIR/.github/hooks"

echo "=== Self-Learning Hooks Installer ==="
echo ""

# 1. Copy hook scripts
mkdir -p "$HOOKS_DEST"
for f in "$HOOKS_SRC"/*.sh "$HOOKS_SRC"/*.ps1; do
  [ -f "$f" ] || continue
  base="$(basename "$f")"
  dest="$HOOKS_DEST/self-learning-$base"
  cp "$f" "$dest"
  chmod +x "$dest" 2>/dev/null || true
  echo "  ✓ Installed $dest"
done

# 2. Copy .github/hooks config if present
if [ -f "$GITHUB_HOOKS_DIR/self-learning.json" ]; then
  echo "  ✓ Found .github/hooks/self-learning.json (repo-level hook config)"
fi

# 3. Update config.json with hooks + SESSION_STORE flag
if [ ! -f "$CONFIG" ]; then
  echo '{}' > "$CONFIG"
fi

python3 -c "
import json, sys

config_path = '$CONFIG'
with open(config_path) as f:
    config = json.load(f)

# Copilot CLI expands ~ in hook paths per the config spec.
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
    }],
    'agentStop': [{
        'type': 'command',
        'bash': f'{hooks_dir}/self-learning-agent-stop.sh',
        'timeoutSec': 10
    }],
    'sessionEnd': [{
        'type': 'command',
        'bash': f'{hooks_dir}/self-learning-session-end.sh',
        'timeoutSec': 30
    }]
}

# Merge: append self-learning hooks to any existing hooks
existing_hooks = config.get('hooks', {})
for event, hook_list in self_learning_hooks.items():
    if event not in existing_hooks:
        existing_hooks[event] = []
    # Remove any previous self-learning hooks (idempotent reinstall)
    existing_hooks[event] = [
        h for h in existing_hooks[event]
        if 'self-learning' not in h.get('bash', '')
    ]
    existing_hooks[event].extend(hook_list)

config['hooks'] = existing_hooks

# Enable SESSION_STORE feature flag for cross-session recall
features = config.get('features', {})
if 'SESSION_STORE' not in features:
    features['SESSION_STORE'] = True
    print('  ✓ Enabled SESSION_STORE feature flag')
else:
    print('  ✓ SESSION_STORE feature flag already set')
config['features'] = features

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print('  ✓ Updated ~/.copilot/config.json (5 hooks registered)')
"

echo ""
echo "Done! Self-learning hooks are now active globally."
echo "Hooks installed: sessionStart, preToolUse, postToolUse, agentStop, sessionEnd"
echo ""
echo "Skills: Place skills in .github/skills/<name>/SKILL.md for auto-discovery."
echo ""
echo "To uninstall: python3 $(dirname "$0")/uninstall-hooks.py"
