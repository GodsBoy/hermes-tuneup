"""R6: model_thresholds rules that apply to no route the profile runs."""

from __future__ import annotations

from .. import hermes_adapter as adapter
from ..config_access import raw_section
from ..redact import clean
from ..report import Finding
from ..routes import format_tokens
from ..severity import effect_timing

KEY = ["compression", "model_thresholds"]
CAVEAT = "cron jobs and /model switches are not checked"


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


def _main_trigger_text(routes) -> str:
    main = next((r for r in routes if r.role == "main" and r.trigger), None)
    return f" The main route ({clean(main.model)}) compacts at about {format_tokens(main.trigger)}." if main else ""


def check(snapshot, routes) -> list[Finding]:
    rules = raw_section(snapshot, "compression", "model_thresholds")
    if not rules:
        return []
    candidates = [r for r in routes if r.role in ("main", "fallback", "delegation") and r.model]
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
            substr = str(key).partition(":")[2]
            proposed[f"{target.provider}:{substr}"] = value
            reason = (
                f"rule '{clean(key)}' never applies: no route runs on that provider. It matches "
                f"{clean(target.model)} on {clean(target.provider)}, so rescope it to that provider."
            )
        else:
            reason = (
                f"rule '{clean(key)}' matches none of the configured main, fallback, delegation or summariser "
                f"routes ({CAVEAT}). Remove it unless you rely on it for a model you switch to."
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
