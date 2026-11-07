"""A summariser window too small for the trigger it must summarise."""

from __future__ import annotations

from .. import hermes_adapter as adapter
from ..config_access import raw_section
from ..redact import clean
from ..report import Finding
from ..routes import format_tokens
from ..severity import effect_timing

KEY = ["auxiliary", "compression"]


def check(snapshot, routes) -> list[Finding]:
    summariser = next((r for r in routes if r.role == "summariser" and r.status == "resolved"), None)
    main = next((r for r in routes if r.role == "main"), None)
    if summariser is None or main is None or main.status != "resolved" or not summariser.window:
        return []
    current = raw_section(snapshot, "auxiliary", "compression")
    proposed = {**current, "provider": "auto", "model": ""}
    try:
        minimum = adapter.minimum_context_length()
    except adapter.Unresolved:
        minimum = 0
    if summariser.window < minimum:
        severity = "high"
        summary = (
            f"the summariser {clean(summariser.model)} has a {format_tokens(summariser.window)} window, below "
            f"Hermes' {format_tokens(minimum)} minimum, so long chats lose their middle turns without a summary. "
            "Let the summariser follow the main model."
        )
    elif main.factors.get("summariser_ceiling"):
        severity = "medium"
        summary = (
            f"the summariser {clean(summariser.model)} has a {format_tokens(summariser.window)} window, so Hermes "
            f"lowers compaction on {clean(main.model)} from about {format_tokens(main.factors['ratio_trigger'])} "
            f"to {format_tokens(main.trigger)}. Let the summariser follow the main model."
        )
    else:
        return []
    return [
        Finding(
            check="summariser",
            severity=severity,
            summary=summary,
            evidence={
                "summariser": {"model": summariser.model, "provider": summariser.provider, "window": summariser.window},
                "main_trigger": main.trigger,
            },
            key_path=KEY,
            current=current,
            proposed=proposed,
            effect_timing=effect_timing(KEY),
        )
    ]
