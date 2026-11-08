"""Opt-in prediction receipts: when compaction really fired, next to the trigger tuneup predicted.

Hermes compacts on the size of the whole request: the provider's prompt count for the
last request (system prompt, tool schemas and messages) plus what was added since. The
compaction event's own token count is a rough count of the messages alone, so a receipt
compares the trigger with the last request's prompt_tokens from post_api_request and
shows the message-only count only as a labelled aside.

Metadata only. Hooks read just the normalised usage counters and the
compaction kwargs; message content, responses and URLs are never touched.
Session ids are stored as short hashes. Everything is best effort: a hook
never raises, and a locked database simply drops the record.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from . import hermes_adapter as adapter
from .routes import build_routes, format_tokens

logger = logging.getLogger(__name__)

PLUGIN = "hermes-tuneup"
STATE_KEY = "receipts"
THRESHOLD_REASONS = {"pre_api", "post_tool", "between_turns", "gateway_hygiene"}
SESSION_LIMIT = 1024
# A last request between these shares of the predicted trigger reads as in line with it.
# Below: Hermes also counts what was added after that request, often a large tool result.
# Above: the rough count of those additions can undershoot a little before Hermes acts.
IN_LINE_LOW, IN_LINE_HIGH = 0.8, 1.05

TEXT_NO_DB = "receipts off or tuneup not enabled in this profile"
TEXT_OFF = "Receipts are off. Turn on with /tuneup receipts on"
TEXT_EMPTY = "No compactions recorded yet"
NOT_REPORTED = "not reported by this provider"

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS sessions (session TEXT PRIMARY KEY, model TEXT, provider TEXT, calls INTEGER,"
    " prompt_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER, updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS compactions (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, session TEXT,"
    " kind TEXT, reason TEXT, before_tokens INTEGER, after_tokens INTEGER, messages_removed INTEGER,"
    " model TEXT, provider TEXT, predicted_trigger INTEGER, request_tokens INTEGER)",
    "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '2')",
)


class _Seen(NamedTuple):
    """What the last API request in a session told us: its route and its prompt size."""

    model: str
    provider: str
    request_tokens: int | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(session_id: str) -> str:
    return hashlib.sha256(str(session_id or "").encode("utf-8")).hexdigest()[:16]


def _connect() -> sqlite3.Connection:
    from plugins.plugin_storage import plugin_db

    conn = plugin_db(PLUGIN)
    for statement in _SCHEMA:
        conn.execute(statement)
    if "request_tokens" not in {row[1] for row in conn.execute("PRAGMA table_info(compactions)")}:
        # A database from before request sizes were kept: add the column, keep every row.
        conn.execute("ALTER TABLE compactions ADD COLUMN request_tokens INTEGER")
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    return conn


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class Recorder:
    """Holds the per-process session map and writes receipts for the current profile."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.sessions: OrderedDict[str, _Seen] = OrderedDict()
        self._warned = False

    def enabled(self) -> bool:
        try:
            return bool(self.ctx.state.get(STATE_KEY, False))
        except Exception:
            return False

    def set_enabled(self, on: bool) -> None:
        self.ctx.state.set(STATE_KEY, bool(on))
        conn = _connect()
        try:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('enabled', ?)", ("1" if on else "0",))
            conn.commit()
        finally:
            conn.close()

    def _warn_once(self, exc: Exception) -> None:
        if not self._warned:
            self._warned = True
            logger.warning("tuneup receipts skipped a record: %s", type(exc).__name__)

    def on_api_request(self, session_id: str = "", model: str = "", provider: str = "", usage=None, **_kw) -> None:
        try:
            if not self.enabled() or not session_id:
                return
            key = _hash(session_id)
            usage = usage if isinstance(usage, dict) else {}
            # The latest request only (None when the provider reported no usage), never a running total.
            self.sessions[key] = _Seen(str(model or ""), str(provider or ""), _int(usage.get("prompt_tokens")) or None)
            self.sessions.move_to_end(key)
            while len(self.sessions) > SESSION_LIMIT:
                self.sessions.popitem(last=False)
            conn = _connect()
            try:
                conn.execute(
                    "INSERT INTO sessions (session, model, provider, calls, prompt_tokens, cache_read_tokens,"
                    " cache_write_tokens, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?, ?)"
                    " ON CONFLICT(session) DO UPDATE SET calls = calls + 1, model = excluded.model,"
                    " provider = excluded.provider, prompt_tokens = prompt_tokens + excluded.prompt_tokens,"
                    " cache_read_tokens = cache_read_tokens + excluded.cache_read_tokens,"
                    " cache_write_tokens = cache_write_tokens + excluded.cache_write_tokens,"
                    " updated_at = excluded.updated_at",
                    (key, str(model or ""), str(provider or ""), _int(usage.get("prompt_tokens")),
                     _int(usage.get("cache_read_tokens")), _int(usage.get("cache_write_tokens")), _now()),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            self._warn_once(exc)

    def _predict(self, model: str, provider: str) -> int | None:
        from hermes_constants import get_hermes_home

        config = adapter.load_profile_config(Path(get_hermes_home()))
        for route in build_routes(config):
            if route.model == model and route.provider == provider and route.trigger:
                return route.trigger
        window = adapter.resolve_window(config, model, provider, main_route=False)
        return adapter.preview_trigger(config, model, provider, window.tokens).tokens

    def on_compaction(
        self, session_id: str = "", old_session_id: str = "", kind: str = "", reason: str = "",
        before_tokens=None, after_tokens=None, messages_removed=None, **_kw,
    ) -> None:
        try:
            if not self.enabled():
                return
            seen = self.sessions.get(_hash(old_session_id)) if old_session_id else None
            seen = seen or self.sessions.get(_hash(session_id))
            predicted = None
            if seen is not None:
                try:
                    predicted = self._predict(seen.model, seen.provider)
                except Exception:
                    predicted = None
            conn = _connect()
            try:
                conn.execute(
                    "INSERT INTO compactions (at, session, kind, reason, before_tokens, after_tokens, messages_removed,"
                    " model, provider, predicted_trigger, request_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (_now(), _hash(session_id), str(kind or ""), str(reason or ""),
                     before_tokens if isinstance(before_tokens, int) else None,
                     after_tokens if isinstance(after_tokens, int) else None,
                     messages_removed if isinstance(messages_removed, int) else None,
                     seen.model if seen else None, seen.provider if seen else None, predicted,
                     seen.request_tokens if seen else None),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            self._warn_once(exc)


def _threshold(row: dict) -> bool:
    return row["kind"] == "summarize" and row["reason"] in THRESHOLD_REASONS


def _compared(row: dict) -> bool:
    """Like with like only: the last request's full size against the predicted trigger."""
    return _threshold(row) and row["predicted_trigger"] is not None and row.get("request_tokens") is not None


def summary(profile_dir: Path, limit: int = 5) -> dict:
    """The receipts for one profile, read without writing (read-only SQLite URI)."""
    db = Path(profile_dir) / "plugin-data" / PLUGIN / "data.db"
    if not db.is_file():
        return {"state": "none", "text": TEXT_NO_DB, "compactions": [], "cache_read_ratio": None, "cache_note": ""}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
            rows = [dict(r) for r in conn.execute("SELECT * FROM compactions ORDER BY id DESC LIMIT ?", (limit,))]
            totals = conn.execute(
                "SELECT SUM(prompt_tokens) AS p, SUM(cache_read_tokens) AS r, SUM(cache_write_tokens) AS w FROM sessions"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return {"state": "none", "text": TEXT_NO_DB, "compactions": [], "cache_read_ratio": None, "cache_note": ""}
    prompt, read, write = (totals["p"] or 0), (totals["r"] or 0), (totals["w"] or 0)
    ratio = round(read / prompt, 4) if prompt and (read or write) else None
    cache_note = "" if ratio is not None else (NOT_REPORTED if prompt else "")
    fields = ("at", "kind", "reason", "before_tokens", "after_tokens", "predicted_trigger", "request_tokens")
    # A database from before request sizes were kept has no request_tokens column: read it as unknown.
    compactions = [{k: row.get(k) for k in fields} | {"compared": _compared(row)} for row in rows]
    if meta.get("enabled") != "1":
        state, text = "off", TEXT_OFF
    elif not compactions:
        state, text = "empty", TEXT_EMPTY
    else:
        state, text = "on", _describe(compactions, ratio, cache_note)
    return {"state": state, "text": text, "compactions": compactions, "cache_read_ratio": ratio, "cache_note": cache_note}


def _verdict(request: int, predicted: int) -> str:
    if request > predicted * IN_LINE_HIGH:
        return "above"
    if request < predicted * IN_LINE_LOW:
        return "below"
    return "in line with"


def _compared_text(c: dict) -> str:
    request, predicted = c["request_tokens"], c["predicted_trigger"]
    verdict = _verdict(request, predicted)
    text = (
        f"Last threshold compaction ({c['reason']}) fired after a request of {format_tokens(request)}, "
        f"{verdict} the predicted {format_tokens(predicted)} trigger"
    )
    if verdict == "below":
        text += " (Hermes also counts what was added after that request)"
    text += ". Request size is the provider's count of the whole request (system prompt, tools and messages)"
    if c["before_tokens"] is not None:
        text += f"; Hermes' message-only estimate at compaction was {format_tokens(c['before_tokens'])}"
    return text + "."


def _uncompared_text(c: dict) -> str:
    if _threshold(c) and c["predicted_trigger"] is not None:
        text = (
            f"Last threshold compaction ({c['reason']}): no request size was recorded, so it is not compared "
            f"with the predicted {format_tokens(c['predicted_trigger'])} trigger."
        )
        if c["before_tokens"] is not None:
            text += (
                f" Hermes' message-only estimate was {format_tokens(c['before_tokens'])}, "
                "which leaves out the system prompt and tools."
            )
        return text
    detail = "route unknown" if c["predicted_trigger"] is None and c["reason"] in THRESHOLD_REASONS else c["reason"]
    return f"Last compaction: {c['kind']} ({detail}), not compared with a prediction."


def _describe(compactions: list[dict], ratio: float | None, cache_note: str) -> str:
    latest = next((c for c in compactions if c["compared"]), None)
    text = _compared_text(latest) if latest is not None else _uncompared_text(compactions[0])
    if ratio is not None:
        text += f" Cache reads: {round(ratio * 100)}% of prompt tokens."
    elif cache_note:
        text += f" Cache reads: {cache_note}."
    return text
