"""The cap-clamp finding from the trigger explanation (R5) plus the four checks (R6 to R9)."""

from __future__ import annotations


def raw_section(snapshot, *keys) -> dict:
    """A section of the profile's own file (no defaults), or {} when absent."""
    node = snapshot.raw or {}
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


from . import cap_clamp, dead_rules, prune_cache, subagent_effort, summariser  # noqa: E402

ALL_CHECKS = (
    summariser.check,
    prune_cache.check,
    dead_rules.check,
    cap_clamp.check,
    subagent_effort.check,
)
