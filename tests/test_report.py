"""U3: the one core report every surface renders."""

from __future__ import annotations

import json

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
    assert by_name["alpha"]["findings"][0]["fix_command"] == f"hermes tuneup fix {other_code} --profile alpha"
    assert active_code != other_code


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
