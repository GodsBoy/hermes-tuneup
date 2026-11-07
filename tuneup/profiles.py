"""Profile discovery and read-only config snapshots for the whole fleet."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import hermes_adapter as adapter


@dataclass(frozen=True)
class ProfileSnapshot:
    name: str
    path: Path
    config: dict | None
    raw: dict | None
    status: str  # "ok" or "unresolved"
    note: str = ""


def _snapshot(name: str, path: Path) -> ProfileSnapshot:
    try:
        raw = adapter.load_raw_user_config(path)
        config = adapter.load_profile_config(path)
    except adapter.Unresolved as exc:
        return ProfileSnapshot(name, path, None, None, "unresolved", str(exc))
    note = "" if (path / "config.yaml").is_file() else "no config.yaml (Hermes defaults)"
    return ProfileSnapshot(name, path, config, raw, "ok", note)


def read_fleet() -> list[ProfileSnapshot]:
    """Every profile on this machine, default first. A broken profile is reported, never raised."""
    try:
        discovered = adapter.discover_profiles()
    except adapter.Unresolved:
        return []
    discovered.sort(key=lambda item: (item[0] != "default", item[0]))
    return [_snapshot(name, path) for name, path in discovered if path.is_dir()]


def find_profile(name: str) -> ProfileSnapshot | None:
    """Exact match against discovered names only; a raw string never becomes a path."""
    try:
        discovered = dict(adapter.discover_profiles())
    except adapter.Unresolved:
        return None
    path = discovered.get(str(name).strip())
    return _snapshot(str(name).strip(), path) if path is not None and path.is_dir() else None


def active_profile() -> str:
    return adapter.active_profile_name()
