# Self-Learning Auto-Trigger Protocol

Drop this section into your `AGENTS.md` (or `.github/copilot-instructions.md`)
to enable the self-learning loop without manual invocation.

---

## Recommended AGENTS.md Addition

```markdown
## Self-Learning Protocol

### Session Start

At the beginning of each session, before starting work:

1. Load user preferences: `python ~/.copilot/skills/self-learning/resources/memory_cli.py query-prefs`
2. If the user's first message mentions a specific topic, search prior sessions:
   `python ~/.copilot/skills/self-learning/resources/memory_cli.py search-sessions "<topic>" --context 3`
3. Silently incorporate any loaded context. Briefly mention prior-art hits.

### Post-Task

After completing any substantial task (3+ tool calls, multi-phase work),
run all of the following in a single autonomous pass:

1. **Memory nudge** (silent): Store 1-3 novel facts via `memory_cli.py store-memory`.
   Briefly confirm what was stored.
2. **Preference observation** (silent): Store any user-demonstrated conventions
   via `memory_cli.py store-pref`.
3. **Session ingestion** (silent): Archive the user's request and your summary
   via `memory_cli.py ingest-turn` so future sessions can find this work.
4. **Skill creation check** (ask user): Only if the session was a novel 3+ phase
   workflow, ask if the user wants to save it as a skill.
5. **Skill improvement check** (ask user): Only if a skill was used and you
   encountered friction, propose improvements.

Steps 1-3 always run silently. Steps 4-5 are conditional. Execute everything
in one pass — never require the user to prompt each step.

### Do NOT self-trigger when:
- The task was simple Q&A or a single tool call
- The user explicitly asked you to stop learning
- You've already run the post-task flow this session
```

---

## Design Comparison

| Capability | Auto-trigger? |
|------------|--------------|
| Skill auto-creation | Ask user first |
| Skill self-improvement | Ask user first |
| Memory nudges | Silent (1-3 facts) |
| Session search (FTS5) | Proactive before tasks |
| User preference model | Silent (1-2 per session) |

## Key Design Decisions

1. **No background daemon** — Copilot CLI skills run in-conversation, not as
   a persistent process. The "nudge" happens at task boundaries, not on a timer.

2. **Local SQLite, not external backends** — We use a single
   `~/.copilot/self-learning/memory.db` with 4 tables. Simpler,
   no infrastructure, fully user-controlled.

3. **No repo-scoped `store_memory`** — We deliberately avoid it because it's
   visible to all repo users. Everything stays local.

3. **Skills are markdown, not code** — Skills are pure procedure instructions
   that the LLM follows. This keeps skills model-agnostic.

4. **No external skill hub** — Copilot CLI skills live in the repo under
   `.github/skills/`. Sharing happens via git (branches, PRs, forks).
