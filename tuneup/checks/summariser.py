"""A summariser window too small for the trigger it must summarise."""

from __future__ import annotations

from .. import hermes_adapter as adapter
from ..config_access import raw_section
from ..redact import clean
from ..report import Finding
from ..routes import format_tokens, switched_aside
from ..severity import effect_timing

KEY = ["auxiliary", "compression"]


def check(snapshot, routes) -> list[Finding]:
    summariser = next((r for r in routes if r.role == "summariser" and r.status == "resolved"), None)
    main = next((r for r in routes if r.role == "main"), None)
    if summariser is None or main is None or main.status != "resolved" or not summariser.window:
        return []
    # The summariser is profile-wide: report the first route its window lowers, main before the models
    # the profile switches to, as one finding.
    lowered = next(
        (
            r
            for r in routes
            if r.role in ("main", "declared", "seen") and r.status == "resolved" and r.factors.get("summariser_ceiling")
        ),
        None,
    )
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
    elif lowered is not None:
        severity = "medium"
        summary = (
            f"the summariser {clean(summariser.model)} has a {format_tokens(summariser.window)} window, so Hermes "
            f"lowers compaction on {clean(lowered.model)}{switched_aside(lowered)} from about "
            f"{format_tokens(lowered.factors['ratio_trigger'])} to {format_tokens(lowered.trigger)}. "
            "Let the summariser follow the main model."
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
                "lowered_route": (
                    {"role": lowered.role, "model": lowered.model, "trigger": lowered.trigger} if lowered else None
                ),
            },
            key_path=KEY,
            current=current,
            proposed=proposed,
            effect_timing=effect_timing(KEY),
        )
    ]
