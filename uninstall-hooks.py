#!/usr/bin/env python3
"""Remove self-learning hooks from ~/.copilot/hooks/ and config.json."""

import json
import os
import glob

hooks_dir = os.path.expanduser("~/.copilot/hooks")
config_path = os.path.expanduser("~/.copilot/config.json")

# Remove hook scripts
removed = 0
for f in glob.glob(os.path.join(hooks_dir, "self-learning-*")):
    os.remove(f)
    print(f"  ✓ Removed {f}")
    removed += 1

# Clean config.json
if os.path.exists(config_path):
    with open(config_path) as f:
        config = json.load(f)
    hooks = config.get("hooks", {})
    for event in list(hooks.keys()):
        hooks[event] = [
            h for h in hooks[event]
            if "self-learning" not in h.get("bash", "")
        ]
        if not hooks[event]:
            del hooks[event]
    if hooks:
        config["hooks"] = hooks
    elif "hooks" in config:
        del config["hooks"]
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print("  ✓ Cleaned ~/.copilot/config.json")

print(f"\nRemoved {removed} hook scripts.")
