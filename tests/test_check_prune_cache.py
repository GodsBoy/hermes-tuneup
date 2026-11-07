"""U4: proactive pruning on a prompt-cached subscription route (R8)."""

from checkutil import run_check
from tuneup.checks.prune_cache import check


def test_pruning_on_a_claude_subscription_route_is_high(make_profile):
    found = run_check(
        check,
        make_profile,
        """
        model: {default: claude-opus-5-5, provider: claude-subscription-directsdk-experimental}
        compression: {proactive_prune_tokens: 48000}
        """,
    )
    assert len(found) == 1
    f = found[0]
    assert f.severity == "high"
    assert (f.key_path, f.current, f.proposed) == (["compression", "proactive_prune_tokens"], 48000, 0)
    assert "cache" in f.summary
    assert "next message" in f.effect_timing


def test_pruning_on_an_api_key_route_is_not_reported(make_profile):
    found = run_check(
        check,
        make_profile,
        "model: {default: claude-opus-5-5, provider: anthropic}\ncompression: {proactive_prune_tokens: 48000}\n",
    )
    assert found == []


def test_pruning_off_is_not_reported(make_profile):
    found = run_check(
        check,
        make_profile,
        "model: {default: gpt-6.1-sol, provider: openai-codex}\ncompression: {proactive_prune_tokens: 0}\n",
    )
    assert found == []
