# Copilot CLI Self-Learning Skill

A meta-skill that gives GitHub Copilot CLI a closed learning loop — and an
evolution engine that lets the skill **improve itself** using automated
prompt optimization.

## What it does

Five capabilities that compound over time:

1. **Skill auto-creation** — Distill complex sessions into reusable skills
2. **Skill self-improvement** — Revise skills after observing their use
3. **Memory nudges** — Proactively persist important facts
4. **Cross-session recall** — Search past sessions via FTS5 + LLM summarization
5. **User preference model** — Build a deepening model of preferences and workflow

## Skill evolution engine

The plugin includes a [GEPA](https://github.com/google-deepmind/gepa)-powered
evolution engine that automatically rewrites the skill text to improve agent
behavior. It works like this:

```
Seed skill (SKILL.md)
  → GEPA optimize_anything (LLM-guided prompt evolution)
  → LLM-judge scores candidates against golden test cases
  → Real Copilot CLI sessions validate the best candidate (harness)
  → Evolved skill with measurable improvement
```

**First result:** gpt-5.4 evolution achieved **+39.7% improvement** on holdout
evaluation — the evolved skill gained structured priority rules, a decision
table, and a recall flow that the original lacked. Full analysis in
[`evolution/experiments/`](evolution/experiments/).

### Two-tier evaluation

The engine uses a cost-efficient architecture:

- **Inner loop (fast):** LLM-judge scores skill text against expected behaviors
  (~$0.01/eval, 2s)
- **Holdout (accurate):** Real Copilot CLI sessions via the batch runner harness
  (~$0.10/eval, 60-180s) — injects the candidate skill into a temp config dir
  and measures actual agent behavior

### Running evolution

```bash
# Dry run — verify setup without API calls
python -m evolution.evolve_skill --skill self-learning --dry-run

# Evolve with golden dataset + harness holdout
python -m evolution.evolve_skill \
  --skill self-learning \
  --eval-source golden \
  --dataset-path evolution/datasets/self-learning/ \
  --max-calls 50 \
  --harness

# Azure OpenAI backend
export AZURE_OPENAI_ENDPOINT="https://your-endpoint.openai.azure.com/openai/v1"
export AZURE_OPENAI_API_KEY="your-key"
export AZURE_OPENAI_MODEL="your-deployment-name"
python -m evolution.evolve_skill --skill self-learning --harness
```

Results land in `~/.copilot/self-learning/evolution-runs/` with baseline,
evolved skill, and metrics. Experiment tracking lives in
[`evolution/experiments/`](evolution/experiments/).

See the [roadmap](evolution/ROADMAP.md) for what's next: session ingestion,
auto-reflection hooks, closed-loop dataset expansion, and confidence-gated
auto-deployment.

## Installation

### Step 1: Install the plugin

> **Note**: Plugin install support requires Copilot CLI with plugin support
> enabled. Check [GitHub docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-finding-installing) for availability.

```bash
copilot plugin install TruaShamu/copilotcli-selflearning
```

To update: `copilot plugin update self-learning`
To remove: `copilot plugin uninstall self-learning`

### Step 2: Symlink the skill for discovery

The plugin system registers hooks automatically, but skills may not be
discovered from the plugin directory. Create a symlink so Copilot CLI finds
the skill at the standard user-level location:

```bash
# Linux/macOS
ln -s ~/.copilot/installed-plugins/_direct/TruaShamu--copilotcli-selflearning/skills/self-learning ~/.copilot/skills/self-learning

# Windows (run as admin, or with Developer Mode enabled)
New-Item -ItemType Junction -Path "$env:USERPROFILE\.copilot\skills\self-learning" -Target "$env:USERPROFILE\.copilot\installed-plugins\_direct\TruaShamu--copilotcli-selflearning\skills\self-learning"
```

### Step 3: Add custom instructions

Copy the contents of [`resources/AUTO-TRIGGER-GUIDE.md`](resources/AUTO-TRIGGER-GUIDE.md)
into `~/.copilot/copilot-instructions.md`. This is what makes the self-learning
loop actually trigger — without it, the LLM won't know to store preferences,
nudge memories, or offer skill creation.

See the guide for the full recommended instruction block.

### Manual install (alternative)

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

## Requirements

- Python 3.9+ (for local SQLite memory store)
- GitHub Copilot CLI

## Architecture

All memory is local SQLite (`~/.copilot/self-learning/memory.db`). Cross-session
search reads Copilot CLI's native `~/.copilot/session-store.db` in read-only mode.
Nothing is sent to any external service or repo-scoped storage.

For the full database schema, hook internals, and evolution engine details,
see [ARCHITECTURE.md](ARCHITECTURE.md).

### Plugin structure

```
self-learning/
├── plugin.json              # Plugin manifest
├── hooks.json               # Hook configuration (3 hooks)
├── hooks/                   # Hook scripts (bash + PowerShell)
│   ├── session-start.*      # Logging only
│   ├── pre-tool-use.*       # Block repo-scoped store_memory
│   └── post-tool-use.*      # Log tool sequences + skill usage
├── skills/
│   └── self-learning/
│       └── SKILL.md         # Full skill specification
├── resources/
│   ├── memory_cli.py        # Local SQLite memory store CLI
│   └── AUTO-TRIGGER-GUIDE.md
├── evolution/               # Skill evolution engine
│   ├── evolve_skill.py      # Main orchestrator (GEPA + holdout eval)
│   ├── fitness.py           # LLM-judge scoring
│   ├── llm_client.py        # OpenAI / Azure OpenAI client factory
│   ├── harness/             # Copilot CLI batch runner
│   │   └── __init__.py      # Runs real agent sessions for evaluation
│   ├── datasets/            # Golden test cases
│   ├── experiments/         # Tracked experiment batches + analysis
│   └── ROADMAP.md           # Evolution engine roadmap
├── install-hooks.sh         # Manual hook installer (Linux/macOS)
├── install-hooks.ps1        # Manual hook installer (Windows)
└── uninstall-hooks.py       # Hook uninstaller
```

### Hook limitations

Per the [official Copilot CLI docs](https://docs.github.com/en/copilot/reference/hooks-configuration),
**only `preToolUse` hooks can return actionable output** (allow/deny decisions).
All other hook types (`sessionStart`, `postToolUse`, `sessionEnd`) have their
output **ignored** — they can only perform side effects like logging.

This means preferences and memories **cannot** be injected via hooks. The
custom instructions in `~/.copilot/copilot-instructions.md` are what make the
LLM proactively load preferences and store memories.

See [SKILL.md](skills/self-learning/SKILL.md) for the full skill specification.

## License

MIT
