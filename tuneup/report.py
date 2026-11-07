"""The one core report every surface renders: tool, /tuneup, CLI and pane.

Surfaces add no findings of their own; they only format this object.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from . import hermes_adapter as adapter
from . import profiles as profiles_mod
from .redact import clean, scrub
from .routes import Route, build_routes

SCHEMA_VERSION = 1
CANNOT_APPLY = "Read-only. Fixes are applied only when the user types the fix command shown with each finding."


@dataclass
class Finding:
    check: str
    severity: str  # "high", "medium" or "low"
    summary: str
    evidence: dict
    key_path: list
    current: Any
    proposed: Any
    effect_timing: str
    code: str = ""
    profile: str = ""
    fix_command: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "profile": self.profile,
            "check": self.check,
            "severity": self.severity,
            "summary": clean(self.summary, 600),
            "evidence": scrub(self.evidence),
            "proposed_change": {"key_path": scrub(self.key_path), "from": scrub(self.current), "to": scrub(self.proposed)},
            "effect_timing": self.effect_timing,
            "fix_command": self.fix_command,
            **({"extra": scrub(self.extra)} if self.extra else {}),
        }


Check = Callable[[profiles_mod.ProfileSnapshot, list[Route]], list[Finding]]


def finding_code(profile: str, check: str, key_path: list, observed: Any) -> str:
    payload = json.dumps([profile, check, key_path, observed], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:6]


def fix_command(code: str, profile: str, active: str) -> str:
    if profile == active:
        return f"/tuneup fix {code}"
    return f"hermes tuneup fix {code} --profile {profile}"


def _profile_entry(snapshot: profiles_mod.ProfileSnapshot, active: str, checks: list[Check]) -> dict:
    entry = {
        "name": clean(snapshot.name),
        "active": snapshot.name == active,
        "status": snapshot.status,
        "note": clean(snapshot.note, 200),
        "routes": [],
        "findings": [],
    }
    if snapshot.status != "ok" or snapshot.config is None:
        return entry
    route_list = build_routes(snapshot.config)
    entry["routes"] = [r.to_dict() for r in route_list]
    entry["findings"] = [f.to_dict() for f in findings_for(snapshot, active, checks, route_list)]
    from .receipts import summary as receipts_summary

    entry["receipts"] = receipts_summary(snapshot.path)
    return entry


def findings_for(
    snapshot: profiles_mod.ProfileSnapshot,
    active: str,
    checks: list[Check] | None = None,
    route_list: list[Route] | None = None,
) -> list[Finding]:
    """The profile's findings with codes and fix commands, raw values intact for the fix flow."""
    if snapshot.status != "ok" or snapshot.config is None:
        return []
    checks = default_checks() if checks is None else checks
    route_list = build_routes(snapshot.config) if route_list is None else route_list
    findings: list[Finding] = []
    for check in checks:
        findings.extend(check(snapshot, route_list))
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f.severity, 3), f.check))
    for f in findings:
        f.profile = snapshot.name
        f.code = finding_code(snapshot.name, f.check, f.key_path, f.current)
        f.fix_command = fix_command(f.code, snapshot.name, active)
    return findings


def default_checks() -> list[Check]:
    try:
        from .checks import ALL_CHECKS
    except ImportError:
        return []
    return list(ALL_CHECKS)


def build_report(active: str | None = None, checks: list[Check] | None = None, only: str | None = None) -> dict:
    """The report for every profile, or for one profile when `only` names it."""
    active = active or profiles_mod.active_profile()
    checks = default_checks() if checks is None else checks
    if only is not None:
        found = profiles_mod.find_profile(only)
        fleet = [found] if found is not None else []
    else:
        fleet = profiles_mod.read_fleet()
    return {
        "schema_version": SCHEMA_VERSION,
        "hermes_version": adapter.hermes_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "read_only": True,
        "cannot_apply": CANNOT_APPLY,
        "active_profile": clean(active),
        "profiles": [_profile_entry(snapshot, active, checks) for snapshot in fleet],
        "notes": [],
    }
