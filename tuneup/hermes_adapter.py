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
import importlib
import inspect
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

# module -> names tuneup calls. Signature checks below cover the parameters we pass.
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
    "hermes_cli.profiles": ("list_profile_names", "get_profile_dir", "get_active_profile_name"),
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

# Files a window lookup may read from a profile's home; copied, never linked.
_CACHE_FILES = ("context_length_cache.yaml",)
_CACHE_DIRS = ("cache",)


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
                if (source_dir / name).is_file():
                    shutil.copy2(source_dir / name, temp / name)
            for name in _CACHE_DIRS:
                if (source_dir / name).is_dir():
                    shutil.copytree(source_dir / name, temp / name, symlinks=False)
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


def load_profile_config(profile_dir: Path) -> dict:
    """The profile's effective config merged over Hermes' defaults, read without side effects."""
    from hermes_cli.config import DEFAULT_CONFIG

    return _deep_merge(DEFAULT_CONFIG, load_raw_user_config(profile_dir))


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


def rule_rank(key: str, model: str, provider: str) -> tuple[int, int] | None:
    """Hermes' own ranking of one model_thresholds key for a route; None when it does not apply."""
    _require()
    from agent.context_compressor import _model_threshold_key_rank

    return _model_threshold_key_rank(str(key), model or "", (provider or "").strip().lower())


def _section(config: dict, key: str) -> dict:
    value = config.get(key) if isinstance(config, dict) else None
    return value if isinstance(value, dict) else {}


def resolve_window(config: dict, model: str, provider: str, *, main_route: bool = True) -> Window:
    """The route's context window, resolved offline (no base URL or key is ever passed)."""
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


def minimum_context_length() -> int:
    """The smallest window Hermes accepts for a summariser."""
    _require()
    from agent.model_metadata import MINIMUM_CONTEXT_LENGTH

    return int(MINIMUM_CONTEXT_LENGTH)
