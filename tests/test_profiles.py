"""U2: profile discovery and read-only snapshots for the whole fleet."""

from __future__ import annotations

from tuneup import profiles


def test_fleet_lists_default_and_named_profiles(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    make_profile("alpha", "model: {default: gpt-6.1-sol, provider: openai-codex}\n")
    fleet = profiles.read_fleet()
    names = [p.name for p in fleet]
    assert names[0] == "default"
    assert set(names) == {"default", "alpha"}
    assert all(p.status == "ok" for p in fleet)


def test_invalid_profile_is_reported_not_raised(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    make_profile("broken", "compression: [unclosed\n")
    fleet = {p.name: p for p in profiles.read_fleet()}
    assert fleet["broken"].status == "unresolved"
    assert "invalid YAML" in fleet["broken"].note
    assert fleet["default"].status == "ok"


def test_profile_without_config_reports_defaults(hermes_home, make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    bare = hermes_home / "profiles" / "bare"
    bare.mkdir(parents=True)
    (bare / "SOUL.md").write_text("identity\n", encoding="utf-8")
    fleet = {p.name: p for p in profiles.read_fleet()}
    assert fleet["bare"].status == "ok"
    assert "no config.yaml" in fleet["bare"].note


def test_find_profile_matches_only_discovered_names(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    make_profile("alpha", "model: {default: gpt-6.1-sol, provider: openai-codex}\n")
    assert profiles.find_profile("alpha").name == "alpha"
    assert profiles.find_profile("../alpha") is None
    assert profiles.find_profile("missing") is None
