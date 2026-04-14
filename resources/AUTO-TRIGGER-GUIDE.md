# Self-Learning Auto-Trigger Protocol

Add this to your `~/.copilot/copilot-instructions.md` to enable the
self-learning loop. This is **required** — without it, the LLM won't know
to use the plugin's commands.

---

## Recommended `copilot-instructions.md` Addition

```markdown
# Personal Instructions

## Self-Learning Integration

The self-learning skill plugin is installed. Use it throughout sessions:

### Session start (do this first, silently)
At the start of every session, before responding to the first prompt, silently run `query-prefs` to load my stored preferences. Use them to inform your behavior throughout the session. Don't mention that you did this unless I ask.

### Skill auto-creation
After completing any multi-step task involving 3 or more distinct phases (e.g., research → implement → test), evaluate whether the workflow could be saved as a reusable skill. If it looks reusable, ask me:
> "This looked like a reusable workflow. Want me to save it as a skill?"

Don't save trivial tasks, single-tool operations, or one-off debugging sessions.

### Skill self-improvement
When using an existing skill and you encounter friction (wrong steps, missing steps, outdated info), note it. After the task, ask:
> "I noticed some improvements to the <skill> skill. Apply them?"

### Preference detection
When I express a preference about code style, tooling, workflow, or conventions — either explicitly ("I prefer X") or implicitly (consistently choosing X over Y) — store it using `store-pref`. Do this silently without asking.

### Memory nudges
When discovering important project facts, gotchas, or conventions that would be useful in future sessions (e.g., "this repo uses pnpm not npm", "auth tokens expire after 1 hour"), store them using `store-memory`. Do this silently without asking.

### Cross-session recall
When I ask about something I've **worked on before** or past sessions (e.g., "what did I do last week", "how did I fix that bug"), search past sessions using the self-learning skill's `search-sessions` command — do NOT use the `session_store_sql` tool (it's unavailable in this environment). Do NOT use search-sessions for preferences or memories — those have their own query commands (`query-prefs`, `query-memory`).

### How to run self-learning commands
All commands (`query-prefs`, `store-pref`, `query-memory`, `store-memory`, `search-sessions`, etc.) are subcommands of `memory_cli.py` in the self-learning plugin. Run them via powershell:

python "$env:USERPROFILE\.copilot\installed-plugins\_direct\TruaShamu--copilotcli-selflearning\resources\memory_cli.py" <command> [args]

Examples:
- `python "...memory_cli.py" query-prefs` — list all stored preferences
- `python "...memory_cli.py" store-pref code-style "prefers single quotes" --confidence 0.9`
- `python "...memory_cli.py" query-memory` — list ALL stored memories (no args = all)
- `python "...memory_cli.py" query-memory --search "auth"` — search memories by keyword
- `python "...memory_cli.py" search-sessions "how did I fix the bug" --limit 5`
- `python "...memory_cli.py" store-memory project-fact "this repo uses pnpm not npm"`

Important:
- Do NOT use the `session_store_sql` tool — it hits a cloud backend that returns HTTP 404 in this environment. All session/preference/memory data is local.
- `query-memory` with no args returns all memories. Don't use wildcards like `--search "*"`.
- Hooks are loaded from the self-learning plugin automatically (3 hooks: sessionStart, preToolUse, postToolUse). They won't appear in `~/.copilot/hooks/` — that's normal.
```

---

## Why custom instructions are required

Copilot CLI hooks have a key limitation: **only `preToolUse` can return
actionable output** (allow/deny decisions). All other hooks (`sessionStart`,
`postToolUse`, `sessionEnd`) have their output **ignored** by the runtime.

This means:
- Preferences **cannot** be injected via the sessionStart hook
- Memories **cannot** be surfaced via hooks
- Skill creation prompts **cannot** be triggered via hooks

The custom instructions in `copilot-instructions.md` are loaded into every
session as system context, making them the most reliable way to get the LLM
to use the plugin's commands. They are not 100% deterministic (the LLM may
still not follow them), but they work well in practice.

## Design Comparison

| Capability | Trigger | Deterministic? |
|---|---|---|
| Preference loading | Instructions (LLM runs `query-prefs` at start) | Best-effort |
| Preference detection | Instructions (LLM runs `store-pref` mid-session) | Best-effort |
| Memory nudges | Instructions (LLM runs `store-memory` post-task) | Best-effort |
| Cross-session search | Instructions (LLM runs `search-sessions` on demand) | Best-effort |
| Skill auto-creation | Instructions (LLM asks user after complex tasks) | Best-effort |
| Tool deny (store_memory) | `preToolUse` hook | **Deterministic** |
| Tool logging | `postToolUse` hook | **Deterministic** (side-effect only) |
