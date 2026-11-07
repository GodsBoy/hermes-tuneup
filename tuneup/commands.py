"""The /tuneup slash command. Runs in the gateway process: returns text, never prints."""

from __future__ import annotations

from . import profiles, render_text, report

MESSAGING_CAP = 3500
LOCAL_PLATFORMS = {"", "cli", "tui", "desktop", "local"}
USAGE = (
    "Usage: /tuneup (report for this profile), /tuneup fix <code> (apply one fix after you confirm), "
    "/tuneup receipts on|off (record compaction receipts)."
)


def _cap_for(platform: str) -> int | None:
    return None if (platform or "").strip().lower() in LOCAL_PLATFORMS else MESSAGING_CAP


def handle(raw_args: str = "", *, session_id: str = "", platform: str = "", source=None, **_kw) -> str:
    parts = (raw_args or "").split()
    sub = parts[0].lower() if parts else ""
    if sub in ("", "report"):
        rep = report.build_report(active=profiles.active_profile())
        return render_text.render_active(rep, cap=_cap_for(platform))
    return USAGE
