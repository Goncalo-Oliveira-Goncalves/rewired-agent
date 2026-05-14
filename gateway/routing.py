"""
Syntax-based message routing for Hermes Agent.

Allows AI agents to choose where their output goes by prefixing
root-level lines with routing markers:

    [SLACK]    → send the remainder of this message to Slack
    [TELEGRAM] → send the remainder of this message to Telegram
    [SILENT]   → suppress all output (work silently)
    no marker  → suppress all output (work silently)

If the entire response text starts with one of these markers,
the full response is routed to the specified platform.
If no marker is present, nothing is sent — the agent works silently.
"""

import re
from typing import Optional, Tuple

# ── public API ──────────────────────────────────────────────────────

_ROUTE_RE = re.compile(
    r'^\s*\[(SLACK|TELEGRAM|SILENT)\]\s*\n?',
    re.MULTILINE,
)


def parse_routing(response: str) -> Tuple[Optional[str], str]:
    """Parse a response for platform routing markers.

    Returns
    -------
    (target_platform_or_None, cleaned_content)
        target_platform = ``"slack"``, ``"telegram"``, or ``None``.
        When ``None``, the caller SHOULD NOT deliver any message — the
        agent is working silently.

        cleaned_content has the marker line stripped.
    """
    if not response or not response.strip():
        return None, ""

    match = _ROUTE_RE.match(response)
    if not match:
        # No marker → silent work
        return None, response

    tag = match.group(1).upper()
    if tag == "SILENT":
        return None, response[match.end():].strip()

    platform = tag.lower()  # "slack" or "telegram"
    cleaned = response[match.end():].strip()
    return platform, cleaned


def has_routing_marker(response: str) -> bool:
    """Return True if the response starts with any ``[MARKER]``."""
    return bool(_ROUTE_RE.match(response or ""))


def strip_routing_marker(response: str) -> str:
    """Remove the first routing marker line if present."""
    _, cleaned = parse_routing(response)
    return cleaned
