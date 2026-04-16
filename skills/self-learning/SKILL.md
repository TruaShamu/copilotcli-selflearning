---
name: self-learning
version: 2.0.0
description: Hook-driven autonomous learning — memories, preferences, and skills are managed automatically by hooks.
trigger: Automatically active via hooks. Manual commands available for explicit memory operations.
---

# Self-Learning System

**Hooks handle memory I/O automatically. You focus on coding. When prompted to reflect, follow the instructions.**

## Overview

The self-learning system captures user preferences, project patterns, and reusable skills across sessions. It uses a vector memory store (ChromaDB) so relevant context is automatically retrieved and injected into your system prompt at session start.

You do **not** need to manage memories yourself. Hooks do it.

## How Hooks Work

| Hook | When | What It Does |
|------|------|-------------|
| `agentStart` | Session begins | Queries memory store for relevant context and injects it into the system prompt. |
| `agentStop` | Session ends | Prompts you to reflect on the session and extracts memories/skills to store. |

- **agentStart**: No action needed from you. Context appears automatically.
- **agentStop**: You will be prompted to reflect. Follow the prompt instructions — summarize what was learned, what the user preferred, and any reusable patterns.

## When You're Prompted to Reflect

At session end, the `agentStop` hook will ask you to reflect. When this happens:

1. **Answer the reflection prompt directly** — describe what happened, what was learned, and any user preferences observed.
2. **Be specific** — "user prefers TypeScript strict mode" is better than "user has coding preferences."
3. **Focus on reusable knowledge** — things that would help in future sessions.
4. **Skip trivial details** — don't store one-off facts or obvious things.

## Manual Commands

If you want to explicitly store something mid-session, use `memory_cli.py`:

```bash
# Store a memory
python ~/.hermes/hermes-agent/copilotcli-selflearning/memory_cli.py add --type preference --content "User prefers pytest over unittest"

# Search memories
python ~/.hermes/hermes-agent/copilotcli-selflearning/memory_cli.py search --query "testing preferences"

# List recent memories
python ~/.hermes/hermes-agent/copilotcli-selflearning/memory_cli.py list --limit 10
```

Use this sparingly — hooks handle the common case.

## Quality Standards

### Good Memories
- Specific user preferences: *"Always use black for Python formatting with line-length 100"*
- Project patterns: *"This repo uses a monorepo structure with pnpm workspaces"*
- Corrections: *"User corrected: use `const` not `let` for all non-reassigned variables"*

### Good Skills
- Reusable procedures: *"To deploy this project: run `make build`, then `kubectl apply -f deploy/`"*
- Non-obvious patterns: *"Error handling in this codebase always uses custom AppError class"*

### Don't Store
- Obvious language/framework defaults
- One-time debugging details
- Anything already in the project's README or docs
