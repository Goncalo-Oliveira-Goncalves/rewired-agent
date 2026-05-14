SYMPTOMS: WARNING gateway.platforms.base: [Slack] Cannot route to slack: no adapter
CAUSE: [SLACK] marker triggered cross-platform routing lookup instead of replying to originating channel
STATUS: fixed
FIX: base.py patched to detect routing_target == source_platform and deliver directly
DATE: 2026-05-12
