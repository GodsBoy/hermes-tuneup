"""Fixed tables: when a change takes effect, and which efforts count as costly."""

from __future__ import annotations

NEXT_MESSAGE = (
    "the next message in gateway-backed sessions (messaging and Desktop); a new session in the classic CLI"
)
NEW_SESSION = "a new session"

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

COSTLY_EFFORTS = {"xhigh": "medium", "max": "medium", "ultra": "medium", "high": "low"}


def effect_timing(key_path: list) -> str:
    """When a change to this config key reaches running sessions.

    The gateway rebuilds its cached agent only for compression keys; summariser and
    delegation settings, and anything in the classic CLI, wait for a new session.
    """
    return NEXT_MESSAGE if key_path and key_path[0] == "compression" else NEW_SESSION


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(severity, len(SEVERITY_ORDER))


def severity_counts(findings: list) -> dict:
    """{"high": n, "medium": n, "low": n} for finding dicts."""
    return {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_ORDER}
