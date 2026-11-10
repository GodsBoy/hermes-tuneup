"""The only module in hermes-tuneup that imports undocumented Hermes internals.

Everything tuneup reports about a compaction trigger comes from Hermes' own
code: the compression-config parser, the ContextCompressor preview and the
model window lookup. Reads never touch a real profile: each one runs inside a
private temporary Hermes home that holds copies of the files Hermes needs, so
any backup or cache file Hermes writes lands there and is deleted.

If an entry point tuneup relies on is missing or has changed shape, every
call raises Unresolved naming the Hermes version, and callers report the
route as unresolved instead of guessing a number.
"""

from __future__ import annotations

import copy
import functools
import importlib
import inspect
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

from .config_access import section as _section

REQUIRED_ENTRY_POINTS: dict[str, tuple[str, ...]] = {
    "agent.agent_init": ("_parse_compression_config", "_compressor_max_tokens"),
    "agent.context_compressor": (
        "ContextCompressor",
        "resolve_model_threshold",
        "_model_threshold_key_rank",
    ),
    "agent.model_metadata": (
        "get_model_context_length",
        "DEFAULT_FALLBACK_CONTEXT",
        "DEFAULT_CONTEXT_LENGTHS",
        "MINIMUM_CONTEXT_LENGTH",
        "_longest_key_match",
    ),
    "hermes_cli.config_effective": ("load_user_config_effective",),
    "hermes_cli.model_normalize": ("normalize_model_for_provider", "_AGGREGATOR_PROVIDERS"),
    "hermes_cli.models": ("normalize_provider",),
    "hermes_cli.profiles": ("list_profile_names", "get_profile_dir", "get_active_profile_name"),
    "hermes_constants": ("parse_reasoning_effort",),
    "tools.delegate_tool": ("_child_compression_cap_tokens",),
}

_REQUIRED_PARAMETERS: dict[tuple[str, str], tuple[str, ...]] = {
    ("agent.model_metadata", "get_model_context_length"): (
        "model",
        "base_url",
        "api_key",
        "config_context_length",
        "provider",
        "custom_providers",
    ),
    ("agent.context_compressor", "ContextCompressor"): (
        "model",
        "threshold_percent",
        "provider",
        "max_tokens",
        "model_thresholds",
        "threshold_tokens_cap",
        "quiet_mode",
        "custom_providers",
    ),
}

_COMPRESSOR_METHODS = ("_derive_trigger", "_effective_threshold_cap", "_compute_threshold_tokens")

# The only files a window lookup reads from a profile's home. Copied one by one and
# size-capped: a profile's cache/ directory can hold many gigabytes of unrelated data.
_CACHE_FILES = (
    "context_length_cache.yaml",
    "cache/local_endpoint_probes.json",
    "cache/openrouter_model_metadata.json",
    "cache/endpoint_model_metadata.json",
)
_MAX_COPY_BYTES = 8 * 1024 * 1024


class Unresolved(Exception):
    """Hermes could not answer this question faithfully; report it, never guess."""


@dataclass(frozen=True)
class Window:
    tokens: int
    source: str  # "config", "custom provider", "hermes" or "fallback"
    assumed: bool


@dataclass(frozen=True)
class TriggerPreview:
    tokens: int
    ratio_tokens: int
    base_percent: float
    effective_percent: float
    cap: int | None
    output_reservation: int | None
    matched_rule: str | None
    floor_applied: bool


def hermes_version() -> str:
    try:
        from hermes_cli import __version__

        return str(__version__)
    except Exception:
        return "unknown"


def missing_entry_points() -> list[str]:
    """Dotted names tuneup needs that this Hermes does not provide in the expected shape."""
    missing: list[str] = []
    for module_name, names in REQUIRED_ENTRY_POINTS.items():
        try:
            module = importlib.import_module(module_name)
        except Exception:
            missing.extend(f"{module_name}.{name}" for name in names)
            continue
        for name in names:
            if not hasattr(module, name):
                missing.append(f"{module_name}.{name}")
    for (module_name, name), params in _REQUIRED_PARAMETERS.items():
        target = _lookup(module_name, name)
        if target is None:
            continue
        try:
            accepted = inspect.signature(target).parameters
        except (TypeError, ValueError):
            missing.append(f"{module_name}.{name}(signature)")
            continue
        missing.extend(f"{module_name}.{name}({p})" for p in params if p not in accepted)
    compressor = _lookup("agent.context_compressor", "ContextCompressor")
    if compressor is not None:
        missing.extend(
            f"agent.context_compressor.ContextCompressor.{m}" for m in _COMPRESSOR_METHODS if not hasattr(compressor, m)
        )
    return missing


def _lookup(module_name: str, name: str) -> Any:
    try:
        return getattr(importlib.import_module(module_name), name, None)
    except Exception:
        return None


def _require() -> None:
    missing = missing_entry_points()
    if missing:
        raise Unresolved(f"Hermes {hermes_version()} does not provide {', '.join(missing)}")


@contextmanager
def isolated_home(source_dir: Path | None = None) -> Iterator[Path]:
    """A throwaway Hermes home holding copies of a profile's config and caches."""
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    temp = Path(tempfile.mkdtemp(prefix="tuneup-home-"))
    try:
        if source_dir is not None:
            config = source_dir / "config.yaml"
            if config.is_file():
                shutil.copy2(config, temp / "config.yaml")
            for name in _CACHE_FILES:
                source = source_dir / name
                if source.is_file() and not source.is_symlink() and source.stat().st_size <= _MAX_COPY_BYTES:
                    (temp / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, temp / name)
        token = set_hermes_home_override(temp)
        try:
            yield temp
        finally:
            reset_hermes_home_override(token)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def _deep_merge(base: dict, overlay: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_raw_user_config(profile_dir: Path) -> dict:
    """The profile's user layer as Hermes reads it (env expanded, managed overlay), no defaults."""
    _require()
    from hermes_cli.config_effective import load_user_config_effective

    with isolated_home(profile_dir) as home:
        try:
            return load_user_config_effective(home / "config.yaml", fail_closed=True)
        except Exception as exc:  # Hermes raises its YAML parser's error type
            raise Unresolved(f"invalid YAML in config.yaml: {type(exc).__name__}") from None


def load_profile_config(profile_dir: Path, raw: dict | None = None) -> dict:
    """The profile's effective config merged over Hermes' defaults, read without side effects.

    Pass the already-loaded user layer as `raw` to avoid reading the profile twice.
    """
    from hermes_cli.config import DEFAULT_CONFIG

    return _deep_merge(DEFAULT_CONFIG, load_raw_user_config(profile_dir) if raw is None else raw)


def discover_profiles() -> list[tuple[str, Path]]:
    _require()
    from hermes_cli.profiles import get_profile_dir, list_profile_names

    return [(name, Path(get_profile_dir(name))) for name in list_profile_names()]


def active_profile_name() -> str:
    try:
        from hermes_cli.profiles import get_active_profile_name

        return str(get_active_profile_name() or "default")
    except Exception:
        return "default"


@functools.lru_cache(maxsize=256)
def runtime_identity(model: str, provider: str) -> tuple[str, str]:
    """The (model, provider) a running agent uses for a route, as Hermes normalises them at start-up.

    Hermes canonicalises the provider (an alias such as "claude" becomes "anthropic") and, except on
    an aggregator, rewrites the model id for it (Anthropic dots become hyphens). An empty or "auto"
    provider is left alone: Hermes resolves those from credentials, never from the name.

    Cached: the answer depends only on the two names (it is worked out in an empty home), and each
    fresh home makes Hermes rebuild its provider registry, which a report polled every minute
    would otherwise pay for every route.
    """
    _require()
    from hermes_cli.model_normalize import _AGGREGATOR_PROVIDERS, normalize_model_for_provider
    from hermes_cli.models import normalize_provider

    model = (model or "").strip()
    raw = (provider or "").strip().lower()
    if raw in ("", "auto"):
        return model, raw
    with isolated_home():
        canonical = normalize_provider(raw)
        if not model or canonical in _AGGREGATOR_PROVIDERS:
            return model, canonical
        return normalize_model_for_provider(model, canonical), canonical


def rule_rank(key: str, model: str, provider: str) -> tuple[int, int] | None:
    """Hermes' own ranking of one model_thresholds key for a route; None when it does not apply."""
    _require()
    from agent.context_compressor import _model_threshold_key_rank

    return _model_threshold_key_rank(str(key), model or "", (provider or "").strip().lower())


def _bedrock_window(model: str) -> Window | None:
    """A Bedrock model's window from Hermes' offline table, or None when that table is unavailable.

    Hermes' full lookup finds a Bedrock window by sending oversized prompts with the machine's AWS
    credentials. A read-only report must never do that, so Bedrock routes stop at the table Hermes
    itself falls back to, and an unknown model is reported as assumed.
    """
    try:
        from agent.bedrock_adapter import BEDROCK_DEFAULT_CONTEXT_LENGTH, bedrock_static_context_length
    except Exception:  # Hermes skips Bedrock entirely when its adapter cannot be imported
        return None
    try:
        known = bedrock_static_context_length(model)
    except Exception:
        known = None
    if isinstance(known, int) and known > 0:
        return Window(tokens=known, source="hermes", assumed=False)
    return Window(tokens=int(BEDROCK_DEFAULT_CONTEXT_LENGTH), source="fallback", assumed=True)


def _moa_aggregator(config: dict, preset: str) -> tuple[str, str] | None:
    """(model, provider) of the aggregator behind a Mixture of Agents preset, or None if it has none.

    Hermes' full lookup resolves the aggregator's base URL and API key and probes with them. tuneup
    reads the preset from config alone, so the aggregator is priced like any other route, without a key.
    """
    try:
        from hermes_cli.moa_config import resolve_moa_preset

        aggregator = resolve_moa_preset(config.get("moa") or {}, preset).get("aggregator") or {}
    except Exception:
        return None
    provider = str(aggregator.get("provider") or "").strip()
    model = str(aggregator.get("model") or "").strip()
    if not model or not provider or provider.lower() == "moa":
        return None
    return model, provider


def resolve_window(config: dict, model: str, provider: str, *, main_route: bool = True) -> Window:
    """The route's context window. No base URL or key is ever passed, so no request carries credentials.

    Most routes are resolved from what Hermes ships. For OpenRouter and Nous routes, and for a route
    with no provider, Hermes' lookup may fetch OpenRouter's public model list; for Novita, Novita's.
    Bedrock and Mixture of Agents routes never reach that lookup: Hermes would probe AWS, or resolve
    the aggregator's key, to answer them.
    """
    _require()
    from agent.model_metadata import (
        DEFAULT_CONTEXT_LENGTHS,
        DEFAULT_FALLBACK_CONTEXT,
        _longest_key_match,
        get_model_context_length,
    )

    model_cfg = _section(config, "model")
    custom_providers = config.get("custom_providers") if isinstance(config.get("custom_providers"), list) else None
    pin, source = None, "hermes"
    if main_route and model_cfg.get("context_length"):
        try:
            pin, source = int(model_cfg["context_length"]), "config"
        except (TypeError, ValueError):
            pin = None
    if pin is None and custom_providers:
        try:
            from hermes_cli.config import get_custom_provider_context_length

            found = get_custom_provider_context_length(
                model=model, base_url=str(model_cfg.get("base_url") or ""), custom_providers=custom_providers
            )
            if found:
                pin, source = int(found), "custom provider"
        except Exception:
            pin = None
    if pin is None and (provider or "") == "bedrock":
        bedrock = _bedrock_window(model)
        if bedrock is not None:
            return bedrock
    if pin is None and (provider or "").strip().lower() == "moa":
        aggregator = _moa_aggregator(config, model)
        if aggregator is None:
            return Window(tokens=int(DEFAULT_FALLBACK_CONTEXT), source="fallback", assumed=True)
        return resolve_window(config, *runtime_identity(*aggregator), main_route=False)
    with isolated_home():
        tokens = int(
            get_model_context_length(
                model,
                base_url="",
                api_key="",
                config_context_length=pin,
                provider=provider or "",
                custom_providers=custom_providers,
            )
        )
    if pin is None and tokens == DEFAULT_FALLBACK_CONTEXT and _longest_key_match(DEFAULT_CONTEXT_LENGTHS, model.lower()) is None:
        return Window(tokens=tokens, source="fallback", assumed=True)
    return Window(tokens=tokens, source=source, assumed=False)


def compression_settings(config: dict, model: str, provider: str) -> SimpleNamespace:
    """Hermes' own parse of the compression section for one route."""
    _require()
    from agent.agent_init import _parse_compression_config

    agent = SimpleNamespace(model=model, provider=provider or "", api_mode="", base_url="", max_tokens=None)
    try:
        return _parse_compression_config(agent, config)
    except Exception as exc:
        raise Unresolved(f"Hermes rejected the compression settings: {type(exc).__name__}") from None


def preview_trigger(config: dict, model: str, provider: str, window: int) -> TriggerPreview:
    """The compaction trigger Hermes would install for this route and window."""
    _require()
    from agent.agent_init import _compressor_max_tokens
    from agent.context_compressor import ContextCompressor

    provider = provider or ""
    cs = compression_settings(config, model, provider)
    agent = SimpleNamespace(model=model, provider=provider, api_mode="", base_url="", max_tokens=None)
    reservation = _compressor_max_tokens(agent)
    compressor = ContextCompressor(
        model=model,
        threshold_percent=cs.threshold,
        provider=provider,
        max_tokens=reservation,
        model_thresholds=cs.model_thresholds,
        threshold_tokens_cap=cs.threshold_tokens,
        quiet_mode=True,
        custom_providers=config.get("custom_providers") if isinstance(config.get("custom_providers"), list) else None,
    )
    base, effective, tokens = compressor._derive_trigger(model, window, provider)
    ratio = compressor._compute_threshold_tokens(window, effective, compressor.max_tokens)
    ranked = [(rule_rank(k, model, provider), k) for k in cs.model_thresholds]
    best = max(((r, k) for r, k in ranked if r is not None), default=None)
    return TriggerPreview(
        tokens=int(tokens),
        ratio_tokens=int(ratio),
        base_percent=float(base),
        effective_percent=float(effective),
        cap=compressor._effective_threshold_cap(window),
        output_reservation=compressor.max_tokens,
        matched_rule=best[1] if best else None,
        floor_applied=float(effective) > float(base),
    )


def delegation_cap(raw: Any) -> int | None:
    """Hermes' validation of delegation.compression_threshold_tokens (an int >= 16000, else no cap)."""
    _require()
    from tools.delegate_tool import _child_compression_cap_tokens

    return _child_compression_cap_tokens(raw)


def parse_reasoning_effort(raw: Any) -> dict | None:
    """Hermes' reading of a reasoning effort: None if unset or unknown, {"enabled": False} if disabled."""
    _require()
    from hermes_constants import parse_reasoning_effort as _parse

    return _parse(raw)


def minimum_context_length() -> int:
    """The smallest window Hermes accepts for a summariser."""
    _require()
    from agent.model_metadata import MINIMUM_CONTEXT_LENGTH

    return int(MINIMUM_CONTEXT_LENGTH)


@contextmanager
def profile_home(profile_dir: Path) -> Iterator[Path]:
    """Point Hermes' config writer at a real profile home, for a confirmed fix only."""
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(profile_dir)
    try:
        yield profile_dir
    finally:
        reset_hermes_home_override(token)


def is_managed() -> bool:
    """True when an administrator manages this config and Hermes refuses user writes."""
    from hermes_cli.config import is_managed as _is_managed

    try:
        return bool(_is_managed())
    except Exception:
        return False


def write_value(key_path: list, value: Any) -> None:
    """Set one key on a fresh read of the current home's config.yaml and save it through Hermes.

    Must run inside isolated_home() or profile_home(); the whole raw dict is round-tripped so
    dotted and colon-bearing keys such as "openai-codex:gpt-5.6" stay intact.
    """
    from hermes_cli.config import read_raw_config, save_config

    config = read_raw_config()
    node = config
    for key in key_path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[key_path[-1]] = copy.deepcopy(value)
    save_config(config)
