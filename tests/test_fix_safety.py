"""The fix flow never shows a secret, and every refusal or failure leaves the config as it was."""

from __future__ import annotations

import argparse

import pytest

from tuneup import cli, fixes, profiles, report

SECRETS = ("hunter2pass", "plainsecretvalue99", "pw@relay", "cookiesecret42", "credsecret42", "blocksecret42")

FLOW = """
model: {default: claude-opus-5-5, provider: anthropic}
compression: {threshold: 0.5}
auxiliary: {compression: {provider: openai-codex, model: gpt-6.1-sol, api_key: hunter2pass, base_url: 'https://user:pw@relay.test/v1'}}
providers: {x: {api_key: plainsecretvalue99, name: x}}
"""

BLOCK = """
model:
  default: claude-opus-5-5
  provider: anthropic
compression:
  threshold: 0.5
auxiliary:
  compression:
    provider: openai-codex
    session_cookie: cookiesecret42
    model: gpt-6.1-sol
    credential_file: credsecret42
    api_key: blocksecret42
"""

PRUNE = """
model: {default: claude-opus-5-5, provider: claude-subscription-directsdk-experimental}
compression: {proactive_prune_tokens: 48000}
"""


def _code(check: str, name: str = "default") -> str:
    found = report.findings_for(profiles.find_profile(name), "default")
    return next(f.code for f in found if f.check == check)


def _backups(home) -> list:
    folder = home / "backups" / "config"
    return sorted(p.name for p in folder.glob("config.yaml.tuneup.*")) if folder.exists() else []


def _assert_no_secret(text: str) -> None:
    leaked = [s for s in SECRETS if s in text]
    assert not leaked, f"secrets shown: {leaked}\n{text}"


@pytest.mark.parametrize("config", [FLOW, BLOCK], ids=["flow", "block"])
def test_preview_diff_redacts_secret_values_in_any_yaml_style(make_profile, config):
    make_profile("default", config)
    plan = fixes.prepare(_code("summariser"), profile="default", active="default")
    _assert_no_secret(plan.diff)
    assert "provider: auto" in plan.diff
    assert "[redacted]" in plan.diff


def test_preview_diff_keeps_numbers_under_token_named_keys():
    before = "compression: {threshold_tokens: 256000, threshold: 0.5}\n"
    after = "compression: {threshold: 0.5}\n"
    diff = fixes._redacted_diff(before, after)
    assert "threshold_tokens: 256000" in diff


def test_applied_message_redacts_secrets_in_mapping_values(make_profile):
    make_profile("default", FLOW)
    plan = fixes.prepare(_code("summariser"), profile="default", active="default")
    text = fixes.describe(fixes.apply(plan))
    _assert_no_secret(text)
    assert "auto" in text


def test_managed_config_is_refused_before_anything_is_written(make_profile, monkeypatch):
    home = make_profile("default", PRUNE)
    code = _code("prune_cache")
    before = (home / "config.yaml").read_bytes()
    monkeypatch.setattr(fixes.adapter, "is_managed", lambda: True)
    with pytest.raises(fixes.FixRefused, match="managed by an administrator"):
        fixes.prepare(code, profile="default", active="default")
    assert (home / "config.yaml").read_bytes() == before
    assert _backups(home) == []


def test_unreadable_profile_is_refused(make_profile):
    home = make_profile("default", PRUNE)
    code = _code("prune_cache")
    (home / "config.yaml").write_text("compression: {proactive_prune_tokens: [unclosed\n", encoding="utf-8")
    with pytest.raises(fixes.FixRefused, match="could not be read"):
        fixes.prepare(code, profile="default", active="default")
    assert _backups(home) == []


def _cli_fix(code: str) -> int:
    parser = argparse.ArgumentParser()
    cli.setup(parser)
    return cli.handle(parser.parse_args(["fix", code]))


@pytest.mark.parametrize("answer", ["no", "", "y", "YES please"])
def test_cli_anything_but_yes_changes_nothing(make_profile, monkeypatch, capsys, answer):
    home = make_profile("default", PRUNE)
    before = (home / "config.yaml").read_bytes()
    monkeypatch.setattr(cli.confirm, "cli_refusal", lambda: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    assert _cli_fix(_code("prune_cache")) == cli.EXIT_CLEAN
    assert "Nothing changed" in capsys.readouterr().out
    assert (home / "config.yaml").read_bytes() == before
    assert _backups(home) == []


def test_cli_apply_refusal_exits_unresolved(make_profile, monkeypatch, capsys):
    make_profile("default", PRUNE)
    monkeypatch.setattr(cli.confirm, "cli_refusal", lambda: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")

    def refuse(plan):
        raise fixes.FixRefused("The config changed while you were deciding. Nothing changed.")

    monkeypatch.setattr(cli.fixes, "apply", refuse)
    assert _cli_fix(_code("prune_cache")) == cli.EXIT_UNRESOLVED
    assert "changed while you were deciding" in capsys.readouterr().out


def test_cli_read_back_mismatch_warns_and_exits_high(make_profile, monkeypatch, capsys):
    make_profile("default", PRUNE)
    monkeypatch.setattr(cli.confirm, "cli_refusal", lambda: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    real_apply = fixes.apply

    def mismatched(plan):
        result = real_apply(plan)
        result.read_back_ok = False
        return result

    monkeypatch.setattr(cli.fixes, "apply", mismatched)
    assert _cli_fix(_code("prune_cache")) == cli.EXIT_HIGH
    assert "Warning: reading the value back" in capsys.readouterr().out


def test_read_back_failure_after_the_write_still_reports_the_backup(make_profile, monkeypatch):
    home = make_profile("default", PRUNE)
    plan = fixes.prepare(_code("prune_cache"), profile="default", active="default")

    def broken(*args, **kwargs):
        raise OSError("read failed")

    monkeypatch.setattr(fixes.adapter, "load_profile_config", broken)
    result = fixes.apply(plan)
    assert result.read_back_ok is False
    assert result.backup.exists() and result.backup.parent == home / "backups" / "config"
    text = fixes.describe(result)
    assert f"Backup: {result.backup}" in text
    assert "Warning: reading the value back" in text
