"""The /tuneup slash command. Runs in the gateway process: returns text, never prints."""

from __future__ import annotations

from . import confirm, fixes, profiles, render_text, report

MESSAGING_CAP = 3500
USAGE = (
    "Usage: /tuneup (report for this profile), /tuneup fix <code> (apply one fix after you confirm), "
    "/tuneup receipts on|off (record compaction receipts)."
)


def _cap_for(platform: str) -> int | None:
    return None if (platform or "").strip().lower() in confirm.LOCAL_PLATFORMS | {""} else MESSAGING_CAP


def _list_fixable(active: str) -> str:
    snapshot = profiles.find_profile(active)
    findings = report.findings_for(snapshot, active) if snapshot is not None else []
    if not findings:
        return "Nothing to fix on this profile."
    return "Fixable findings:\n" + "\n".join(f"  {f.code}  [{f.severity.upper()}] {f.check}" for f in findings)


def _fix(code: str | None, ctx, platform: str, source) -> str:
    active = profiles.active_profile()
    cron_active = bool(ctx is not None and ctx.current_cron_execution() is not None)
    refusal = confirm.slash_refusal(platform, source, cron_active)
    if refusal:
        return refusal
    if not code:
        return _list_fixable(active)
    try:
        plan = fixes.prepare(code, profile=active, active=active)
    except fixes.FixRefused as exc:
        return str(exc)
    answer = ctx.ask_choice(confirm.question(plan), list(confirm.CHOICES)) if ctx is not None else None
    if answer != "Apply":
        return confirm.NOTHING_CHANGED.format(code=fixes.normalise_code(code))
    try:
        return fixes.describe(fixes.apply(plan))
    except fixes.FixRefused as exc:
        return str(exc)


def _receipts(arg: str | None, recorder) -> str:
    if recorder is None:
        return "Receipts are not available on this surface."
    if arg not in ("on", "off"):
        return f"Receipts are {'on' if recorder.enabled() else 'off'}. Use /tuneup receipts on or /tuneup receipts off."
    recorder.set_enabled(arg == "on")
    if arg == "on":
        return (
            "Receipts are on for this profile. tuneup now records, locally and as metadata only, when each "
            "compaction fires and the cache-read share of prompt tokens. Turn off with /tuneup receipts off."
        )
    return "Receipts are off for this profile. Existing records stay until you delete plugin-data/hermes-tuneup."


def handle(
    raw_args: str = "", *, ctx=None, recorder=None, session_id: str = "", platform: str = "", source=None, **_kw
) -> str:
    parts = (raw_args or "").split()
    sub = parts[0].lower() if parts else ""
    if sub in ("", "report"):
        rep = report.build_report(active=profiles.active_profile())
        return render_text.render_active(rep, cap=_cap_for(platform))
    if sub == "fix":
        return _fix(parts[1] if len(parts) > 1 else None, ctx, platform, source)
    if sub == "receipts":
        return _receipts(parts[1].lower() if len(parts) > 1 else None, recorder)
    return USAGE


def make_handler(ctx, recorder=None):
    """Bind the plugin context so the handler can ask for confirmation, see cron runs and toggle receipts."""

    def handler(raw_args: str = "", *, session_id: str = "", platform: str = "", source=None) -> str:
        return handle(raw_args, ctx=ctx, recorder=recorder, session_id=session_id, platform=platform, source=source)

    return handler

