"""Every model route a profile can run, with the compaction trigger Hermes gives it."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import hermes_adapter as adapter
from .config_access import section as _section
from .redact import clean


# Routes a profile reaches by switching models rather than through config.yaml, with the label
# every surface shows for them. Other roles are shown under their own name.
ROLE_LABELS = {"declared": "you switch to", "seen": "seen recently"}
SWITCHED_ROLES = tuple(ROLE_LABELS)
# The words a finding uses, commas included, to say why a switched route counts.
_ASIDES = {"declared": ", a model you switch to,", "seen": ", a model seen in recent sessions,"}


@dataclass(frozen=True)
class Route:
    role: str  # "main", "fallback", "delegation", "declared", "seen" or "summariser"
    model: str
    provider: str
    window: int | None = None
    window_source: str = ""
    window_assumed: bool = False
    trigger: int | None = None
    trigger_pct: float | None = None
    factors: dict = field(default_factory=dict)
    explain: str = ""
    status: str = "resolved"  # "resolved", "unresolved" or "off"
    note: str = ""

    def to_dict(self) -> dict:
        """Serialised for a report: every config-derived string passes through the redactor."""
        out = asdict(self)
        out["model"], out["provider"], out["note"] = clean(self.model), clean(self.provider), clean(self.note, 200)
        out["label"] = ROLE_LABELS.get(self.role, self.role)
        return out


def switched_aside(route: Route) -> str:
    """Words, set off by commas, that tell a finding why a switched route counts; "" for any other route."""
    return _ASIDES.get(route.role, "")


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{round(n / 1_000_000, 2):g}M"
    return f"{round(n / 1000)}K"


def _main_identity(config: dict) -> tuple[str, str]:
    model = config.get("model")
    if isinstance(model, dict):
        return str(model.get("default") or model.get("model") or ""), str(model.get("provider") or "")
    return str(model or ""), str(config.get("provider") or "")


def _fallback_identities(config: dict) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    entries = config.get("fallback_providers")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("model"):
                found.append((str(entry["model"]), str(entry.get("provider") or "")))
    legacy = config.get("fallback_model")
    if isinstance(legacy, dict) and legacy.get("model"):
        found.append((str(legacy["model"]), str(legacy.get("provider") or "")))
    return found


def summariser_identity(config: dict) -> tuple[str, str] | None:
    """The summariser's (model, provider), or None when it follows the main route."""
    aux = _section(_section(config, "auxiliary"), "compression")
    model = str(aux.get("model") or "").strip()
    provider = str(aux.get("provider") or "auto").strip()
    if not model or provider == "main":
        return None
    main_model, main_provider = _main_identity(config)
    resolved_provider = main_provider if provider in ("", "auto") else provider
    if model == main_model and resolved_provider == main_provider:
        return None
    return model, resolved_provider


def _summariser_route(config: dict) -> Route | None:
    identity = summariser_identity(config)
    if identity is None:
        return None
    model, provider = identity
    aux = _section(_section(config, "auxiliary"), "compression")
    try:
        if aux.get("context_length"):
            window = adapter.Window(int(aux["context_length"]), "config", False)
        else:
            window = adapter.resolve_window(config, model, provider, main_route=False)
    except (adapter.Unresolved, TypeError, ValueError) as exc:
        return Route("summariser", model, provider, status="unresolved", note=str(exc))
    return Route(
        "summariser",
        model,
        provider,
        window=window.tokens,
        window_source=window.source,
        window_assumed=window.assumed,
        explain=f"summarises with a {format_tokens(window.tokens)} window",
    )


def _explain(window: adapter.Window, trigger: int, pct: float, factors: dict) -> str:
    text = f"compacts at about {format_tokens(trigger)} tokens ({round(pct * 100)}% of a {format_tokens(window.tokens)} window)"
    reasons = []
    if factors.get("summariser_ceiling") and factors["summariser_ceiling"] == trigger:
        reasons.append("lowered to the summariser's window")
    elif factors.get("cap") and factors["cap"] == trigger and factors.get("ratio_trigger", 0) > trigger:
        reasons.append(f"capped by threshold_tokens instead of {format_tokens(factors['ratio_trigger'])}")
    if factors.get("matched_rule"):
        reasons.append(f"rule '{factors['matched_rule']}' sets {round(factors['base_percent'] * 100)}%")
    if factors.get("floor_applied"):
        reasons.append("small-window floor raises it to 75%")
    if window.assumed:
        reasons.append("window assumed; set model.context_length to pin it")
    return text + (": " + "; ".join(reasons) if reasons else "")


def _route(role: str, model: str, provider: str, config: dict, *, ceiling: int | None, extra_cap: int | None) -> Route:
    name, prov = model, provider
    if not model:
        return Route(role, name, prov, status="unresolved", note="no model configured")
    if not _section(config, "compression").get("enabled", True):
        return Route(role, name, prov, status="off", explain="compaction is off for this profile")
    try:
        window = adapter.resolve_window(config, model, provider, main_route=(role == "main"))
        route_config = config
        if extra_cap:
            compression = dict(_section(config, "compression"))
            existing = compression.get("threshold_tokens")
            compression["threshold_tokens"] = min(extra_cap, existing) if isinstance(existing, int) and existing > 0 else extra_cap
            route_config = {**config, "compression": compression}
        preview = adapter.preview_trigger(route_config, model, provider, window.tokens)
    except adapter.Unresolved as exc:
        return Route(role, name, prov, status="unresolved", note=str(exc))
    trigger = preview.tokens
    applied_ceiling = ceiling if ceiling is not None and ceiling < trigger else None
    if applied_ceiling is not None:
        trigger = applied_ceiling
    factors = {
        "matched_rule": clean(preview.matched_rule) if preview.matched_rule else None,
        "base_percent": preview.base_percent,
        "effective_percent": preview.effective_percent,
        "floor_applied": preview.floor_applied,
        "output_reservation": preview.output_reservation,
        "cap": preview.cap,
        "ratio_trigger": preview.ratio_tokens,
        "summariser_ceiling": applied_ceiling,
    }
    pct = trigger / window.tokens if window.tokens else 0.0
    return Route(
        role,
        name,
        prov,
        window=window.tokens,
        window_source=window.source,
        window_assumed=window.assumed,
        trigger=trigger,
        trigger_pct=round(pct, 4),
        factors=factors,
        explain=_explain(window, trigger, pct, factors),
    )


def identity(model: str, provider: str) -> tuple[str, str]:
    """(model, provider) as Hermes runs them, or as given (provider lower-cased) when Hermes cannot say."""
    try:
        return adapter.runtime_identity(model, provider)
    except adapter.Unresolved:
        return model, (provider or "").strip().lower()


def _already_routed(wanted: tuple[str, str], taken: list[tuple[str, str]]) -> bool:
    """Whether a route already built runs this switched model, compared as Hermes runs both.

    Only an exact match counts. A configured route with no provider (or "auto") is not the same
    route as a model seen on a named provider: the seen route carries the provider Hermes really
    used, which is what a provider-scoped model_thresholds rule is matched against.
    """
    return wanted in taken


def build_routes(config: dict, switched=()) -> list[Route]:
    """Main, fallback and delegation routes, then the models the profile switches to, then the
    summariser when it is a separate model.

    `switched` holds (role, model, provider) for declared and recently seen models; each one that is
    not already a configured route is priced by Hermes like a fallback, under the same summariser.
    """
    summariser = _summariser_route(config)
    ceiling = summariser.window if summariser is not None and summariser.status == "resolved" else None
    main_model, main_provider = _main_identity(config)
    found = [_route("main", main_model, main_provider, config, ceiling=ceiling, extra_cap=None)]
    for model, provider in _fallback_identities(config):
        found.append(_route("fallback", model, provider, config, ceiling=ceiling, extra_cap=None))
    delegation = _section(config, "delegation")
    child_model = str(delegation.get("model") or "") or main_model
    child_provider = str(delegation.get("provider") or "") or main_provider
    try:
        child_cap = adapter.delegation_cap(delegation.get("compression_threshold_tokens"))
    except adapter.Unresolved:
        child_cap = None
    found.append(_route("delegation", child_model, child_provider, config, ceiling=ceiling, extra_cap=child_cap))
    # Checked against every route built so far, so a seen model already declared is added once.
    taken = [identity(r.model, r.provider) for r in found] if switched else []
    for role, model, provider in switched:
        if not model:
            continue
        wanted = identity(model, provider)
        if _already_routed(wanted, taken):
            continue
        taken.append(wanted)
        found.append(_route(role, model, provider, config, ceiling=ceiling, extra_cap=None))
    if summariser is not None:
        found.append(summariser)
    return found
