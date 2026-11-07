"""U2: the adapter reproduces Hermes' own numbers, offline, without writing anything."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuneup import hermes_adapter as adapter


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def no_network(monkeypatch):
    attempts = []

    def _blocked(*args, **kwargs):
        attempts.append(args)
        raise OSError("network blocked by test")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    return attempts


def _hermes_trigger(config: dict, model: str, provider: str, window: int) -> int:
    """Build the compressor exactly the way Hermes builds a session's, then preview."""
    from agent.agent_init import _compressor_max_tokens, _parse_compression_config
    from agent.context_compressor import ContextCompressor

    agent = SimpleNamespace(model=model, provider=provider, api_mode="", base_url="", max_tokens=None)
    cs = _parse_compression_config(agent, config)
    compressor = ContextCompressor(
        model=model,
        threshold_percent=cs.threshold,
        provider=provider,
        max_tokens=_compressor_max_tokens(agent),
        model_thresholds=cs.model_thresholds,
        threshold_tokens_cap=cs.threshold_tokens,
        quiet_mode=True,
    )
    return compressor.preview_threshold_tokens(model, window, provider)


def test_two_profiles_in_one_process_return_their_own_values(make_profile):
    a = make_profile("alpha", "compression: {threshold: 0.6}\n")
    b = make_profile("beta", "compression: {threshold: 0.7}\n")
    env_before = dict(os.environ)
    assert adapter.load_profile_config(a)["compression"]["threshold"] == 0.6
    assert adapter.load_profile_config(b)["compression"]["threshold"] == 0.7
    assert dict(os.environ) == env_before


def test_loaded_config_is_merged_over_hermes_defaults(make_profile):
    from hermes_cli.config import DEFAULT_CONFIG

    a = make_profile("alpha", "compression: {threshold: 0.6}\n")
    cfg = adapter.load_profile_config(a)
    assert cfg["compression"]["threshold"] == 0.6
    assert cfg["compression"]["proactive_prune_tokens"] == DEFAULT_CONFIG["compression"]["proactive_prune_tokens"]
    assert "delegation" in cfg


def test_reading_a_profile_writes_nothing_into_it(make_profile, no_network):
    target = make_profile(
        "alpha",
        "model: {default: claude-opus-5-5, provider: anthropic}\ncompression: {threshold: 0.5}\n",
    )
    before = _tree_snapshot(target)
    cfg = adapter.load_profile_config(target)
    adapter.resolve_window(cfg, "claude-opus-5-5", "anthropic")
    assert _tree_snapshot(target) == before
    assert not (target / "backups").exists()


def test_reading_the_active_default_home_writes_nothing(make_profile, hermes_home, no_network):
    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    before = _tree_snapshot(hermes_home)
    adapter.load_profile_config(hermes_home)
    assert _tree_snapshot(hermes_home) == before


def test_window_resolution_is_offline_and_matches_hermes(no_network):
    from agent.model_metadata import get_model_context_length

    for model, provider in [
        ("claude-opus-5-5[1m]", "claude-subscription-directsdk-experimental"),
        ("gpt-6.1-sol", "openai-codex"),
    ]:
        window = adapter.resolve_window({}, model, provider)
        expected = get_model_context_length(model, base_url="", api_key="", provider=provider)
        assert window.tokens == expected
        assert window.assumed is False
    assert no_network == []


def test_unknown_model_window_is_marked_assumed(no_network):
    window = adapter.resolve_window({}, "totally-unknown-model-x", "custom")
    assert window.tokens == 256_000
    assert window.assumed is True
    assert window.source == "fallback"


def test_config_pin_wins_and_is_reported_as_the_source(no_network):
    window = adapter.resolve_window({"model": {"context_length": 400_000}}, "totally-unknown-model-x", "custom")
    assert window.tokens == 400_000
    assert window.source == "config"
    assert window.assumed is False


@pytest.mark.parametrize(
    "compression, model, provider, window",
    [
        ({"threshold": 0.5}, "claude-opus-5-5", "anthropic", 1_000_000),
        ({"threshold": 0.5, "threshold_tokens": 256_000}, "claude-opus-5-5", "anthropic", 1_000_000),
        ({"threshold": 0.5}, "small-model", "custom", 200_000),
        ({"threshold": 0.5, "model_thresholds": {"anthropic:claude-opus": 0.8}}, "claude-opus-5-5", "anthropic", 1_000_000),
        ({"threshold": 0.5, "model_thresholds": {"anthropic:claude-opus": 0.8}}, "claude-opus-5-5", "openrouter", 1_000_000),
        ({"threshold": 0.5}, "gpt-6.1-sol", "openai-codex", 272_000),
    ],
)
def test_trigger_parity_with_hermes(compression, model, provider, window):
    config = {"compression": compression}
    preview = adapter.preview_trigger(config, model, provider, window)
    assert preview.tokens == _hermes_trigger(config, model, provider, window)


def test_explicit_cap_is_reported_as_a_factor():
    config = {"compression": {"threshold": 0.5, "threshold_tokens": 256_000}}
    preview = adapter.preview_trigger(config, "claude-opus-5-5", "anthropic", 1_000_000)
    assert preview.tokens == 256_000
    assert preview.cap == 256_000
    assert preview.ratio_tokens > preview.tokens


def test_small_window_floor_is_reported():
    preview = adapter.preview_trigger({"compression": {"threshold": 0.5}}, "small-model", "custom", 200_000)
    assert preview.effective_percent >= 0.75
    assert preview.floor_applied is True


def test_matched_rule_is_reported_only_when_it_applies():
    cfg = {"compression": {"threshold": 0.5, "model_thresholds": {"anthropic:claude-opus": 0.8}}}
    hit = adapter.preview_trigger(cfg, "claude-opus-5-5", "anthropic", 1_000_000)
    miss = adapter.preview_trigger(cfg, "claude-opus-5-5", "claude-subscription-directsdk-experimental", 1_000_000)
    assert hit.matched_rule == "anthropic:claude-opus"
    assert miss.matched_rule is None


def test_rule_rank_uses_hermes_semantics():
    assert adapter.rule_rank("openai-codex:gpt-6", "gpt-6.1-sol", "openai-codex") is not None
    assert adapter.rule_rank("openai-codex:gpt-6", "claude-opus-5-5[1m]", "claude-subscription-directsdk-experimental") is None
    assert adapter.rule_rank("claude-opus", "claude-opus-5-5", "anything") is not None


def test_missing_entry_point_makes_the_adapter_unavailable(monkeypatch):
    import agent.context_compressor as cc

    monkeypatch.delattr(cc, "resolve_model_threshold")
    missing = adapter.missing_entry_points()
    assert "agent.context_compressor.resolve_model_threshold" in missing
    with pytest.raises(adapter.Unresolved) as err:
        adapter.preview_trigger({"compression": {}}, "claude-opus-5-5", "anthropic", 1_000_000)
    assert adapter.hermes_version() in str(err.value)


def test_invalid_yaml_is_unresolved_and_writes_nothing(make_profile):
    target = make_profile("broken", "compression: [unclosed\n")
    before = _tree_snapshot(target)
    with pytest.raises(adapter.Unresolved, match="invalid YAML"):
        adapter.load_profile_config(target)
    assert _tree_snapshot(target) == before


def test_missing_config_yields_defaults(hermes_home):
    target = hermes_home / "profiles" / "empty"
    target.mkdir(parents=True)
    (target / "SOUL.md").write_text("identity\n", encoding="utf-8")
    cfg = adapter.load_profile_config(target)
    assert cfg["compression"]["enabled"] is True
