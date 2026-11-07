"""The /tuneup and CLI text layout, including the messaging cap."""

from fleetutil import busy_fleet
from tuneup import render_text, report


def test_layout_is_header_then_findings_high_to_low_then_fleet_line(make_profile):
    busy_fleet(make_profile, extra=1)
    text = render_text.render_active(report.build_report(active="default"))
    lines = text.splitlines()
    assert lines[0].startswith("tuneup: profile default")
    assert "compacts at about" in lines[0]
    tags = [line.split("]")[0] + "]" for line in lines if line.startswith("[")]
    assert tags == sorted(tags, key=lambda t: ["[HIGH]", "[MEDIUM]", "[LOW]"].index(t))
    assert any(line.strip().startswith("fix: /tuneup fix ") for line in lines)
    assert lines[-1].startswith("Fleet: 2 profiles")


def test_messaging_cap_drops_whole_low_findings_and_keeps_the_high_one(make_profile):
    busy_fleet(make_profile, extra=0)
    rep = report.build_report(active="default")
    full = render_text.render_active(rep)
    high = next(f for f in rep["profiles"][0]["findings"] if f["severity"] == "high")
    capped = render_text.render_active(rep, cap=len(full) - 10)
    assert len(capped) <= len(full) - 10
    assert high["fix_command"] in capped
    assert "more, run hermes tuneup check" in capped
    kept = {line.strip().split()[-1] for line in capped.splitlines() if line.strip().startswith("fix: ")}
    dropped = {f["code"] for f in rep["profiles"][0]["findings"]} - kept
    assert dropped, "the cap should have dropped at least one finding"
    assert all(code not in capped for code in dropped)


def test_clean_profile_says_no_findings_and_still_shows_the_trigger(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    text = render_text.render_active(report.build_report(active="default"))
    assert "compacts at about 500K" in text
    assert "No findings" in text


def test_fleet_line_uses_singular_for_one(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\ndelegation: {reasoning_effort: high}\n")
    text = render_text.render_active(report.build_report(active="default"))
    assert text.splitlines()[-1].startswith("Fleet: 1 profile, 1 finding (")
