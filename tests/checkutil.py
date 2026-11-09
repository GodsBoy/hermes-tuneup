"""Helpers shared by the check tests."""

from __future__ import annotations

from tuneup import profiles, report


def run_check(check, make_profile, config: str, name: str = "default"):
    """Run one check the way the report does, so declared and seen models count as routes."""
    make_profile(name, config)
    snapshot = profiles.find_profile(name)
    assert snapshot is not None and snapshot.status == "ok", snapshot
    return check(snapshot, report.routes_for(snapshot))
