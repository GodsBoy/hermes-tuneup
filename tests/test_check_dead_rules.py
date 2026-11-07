"""U4: model_thresholds rules that never apply to any route the profile runs (R6)."""

from checkutil import run_check
from tuneup.checks.dead_rules import check

SUBSCRIPTION = "claude-subscription-directsdk-experimental"


def test_covers_ae1_provider_scope_mismatch_is_reported_with_a_rescope(make_profile):
    found = run_check(
        check,
        make_profile,
        f"""
        model: {{default: claude-opus-5-5, provider: {SUBSCRIPTION}}}
        compression:
          threshold: 0.5
          model_thresholds: {{"anthropic:claude-opus": 0.8}}
        """,
    )
    assert len(found) == 1
    f = found[0]
    assert f.severity == "medium"
    assert "anthropic:claude-opus" in f.summary
    assert "500K" in f.summary
    assert f.key_path == ["compression", "model_thresholds"]
    assert f.current == {"anthropic:claude-opus": 0.8}
    assert f.proposed == {f"{SUBSCRIPTION}:claude-opus": 0.8}


def test_a_rule_live_on_the_delegation_route_is_not_reported(make_profile):
    found = run_check(
        check,
        make_profile,
        f"""
        model: {{default: "claude-opus-5-5[1m]", provider: {SUBSCRIPTION}}}
        delegation: {{model: gpt-6.1-sol, provider: openai-codex}}
        compression:
          model_thresholds: {{"openai-codex:gpt-6": 0.85}}
        """,
    )
    assert found == []


def test_a_rule_matching_nothing_proposes_removal_with_the_caveat(make_profile):
    found = run_check(
        check,
        make_profile,
        """
        model: {default: claude-opus-5-5, provider: anthropic}
        compression:
          model_thresholds: {"llama-9": 0.7, "claude-opus": 0.6}
        """,
    )
    assert len(found) == 1
    f = found[0]
    assert "llama-9" in f.summary
    assert "cron jobs and /model switches are not checked" in f.summary
    assert f.proposed == {"claude-opus": 0.6}


def test_a_dotted_key_stored_as_a_nested_mapping_is_flattened(make_profile):
    found = run_check(
        check,
        make_profile,
        """
        model: {default: gpt-6.1-sol, provider: openai-codex}
        compression:
          model_thresholds:
            gpt-6:
              1-sol: 0.85
        """,
    )
    assert len(found) == 1
    assert found[0].proposed == {"gpt-6.1-sol": 0.85}
    assert "nested" in found[0].summary


def test_no_rules_means_no_finding(make_profile):
    assert run_check(check, make_profile, "model: {default: claude-opus-5-5, provider: anthropic}\n") == []
