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
from . import models as models_mod
from . import profiles as profiles_mod
from .receipts import summary as receipts_summary
from .redact import clean, scrub
from .routes import Route, build_routes
from .severity import severity_rank

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


def hermes_command(active: str, args: str) -> str:
    """A terminal command line that runs in the active profile, where tuneup is enabled.

    Hermes takes -p/--profile from anywhere on the line as its own profile switch, so the
    profile goes before the subcommand. Hermes names a home outside its profiles folder
    "custom", which -p cannot select, so that command relies on the shell's HERMES_HOME.
    """
    return f"hermes {args}" if active == "custom" else f"hermes -p {active} {args}"


def fix_command(code: str, profile: str, active: str, terminal: bool = False) -> str:
    """The slash command for the active profile in chat; otherwise a terminal command.

    At a shell prompt (`terminal`) a slash command does nothing, so every finding gets the
    terminal command. Another profile's finding gets it in chat too: the code names its profile.
    """
    if profile == active and not terminal:
        return f"/tuneup fix {code}"
    return hermes_command(active, f"tuneup fix {code}")


def routes_for(snapshot: profiles_mod.ProfileSnapshot) -> list[Route]:
    """Every route the profile runs: config.yaml's, plus the models it declares or was seen using.

    The report and the fix flow both build routes here, so a code a report shows is the code a
    fix finds.
    """
    return build_routes(snapshot.config, models_mod.switched_for(snapshot.path))


def _profile_entry(
    snapshot: profiles_mod.ProfileSnapshot, active: str, checks: list[Check], terminal: bool = False
) -> dict:
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
    route_list = routes_for(snapshot)
    entry["routes"] = [r.to_dict() for r in route_list]
    entry["findings"] = [f.to_dict() for f in findings_for(snapshot, active, checks, route_list, terminal)]
    entry["receipts"] = receipts_summary(snapshot.path)
    return entry


def findings_for(
    snapshot: profiles_mod.ProfileSnapshot,
    active: str,
    checks: list[Check] | None = None,
    route_list: list[Route] | None = None,
    terminal: bool = False,
) -> list[Finding]:
    """The profile's findings with codes and fix commands, raw values intact for the fix flow."""
    if snapshot.status != "ok" or snapshot.config is None:
        return []
    checks = default_checks() if checks is None else checks
    route_list = routes_for(snapshot) if route_list is None else route_list
    findings: list[Finding] = []
    for check in checks:
        findings.extend(check(snapshot, route_list))
    findings.sort(key=lambda f: (severity_rank(f.severity), f.check))
    for f in findings:
        f.profile = snapshot.name
        # The proposed value is part of the code, so two findings on one key (two dead rules) stay distinct.
        f.code = finding_code(snapshot.name, f.check, f.key_path, [f.current, f.proposed])
        f.fix_command = fix_command(f.code, snapshot.name, active, terminal)
    return findings


def default_checks() -> list[Check]:
    from .checks import ALL_CHECKS  # deferred: the check modules import this one

    return list(ALL_CHECKS)


def build_report(
    active: str | None = None, checks: list[Check] | None = None, only: str | None = None, terminal: bool = False
) -> dict:
    """The report for every profile, or for one profile when `only` names it.

    `terminal` is for the shell: every fix command is then one that runs there.
    """
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
        "profiles": [_profile_entry(snapshot, active, checks, terminal) for snapshot in fleet],
        "notes": [],
    }
