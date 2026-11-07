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


def handle(raw_args: str = "", *, ctx=None, session_id: str = "", platform: str = "", source=None, **_kw) -> str:
    parts = (raw_args or "").split()
    sub = parts[0].lower() if parts else ""
    if sub in ("", "report"):
        rep = report.build_report(active=profiles.active_profile())
        return render_text.render_active(rep, cap=_cap_for(platform))
    if sub == "fix":
        return _fix(parts[1] if len(parts) > 1 else None, ctx, platform, source)
    return USAGE


def make_handler(ctx):
    """Bind the plugin context so the handler can ask for confirmation and see cron runs."""

    def handler(raw_args: str = "", *, session_id: str = "", platform: str = "", source=None) -> str:
        return handle(raw_args, ctx=ctx, session_id=session_id, platform=platform, source=source)

    return handler

