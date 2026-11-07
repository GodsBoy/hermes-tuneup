"""R9: subagents running at high or extra-high reasoning effort."""

from __future__ import annotations

from hermes_constants import parse_reasoning_effort

from ..report import Finding
from ..severity import COSTLY_EFFORTS, effect_timing
from . import raw_section

KEY = ["delegation", "reasoning_effort"]


def _level(raw) -> str | None:
    parsed = parse_reasoning_effort(raw)
    if not parsed or parsed.get("enabled") is False:
        return None
    return str(parsed.get("effort") or "").strip().lower() or None


def _parent_level(config: dict, model: str) -> str:
    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    overrides = agent.get("reasoning_overrides") if isinstance(agent.get("reasoning_overrides"), dict) else {}
    if model in overrides:
        return _level(overrides[model]) or "medium"
    return _level(agent.get("reasoning_effort")) or "medium"


def check(snapshot, routes) -> list[Finding]:
    config = snapshot.config or {}
    delegation = config.get("delegation") if isinstance(config.get("delegation"), dict) else {}
    main = next((r for r in routes if r.role == "main"), None)
    own = _level(delegation.get("reasoning_effort"))
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
