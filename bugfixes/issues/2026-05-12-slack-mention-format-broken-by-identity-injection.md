# BUG: Slack Mention Format Broken by Identity Injection in session.py

## SYMPTOMS
Agent outputs `@U0B2USNT6E9` (raw ID, no angle brackets) instead of `<@U0B2USNT6E9>` (proper Slack mention format).
In Slack this renders as literal text `@U0B2USNT6E9` instead of the clickable `@System Architect` mention.

## CAUSE
An "identity injection" block was added to `build_session_context_prompt()` in `gateway/session.py`.
The block injected a line like:

    **Your identity:** You are **The Agent** (profile: `agent-agent`, Slack ID: `<@U0B3SADDZAL>`).

Two problems:
1. The agent's OWN Slack ID was embedded in backticks inside the identity line.
   The LLM learned from this that mention IDs appear in the format `@USERID` (without `<>`),
   because backtick-wrapped content is treated as a literal code description, not a format template.
2. The colleagues list already correctly taught agents to use `<@USERID>` format via the `→ <@USERID>` pattern.
   Adding a competing format reference caused the LLM to regress.

## RULE — NEVER DO THIS
DO NOT embed `<@USERID>` syntax inside backticks or description prose in the system prompt.
The ONLY correct place to show Slack mention format is in the colleagues list, naked (no backticks):
    System Architect (agent-arch-system-design) → <@U0B2USNT6E9>

DO NOT add a self-identity line that includes the agent's own `<@USERID>` in any form.
If agents need to know their own identity, inject only their display name and profile slug — NOT their Slack ID.

## AFFECTED FILES
- `gateway/session.py` — `build_session_context_prompt()`, Slack platform block

## COMMITS
- BROKE: 9e3b94d12 "fix: inject per-agent identity into Slack context prompt"
- BROKE: 42d388489 "revert: undo identity injection, broke mention generation" (revert was incomplete — slack.py not restored)
- FIXED: a2803d186 "revert: restore slack.py to af7cb11f4 working state"

## LAST KNOWN GOOD STATE
Commit `af7cb11f4` — "Add bot-to-bot loop prevention context to Slack agent prompt"
