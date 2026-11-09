"""Rules in model_thresholds that apply to no route the profile runs."""

from __future__ import annotations

from .. import hermes_adapter as adapter
from ..config_access import raw_section
from ..redact import clean
from ..report import Finding, hermes_command
from ..routes import SWITCHED_ROLES, format_tokens, switched_aside
from ..severity import effect_timing

KEY = ["compression", "model_thresholds"]
CAVEAT = "cron jobs are not checked"
# Configured routes plus the models the profile switches to: a rule matching any of them is used.
CANDIDATE_ROLES = ("main", "fallback", "delegation", *SWITCHED_ROLES)


def _flatten(rules: dict) -> dict:
    flat = {}
    for key, value in rules.items():
        if isinstance(value, dict):
            for sub, inner in _flatten(value).items():
                flat[f"{key}.{sub}"] = inner
        else:
            flat[key] = value
    return flat


def _matches(key: str, routes) -> bool:
    return any(adapter.rule_rank(key, r.model, r.provider) is not None for r in routes)


def _rescope_target(key: str, routes):
    scope, sep, substr = key.partition(":")
    if not sep:
        return None
    for r in routes:
        if substr and substr in r.model and r.provider and r.provider.lower() != scope.strip().lower():
            return r
    return None


def _declare_hint(profile: str, spec: str) -> str:
    """How to declare a model in the finding's own profile. A check cannot know which surface or
    profile will show the finding, so it names both forms for that profile."""
    command = hermes_command(profile, f"tuneup models add {spec}")
    return f"{command} in a terminal, or /tuneup models add {spec} in a chat for that profile"


def _main_trigger_text(routes) -> str:
    main = next((r for r in routes if r.role == "main" and r.trigger), None)
    return f" The main route ({clean(main.model)}) compacts at about {format_tokens(main.trigger)}." if main else ""


def check(snapshot, routes) -> list[Finding]:
    rules = raw_section(snapshot, "compression", "model_thresholds")
    if not rules:
        return []
    candidates = [r for r in routes if r.role in CANDIDATE_ROLES and r.model]
    findings: list[Finding] = []
    nested = {k: v for k, v in rules.items() if isinstance(v, dict)}
    if nested:
        proposed = {k: v for k, v in rules.items() if not isinstance(v, dict)}
        proposed.update(_flatten(nested))
        return [
            Finding(
                check="dead_rules",
                severity="medium",
                summary=(
                    "model_thresholds holds a dotted model name stored as a nested mapping "
                    f"({', '.join(clean(k) for k in nested)}), which Hermes ignores. Flatten it so the rule applies."
                ),
                evidence={"nested_keys": [clean(k) for k in nested]},
                key_path=KEY,
                current=rules,
                proposed=proposed,
                effect_timing=effect_timing(KEY),
            )
        ]
    for key, value in rules.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or _matches(str(key), candidates):
            continue
        target = _rescope_target(str(key), candidates)
        proposed = {k: v for k, v in rules.items() if k != key}
        if target is not None:
            scope, _, substr = str(key).partition(":")
            proposed[f"{target.provider}:{substr}"] = value
            reason = (
                f"rule '{clean(key)}' never applies: no route runs on that provider. It matches "
                f"{clean(target.model)}{switched_aside(target)} on {clean(target.provider)}, so rescope it to that "
                f"provider. If you also switch to a model on {clean(scope.strip())}, declare it instead: "
                f"{_declare_hint(snapshot.name, clean(scope.strip().lower()) + ':<model>')}."
            )
        else:
            reason = (
                f"rule '{clean(key)}' matches none of this profile's configured routes, the models declared "
                f"for it or the models seen in its recent sessions ({CAVEAT}). If it is for a model you switch "
                f"to, declare that model: {_declare_hint(snapshot.name, '<provider>:<model>')}. Otherwise remove it."
            )
        findings.append(
            Finding(
                check="dead_rules",
                severity="medium",
                summary=reason + _main_trigger_text(routes),
                evidence={
                    "rule": clean(key),
                    "value": value,
                    "routes_checked": [{"role": r.role, "model": r.model, "provider": r.provider} for r in candidates],
                },
                key_path=KEY,
                current=rules,
                proposed=proposed,
                effect_timing=effect_timing(KEY),
                extra={"rule": clean(key)},
            )
        )
    return findings
