# Plan: Fix Bot-to-Bot Thread Context — Agent B Only Sees Thread Root, Not Agent A's Message

## Problem Statement

When Agent A mentions Agent B inside a Slack thread reply, Agent B's LLM turn fires
but only receives Gonçalo's original message (the thread root / "mother message") as
context — NOT Agent A's actual message that contained the mention.

Expected behavior:
  Gonçalo → The Agent → "can you ping System Architect?"
  The Agent → System Architect → "<@U0B2USNT6E9> please respond"
  System Architect's context should contain:
    [1] The Agent's message: "<@U0B2USNT6E9> please respond"   ← MISSING
    [2] (optionally) Gonçalo's thread root for context

Actual behavior:
  System Architect's context only contains Gonçalo's original message.
  It responds as if Gonçalo asked it something, not The Agent.

---

## Repo Location

All code lives at: /home/ubuntu/.rewired/hermes-agent/
Run all commands from that directory.
The venv is at: /home/ubuntu/.rewired/hermes-agent/venv/
Active branch: agent-swarm-comms

---

## Investigation Steps (do these first, in order)

### Step 1 — Find how thread events are processed in the Slack adapter

File: gateway/platforms/slack.py
Search for: `thread_ts`, `thread_ts`, `parent_message`, `fetch_thread`, `replies`

Questions to answer:
  - When a message event arrives with a thread_ts, does the adapter fetch the parent
    (thread root) message and prepend it to the text?
  - Does the adapter use thread_ts as part of the session key, tying Agent B's new
    turn to an EXISTING session that already has Gonçalo's message as history?
  - Is the incoming message text (Agent A's message) passed correctly as the current
    user turn input, or is it dropped in favor of fetched thread history?

Key grep commands:
  grep -n "thread_ts" gateway/platforms/slack.py | head -40
  grep -n "fetch\|replies\|parent\|root\|thread" gateway/platforms/slack.py | head -40

### Step 2 — Find how session key is built for thread messages

File: gateway/session.py  (function: build_session_key)
File: gateway/run.py      (search: build_session_key, get_or_create_session)

Questions to answer:
  - When Agent B gets a message inside a thread (thread_ts = X), does the session key
    for Agent B's turn use the same thread_ts X as the key?
  - If yes: does that collide with an existing session (the one Gonçalo/Agent A have
    been using in that thread) so Agent B inherits wrong conversation history?
  - Or does each bot get an independent session even in the same thread?

Key grep commands:
  grep -n "thread_ts\|thread_id\|session_key\|build_session_key" gateway/session.py | head -40
  grep -n "thread_ts\|thread_id\|session_key" gateway/run.py | head -40

### Step 3 — Trace what text is passed as the LLM turn input

File: gateway/run.py
Search for where the actual user/message text gets added to the conversation history
for a new turn. Specifically:
  - Is `event["text"]` (Agent A's message) the turn input?
  - Or is it replaced by fetched thread context?

Key grep commands:
  grep -n "event\[.text.\]\|original_text\|turn_input\|user_message\|append.*text" gateway/run.py | head -40

---

## Hypothesis (most likely root cause)

The Slack adapter likely fetches the thread parent message and REPLACES or PREPENDS
it as the context, but in doing so it either:
  (a) Overwrites the incoming message text (Agent A's message) with the thread root
      (Gonçalo's message), losing Agent A's message entirely, OR
  (b) Builds the session key from thread_ts, colliding with an existing session
      that has Gonçalo's message as [Human] turn, making Agent B think the human
      said what Gonçalo said.

---

## The Fix (implement only after confirming hypothesis via investigation)

### If cause is (a) — incoming text overwritten by thread fetch:

In gateway/platforms/slack.py, locate where parent/thread-root context is prepended.
Ensure the structure is:
  [thread root as system/context note]  ← optional, keep if useful
  [Agent A's actual message as the turn input]  ← MUST be the active turn

The turn input to the LLM must always be the EVENT message (what Agent A said),
not the fetched thread root.

### If cause is (b) — session key collision:

In gateway/session.py build_session_key():
  For bot-originated messages (event has bot_id), use a session key that includes
  the sending bot's user_id so Agent B gets a fresh session not shared with the
  Gonçalo/Agent A thread:
    agent:main:slack:channel:{channel_id}:bot-turn:{sender_bot_user_id}:{thread_ts}
  
  This gives Agent B its own isolated turn context while still knowing the thread.

### After the fix:

1. Clear pyc cache:
   find /home/ubuntu/.rewired/hermes-agent -name '*.pyc' -delete
   find /home/ubuntu/.rewired/hermes-agent -name '__pycache__' -type d -exec rm -rf {} +

2. Clear agent sessions:
   find /home/ubuntu/.rewired/agents/agent-agent -path '*/sessions/*' -delete
   find /home/ubuntu/.rewired/agents/agent-arch-system-design -path '*/sessions/*' -delete

3. Restart agents:
   systemctl --user restart hermes-gateway-agent-agent hermes-gateway-agent-arch-system-design

4. Commit on branch agent-swarm-comms:
   cd /home/ubuntu/.rewired/hermes-agent
   git add -p   # review each change before staging
   git commit -m "fix: agent B receives mentioning agent's message, not thread root"
   git push origin agent-swarm-comms

---

## Safety Rules (do not break these)

1. DO NOT modify the `<@USERID>` format in the swarm colleagues list in session.py.
   The only correct format is naked: → <@U0B2USNT6E9>  (no backticks, no prose wrapping)
   See: bugfixes/issues/2026-05-12-slack-mention-format-broken-by-identity-injection.md

2. DO NOT add a self-identity block to build_session_context_prompt() in session.py.
   It breaks the mention format. See the bug doc above.

3. DO NOT change the [SLACK] routing protocol or remove it.
   Without [SLACK] at the start of a response, messages are silently discarded.

4. DO NOT re-add the hard-ignore of all bot messages in slack.py.
   Commit af7cb11f4 is the last known good state for that file.

5. Test with a real mention cycle before committing:
   Ask The Agent to mention System Architect → System Architect must reply to
   WHAT THE AGENT SAID, not to Gonçalo's original message.

---

## Files to read before starting

- gateway/platforms/slack.py       (Slack event handling)
- gateway/session.py               (session key logic, context prompt building)
- gateway/run.py                   (turn orchestration, message dispatch)
- bugfixes/issues/                 (known issues, avoid repeating them)
