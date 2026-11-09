"""Models a profile switches to: declared by the user, or seen by receipts in the last N days."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tuneup import models

CFG = "model: {default: gpt-6.1-sol, provider: openai-codex}\n"


def _db(home):
    return home / "plugin-data" / "hermes-tuneup" / "data.db"


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _seen_rows(home, rows, table="models_seen"):
    _db(home).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_db(home)) as conn:
        if table == "models_seen":
            conn.execute("CREATE TABLE models_seen (model TEXT, provider TEXT, last_seen TEXT)")
            conn.executemany("INSERT INTO models_seen VALUES (?, ?, ?)", rows)
        else:
            conn.execute(
                "CREATE TABLE sessions (session TEXT PRIMARY KEY, model TEXT, provider TEXT, calls INTEGER,"
                " prompt_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER, updated_at TEXT)"
            )
            conn.executemany(
                "INSERT INTO sessions VALUES (?, ?, ?, 1, 0, 0, 0, ?)",
                [(f"s{i}", model, provider, at) for i, (model, provider, at) in enumerate(rows)],
            )


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("anthropic:claude-opus-5-5", ("anthropic", "claude-opus-5-5")),
        # Stored in the form Hermes runs: provider aliases resolved, Anthropic dots made hyphens.
        ("claude:claude-opus-4.5", ("anthropic", "claude-opus-4-5")),
        ("Anthropic:claude-opus-5-5", ("anthropic", "claude-opus-5-5")),
        # Split on the first colon, as Hermes splits a scoped model_thresholds key.
        ("ollama:llama3:8b", ("custom", "llama3:8b")),
        ("claude-subscription-directsdk-experimental:claude-opus-5-5[1m]",
         ("claude-subscription-directsdk-experimental", "claude-opus-5-5[1m]")),
        ("openrouter:anthropic/claude-opus-5-5", ("openrouter", "anthropic/claude-opus-5-5")),
    ],
)
def test_a_spec_parses_to_the_identity_hermes_runs(spec, expected):
    assert models.parse_spec(spec) == expected


@pytest.mark.parametrize("spec", ["", "claude-opus-5-5", ":claude-opus-5-5", "anthropic:", "anthropic: claude", "a b:c", "x:" + "m" * 201])
def test_a_bad_spec_is_rejected_with_the_expected_form(spec):
    with pytest.raises(models.SpecError, match="<provider>:<model>"):
        models.parse_spec(spec)


def test_declare_list_and_forget_round_trip(make_profile):
    home = make_profile("default", CFG)
    before = (home / "config.yaml").read_bytes()
    assert models.declare("anthropic", "claude-opus-5-5") is True
    assert models.declare("anthropic", "claude-opus-5-5") is False
    assert models.declare("openai-codex", "gpt-6.1-sol") is True
    assert models.read(home).declared == [("anthropic", "claude-opus-5-5"), ("openai-codex", "gpt-6.1-sol")]
    assert models.forget("anthropic", "claude-opus-5-5") is True
    assert models.forget("anthropic", "claude-opus-5-5") is False
    assert models.read(home).declared == [("openai-codex", "gpt-6.1-sol")]
    assert (home / "config.yaml").read_bytes() == before, "declared models never go in config.yaml"


def test_the_seen_window_defaults_to_30_days_and_can_change(make_profile):
    home = make_profile("default", CFG)
    assert models.read(home).days == models.DEFAULT_DAYS == 30
    models.set_seen_days(14)
    assert models.read(home).days == 14
    models.set_seen_days(0)
    assert models.read(home).days == 0


def test_seen_models_inside_the_window_count_and_older_ones_do_not(make_profile):
    home = make_profile("default", CFG)
    _seen_rows(home, [
        ("claude-opus-5-5", "anthropic", _ago(3)),
        ("claude-haiku-4-5", "anthropic", _ago(45)),
        ("gpt-6.1-sol", "openai-codex", _ago(0.1)),
    ])
    assert models.read(home).seen == [("openai-codex", "gpt-6.1-sol"), ("anthropic", "claude-opus-5-5")]


def test_a_shorter_window_and_zero_days(make_profile):
    home = make_profile("default", CFG)
    models.set_seen_days(2)
    with sqlite3.connect(_db(home)) as conn:
        conn.execute("CREATE TABLE models_seen (model TEXT, provider TEXT, last_seen TEXT)")
        conn.executemany("INSERT INTO models_seen VALUES (?, ?, ?)",
                         [("claude-opus-5-5", "anthropic", _ago(3)), ("gpt-6.1-sol", "openai-codex", _ago(1))])
    assert models.read(home).seen == [("openai-codex", "gpt-6.1-sol")]
    models.set_seen_days(0)
    assert models.read(home).seen == []


def test_an_unmigrated_database_reads_seen_models_from_sessions(make_profile):
    home = make_profile("default", CFG)
    _seen_rows(home, [
        ("claude-opus-5-5", "anthropic", _ago(5)),
        ("claude-haiku-4-5", "anthropic", _ago(60)),
    ], table="sessions")
    before = _db(home).read_bytes()
    assert models.read(home).seen == [("anthropic", "claude-opus-5-5")]
    assert _db(home).read_bytes() == before, "reading never migrates or writes the database"


def test_a_profile_without_plugin_data_has_nothing_and_gains_nothing(make_profile):
    home = make_profile("default", CFG)
    known = models.read(home)
    assert (known.declared, known.seen, known.days) == ([], [], 30)
    assert not (home / "plugin-data").exists()


def test_a_model_both_declared_and_seen_is_listed_once_as_declared(make_profile):
    home = make_profile("default", CFG)
    _seen_rows(home, [("claude-opus-5-5", "anthropic", _ago(1)), ("claude-haiku-4-5", "anthropic", _ago(1))])
    models.declare("anthropic", "claude-opus-5-5")
    assert models.switched_for(home) == [
        ("declared", "claude-opus-5-5", "anthropic"),
        ("seen", "claude-haiku-4-5", "anthropic"),
    ]


def test_another_profiles_models_are_read_from_its_own_folder(make_profile, hermes_home):
    work = make_profile("work", CFG)
    make_profile("default", CFG)
    models.declare("anthropic", "claude-opus-5-5")  # the current home is the default profile
    assert models.read(work).declared == []
    assert models.read(hermes_home).declared == [("anthropic", "claude-opus-5-5")]
