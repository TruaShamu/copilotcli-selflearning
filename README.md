# Copilot CLI Self-Learning

Hook-driven self-learning for GitHub Copilot CLI — preferences, memories, skills,
and cross-session recall that compound over time. Includes an experimental
evolution engine for automated skill improvement.

## What it does

Five capabilities powered by Copilot CLI's native hook system:

1. **Preference & memory injection** — `sessionStart` loads ranked memories and preferences into every session via `additionalContext`
2. **Policy enforcement** — `preToolUse` blocks repo-scoped `store_memory` to keep all data in local SQLite
3. **Tool usage tracking** — `postToolUse` logs every tool call + skill invocation to SQLite for pattern analysis
4. **Self-reflection gating** — `agentStop` blocks complex sessions (5+ tool calls) and forces the agent to store learnings and create skills before finishing
5. **Session extraction** — `sessionEnd` runs gpt-4o-mini to extract facts, preferences, and skill candidates from completed sessions

## Hook architecture

All 5 hooks return actionable output — this is **not** just logging:

| Hook | Returns | Effect |
|------|---------|--------|
| `sessionStart` | `additionalContext` | Injects preferences, memories (ranked by `memory_score`), and session store recall nudge |
| `preToolUse` | `decision:deny` | Blocks `store_memory` tool (policy enforcement) |
| `postToolUse` | _(side effects)_ | Logs tool sequences + skill usage to SQLite |
| `agentStop` | `decision:block` | Forces self-reflection on complex sessions without skills |
| `sessionEnd` | _(side effects)_ | LLM-extracts learnings and stores to memory.db |

### Memory scoring

Memories are ranked by `memory_score` — a composite of:
- **Access count** — how often a memory has been recalled
- **Recency** — exponential decay with ~23-day half-life
- **Confidence** — original storage confidence weight
- **Access boost** — bonus for frequently-accessed items

Only top-N memories by score are injected at session start, not all.
`memory-decay` flags items scoring below 0.1 threshold for cleanup.

### Cross-session recall

The `sessionStart` hook nudges the agent to search Copilot CLI's native
`session-store.db` via the `sql` tool with `database:'session_store'`. This
enables the agent to recall past approaches, mistakes, and solutions across
sessions without any custom infrastructure.

Requires the `SESSION_STORE` feature flag (see Installation).

## Skills

Skills live in `.github/skills/<name>/SKILL.md` — the native Copilot CLI
discovery path. Frontmatter supports only:
- `name` — skill identifier
- `description` — what the skill does
- `user-invocable` — whether users can call it directly

> **Note:** `version` and `trigger` fields are **not supported** by Copilot CLI
> and will cause errors if included.

The `agentStop` hook prompts the agent to auto-create skills when it detects
reusable workflows. Skills are invoked natively via `skill()` — Copilot CLI
discovers them automatically from `.github/skills/`.

## Installation

### Option A: Plugin install

```bash
copilot plugin install TruaShamu/copilotcli-selflearning
```

### Option B: Clone + manual install

```bash
git clone https://github.com/TruaShamu/copilotcli-selflearning.git
cd copilotcli-selflearning

# Linux/macOS
bash install-hooks.sh

# Windows
powershell -ExecutionPolicy Bypass -File install-hooks.ps1
```

### Enable SESSION_STORE (recommended)

Cross-session recall requires the `SESSION_STORE` feature flag:

```bash
# Add to ~/.copilot/config.json (create if missing):
{
  "features": {
    "SESSION_STORE": true
  }
}
```

Or merge it into your existing config. The installer scripts do this
automatically.

### Enable skill discovery

Skills in `.github/skills/` are discovered automatically by Copilot CLI when
the repo is cloned. For plugin installs, symlink if needed:

```bash
# Linux/macOS
ln -s ~/.copilot/installed-plugins/_direct/TruaShamu--copilotcli-selflearning/.github/skills ~/.github/skills

# Or just clone the repo into a project directory — skills are repo-scoped
```

### Custom instructions (optional)

Copy [`resources/AUTO-TRIGGER-GUIDE.md`](resources/AUTO-TRIGGER-GUIDE.md) into
`~/.copilot/copilot-instructions.md` for enhanced auto-triggering of memory
storage and skill creation.

## Requirements

- Python 3.9+ (for SQLite memory store and hook scripts)
- GitHub Copilot CLI

## Architecture

All memory is local SQLite (`~/.copilot/self-learning/memory.db`). Tables:
- `preferences` — user preferences with category and confidence
- `personal_memory` — facts with subject, confidence, access tracking
- `tool_usage` — per-session tool call sequences with error flags

Full-text search via FTS5. Nothing leaves your machine.

### memory_cli.py

The memory backend with subcommands:

| Command | Purpose |
|---------|---------|
| `search-context` | FTS5 search across all memory |
| `store-memory` | Store a fact with subject + confidence |
| `store-pref` | Store a user preference |
| `extract-session` | LLM-extract learnings from a session transcript |
| `session-stats` | Get tool call counts / complexity for a session |
| `list-all` | Dump all stored memories |
| `memory-score` | Show ranked memories by composite score |
| `memory-decay` | Flag low-scoring items for cleanup |

### Project structure

```
copilotcli-selflearning/
├── .github/
│   ├── hooks/
│   │   └── self-learning.json    # Hook configuration (6 event types)
│   └── skills/
│       └── python-project-scaffold/
│           └── SKILL.md           # Auto-created skill example
├── hooks/                         # Hook scripts (bash + PowerShell)
│   ├── session-start.sh/.ps1     # Inject preferences + memories + session store nudge
│   ├── pre-tool-use.sh/.ps1      # Block repo-scoped store_memory
│   ├── post-tool-use.sh/.ps1     # Log tool sequences + skill usage
│   ├── agent-stop.sh             # Block complex sessions for self-reflection
│   ├── session-end.sh            # LLM-extract learnings from session
│   └── user-prompt-submitted.sh  # Prompt analysis hook
├── skills/
│   ├── self-learning/SKILL.md    # Core self-learning skill spec
│   └── python-project-scaffold/SKILL.md
├── resources/
│   ├── memory_cli.py             # SQLite memory backend
│   └── AUTO-TRIGGER-GUIDE.md     # Custom instructions template
├── evolution/                     # Skill evolution engine (experimental)
│   ├── evolve_skill.py           # GEPA + holdout eval orchestrator
│   ├── fitness.py                # LLM-judge scoring
│   ├── llm_client.py            # OpenAI / Azure client
│   ├── harness/                  # Copilot CLI batch runner
│   ├── datasets/                 # Golden test cases
│   ├── experiments/              # Tracked experiment batches
│   └── ROADMAP.md
├── hooks.json                    # Legacy hook config (user-level)
├── plugin.json                   # Plugin manifest
├── install-hooks.sh              # Hook installer (Linux/macOS)
├── install-hooks.ps1             # Hook installer (Windows)
├── uninstall-hooks.py            # Hook uninstaller
├── requirements.txt
├── ARCHITECTURE.md
└── EVALUATION.md
```

## Skill evolution engine (experimental)

A [GEPA](https://github.com/google-deepmind/gepa)-powered engine that
automatically rewrites skill text to improve agent behavior:

```
Seed skill → GEPA optimize_anything → LLM-judge scoring → Copilot CLI harness validation → Evolved skill
```

**Best result:** gpt-5.4 evolution achieved **+39.7% improvement** on holdout
evaluation with **-26.7% size reduction**. Full analysis in
[`evolution/experiments/`](evolution/experiments/).

> ⚠️ **Known issue:** Over-prunes when the evaluation dataset lacks richness.
> Use golden datasets with diverse scenarios for best results.

```bash
# Dry run
python -m evolution.evolve_skill --skill self-learning --dry-run

# Full evolution with harness
python -m evolution.evolve_skill \
  --skill self-learning \
  --eval-source golden \
  --dataset-path evolution/datasets/self-learning/ \
  --max-calls 50 \
  --harness
```

See [evolution/ROADMAP.md](evolution/ROADMAP.md) for what's next.

## License

MIT
