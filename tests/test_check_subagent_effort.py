"""U4: subagents running at high or extra-high reasoning effort (R9)."""

import pytest

from checkutil import run_check
from tuneup.checks.subagent_effort import check

BASE = "model: {default: claude-opus-5-5, provider: anthropic}\n"


def test_delegation_xhigh_is_medium(make_profile):
    found = run_check(check, make_profile, BASE + "delegation: {reasoning_effort: xhigh}\n")
    assert len(found) == 1
    f = found[0]
    assert f.severity == "medium"
    assert "delegation.reasoning_effort" in f.summary
    assert (f.key_path, f.current, f.proposed) == (["delegation", "reasoning_effort"], "xhigh", "medium")
    assert f.effect_timing == "a new session"


def test_inherited_parent_xhigh_is_medium_and_cites_inheritance(make_profile):
    found = run_check(check, make_profile, BASE + "agent: {reasoning_effort: xhigh}\ndelegation: {reasoning_effort: ''}\n")
    assert len(found) == 1
    assert found[0].severity == "medium"
    assert "inherit" in found[0].summary
    assert found[0].current == ""


def test_parent_medium_unset_delegation_is_clean(make_profile):
    assert run_check(check, make_profile, BASE + "agent: {reasoning_effort: medium}\n") == []


def test_delegation_high_is_low(make_profile):
    found = run_check(check, make_profile, BASE + "delegation: {reasoning_effort: high}\n")
    assert [f.severity for f in found] == ["low"]


@pytest.mark.parametrize("value", ["false", "none", "disabled"])
def test_disabled_delegation_effort_is_an_explicit_override_not_inheritance(make_profile, value):
    config = BASE + f"agent: {{reasoning_effort: xhigh}}\ndelegation: {{reasoning_effort: {value}}}\n"
    assert run_check(check, make_profile, config) == []


def test_unknown_delegation_effort_inherits_the_parent_like_hermes(make_profile):
    config = BASE + "agent: {reasoning_effort: xhigh}\ndelegation: {reasoning_effort: hgih}\n"
    found = run_check(check, make_profile, config)
    assert [f.severity for f in found] == ["medium"]
    assert "inherit" in found[0].summary


def test_reasoning_parser_is_reached_through_the_adapter():
    import tuneup.checks.subagent_effort as module

    assert "hermes_constants" not in vars(module)
    assert "parse_reasoning_effort" not in vars(module)
