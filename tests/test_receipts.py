"""Opt-in prediction receipts, metadata only."""

from __future__ import annotations

import sqlite3

import pytest

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
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage(497_000, 400_000))
    rec.on_compaction(session_id="s1", old_session_id="", kind="summarize", reason="pre_api", before_tokens=478_000, after_tokens=60_000)
    [row] = _rows(home, "compactions")
    assert row["predicted_trigger"] == 500_000 and row["before_tokens"] == 478_000 and row["request_tokens"] == 497_000
    summary = receipts.summary(home)
    assert summary["compactions"][0]["compared"] is True
    assert "fired after a request of 497K" in summary["text"] and "in line with the predicted 500K trigger" in summary["text"]
    assert "message-only estimate at compaction was 478K" in summary["text"]


HAIKU = "model: {default: claude-haiku-4-5, provider: anthropic}\ncompression: {threshold: 0.75}\n"
HAIKU_ROUTE = {"model": "claude-haiku-4-5", "provider": "anthropic"}


def _haiku_session(home, last_prompt, before=131_707, reason="post_tool"):
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="s1", **HAIKU_ROUTE, usage=_usage(96_000, 90_000))
    rec.on_api_request(session_id="s1", **HAIKU_ROUTE, usage=_usage(last_prompt, last_prompt - 9_000))
    rec.on_compaction(session_id="s1", old_session_id="", kind="summarize", reason=reason, before_tokens=before, after_tokens=28_276)
    return receipts.summary(home)


def test_demo_compaction_compares_the_last_request_with_the_trigger(make_profile):
    # The tuneup-demo case: Hermes' message-only estimate was 131707 (no system prompt or tools),
    # tuneup predicted 150000, and the request just before the compaction was near the trigger.
    home = make_profile("default", HAIKU)
    summary = _haiku_session(home, last_prompt=147_912)
    [row] = _rows(home, "compactions")
    assert row["predicted_trigger"] == 150_000 and row["before_tokens"] == 131_707
    assert row["request_tokens"] == 147_912, "the last request, not the session's running total"
    [c] = summary["compactions"]
    assert c["compared"] is True and c["request_tokens"] == 147_912
    text = summary["text"]
    assert text.startswith(
        "Last threshold compaction (post_tool) fired after a request of 148K, in line with the predicted 150K trigger."
    )
    assert "provider's count of the whole request (system prompt, tools and messages)" in text
    assert "Hermes' message-only estimate at compaction was 132K" in text
    assert "fired at 132K" not in text


@pytest.mark.parametrize(
    ("last_prompt", "verdict"),
    [
        (120_000, "in line with the predicted 150K trigger"),
        (157_000, "in line with the predicted 150K trigger"),
        (171_000, "above the predicted 150K trigger"),
        (100_000, "below the predicted 150K trigger"),
    ],
)
def test_request_size_against_the_trigger_wording(make_profile, last_prompt, verdict):
    home = make_profile("default", HAIKU)
    assert verdict in _haiku_session(home, last_prompt=last_prompt)["text"]


def test_below_the_trigger_says_what_else_hermes_counts(make_profile):
    home = make_profile("default", HAIKU)
    text = _haiku_session(home, last_prompt=100_000)["text"]
    assert "Hermes also counts what was added after that request" in text


def test_provider_without_usage_leaves_the_request_size_unknown(make_profile):
    home = make_profile("default", HAIKU)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="s1", **HAIKU_ROUTE, usage=_usage(140_000, 0))
    rec.on_api_request(session_id="s1", **HAIKU_ROUTE, usage=None)
    rec.on_compaction(session_id="s1", kind="summarize", reason="post_tool", before_tokens=131_707)
    assert _rows(home, "compactions")[0]["request_tokens"] is None
    summary = receipts.summary(home)
    assert summary["compactions"][0]["compared"] is False
    assert "no request size was recorded" in summary["text"] and "predicted 150K" in summary["text"]


def test_rotated_session_uses_the_old_session_request_size(make_profile):
    home = make_profile("default", HAIKU)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="old", **HAIKU_ROUTE, usage=_usage(149_000, 140_000))
    rec.on_api_request(session_id="new", **HAIKU_ROUTE, usage=_usage(30_000, 0))
    rec.on_compaction(session_id="new", old_session_id="old", kind="summarize", reason="pre_api", before_tokens=130_000)
    assert _rows(home, "compactions")[0]["request_tokens"] == 149_000


_V1_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE sessions (session TEXT PRIMARY KEY, model TEXT, provider TEXT, calls INTEGER,"
    " prompt_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER, updated_at TEXT)",
    "CREATE TABLE compactions (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, session TEXT,"
    " kind TEXT, reason TEXT, before_tokens INTEGER, after_tokens INTEGER, messages_removed INTEGER,"
    " model TEXT, provider TEXT, predicted_trigger INTEGER)",
    "INSERT INTO meta VALUES ('schema_version', '1'), ('enabled', '1')",
    "INSERT INTO sessions VALUES ('ba34c411afee30d5', 'claude-haiku-4-5', 'anthropic', 9, 732740, 473902, 258721,"
    " '2026-11-08T20:19:16+00:00')",
    "INSERT INTO compactions (at, session, kind, reason, before_tokens, after_tokens, messages_removed, model,"
    " provider, predicted_trigger) VALUES ('2026-11-08T20:18:58+00:00', 'ba34c411afee30d5', 'summarize',"
    " 'post_tool', 131707, 28276, 6, 'claude-haiku-4-5', 'anthropic', 150000)",
)


def _v1_database(home):
    _db(home).parent.mkdir(parents=True)
    with sqlite3.connect(_db(home)) as conn:
        for statement in _V1_SCHEMA:
            conn.execute(statement)
    return _db(home)


def test_compaction_recorded_before_request_sizes_is_not_compared(make_profile):
    # The demo profile's receipt was recorded before tuneup kept request sizes.
    home = make_profile("default", HAIKU)
    db = _v1_database(home)
    before = db.read_bytes()
    summary = receipts.summary(home)
    assert db.read_bytes() == before, "reading receipts never writes or upgrades the database"
    [c] = summary["compactions"]
    assert c["compared"] is False and c["request_tokens"] is None
    text = summary["text"]
    assert text.startswith(
        "Last threshold compaction (post_tool): no request size was recorded, so it is not compared with the"
        " predicted 150K trigger."
    )
    assert "Hermes' message-only estimate was 132K, which leaves out the system prompt and tools." in text
    assert "against a predicted" not in text
    assert "Cache reads: 65% of prompt tokens." in text


def test_recording_upgrades_an_older_database_and_keeps_its_rows(make_profile):
    home = make_profile("default", HAIKU)
    _v1_database(home)
    summary = _haiku_session(home, last_prompt=147_912)
    old, new = _rows(home, "compactions")
    assert old["before_tokens"] == 131_707 and old["request_tokens"] is None
    assert new["request_tokens"] == 147_912
    assert summary["compactions"][0]["compared"] is True and summary["compactions"][1]["compared"] is False
    assert "fired after a request of 148K" in summary["text"]


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


def test_missing_message_estimate_still_compares_the_request(make_profile):
    home = make_profile("default", CFG)
    rec = receipts.Recorder(Ctx())
    rec.set_enabled(True)
    rec.on_api_request(session_id="s1", model="claude-opus-5-5", provider="anthropic", usage=_usage(495_000, 0))
    rec.on_compaction(session_id="s1", kind="summarize", reason="pre_api", before_tokens=None)
    summary = receipts.summary(home)
    assert summary["compactions"][0]["compared"] is True
    assert "fired after a request of 495K, in line with the predicted 500K trigger." in summary["text"]
    assert "message-only" not in summary["text"]


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
