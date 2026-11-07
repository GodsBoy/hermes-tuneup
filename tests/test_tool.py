"""U5: the read-only tuneup_check agent tool."""

import json

from fleetutil import busy_fleet
from tuneup import tool


def test_schema_has_no_write_style_argument():
    props = tool.SCHEMA["parameters"]["properties"]
    for banned in ("apply", "confirm", "yes", "force", "dry_run", "fix"):
        assert banned not in props
    assert len(tool.SCHEMA["description"]) <= 600


def test_active_scope_returns_findings_with_fix_commands(make_profile):
    busy_fleet(make_profile, extra=1)
    out = json.loads(tool.handle({}))
    assert out["read_only"] is True
    assert [p["name"] for p in out["profiles"]] == ["default"]
    findings = out["profiles"][0]["findings"]
    assert findings and all(f["fix_command"].startswith("/tuneup fix ") for f in findings)
    assert out["profiles"][0]["routes"][0]["role"] == "main"


def test_all_scope_on_ten_profiles_stays_small_and_flags_truncation(make_profile):
    busy_fleet(make_profile, extra=9)
    raw = tool.handle({"scope": "all"})
    out = json.loads(raw)
    assert len(raw.encode("utf-8")) <= tool.MAX_BYTES
    assert len(out["profiles"]) == 10
    assert out["truncated"] is False
    assert all("routes" not in p for p in out["profiles"])
    others = [p for p in out["profiles"] if not p["active"]]
    assert all(p["top_finding"]["fix_command"].startswith("hermes tuneup fix ") for p in others)
    active = next(p for p in out["profiles"] if p["active"])
    assert active["top_finding"]["fix_command"].startswith("/tuneup fix ")


def test_unknown_profile_is_a_json_error(make_profile):
    busy_fleet(make_profile, extra=0)
    out = json.loads(tool.handle({"scope": "profile", "profile": "../etc"}))
    assert "error" in out


def test_internal_failure_still_returns_json(make_profile, monkeypatch):
    busy_fleet(make_profile, extra=0)

    def boom(*a, **k):
        raise RuntimeError("adapter exploded")

    monkeypatch.setattr(tool.report, "build_report", boom)
    out = json.loads(tool.handle({}))
    assert out["error"].startswith("tuneup could not build the report")
