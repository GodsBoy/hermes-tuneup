"""hermes-tuneup: compaction and cost advisor for Hermes Agent.

register(ctx) wires the agent tool, the /tuneup slash command, the
`hermes tuneup` CLI and the hooks. It does no I/O and touches no Hermes home,
because `hermes plugins validate` imports it in a throwaway home.
"""

from __future__ import annotations


def register(ctx) -> None:
    """Register tuneup's surfaces with Hermes."""
    return None
