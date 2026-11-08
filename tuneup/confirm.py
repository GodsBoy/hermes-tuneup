"""Who may apply a fix, where, and how they confirm it. Every gate fails closed."""

from __future__ import annotations

import os
import sys

LOCAL_PLATFORMS = {"cli", "tui", "desktop", "local"}
MESSAGING_PLATFORMS = {
    "telegram", "discord", "slack", "whatsapp", "signal", "matrix", "mattermost",
    "email", "sms", "imessage", "line", "wechat", "feishu", "dingtalk", "teams", "xchat",
}
CHOICES = ["Apply", "Cancel"]
NOTHING_CHANGED = (
    "Nothing changed. If no confirmation appeared on this surface, run "
    "`{command}` in a terminal instead."
)
UNATTENDED = "Fixes never run unattended (cron or a scheduled run). Nothing changed."


def slash_refusal(platform: str, source, cron_active: bool) -> str | None:
    """None when a /tuneup fix may ask for confirmation here, else the reason it may not."""
    if cron_active:
        return UNATTENDED
    p = (platform or "").strip().lower()
    if p in LOCAL_PLATFORMS:
        return None
    if p in MESSAGING_PLATFORMS:
        if source is None:
            return "This chat did not identify itself, so tuneup will not change config from it. Nothing changed."
        if str(getattr(source, "chat_type", "") or "").lower() == "dm":
            return None
        return "Fixes only run in a direct message or a terminal, never in a group chat. Nothing changed."
    return "Fixes only run in the Hermes CLI, TUI, Desktop or a direct message. Nothing changed."


def agent_spawned() -> bool:
    """True inside a command one of the agent's own tools launched (Hermes marks those)."""
    return bool(os.environ.get("HERMES_SESSION_ID", "").strip())


def cli_refusal() -> str | None:
    """None when a person is at a real terminal, else the reason the CLI fix will not run."""
    if agent_spawned():
        return (
            "This shell carries the agent's session marker (HERMES_SESSION_ID), so the command was "
            "started by the agent, not by you, and it will not change config. If you are at this "
            "terminal yourself, run it from a fresh shell. Nothing changed."
        )
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "hermes tuneup fix needs a person at a real terminal to confirm. Nothing changed."
    return None


def question(plan) -> str:
    return (
        f"Apply this change to profile {plan.profile}?\n{plan.diff}\n"
        f"Takes effect: {plan.effect_timing}."
    )
