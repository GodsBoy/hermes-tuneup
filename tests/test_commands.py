"""The /tuneup slash command report."""

from checkutil import record_seen
from fleetutil import busy_fleet
from tuneup import commands


def test_report_on_the_cli(make_profile):
    busy_fleet(make_profile, extra=1)
    out = commands.handle("", platform="cli")
    assert out.startswith("tuneup: profile default")
    assert "Fleet: 2 profiles" in out


def test_report_is_capped_on_telegram(make_profile):
    busy_fleet(make_profile, extra=1)
    assert len(commands.handle("", platform="telegram")) <= commands.MESSAGING_CAP


def test_unknown_subcommand_shows_usage(make_profile):
    busy_fleet(make_profile, extra=0)
    assert "Usage" in commands.handle("frobnicate", platform="cli")


CODEX = "model: {default: gpt-6.1-sol, provider: openai-codex}\n"


def test_slash_models_declares_lists_and_forgets_without_touching_config(make_profile):
    home = make_profile("default", CODEX)
    before = (home / "config.yaml").read_bytes()
    out = commands.handle("models add anthropic:claude-opus-5-5", platform="cli")
    assert out.startswith("Declared anthropic:claude-opus-5-5 for profile default.")
    listed = commands.handle("models", platform="cli")
    assert "You switch to: anthropic:claude-opus-5-5" in listed
    assert "/tuneup models add <provider>:<model>" in listed and "/tuneup models days <n>" in listed
    assert "already declared" in commands.handle("models add anthropic:claude-opus-5-5", platform="cli")
    assert commands.handle("models remove anthropic:claude-opus-5-5", platform="cli").startswith("Forgot")
    assert "You switch to: none declared" in commands.handle("models list", platform="cli")
    assert (home / "config.yaml").read_bytes() == before


def test_slash_models_says_when_hermes_runs_a_model_under_another_name(make_profile):
    make_profile("default", CODEX)
    out = commands.handle("models add claude:claude-opus-4.5", platform="cli")
    assert out.startswith("Declared anthropic:claude-opus-4-5 for profile default.")
    assert "how Hermes runs claude:claude-opus-4.5" in out


def test_slash_models_days_changes_the_seen_window(make_profile):
    make_profile("default", CODEX)
    assert "last 7 days" in commands.handle("models days 7", platform="cli")
    assert "Seen in the last 7 days" in commands.handle("models", platform="cli")
    assert "off" in commands.handle("models days 0", platform="cli")
    assert "whole number from 0 to 365" in commands.handle("models days 400", platform="cli")


def test_slash_models_rejects_a_bad_spec_or_action(make_profile):
    make_profile("default", CODEX)
    assert "<provider>:<model>" in commands.handle("models add claude-opus-5-5", platform="cli")
    assert "Usage: /tuneup models" in commands.handle("models frobnicate", platform="cli")
    assert "Usage: /tuneup models" in commands.handle("models add", platform="cli")


def test_chat_report_shows_the_models_you_switch_to(make_profile):
    make_profile("default", CODEX)
    commands.handle("models add anthropic:claude-opus-5-5", platform="cli")
    out = commands.handle("", platform="cli")
    assert "\nyou switch to: claude-opus-5-5 on anthropic compacts at about" in out


def test_many_models_never_push_findings_out_of_a_capped_chat(make_profile):
    busy_fleet(make_profile, extra=0)
    for i in range(40):
        record_seen(f"claude-opus-5-{i}", "anthropic")
    out = commands.handle("", platform="telegram")
    assert len(out) <= commands.MESSAGING_CAP
    assert "[HIGH]" in out and "/tuneup fix " in out
    assert "more models you switch to or were seen using, run /tuneup models" in out
    # Without a cap every route is listed.
    assert out.count("seen recently:") < commands.handle("", platform="cli").count("seen recently:") == 40
