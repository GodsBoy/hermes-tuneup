"""An explicit threshold_tokens that pulls the trigger below the ratio trigger."""

from checkutil import run_check
from tuneup.checks.cap_clamp import check


def test_covers_ae2_a_256k_cap_on_a_1m_window_is_low_and_reports_both_numbers(make_profile):
    found = run_check(
        check,
        make_profile,
        "model: {default: claude-opus-5-5, provider: anthropic}\ncompression: {threshold: 0.5, threshold_tokens: 256000}\n",
    )
    assert len(found) == 1
    f = found[0]
    assert f.severity == "low"
    assert "256K" in f.summary and "500K" in f.summary
    assert f.key_path == ["compression", "threshold_tokens"]
    assert (f.current, f.proposed) == (256000, None)
    assert "raise" in f.summary


def test_a_128k_cap_on_a_1m_window_is_medium(make_profile):
    found = run_check(
        check,
        make_profile,
        "model: {default: claude-opus-5-5, provider: anthropic}\ncompression: {threshold: 0.5, threshold_tokens: 128000}\n",
    )
    assert [f.severity for f in found] == ["medium"]


def test_no_cap_means_no_finding(make_profile):
    assert run_check(check, make_profile, "model: {default: claude-opus-5-5, provider: anthropic}\n") == []


def test_a_cap_above_the_ratio_trigger_is_not_reported(make_profile):
    found = run_check(
        check,
        make_profile,
        "model: {default: claude-opus-5-5, provider: anthropic}\ncompression: {threshold: 0.5, threshold_tokens: 600000}\n",
    )
    assert found == []
