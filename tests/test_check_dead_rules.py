"""Rules in model_thresholds that never apply to any route the profile runs."""

import pytest

from checkutil import record_seen, run_check
from tuneup import models
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
    assert "cron jobs are not checked" in f.summary and "/model switches" not in f.summary
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


def test_two_dead_rules_get_distinct_fix_codes(make_profile):
    from tuneup import profiles, report

    make_profile(
        "default",
        """
        model: {default: claude-opus-5-5, provider: anthropic}
        compression:
          model_thresholds: {"llama-9": 0.7, "mistral-7": 0.6, "claude-opus": 0.5}
        """,
    )
    found = report.findings_for(profiles.find_profile("default"), "default", checks=[check])
    assert sorted(f.extra["rule"] for f in found) == ["llama-9", "mistral-7"]
    assert len({f.code for f in found}) == 2


CODEX_WITH_CLAUDE_RULE = """
model: {{default: gpt-6.1-sol, provider: openai-codex}}
delegation: {{model: gpt-6.1-sol, provider: openai-codex}}
compression:
  threshold: 0.5
  model_thresholds: {{"{rule}": 0.8}}
"""


@pytest.mark.parametrize(
    "declared, rule",
    [
        # The tuneup-demo case: switched to Codex, still switching back to Claude.
        (("anthropic", "claude-opus-5-5"), "anthropic:claude-opus"),
        ((SUBSCRIPTION, "claude-opus-5-5[1m]"), f"{SUBSCRIPTION}:claude-opus"),
    ],
)
def test_covers_ae1_ae2_a_rule_for_a_declared_model_is_not_flagged(make_profile, declared, rule):
    models.declare(*declared)
    assert run_check(check, make_profile, CODEX_WITH_CLAUDE_RULE.format(rule=rule)) == []


def test_a_rule_for_a_model_seen_in_recent_sessions_is_not_flagged(make_profile):
    make_profile("default", CODEX_WITH_CLAUDE_RULE.format(rule="anthropic:claude-opus"))
    record_seen("claude-opus-5-5", "anthropic")
    assert run_check(check, make_profile, CODEX_WITH_CLAUDE_RULE.format(rule="anthropic:claude-opus")) == []


def test_covers_ae3_an_unmatched_rule_says_how_to_declare_in_its_own_profile(make_profile):
    found = run_check(check, make_profile, CODEX_WITH_CLAUDE_RULE.format(rule="anthropic:claude-opus"), name="work")
    [f] = found
    assert "matches none of" in f.summary and "declared" in f.summary
    assert "hermes -p work tuneup models add <provider>:<model>" in f.summary
    assert "/tuneup models add <provider>:<model> in a chat for that profile" in f.summary
    assert "cron jobs are not checked" in f.summary
    assert f.proposed == {}
    assert len(f.to_dict()["summary"]) == len(f.summary), "the summary fits the report without truncation"


def test_a_rescope_still_points_at_a_declared_route_on_another_provider(make_profile):
    models.declare(SUBSCRIPTION, "claude-opus-5-5[1m]")
    [f] = run_check(check, make_profile, CODEX_WITH_CLAUDE_RULE.format(rule="anthropic:claude-opus"))
    assert f.proposed == {f"{SUBSCRIPTION}:claude-opus": 0.8}
    assert "a model you switch to" in f.summary
    assert "hermes -p default tuneup models add anthropic:<model>" in f.summary
