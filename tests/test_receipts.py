"""U8: opt-in prediction receipts, metadata only."""

from __future__ import annotations

import sqlite3

from tuneup import commands, receipts, report

CFG = "model: {default: claude-opus-5-5, provider: anthropic}\ncompression: {threshold: 0.5}\n"


class FakeState:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class Ctx:
    def __init__(self):
        self.state = FakeState()

    def current_cron_execution(self):
        return None

    def ask_choice(self, question, choices):
        return None


def _db(home):
    return home / "plugin-data" / "hermes-tuneup" / "data.db"


def _usage(prompt=100_000, cache_read=80_000):
    return {"input_tokens": prompt - cache_read, "cache_read_tokens": cache_read, "cache_write_tokens": 0, "prompt_tokens": prompt}


def _rows(home, table):
    with sqlite3.connect(_db(home)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]


def test_off_by_default_records_nothing(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage())
    rec.on_compaction(session_id="s1", kind="summarize", reason="pre_api", before_tokens=498_000)
    assert not _db(home).exists()


def test_threshold_compaction_is_compared_with_the_prediction(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage())
    rec.on_compaction(session_id="s1", old_session_id="", kind="summarize", reason="pre_api", before_tokens=498_000, after_tokens=60_000)
    [row] = _rows(home, "compactions")
    assert row["predicted_trigger"] == 500_000 and row["before_tokens"] == 498_000
    summary = receipts.summary(home)
    assert summary["compactions"][0]["compared"] is True
    assert "498K" in summary["text"] and "500K" in summary["text"] and "estimate" in summary["text"]


def test_manual_overflow_and_prune_events_are_stored_but_not_compared(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage())
    rec.on_compaction(session_id="s1", kind="summarize", reason="manual", before_tokens=200_000)
    rec.on_compaction(session_id="s1", kind="summarize", reason="overflow", before_tokens=990_000)
    rec.on_compaction(session_id="s1", kind="prune_tool_results", reason="proactive_prune", before_tokens=300_000)
    summary = receipts.summary(home)
    assert len(summary["compactions"]) == 3
    assert all(c["compared"] is False for c in summary["compactions"])


def test_rotated_session_uses_the_old_session_id(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="old", model="claude-opus-5-5", provider="anthropic", usage=_usage())
    rec.on_compaction(session_id="new", old_session_id="old", kind="summarize", reason="pre_api", before_tokens=501_000)
    assert _rows(home, "compactions")[0]["predicted_trigger"] == 500_000


def test_unknown_session_has_no_prediction(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_compaction(session_id="ghost", kind="summarize", reason="pre_api", before_tokens=400_000)
    assert _rows(home, "compactions")[0]["predicted_trigger"] is None
    assert "route unknown" in receipts.summary(home)["text"]


def test_missing_before_tokens_is_not_compared(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage())
    rec.on_compaction(session_id="s1", kind="summarize", reason="pre_api", before_tokens=None)
    assert receipts.summary(home)["compactions"][0]["compared"] is False


def test_hooks_swallow_database_errors(make_profile, monkeypatch):
    make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(receipts, "_connect", locked)
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage())
    rec.on_compaction(session_id="s1", kind="summarize", reason="pre_api", before_tokens=1)


def test_covers_ae7_no_cache_fields_reads_not_reported(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage(cache_read=0))
    assert receipts.summary(home)["cache_note"] == "not reported by this provider"


def test_cache_read_ratio_on_a_reporting_provider(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage(100_000, 80_000))
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage(100_000, 60_000))
    assert receipts.summary(home)["cache_read_ratio"] == 0.7


def test_message_content_is_never_stored(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    marker = "SECRET-CONTENT-MARKER-42"
    rec.on_api_request(
        session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage(),
        response={"text": marker}, assistant_message=marker, base_url=f"https://x/{marker}",
    )
    rec.on_compaction(session_id="s1", kind="summarize", reason="pre_api", before_tokens=1, summary=marker)
    assert marker.encode() not in _db(home).read_bytes()
    assert b"s1" not in _db(home).read_bytes()


def test_receipt_texts_for_each_state(make_profile, hermes_home):
    home = make_profile("default", CFG)
    assert receipts.summary(home)["text"] == "receipts off or tuneup not enabled in this profile"
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    assert receipts.summary(home)["text"] == "No compactions recorded yet"
    rec.set_enabled(False)
    assert receipts.summary(home)["text"] == "Receipts are off. Turn on with /tuneup receipts on"


def test_slash_toggle_uses_state_and_leaves_config_alone(make_profile):
    home = make_profile("default", CFG)
    before = (home / "config.yaml").read_bytes()
    ctx = Ctx()
    rec = receipts.Recorder(ctx)
    out = commands.handle("receipts on", ctx=ctx, recorder=rec, platform="cli")
    assert "on" in out and ctx.state.data["receipts"] is True
    commands.handle("receipts off", ctx=ctx, recorder=rec, platform="cli")
    assert ctx.state.data["receipts"] is False
    assert (home / "config.yaml").read_bytes() == before


def test_report_carries_the_receipts_section(make_profile):
    make_profile("default", CFG)
    rep = report.build_report(active="default", checks=[])
    assert rep["profiles"][0]["receipts"]["text"] == "receipts off or tuneup not enabled in this profile"


def test_register_wires_both_hooks(recording_ctx):
    from conftest import load_plugin_module

    load_plugin_module().register(recording_ctx)
    assert {"post_api_request", "post_compaction", "pre_tool_call"} <= set(recording_ctx.hooks)


def test_slash_report_and_cli_report_show_receipts(make_profile, capsys):
    import argparse

    from tuneup import cli

    make_profile("default", CFG)
    assert "Receipts: receipts off or tuneup not enabled in this profile" in commands.handle("", platform="cli")
    parser = argparse.ArgumentParser()
    cli.setup(parser)
    assert cli.handle(parser.parse_args(["report"])) == 0
    out = capsys.readouterr().out
    assert "default:" in out and "receipts off or tuneup not enabled" in out
