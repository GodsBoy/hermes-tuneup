"""Subagents running at high or extra-high reasoning effort."""

from __future__ import annotations

from .. import hermes_adapter as adapter
from ..config_access import raw_section, section
from ..report import Finding
from ..severity import COSTLY_EFFORTS, effect_timing

KEY = ["delegation", "reasoning_effort"]


def _effort(parsed: dict | None) -> str | None:
    """The effort level a parsed setting sends, or None when it is unset, unknown or disabled."""
    if not parsed or parsed.get("enabled") is False:
        return None
    return str(parsed.get("effort") or "").strip().lower() or None


def _level(raw) -> str | None:
    return _effort(adapter.parse_reasoning_effort(raw))


def _parent_level(config: dict, model: str) -> str:
    agent = section(config, "agent")
    overrides = section(agent, "reasoning_overrides")
    if model in overrides:
        return _level(overrides[model]) or "medium"
    return _level(agent.get("reasoning_effort")) or "medium"


def check(snapshot, routes) -> list[Finding]:
    config = snapshot.config or {}
    delegation = section(config, "delegation")
    main = next((r for r in routes if r.role == "main"), None)
    raw = delegation.get("reasoning_effort")
    # Same reading as Hermes' _child_reasoning: a YAML false counts as set, and a disabled
    # value is an explicit override that turns subagent thinking off rather than inheriting.
    parsed = adapter.parse_reasoning_effort(raw) if (raw or raw is False) else None
    if parsed is not None and parsed.get("enabled") is False:
        return []
    own = _effort(parsed)
    if own is not None:
        level, source = own, "delegation.reasoning_effort"
    else:
        level, source = _parent_level(config, main.model if main else ""), "inherited from the parent's agent.reasoning_effort"
    severity = COSTLY_EFFORTS.get(level)
    if severity is None:
        return []
    current = raw_section(snapshot, "delegation").get("reasoning_effort", "")
    return [
        Finding(
            check="subagent_effort",
            severity=severity,
            summary=(
                f"every subagent runs at {level} reasoning effort ({source}), which multiplies the cost of "
                "delegated work. Set delegation.reasoning_effort to medium unless subagents need deeper thinking."
            ),
            evidence={"effort": level, "source": source},
            key_path=KEY,
            current=current,
            proposed="medium",
            effect_timing=effect_timing(KEY),
        )
    ]
