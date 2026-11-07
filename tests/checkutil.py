"""Helpers shared by the check tests."""

from __future__ import annotations

from tuneup import profiles
from tuneup.routes import build_routes


def run_check(check, make_profile, config: str, name: str = "default"):
    make_profile(name, config)
    snapshot = profiles.find_profile(name)
    assert snapshot is not None and snapshot.status == "ok", snapshot
    return check(snapshot, build_routes(snapshot.config))
