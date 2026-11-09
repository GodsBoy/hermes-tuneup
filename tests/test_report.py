"""The one core report every surface renders."""

from __future__ import annotations

import json
import sys

import pytest

from tuneup import report
from tuneup.report import Finding


def _dummy_check(observed):
    def check(profile, routes_):
        return [
            Finding(
                check="dummy",
                severity="medium",
                summary=f"value is {observed}",
                evidence={"observed": observed},
                key_path=["compression", "proactive_prune_tokens"],
                current=observed,
                proposed=0,
                effect_timing="next message on the gateway",
            )
        ]

    return check


def test_report_shape(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    rep = report.build_report(active="default", checks=[])
    assert rep["schema_version"] == report.SCHEMA_VERSION
    assert rep["read_only"] is True
    assert "types the fix command" in rep["cannot_apply"]
    assert rep["profiles"][0]["name"] == "default"
    assert rep["profiles"][0]["active"] is True
    assert rep["profiles"][0]["routes"][0]["role"] == "main"
    json.dumps(rep)


def test_finding_code_is_stable_and_content_derived(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    a = report.build_report(active="default", checks=[_dummy_check(48000)])
    b = report.build_report(active="default", checks=[_dummy_check(48000)])
    c = report.build_report(active="default", checks=[_dummy_check(64000)])
    code_a = a["profiles"][0]["findings"][0]["code"]
    assert code_a == b["profiles"][0]["findings"][0]["code"]
    assert code_a != c["profiles"][0]["findings"][0]["code"]
    assert len(code_a) == 6 and all(ch in "0123456789abcdef" for ch in code_a)


def test_fix_command_depends_on_whether_the_profile_is_active(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    make_profile("alpha", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    rep = report.build_report(active="default", checks=[_dummy_check(48000)])
    by_name = {p["name"]: p for p in rep["profiles"]}
    active_code = by_name["default"]["findings"][0]["code"]
    other_code = by_name["alpha"]["findings"][0]["code"]
    assert by_name["default"]["findings"][0]["fix_command"] == f"/tuneup fix {active_code}"
    assert by_name["alpha"]["findings"][0]["fix_command"] == f"hermes -p default tuneup fix {other_code}"
    assert active_code != other_code


def test_terminal_commands_name_the_profile_they_run_in(make_profile):
    assert report.fix_command("ab12cd", "alpha", "beta") == "hermes -p beta tuneup fix ab12cd"
    # Hermes calls a home outside its profiles folder "custom", which -p cannot name.
    assert report.fix_command("ab12cd", "alpha", "custom") == "hermes tuneup fix ab12cd"


def test_terminal_report_prints_terminal_fix_commands_for_the_active_profile_too(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    make_profile("alpha", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    assert report.fix_command("ab12cd", "alpha", "alpha", terminal=True) == "hermes -p alpha tuneup fix ab12cd"
    assert report.fix_command("ab12cd", "alpha", "custom", terminal=True) == "hermes tuneup fix ab12cd"
    rep = report.build_report(active="default", checks=[_dummy_check(48000)], terminal=True)
    for entry in rep["profiles"]:
        [finding] = entry["findings"]
        assert finding["fix_command"] == f"hermes -p default tuneup fix {finding['code']}"


def test_unresolved_profile_is_carried_with_its_reason(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    make_profile("broken", "compression: [unclosed\n")
    rep = report.build_report(active="default", checks=[])
    broken = {p["name"]: p for p in rep["profiles"]}["broken"]
    assert broken["status"] == "unresolved"
    assert "invalid YAML" in broken["note"]
    assert broken["routes"] == []


def test_profile_scope_limits_the_report(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    make_profile("alpha", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    rep = report.build_report(active="default", checks=[], only="alpha")
    assert [p["name"] for p in rep["profiles"]] == ["alpha"]


def test_a_check_module_that_fails_to_import_raises_instead_of_reporting_no_findings(make_profile, monkeypatch):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    monkeypatch.setitem(sys.modules, "tuneup.checks", None)
    with pytest.raises(ImportError):
        report.default_checks()
    with pytest.raises(ImportError):
        report.build_report(active="default")


SWITCHER = """
model: {default: gpt-6.1-sol, provider: openai-codex}
compression:
  model_thresholds: {"anthropic:claude-opus": 0.8, "llama-9": 0.7}
"""


def test_declared_models_are_routes_in_the_report_and_in_the_fix_lookup(make_profile):
    from tuneup import models, profiles

    make_profile("default", SWITCHER)
    models.declare("anthropic", "claude-opus-5-5")
    entry = report.build_report(active="default")["profiles"][0]
    declared = [r for r in entry["routes"] if r["role"] == "declared"]
    assert [(r["model"], r["provider"], r["label"]) for r in declared] == [("claude-opus-5-5", "anthropic", "you switch to")]
    # The fix flow finds findings through findings_for, so it must see the same routes and codes.
    fix_side = report.findings_for(profiles.find_profile("default"), "default")
    assert sorted(f["code"] for f in entry["findings"]) == sorted(f.code for f in fix_side)
    assert [r["role"] for r in entry["routes"]] == ["main", "delegation", "declared"]
