"""Fixed tables: when a change takes effect, and which efforts count as costly."""

from __future__ import annotations

NEXT_MESSAGE = (
    "the next message in gateway-backed sessions (messaging and Desktop); a new session in the classic CLI"
)
NEW_SESSION = "a new session"

COSTLY_EFFORTS = {"xhigh": "medium", "max": "medium", "ultra": "medium", "high": "low"}


def effect_timing(key_path: list) -> str:
    """When a change to this config key reaches running sessions.

    The gateway rebuilds its cached agent only for compression keys; summariser and
    delegation settings, and anything in the classic CLI, wait for a new session.
    """
    return NEXT_MESSAGE if key_path and key_path[0] == "compression" else NEW_SESSION
