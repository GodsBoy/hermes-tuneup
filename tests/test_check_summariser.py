"""A summariser too small for the trigger it must summarise."""

from checkutil import run_check
from tuneup import models
from tuneup.checks.summariser import check


def test_covers_ae3_a_smaller_summariser_lowers_the_live_trigger(make_profile):
    found = run_check(
        check,
        make_profile,
        """
        model: {default: claude-opus-5-5, provider: anthropic}
        compression: {threshold: 0.5}
        auxiliary: {compression: {provider: openai-codex, model: gpt-6.1-sol, timeout: 120}}
        """,
    )
    assert len(found) == 1
    f = found[0]
    assert f.severity == "medium"
    assert "272K" in f.summary and "500K" in f.summary
    assert f.key_path == ["auxiliary", "compression"]
    assert f.proposed["provider"] == "auto" and f.proposed["model"] == ""
    assert f.proposed["timeout"] == 120
    assert f.effect_timing == "a new session"


def test_a_summariser_below_the_minimum_drops_middle_turns(make_profile):
    found = run_check(
        check,
        make_profile,
        """
        model: {default: claude-opus-5-5, provider: anthropic}
        auxiliary: {compression: {provider: custom, model: tiny-summariser, context_length: 32000}}
        """,
    )
    assert [f.severity for f in found] == ["high"]
    assert "without a summary" in found[0].summary


def test_auto_summariser_has_no_finding(make_profile):
    found = run_check(
        check,
        make_profile,
        "model: {default: claude-opus-5-5, provider: anthropic}\nauxiliary: {compression: {provider: auto, model: ''}}\n",
    )
    assert found == []


def test_a_large_summariser_has_no_finding(make_profile):
    found = run_check(
        check,
        make_profile,
        """
        model: {default: claude-opus-5-5, provider: anthropic}
        auxiliary: {compression: {provider: openai-codex, model: gpt-6-luna-900k}}
        """,
    )
    assert found == []


def test_a_summariser_that_lowers_only_a_route_you_switch_to_is_reported(make_profile):
    models.declare("anthropic", "claude-opus-5-5")
    found = run_check(
        check,
        make_profile,
        """
        model: {default: claude-haiku-4-5, provider: anthropic}
        compression: {threshold: 0.5}
        auxiliary: {compression: {provider: openai-codex, model: gpt-6.1-sol}}
        """,
    )
    [f] = found
    assert f.severity == "medium"
    assert "lowers compaction on claude-opus-5-5, a model you switch to, from about 500K to 272K" in f.summary
