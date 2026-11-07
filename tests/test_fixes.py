"""A confirmed fix applies one change safely, or changes nothing."""

from __future__ import annotations

import argparse
import os
import stat
from types import SimpleNamespace

import pytest
import yaml

from fleetutil import BUSY
from tuneup import cli, commands, fixes, profiles, report

SUB = "claude-subscription-directsdk-experimental"
PRUNE = f"model: {{default: claude-opus-5-5, provider: {SUB}}}\ncompression: {{proactive_prune_tokens: 48000}}\n"


class FakeCtx:
    def __init__(self, answer="Apply", cron=None):
        self.answer, self.cron, self.questions = answer, cron, []

    def ask_choice(self, question, choices):
        self.questions.append((question, choices))
        return self.answer

    def current_cron_execution(self):
        return self.cron


def _code(name="default", check="prune_cache"):
    rep = report.build_report(active="default")
    entry = next(p for p in rep["profiles"] if p["name"] == name)
    return next(f["code"] for f in entry["findings"] if f["check"] == check)


def _slash(raw, ctx, platform="cli", source=None):
    return commands.handle(raw, ctx=ctx, platform=platform, source=source)


def _config(path):
    return yaml.safe_load((path / "config.yaml").read_text(encoding="utf-8")) or {}


def _backups(path):
    folder = path / "backups" / "config"
    return sorted(folder.glob("config.yaml.tuneup.*")) if folder.is_dir() else []


def test_confirmed_prune_fix_writes_backup_and_reads_back(make_profile):
    home = make_profile("default", PRUNE)
    original = (home / "config.yaml").read_bytes()
    ctx = FakeCtx("Apply")
    out = _slash(f"fix {_code()}", ctx)
    assert _config(home).get("compression", {}).get("proactive_prune_tokens", 0) == 0
    [backup] = _backups(home)
    assert backup.read_bytes() == original
    assert "next message" in out and "new session in the classic CLI" in out
    assert str(backup) in out
    question, choices = ctx.questions[0]
    assert choices == ["Apply", "Cancel"]
    assert "default" in question and "48000" in question and "next message" in question


def test_covers_ae5_delegation_fix_says_new_session(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\ndelegation: {reasoning_effort: xhigh}\n")
    out = _slash(f"fix {_code(check='subagent_effort')}", FakeCtx("Apply"))
    assert "Takes effect: a new session" in out


@pytest.mark.parametrize("answer", ["Cancel", None])
def test_cancel_or_no_asker_changes_nothing(make_profile, answer):
    home = make_profile("default", PRUNE)
    before = (home / "config.yaml").read_bytes()
    out = _slash(f"fix {_code()}", FakeCtx(answer))
    assert out.startswith("Nothing changed")
    assert "hermes tuneup fix" in out
    assert (home / "config.yaml").read_bytes() == before
    assert _backups(home) == []


def test_covers_ae6_cron_refuses(make_profile):
    home = make_profile("default", PRUNE)
    before = (home / "config.yaml").read_bytes()
    out = _slash(f"fix {_code()}", FakeCtx("Apply", cron=object()))
    assert "unattended" in out
    assert (home / "config.yaml").read_bytes() == before


def test_covers_ae9_group_chat_refuses_and_dm_reaches_confirm(make_profile):
    home = make_profile("default", PRUNE)
    before = (home / "config.yaml").read_bytes()
    group = SimpleNamespace(chat_type="group", user_id="7")
    ctx = FakeCtx("Apply")
    out = _slash(f"fix {_code()}", ctx, platform="telegram", source=group)
    assert "direct message" in out and ctx.questions == []
    assert (home / "config.yaml").read_bytes() == before
    dm = SimpleNamespace(chat_type="dm", user_id="7")
    _slash(f"fix {_code()}", FakeCtx("Cancel"), platform="telegram", source=dm)


@pytest.mark.parametrize("platform, source", [("telegram", None), ("weird-platform", SimpleNamespace(chat_type="dm")), ("", None)])
def test_gate_fails_closed(make_profile, platform, source):
    home = make_profile("default", PRUNE)
    before = (home / "config.yaml").read_bytes()
    ctx = FakeCtx("Apply")
    _slash(f"fix {_code()}", ctx, platform=platform, source=source)
    assert ctx.questions == []
    assert (home / "config.yaml").read_bytes() == before


def test_bare_fix_lists_codes_and_bad_codes_are_explained(make_profile):
    make_profile("default", PRUNE)
    code = _code()
    assert code in _slash("fix", FakeCtx())
    assert _slash("fix zzzzzz", FakeCtx()).startswith("No finding with that code")
    ctx = FakeCtx("Cancel")
    _slash(f"fix  {code.upper()}  ", ctx)
    assert ctx.questions, "upper-case code with spaces should still match"


def test_stale_code_after_config_edit_is_refused(make_profile):
    home = make_profile("default", PRUNE)
    code = _code()
    (home / "config.yaml").write_text(PRUNE.replace("48000", "64000"), encoding="utf-8")
    assert _slash(f"fix {code}", FakeCtx("Apply")).startswith("No finding with that code")


def test_signature_change_between_preview_and_write_aborts(make_profile):
    home = make_profile("default", PRUNE)
    snapshot = profiles.find_profile("default")
    plan = fixes.prepare(_code(), profile="default", active="default")
    (home / "config.yaml").write_text(PRUNE + "# edited\n", encoding="utf-8")
    with pytest.raises(fixes.FixRefused, match="changed"):
        fixes.apply(plan)
    assert _backups(home) == []
    assert snapshot is not None


def test_two_fixes_in_one_second_keep_two_backups(make_profile, monkeypatch):
    home = make_profile("default", BUSY)
    monkeypatch.setattr(fixes, "_timestamp", lambda: "20261107-120000")
    fixes.apply(fixes.prepare(_code(check="prune_cache"), profile="default", active="default"))
    fixes.apply(fixes.prepare(_code(check="subagent_effort"), profile="default", active="default"))
    names = [b.name for b in _backups(home)]
    assert names == ["config.yaml.tuneup.20261107-120000", "config.yaml.tuneup.20261107-120000-2"]


def test_dotted_and_colon_keys_survive_another_fix(make_profile):
    home = make_profile(
        "default",
        f"""
        model: {{default: gpt-6.1-sol, provider: openai-codex}}
        compression:
          proactive_prune_tokens: 48000
          model_thresholds: {{"openai-codex:gpt-5.6": 0.85, "openai-codex:gpt-6": 0.85}}
        """,
    )
    fixes.apply(fixes.prepare(_code(check="prune_cache"), profile="default", active="default"))
    rules = _config(home)["compression"]["model_thresholds"]
    assert rules == {"openai-codex:gpt-5.6": 0.85, "openai-codex:gpt-6": 0.85}


def test_backup_mode_matches_a_private_original(make_profile):
    home = make_profile("default", PRUNE)
    os.chmod(home / "config.yaml", 0o600)
    fixes.apply(fixes.prepare(_code(), profile="default", active="default"))
    [backup] = _backups(home)
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE((home / "config.yaml").stat().st_mode) == 0o600


def test_preview_includes_save_normalisation_and_matches_the_write(make_profile):
    home = make_profile(
        "default",
        f"model: claude-opus-5-5\nprovider: {SUB}\ncompression: {{proactive_prune_tokens: 48000}}\n",
    )
    plan = fixes.prepare(_code(), profile="default", active="default")
    fixes.apply(plan)
    assert (home / "config.yaml").read_bytes() == plan.preview_bytes


def test_named_profile_fix_touches_only_that_profile(make_profile):
    default = make_profile("default", PRUNE)
    other = make_profile("alpha", PRUNE)
    before = (default / "config.yaml").read_bytes()
    fixes.apply(fixes.prepare(_code(name="alpha"), profile="alpha", active="default"))
    assert (default / "config.yaml").read_bytes() == before
    assert _config(other)["compression"].get("proactive_prune_tokens", 0) == 0


def test_code_from_another_profile_is_redirected(make_profile):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    make_profile("alpha", PRUNE)
    out = _slash(f"fix {_code(name='alpha')}", FakeCtx("Apply"))
    assert "belongs to profile alpha" in out and "--profile alpha" in out


def test_write_failure_leaves_the_original_intact(make_profile, monkeypatch):
    home = make_profile("default", PRUNE)
    before = (home / "config.yaml").read_bytes()
    plan = fixes.prepare(_code(), profile="default", active="default")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(fixes.adapter, "write_value", boom)
    with pytest.raises(fixes.FixRefused, match="could not write"):
        fixes.apply(plan)
    assert (home / "config.yaml").read_bytes() == before
    assert len(_backups(home)) == 1


def test_cli_fix_refuses_without_a_real_terminal(make_profile, capsys):
    home = make_profile("default", PRUNE)
    before = (home / "config.yaml").read_bytes()
    parser = argparse.ArgumentParser()
    cli.setup(parser)
    code = cli.handle(parser.parse_args(["fix", _code()]))
    assert code == cli.EXIT_UNRESOLVED
    assert "terminal" in capsys.readouterr().out
    assert (home / "config.yaml").read_bytes() == before


def test_cli_fix_has_no_yes_flag():
    parser = argparse.ArgumentParser()
    cli.setup(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["fix", "abc123", "--yes"])


def test_cli_fix_applies_after_typed_yes(make_profile, monkeypatch, capsys):
    home = make_profile("default", PRUNE)
    monkeypatch.setattr(cli.confirm, "cli_refusal", lambda: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    parser = argparse.ArgumentParser()
    cli.setup(parser)
    assert cli.handle(parser.parse_args(["fix", _code()])) == 0
    assert _config(home)["compression"].get("proactive_prune_tokens", 0) == 0
    assert "Backup:" in capsys.readouterr().out


def test_preview_diff_keeps_yaml_indentation(make_profile):
    make_profile(
        "default",
        f"""
        model:
          default: claude-opus-5-5
          provider: {SUB}
        compression:
          proactive_prune_tokens: 48000
        """,
    )
    plan = fixes.prepare(_code(), profile="default", active="default")
    assert "-  proactive_prune_tokens: 48000" in plan.diff
    assert "+  proactive_prune_tokens: 0" in plan.diff
