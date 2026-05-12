# Re:WIRED — Fork Design Spec
**Date:** 2026-05-12  
**Status:** Approved

---

## 1. Repository & Rename

Full deep fork of `hermes-agent`. Every reference to Hermes gets replaced.

| Before | After |
|--------|-------|
| `~/.hermes/` | `~/.rewired/` |
| `hermes` CLI | `rewired` CLI |
| `hermes_cli/` package | `rewired_cli/` package |
| `hermes-gateway` systemd unit | `rewired-gateway` systemd unit |
| `"Hermes Agent"` in output | `"Re:WIRED"` |
| plain white startup banner | red ASCII art banner |

**Banner** (injected at startup, ANSI red):
```
\033[91m
██████╗ ███████╗       ██╗    ██╗██╗██████╗ ███████╗██████╗
██╔══██╗██╔════╝  ██╗  ██║    ██║██║██╔══██╗██╔════╝██╔══██╗
██████╔╝█████╗    ╚═╝  ██║ █╗ ██║██║████╔╝█████╗  ██║  ██║
██╔══██╗██╔══╝    ██╗  ██║███╗██║██║██╔══██╗██╔══╝  ██║  ██║
██║  ██║███████╗  ╚═╝  ╚███╔███╔╝██║██║  ██║███████╗██████╔╝
╚═╝  ╚═╝╚══════╝        ╚══╝╚══╝ ╚═╝╚═╝  ╚═╝╚══════╝╚═════╝
\033[0m
  the AI swarm  //  forked from Hermes · NousResearch
```

**Migration:** One-time script moves `~/.hermes/` → `~/.rewired/` on first `rewired start`.  
**Rename scope:** Search-replace `hermes`, `Hermes`, `HERMES_` across all `.py` files, systemd units, and shell scripts. Excludes `venv/`, git history, and third-party references.

---

## 2. Credential System

All credentials live in `rewired/keys/` inside the repo, covered by `.gitignore`.

```
rewired/
└── keys/
    ├── .gitignore                  # covers everything in keys/
    ├── key.ai                      # AI provider keys
    ├── messaging/
    │   └── slack/
    │       ├── slack.csv           # per-agent bot credentials
    │       └── slack-oauth.env     # xoxe token + refresh token
    └── integrations/
        ├── github.env              # drop any .env here
        ├── kanban.env              # auto-loaded at startup
        └── ...
```

### key.ai
Flat KEY=VALUE, filled manually:
```
OPENROUTER_API_KEY=sk-or-...
GOOGLE_API_KEY=AIza...
GROQ_API_KEY=gsk_...
CEREBRAS_API_KEY=...
DEEPSEEK_API_KEY=...
MISTRAL_API_KEY=...
```

### messaging/slack/slack.csv
Slim — only what the gateway needs:
```csv
name,profile,bot_token,app_token
coordinator,coordinator,xoxb-...,xapp-...
coder,coder,xoxb-...,
researcher,researcher,xoxb-...,
```
One `app_token` required (Socket Mode). Others leave it empty — share the first.

### messaging/slack/slack-oauth.env
For creating new Slack apps programmatically:
```
SLACK_USER_TOKEN=xoxe-...
SLACK_REFRESH_TOKEN=...
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
```

### integrations/
One `.env` file per integration. Drop a file in, it's loaded automatically on next start.  
No discovery code needed — just `glob('integrations/*.env')` at boot.

---

## 3. Boot Sequence

`rewired start` runs in this order before touching anything else:

1. Load `rewired/keys/key.ai` → inject all KEY=VALUE into process env
2. Load `rewired/keys/messaging/slack/slack.csv` → configure gateway bot tokens
3. Scan `rewired/keys/integrations/*.env` → inject each file into env
4. Start gateway (single instance)

---

## 4. Bug Fixes

### Key-resetting (primary fix)
The root cause: `save_env_value` and `save_config` rewrite `.env` and `config.yaml` during setup wizard, fallback configuration, and doctor runs — overwriting manually set keys.

**Fix:**
- Delete `save_env_value` and all call sites
- Strip all `api_key` field writes from `save_config`
- Remove credential prompts from setup wizard and doctor command
- Keys are owned exclusively by `key.ai` — nothing in the codebase writes them

### Other fixes
- `GATEWAY_ALLOW_ALL_USERS=true` set in default config (currently all users denied)
- Systemd unit renamed to `rewired-gateway`
- Single gateway instance enforced — remove any multi-gateway launch scripts

---

## 5. Out of Scope

- Changing agent profiles or SOUL.md files
- Modifying the AI-to-AI routing (already committed, working)
- UI or dashboard changes
- New agent roles
