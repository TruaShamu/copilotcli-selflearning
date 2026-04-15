---
name: self-learning
description: >-
  Self-learning loop for Copilot CLI. Auto-creates skills from complex sessions,
  improves existing skills after use, nudges persistent memory, recalls cross-session context,
  and builds a user preference model. Trigger with "learn", "reflect", "improve skill",
  "what do you remember", or "review session".
---

---
name: self-learning
description: Recall past work, store durable memory, save user preferences, and evolve reusable skills.
---

# Self-Learning Skill

Use this skill only for self-learning actions:
- recall past work
- remember durable facts
- store user preferences
- create or improve skills

Do **not** let it interfere with normal task execution.

## Core Rules

- **Explicit user instructions always win.** If the user explicitly asks for a tool, package manager, command, file path, or workflow, follow that request even if stored preferences differ.
- **Be lightweight by default.** Do not run heavy review flows for simple tasks.
- **Use only the local memory CLI for persistence.** Do not use built-in remote memory tools or any other backend such as `session_store_sql`.
- **For direct recall questions, use memory first.** Only fall back to session search if memory is empty, weak, or inconclusive.
- **If the user asked not to learn, do not store or review anything.**
- **Do not store secrets, tokens, credentials, or sensitive data.**

## Canonical CLI

Prefer running from the skill resource directory so commands stay short:

```bash
cd ~/.copilot/skills/self-learning/resources
```

Then use:

```bash
python memory_cli.py store-pref <category> "<fact>" --confidence 0.8
python memory_cli.py query-prefs [--category <cat>]
python memory_cli.py supersede-pref <old_id> "<new_fact>"

python memory_cli.py store-memory <subject> "<fact>" --repo "owner/repo"
python memory_cli.py query-memory [--subject <sub>] [--search <text>]

python memory_cli.py log-skill <name> <success|partial|failure|skipped> --friction "..."
python memory_cli.py query-skills [--name <name>]

python memory_cli.py log-learning "<intent>" "<phases>" <tool_count> --candidate
python memory_cli.py query-learnings [--candidates-only]

python memory_cli.py search-sessions "<query>" --context 3 --limit 5
python memory_cli.py recent-sessions --limit 10
python memory_cli.py log-tool <session_id> <tool_name> [--failed]
python memory_cli.py query-tool-sequences [--patterns --window-size 3]
python memory_cli.py stats
```

If you cannot `cd` first, use the full path:
```bash
python ~/.copilot/skills/self-learning/resources/memory_cli.py ...
```

## When to Use This Skill

Activate this skill when the user:
- says "remember this", "save this", or "store a preference"
- says "what do you remember", "recall", "search past sessions", or asks a past-work question
- says "learn", "reflect", "review session", or "what did you learn"
- says "create a skill from this session" or "save this as a skill"
- says "improve skill X" or says a skill did not work well

Also use the lifecycle hooks below when they apply.

## Fast Decision Table

| User intent | What to do |
|---|---|
| Store a preference | `store-pref` immediately |
| Remember a fact | `store-memory` immediately |
| Recall past work / ask what was chosen before | `query-memory` first, then `search-sessions` only if needed |
| Review / reflect | run explicit review flow |
| Create or improve a skill | run the matching capability flow |

---

## Direct Recall Flow

Use this for explicit recall questions such as:
- "Do you remember what database we chose for the analytics service?"
- "What did we decide for auth?"
- "Have we done this before?"

### Required order

1. **Query memory first** with a targeted search.
2. If memory is **empty, weak, or inconclusive**, fall back to `search-sessions`.
3. Summarize:
   - what was found
   - where it came from
   - uncertainty if results are incomplete

### How to form the query

Use 1-3 short variants:
- core subject: `analytics`
- decision phrase: `database analytics`
- fuller phrase: `database analytics service`

### Commands

Example:
```bash
cd ~/.copilot/skills/self-learning/resources
python memory_cli.py query-memory --search "database analytics"
python memory_cli.py query-memory --search "analytics service"
python memory_cli.py query-memory --search "analytics database"
```

If memory is insufficient:
```bash
python memory_cli.py search-sessions "database analytics service" --context 3 --limit 5
```

### When memory is insufficient

Treat memory as insufficient if:
- no matches are returned
- matches are about the wrong subject
- results mention the topic but not the decision
- multiple matches conflict and none is clearly strongest

### Response template

If found in memory:
> "I found a stored memory that the analytics service uses <choice>."

If found only in session search:
> "I didn’t find a direct stored memory, but I found a past session indicating the analytics service used <choice>."

If uncertain:
> "I found related history, but I couldn’t confirm the final choice."

### Architecture-choice example

```bash
cd ~/.copilot/skills/self-learning/resources
python memory_cli.py query-memory --search "database analytics"
python memory_cli.py query-memory --search "analytics service"
python memory_cli.py search-sessions "database analytics service" --context 3 --limit 5
```

---

## Fast Paths For Explicit Requests

### Store a preference

Store it immediately. Do not run a full review first.

Preferred categories:
- `package-manager`
- `workflow`
- `code-style`
- `testing`
- `tools`
- `review-style`

Use normalized fact phrasing when possible.

Canonical package-manager example:
```bash
cd ~/.copilot/skills/self-learning/resources
python memory_cli.py store-pref package-manager "prefers pnpm over npm" --confidence 0.9
```

Then reply briefly:
> "Stored your preference: prefers pnpm over npm."

### Store a fact

Store it immediately with `store-memory`, then acknowledge briefly.

Example:
```bash
cd ~/.copilot/skills/self-learning/resources
python memory_cli.py store-memory build "Use npm run build:prod for production builds" --repo "owner/repo"
```

### Recall/search memory

Run the **Direct Recall Flow** above. Do not force a post-task review.

---

## Lifecycle Hooks

## Session Start (silent)

Run at the beginning of a session before the first substantive task.

1. **Load preferences** — handled automatically by the `sessionStart` hook. Do not repeat manually.
2. **Check prior art** — if the first user message has a clear topic, run **1-3 targeted searches**:
   - first query memory
   - if needed, then search sessions

Example:
```bash
cd ~/.copilot/skills/self-learning/resources
python memory_cli.py query-memory --search "authentication"
python memory_cli.py query-memory --search "Express.js auth"
python memory_cli.py search-sessions "Express.js auth" --context 3 --limit 5
```

3. **Mention only if useful** — briefly mention only clearly relevant prior work.

Example:
> "I found a related past session where you implemented Express auth middleware and debugged token handling."

## Post-Task (autonomous, single pass)

Run this once after a **substantial** task only:
- 3+ tool calls, or
- multi-phase work, or
- meaningful implementation plus validation

Do **not** run it for:
- simple Q&A
- one-command requests
- trivial edits
- sessions where the user asked you not to learn
- if already run this session

Steps:
1. **Memory nudge** — silently store 1-3 durable facts.
2. **Preference observation** — silently store clear durable preferences.
3. **Skill creation check** — ask only if the workflow is reusable.
4. **Skill improvement check** — ask only if a skill was used and friction occurred.

---

## Explicit Review Flow

If the user explicitly asks to review, learn, or reflect, run in this order:

1. Cross-session recall
2. Memory nudge
3. Preference observation
4. Skill creation check
5. Skill improvement check

End with a short summary:
> "Session review complete:
> - Stored 2 facts
> - Found 1 related past session
> - No skill creation candidate
> - No skill improvements needed"

---

## Capability 1 — Skill Auto-Creation

### Trigger

Use when:
- the user explicitly asks to create or save a skill, or
- the session had 5+ tool calls across 3+ distinct phases and looks reusable

Skip if clearly one-off.

### Procedure

1. Extract:
   - user intent
   - ordered workflow
   - decision points
   - final outcome
2. Identify what varies and what stays constant.
3. Draft the skill:

```markdown
---
name: <kebab-case-name>
description: <one-line description with 3+ trigger phrases>
---

# <Skill Name>

<Brief purpose and when to use it.>

## When to Use This Skill
<Trigger conditions>

## Procedure
<Concrete numbered steps>

## Parameters
<What varies>

## Learned From
- Session: <session_id>
- Date: <date>
- Original request: "<original ask>"
```

4. Ask:
   > "This looks like a reusable workflow. Save it as a skill?"

   Use `ask_user` with choices: `["Save skill", "Edit first", "Skip"]`.

5. Save:
```bash
mkdir -p ~/.copilot/skills/<name>
```
Write:
`~/.copilot/skills/<name>/SKILL.md`

### Quality Gates

- self-contained
- at least 3 concrete steps
- concise and actionable
- no references like "in this session"

---

## Capability 2 — Skill Self-Improvement

### Trigger

Use when:
- user says "improve skill X"
- user says a skill did not work well
- a skill was used and meaningful friction occurred

### Procedure

1. Find the skill:
   ```bash
   glob .github/skills/**/SKILL.md
   glob ~/.copilot/skills/**/SKILL.md
   ```
2. Compare expected vs actual execution.
3. Draft:

```markdown
## Proposed Skill Improvements

### Added
- ...

### Modified
- ...

### Removed
- ...
```

4. Ask with `ask_user`: `["Apply all", "Let me review", "Skip"]`
5. If approved, edit in place and append:

```markdown
## Revision History
- <date>: <brief description> (from session <id>)
```

### Heuristics

- repeated success without friction is evidence to leave it alone
- user corrections are strong evidence
- do not remove safety or validation steps without explicit approval

---

## Capability 3 — Memory Nudges

### Trigger

- end of a substantial task
- user says "remember this" or "save this"
- you discover a durable convention, gotcha, or verified command

### Procedure

1. Pick good candidates:
   - verified commands
   - conventions
   - stable architecture facts
   - important gotchas
   - repo-specific distinctions
   - useful user-stated choices
2. Filter: store only facts that are actionable, stable, non-sensitive, and not obvious from a quick code read.
3. Avoid duplicates conservatively.
4. Store:
   ```bash
   cd ~/.copilot/skills/self-learning/resources
   python memory_cli.py store-memory "<subject>" "<fact>" --repo "<owner/repo>"
   ```
5. If user-visible, acknowledge briefly.

### Defaults

- max 3 facts per session
- prefer broadly reusable facts
- when self-triggered, store only after verification

---

## Capability 4 — Cross-Session Recall

### Trigger

- explicit recall question
- session-start prior-art check
- "what did I work on recently"

### Procedure

1. **Memory first**
   - use `query-memory --subject` if there is a stable subject
   - otherwise use `query-memory --search` with 1-3 focused variants
2. **Session search second**
   - only if memory is insufficient
   - use `search-sessions "<query>" --context 3 --limit 5`
3. Summarize only the top 1-2 relevant findings.
4. Say clearly whether the answer came from stored memory or past session history.

### Recent work

```bash
cd ~/.copilot/skills/self-learning/resources
python memory_cli.py recent-sessions --limit 10
```

### Notes

- session transcripts already exist in `~/.copilot/session-store.db`
- do not query other backends directly
- do not use `session_store_sql`

---

## Capability 5 — User Preference Model

### Scope

All memory is local in `~/.copilot/self-learning/memory.db`.
Use `memory_cli.py` only.

### What to Track

- code style conventions
- workflow preferences
- package manager preferences
- test framework preferences
- review expectations
- repeated user corrections

### Procedure

1. Store preferences when the user:
   - explicitly states them
   - corrects your default behavior
   - repeatedly chooses the same approach
2. Canonical command:
   ```bash
   cd ~/.copilot/skills/self-learning/resources
   python memory_cli.py store-pref "<category>" "<fact>" --confidence 0.8
   ```
3. Use `0.9` for explicit durable statements like:
   - "always use pnpm"
   - "show a plan first"
   - "use Vitest in this repo"
4. If a new preference contradicts an old one:
   ```bash
   python memory_cli.py supersede-pref <old_id> "<new_fact>"
   ```

### Guardrails

- never store secrets
- explicit user instructions override stored preferences
- store durable preferences, not one-off choices

## Revision History

- 2026-04-11: Initial prototype
- 2026-04-14: Added hooks and lifecycle guidance
- 2026-04-15: Tightened scope and standardized commands
- 2026-04-15: Added explicit memory-first recall flow, fallback rules, canonical short CLI usage, and backend restrictions
