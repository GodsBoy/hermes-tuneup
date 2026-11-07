"""The cap-clamp finding from the trigger explanation (R5) plus the four checks (R6 to R9)."""

from __future__ import annotations

from . import cap_clamp, dead_rules, prune_cache, subagent_effort, summariser

ALL_CHECKS = (
    summariser.check,
    prune_cache.check,
    dead_rules.check,
    cap_clamp.check,
    subagent_effort.check,
)
