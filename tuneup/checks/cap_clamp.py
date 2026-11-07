"""An explicit threshold_tokens that pulls a route's trigger below its ratio trigger."""

from __future__ import annotations

from ..config_access import raw_section
from ..redact import clean
from ..report import Finding
from ..routes import format_tokens
from ..severity import effect_timing

KEY = ["compression", "threshold_tokens"]


def check(snapshot, routes) -> list[Finding]:
    clamped = [
        r
        for r in routes
        if r.role in ("main", "fallback")
        and r.status == "resolved"
        and r.factors.get("cap")
        and r.factors.get("summariser_ceiling") is None
        and r.trigger == r.factors["cap"]
        and r.factors.get("ratio_trigger", 0) > r.trigger
    ]
    if not clamped:
        return []
    worst = min(clamped, key=lambda r: r.trigger / r.factors["ratio_trigger"])
    severity = "medium" if worst.trigger < worst.factors["ratio_trigger"] / 2 else "low"
    current = raw_section(snapshot, "compression").get("threshold_tokens", worst.factors["cap"])
    summary = (
        f"threshold_tokens caps compaction at {format_tokens(worst.trigger)} on {clean(worst.model)}, "
        f"instead of about {format_tokens(worst.factors['ratio_trigger'])} from the threshold ratio. "
        "Remove the cap to compact where the ratio says, or raise it if you set it on purpose."
    )
    return [
        Finding(
            check="cap_clamp",
            severity=severity,
            summary=summary,
            evidence={
                "routes": [
                    {"role": r.role, "model": r.model, "trigger": r.trigger, "ratio_trigger": r.factors["ratio_trigger"]}
                    for r in clamped
                ]
            },
            key_path=KEY,
            current=current,
            proposed=None,
            effect_timing=effect_timing(KEY),
        )
    ]
