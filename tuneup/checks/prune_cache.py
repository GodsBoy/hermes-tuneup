"""Proactive pruning on a prompt-cached subscription route."""

from __future__ import annotations

from ..config_access import raw_section, section
from ..redact import clean
from ..report import Finding
from ..severity import effect_timing

KEY = ["compression", "proactive_prune_tokens"]

# Hermes has no helper for this, so tuneup keeps the list: subscription routes
# whose quota depends on the prompt cache staying warm.
CACHED_PROVIDER_PREFIXES = ("claude-subscription",)
CACHED_PROVIDERS = {"openai-codex"}


def is_cached_subscription(provider: str) -> bool:
    p = (provider or "").strip().lower()
    return p in CACHED_PROVIDERS or p.startswith(CACHED_PROVIDER_PREFIXES)


def check(snapshot, routes) -> list[Finding]:
    value = section(snapshot.config or {}, "compression").get("proactive_prune_tokens", 0)
    try:
        value = int(value or 0)
    except (TypeError, ValueError):
        return []
    if value <= 0:
        return []
    cached = [r for r in routes if r.role in ("main", "fallback") and is_cached_subscription(r.provider)]
    if not cached:
        return []
    route = cached[0]
    return [
        Finding(
            check="prune_cache",
            severity="high",
            summary=(
                f"proactive pruning is on ({value:,} tokens) while {clean(route.model)} runs on the cached "
                f"subscription route {clean(route.provider)}. Every prune rewrites history and forces a full "
                "prompt-cache miss, which burns quota. Turn pruning off."
            ),
            evidence={"proactive_prune_tokens": value, "routes": [{"model": r.model, "provider": r.provider} for r in cached]},
            key_path=KEY,
            current=raw_section(snapshot, "compression").get("proactive_prune_tokens", value),
            proposed=0,
            effect_timing=effect_timing(KEY),
        )
    ]
