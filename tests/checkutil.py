"""Helpers shared by the check tests."""

from __future__ import annotations

from tuneup import profiles, receipts, report


def run_check(check, make_profile, config: str, name: str = "default"):
    """Run one check the way the report does, so declared and seen models count as routes."""
    make_profile(name, config)
    snapshot = profiles.find_profile(name)
    assert snapshot is not None and snapshot.status == "ok", snapshot
    return check(snapshot, report.routes_for(snapshot))


class _State(dict):
    """The slice of Hermes' plugin state the receipts recorder uses."""

    def set(self, key, value):
        self[key] = value


class _Ctx:
    def __init__(self):
        self.state = _State()


def record_seen(model: str, provider: str) -> None:
    """Record one API request with receipts on, as the post_api_request hook would."""
    recorder = receipts.Recorder(_Ctx())
    recorder.set_enabled(True)
    recorder.on_api_request(session_id="s1", model=model, provider=provider, usage={"prompt_tokens": 1})
