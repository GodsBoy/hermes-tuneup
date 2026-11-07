"""Small, tolerant readers for nested config: a malformed section reads as empty."""

from __future__ import annotations


def section(config, key: str) -> dict:
    """config[key] when it is a mapping, else {}."""
    value = config.get(key) if isinstance(config, dict) else None
    return value if isinstance(value, dict) else {}


def dig(node, *keys):
    """The value at a key path, or None when any step is missing or not a mapping."""
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def raw_section(snapshot, *keys) -> dict:
    """A section of the profile's own file (no defaults), or {} when absent."""
    value = dig(snapshot.raw or {}, *keys)
    return value if isinstance(value, dict) else {}
