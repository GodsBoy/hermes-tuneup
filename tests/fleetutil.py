"""Synthetic fleets shared by the surface tests."""

from __future__ import annotations

BUSY = """
model: {default: claude-opus-5-5, provider: claude-subscription-directsdk-experimental}
compression:
  threshold: 0.5
  threshold_tokens: 400000
  proactive_prune_tokens: 48000
  model_thresholds: {"anthropic:claude-opus": 0.8}
delegation: {reasoning_effort: high}
"""

CLEAN = "model: {default: claude-opus-5-5, provider: anthropic}\n"


def busy_fleet(make_profile, extra: int = 1):
    make_profile("default", BUSY)
    for i in range(extra):
        make_profile(f"spare{i}", BUSY)
