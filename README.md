# Copilot CLI Self-Learning Skill

A meta-skill that gives GitHub Copilot CLI a closed learning loop with five
capabilities that compound over time:

1. **Skill auto-creation** — Distill complex sessions into reusable skills
2. **Skill self-improvement** — Revise skills after observing their use
3. **Memory nudges** — Proactively persist important facts
4. **Cross-session recall** — Search past sessions via FTS5 + LLM summarization
5. **User preference model** — Build a deepening model of preferences and workflow

## Installation

Copy this repo into your Copilot CLI user skills directory:

```bash
git clone https://github.com/TruaShamu/copilotcli-selflearning.git ~/.copilot/skills/self-learning
```

Then add the Self-Learning Protocol from `resources/AUTO-TRIGGER-GUIDE.md` to
your `~/.copilot/instructions.md`.

### Hooks (recommended)

Run the installer to set up user-level hooks that apply to **all repos**:

```bash
# Linux/macOS
bash install-hooks.sh

# Windows
powershell -ExecutionPolicy Bypass -File install-hooks.ps1
```

This copies hook scripts to `~/.copilot/hooks/` and registers them in
`~/.copilot/config.json`. Four hooks are installed:

| Hook | What it does |
|------|-------------|
| `preToolUse` | **Blocks** repo-scoped `store_memory` — enforces local-only policy |
| `sessionStart` | Auto-loads user preferences from memory |
| `sessionEnd` | Archives the session summary for future recall |
| `postToolUse` | Tracks skill invocations and outcomes |

Since hooks are user-level, they work across all repos without any per-project
setup. To uninstall: `python uninstall-hooks.py`

Repo-level hooks (`.github/hooks/`) are also included for teams that want to
layer project-specific policies on top.

## Requirements

- Python 3.9+ (for local SQLite memory store)
- GitHub Copilot CLI

## Architecture

All memory is local SQLite (`~/.copilot/self-learning/memory.db`). Nothing is
sent to any external service or repo-scoped storage.

See [SKILL.md](SKILL.md) for the full skill specification.

## License

MIT
