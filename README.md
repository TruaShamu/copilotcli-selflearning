# Copilot CLI Self-Learning Skill

A meta-skill that gives GitHub Copilot CLI a closed learning loop with five
capabilities that compound over time:

1. **Skill auto-creation** — Distill complex sessions into reusable skills
2. **Skill self-improvement** — Revise skills after observing their use
3. **Memory nudges** — Proactively persist important facts
4. **Cross-session recall** — Search past sessions via FTS5 + LLM summarization
5. **User preference model** — Build a deepening model of preferences and workflow

## Installation

### As a plugin (recommended)

> **Note**: Plugin install support requires Copilot CLI with plugin support
> enabled. Check [GitHub docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-finding-installing) for availability.

```bash
copilot plugin install TruaShamu/copilotcli-selflearning
```

That's it. The plugin registers skills, hooks, and resources automatically.
Works at user level across all repos.

To update: `copilot plugin update self-learning`
To remove: `copilot plugin uninstall self-learning`

### Manual install

Clone into your Copilot CLI user skills directory:

```bash
git clone https://github.com/TruaShamu/copilotcli-selflearning.git ~/.copilot/skills/self-learning
```

Then run the hooks installer:

```bash
# Linux/macOS
bash ~/.copilot/skills/self-learning/install-hooks.sh

# Windows
powershell -ExecutionPolicy Bypass -File ~/.copilot/skills/self-learning/install-hooks.ps1
```

And add the Self-Learning Protocol from `resources/AUTO-TRIGGER-GUIDE.md` to
your `~/.copilot/instructions.md`.

## Requirements

- Python 3.9+ (for local SQLite memory store)
- GitHub Copilot CLI

## Architecture

All memory is local SQLite (`~/.copilot/self-learning/memory.db`). Nothing is
sent to any external service or repo-scoped storage.

For the full database schema, hook internals, and evolution engine details,
see [ARCHITECTURE.md](ARCHITECTURE.md).

### Plugin structure

```
self-learning/
├── plugin.json           # Plugin manifest
├── hooks.json            # Hook configuration
├── hooks/                # Hook scripts (bash + PowerShell)
│   ├── session-start.*   # Load preferences at session start
│   ├── session-end.*     # Archive session summary
│   ├── pre-tool-use.*    # Block repo-scoped store_memory
│   └── post-tool-use.*   # Log tool sequences + skill usage
├── skills/
│   └── self-learning/
│       └── SKILL.md      # Full skill specification
├── resources/
│   ├── memory_cli.py     # Local SQLite memory store CLI
│   └── AUTO-TRIGGER-GUIDE.md
├── evolution/            # Skill evolution engine
├── install-hooks.sh      # Manual hook installer (Linux/macOS)
├── install-hooks.ps1     # Manual hook installer (Windows)
└── uninstall-hooks.py    # Hook uninstaller
```

See [SKILL.md](skills/self-learning/SKILL.md) for the full skill specification.

## License

MIT
