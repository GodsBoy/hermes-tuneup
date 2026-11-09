"""The models a profile switches to: the ones you declare, and the ones receipts saw recently.

Hermes re-resolves per-model settings such as model_thresholds on every /model switch, so a
model you switch to needs checking even though config.yaml never names it. Both lists live in
tuneup's own plugin-data folder for the profile, never in config.yaml. Writes go to the current
profile's folder; reads take any profile's folder and open it read-only.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import hermes_adapter as adapter
from .receipts import PLUGIN

DEFAULT_DAYS = 30
MAX_DAYS = 365
MAX_SPEC = 200
DAYS_KEY = "seen_days"
SPEC_FORM = "<provider>:<model>, for example anthropic:claude-opus-5-5"


class SpecError(ValueError):
    """A model spec tuneup cannot use; the message names the expected form."""


@dataclass(frozen=True)
class Known:
    """One profile's declared and recently seen models, each as (provider, model)."""

    declared: list[tuple[str, str]] = field(default_factory=list)
    seen: list[tuple[str, str]] = field(default_factory=list)
    days: int = DEFAULT_DAYS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _identity(model: str, provider: str) -> tuple[str, str]:
    """(provider, model) in the form Hermes runs, or as given when Hermes cannot say."""
    try:
        model, provider = adapter.runtime_identity(model, provider)
    except adapter.Unresolved:
        provider = (provider or "").strip().lower()
    return provider, model


def parse_spec(text: str) -> tuple[str, str]:
    """(provider, model) from "<provider>:<model>", split on the first colon as Hermes splits a scoped
    model_thresholds key, then normalised the way Hermes normalises the route it runs."""
    raw = (text or "").strip()
    provider, sep, model = raw.partition(":")
    if not (sep and provider and model) or len(raw) > MAX_SPEC or any(c.isspace() for c in raw):
        raise SpecError(f"Expected {SPEC_FORM}.")
    return _identity(model, provider)


def _connect() -> sqlite3.Connection:
    from plugins.plugin_storage import plugin_db

    conn = plugin_db(PLUGIN)
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS declared_models (provider TEXT NOT NULL, model TEXT NOT NULL, added_at TEXT,"
        " PRIMARY KEY (provider, model))"
    )
    return conn


def _write(statement: str, params: tuple) -> int:
    conn = _connect()
    try:
        changed = conn.execute(statement, params).rowcount
        conn.commit()
        return changed
    finally:
        conn.close()


def declare(provider: str, model: str) -> bool:
    """Declare a model for the current profile; False when it was already declared."""
    now = _now().isoformat(timespec="seconds")
    return _write(
        "INSERT OR IGNORE INTO declared_models (provider, model, added_at) VALUES (?, ?, ?)", (provider, model, now)
    ) == 1


def forget(provider: str, model: str) -> bool:
    """Forget a declared model for the current profile; False when it was not declared."""
    return _write("DELETE FROM declared_models WHERE provider = ? AND model = ?", (provider, model)) > 0


def set_seen_days(days: int) -> None:
    """How many days a model receipts saw keeps counting; 0 turns seen models off."""
    if not 0 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 0 and {MAX_DAYS}")
    _write("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (DAYS_KEY, str(days)))


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _days(conn: sqlite3.Connection) -> int:
    if not _has_table(conn, "meta"):
        return DEFAULT_DAYS
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (DAYS_KEY,)).fetchone()
    try:
        days = int(row[0]) if row else DEFAULT_DAYS
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return days if 0 <= days <= MAX_DAYS else DEFAULT_DAYS


def _declared(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    if not _has_table(conn, "declared_models"):
        return []
    return [(str(p), str(m)) for p, m in conn.execute("SELECT provider, model FROM declared_models ORDER BY rowid")]


def _seen(conn: sqlite3.Connection, days: int) -> list[tuple[str, str]]:
    if days == 0:
        return []
    cutoff = (_now() - timedelta(days=days)).isoformat(timespec="seconds")
    if _has_table(conn, "models_seen"):
        rows = conn.execute(
            "SELECT model, provider FROM models_seen WHERE model != '' AND last_seen >= ?"
            " ORDER BY last_seen DESC, model",
            (cutoff,),
        ).fetchall()
    elif _has_table(conn, "sessions"):
        # A receipts database not yet migrated: each session's latest model is all it has.
        rows = conn.execute(
            "SELECT model, COALESCE(provider, '') AS provider, MAX(updated_at) AS last FROM sessions"
            " WHERE model IS NOT NULL AND model != '' GROUP BY model, COALESCE(provider, '')"
            " HAVING last >= ? ORDER BY last DESC, model",
            (cutoff,),
        ).fetchall()
    else:
        return []
    found: list[tuple[str, str]] = []
    for row in rows:
        identity = _identity(str(row[0]), str(row[1] or ""))
        if identity not in found:
            found.append(identity)
    return found


def read(profile_dir: Path) -> Known:
    """A profile's declared and seen models, read without writing (read-only SQLite URI)."""
    db = Path(profile_dir) / "plugin-data" / PLUGIN / "data.db"
    if not db.is_file():
        return Known()
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            days = _days(conn)
            return Known(_declared(conn), _seen(conn, days), days)
        finally:
            conn.close()
    except sqlite3.Error:
        return Known()


def switched_for(profile_dir: Path) -> list[tuple[str, str, str]]:
    """(role, model, provider) for every declared model, then every seen model not also declared."""
    known = read(profile_dir)
    switched = [("declared", model, provider) for provider, model in known.declared]
    switched += [("seen", model, provider) for provider, model in known.seen if (provider, model) not in known.declared]
    return switched


def _spec(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def _listing(known: Known, prefix: str, profile: str) -> str:
    declared = ", ".join(_spec(p, m) for p, m in known.declared) or "none declared"
    if known.days == 0:
        seen = f"Seen models are off ({prefix} models days {DEFAULT_DAYS} turns them on)."
    else:
        listed = ", ".join(_spec(p, m) for p, m in known.seen) or "none (receipts record them: /tuneup receipts on)"
        seen = f"Seen in the last {known.days} days: {listed}"
    return "\n".join(
        [
            f"Models tuneup checks for profile {profile}, besides the ones in config.yaml:",
            f"  You switch to: {declared}",
            f"  {seen}",
            f"Declare one with {prefix} models add <provider>:<model>, forget one with {prefix} models remove "
            f"<provider>:<model>, or set how many days a seen model counts with {prefix} models days <n> (0 turns "
            "them off).",
        ]
    )


def _change(action: str, value: str, profile: str) -> tuple[bool, str]:
    if action == "days":
        try:
            days = int(value)
            set_seen_days(days)
        except ValueError:
            return False, f"Days must be a whole number from 0 to {MAX_DAYS}."
        if days == 0:
            return True, f"Seen models are off for profile {profile}; declared and configured models still count."
        return True, f"Models seen in the last {days} days now count for profile {profile}."
    try:
        provider, model = parse_spec(value)
    except SpecError as exc:
        return False, str(exc)
    spec = _spec(provider, model)
    if action == "remove":
        if forget(provider, model):
            return True, f"Forgot {spec} for profile {profile}."
        return False, f"{spec} is not declared for profile {profile}."
    if not declare(provider, model):
        return True, f"{spec} is already declared for profile {profile}."
    text = f"Declared {spec} for profile {profile}. tuneup now checks it as a model you switch to."
    if spec != value.strip():
        text += f" That is how Hermes runs {value.strip()}."
    return True, text


def command(args: list[str], *, prefix: str, profile: str, profile_dir: Path) -> tuple[bool, str]:
    """`models`, `models list`, `models add|remove <provider>:<model>` and `models days <n>` for the
    current profile. `prefix` is how the surface spells tuneup ("/tuneup" in chat, the hermes
    command in a terminal). Returns whether it succeeded and the text to show."""
    action = args[0].lower() if args else "list"
    if action == "list" and len(args) <= 1:
        return True, _listing(read(profile_dir), prefix, profile)
    if action not in ("add", "remove", "days") or len(args) != 2:
        return False, f"Usage: {prefix} models [add <provider>:<model> | remove <provider>:<model> | days <n>]"
    try:
        return _change(action, args[1], profile)
    except (sqlite3.Error, OSError) as exc:
        return False, f"tuneup could not save that ({type(exc).__name__}). Nothing changed."
