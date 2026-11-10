"""The adapter reproduces Hermes' own numbers, offline, without writing anything."""

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

    def _blocked_lookup(host, *args, **kwargs):
        attempts.append(("lookup", host))
        raise socket.gaierror("name lookup blocked by test")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked_lookup)
    return attempts


def _hosts(attempts) -> set[str]:
    """The host of every connection or name lookup the code under test attempted."""
    found = set()
    for attempt in attempts:
        target = attempt[1] if attempt and attempt[0] == "lookup" else attempt[0]
        found.add(str(target[0] if isinstance(target, tuple) else target))
    return found


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


# Routes whose window Hermes resolves from what it ships: no connection and no name lookup.
OFFLINE_ROUTES = [
    ("claude-opus-5-5[1m]", "claude-subscription-directsdk-experimental"),
    ("claude-opus-5-5", "anthropic"),
    ("gpt-6.1-sol", "openai-codex"),
    ("gpt-5.5", "openai"),
    ("gemini-3-pro", "gemini"),
    ("gpt-5.5", "copilot"),
    ("grok-5", "xai"),
    ("deepseek-chat", "deepseek"),
    ("llama3.3:70b", "ollama"),
    ("anthropic.claude-opus-5-5-v1:0", "bedrock"),
    ("some-model-nobody-ships", "bedrock"),
    ("totally-unknown-model-x", "custom"),
    ("mystery-model", "some-new-provider"),
    ("gpt-5.5", "azure"),
    ("glm-5", "zai"),
    ("llama-4-70b", "groq"),
    ("anthropic/claude-opus-5.5", "ai-gateway"),
]

# Routes where Hermes' own lookup may ask for a public model list. tuneup passes no base URL and
# no key, so the request carries no credentials; the README names these hosts.
PUBLIC_LIST_ROUTES = [
    ("deepseek/deepseek-chat", "openrouter", "openrouter.ai"),
    ("anthropic/claude-opus-5.5", "openrouter", "openrouter.ai"),
    ("hermes-4-405b", "nous", "openrouter.ai"),
    ("totally-unknown-model-x", "", "openrouter.ai"),
    ("deepseek/deepseek-v3", "novita", "api.novita.ai"),
]


@pytest.mark.parametrize("model, provider", OFFLINE_ROUTES)
def test_window_lookup_stays_off_the_network(no_network, model, provider):
    window = adapter.resolve_window({}, model, provider, main_route=False)
    assert window.tokens > 0
    assert no_network == []


@pytest.mark.parametrize("model, provider, allowed_host", PUBLIC_LIST_ROUTES)
def test_window_lookup_only_asks_the_disclosed_public_list(no_network, model, provider, allowed_host):
    window = adapter.resolve_window({}, model, provider, main_route=False)
    assert window.tokens > 0
    assert _hosts(no_network) <= {allowed_host}


def test_bedrock_window_comes_from_the_static_table_without_a_probe(no_network, monkeypatch):
    """Hermes' full lookup probes Bedrock with the machine's AWS credentials; tuneup must not."""
    bedrock = pytest.importorskip("agent.bedrock_adapter")
    probed = []
    monkeypatch.setattr(bedrock, "probe_bedrock_context_length", lambda *a, **k: probed.append(a) or None)
    monkeypatch.setattr(bedrock, "_get_bedrock_runtime_client", lambda *a, **k: probed.append(a))

    known = adapter.resolve_window({}, "anthropic.claude-opus-5-5-v1:0", "bedrock", main_route=False)
    assert known.tokens == bedrock.bedrock_static_context_length("anthropic.claude-opus-5-5-v1:0")
    assert known.assumed is False

    unknown = adapter.resolve_window({}, "some-model-nobody-ships", "bedrock", main_route=False)
    assert unknown.tokens == bedrock.BEDROCK_DEFAULT_CONTEXT_LENGTH
    assert unknown.assumed is True
    assert unknown.source == "fallback"

    assert probed == []
    assert no_network == []


def test_bedrock_config_pin_still_wins(no_network):
    window = adapter.resolve_window(
        {"model": {"context_length": 400_000}}, "anthropic.claude-opus-5-5-v1:0", "bedrock"
    )
    assert (window.tokens, window.source, window.assumed) == (400_000, "config", False)
    assert no_network == []


def _moa_config(provider: str, model: str) -> dict:
    return {
        "moa": {
            "default_preset": "duo",
            "presets": {
                "duo": {
                    "aggregator": {"provider": provider, "model": model},
                    "references": [{"provider": "openai-codex", "model": "gpt-6.1-sol"}],
                }
            },
        }
    }


def test_moa_window_is_the_aggregators_and_resolves_no_key(no_network, monkeypatch):
    """Hermes' full lookup resolves the aggregator's API key and probes with it; tuneup must not."""
    import hermes_cli.runtime_provider as runtime_provider

    resolved = []
    monkeypatch.setattr(
        runtime_provider, "resolve_runtime_provider", lambda *a, **k: resolved.append((a, k)) or {}
    )
    window = adapter.resolve_window(_moa_config("anthropic", "claude-opus-5-5"), "duo", "moa", main_route=False)
    expected = adapter.resolve_window({}, "claude-opus-5-5", "anthropic", main_route=False)
    assert window == expected
    assert window.assumed is False
    assert resolved == []
    assert no_network == []


def test_unknown_moa_preset_is_marked_assumed(no_network):
    for config in ({}, _moa_config("anthropic", "claude-opus-5-5")):
        window = adapter.resolve_window(config, "no-such-preset", "moa", main_route=False)
        assert (window.source, window.assumed) == ("fallback", True)
    assert no_network == []


def test_moa_preset_with_a_broken_aggregator_uses_the_one_hermes_substitutes(no_network):
    from hermes_cli.moa_config import resolve_moa_preset

    for config in (_moa_config("moa", "duo"), _moa_config("", "")):
        substituted = resolve_moa_preset(config["moa"], "duo")["aggregator"]
        window = adapter.resolve_window(config, "duo", "moa", main_route=False)
        expected = adapter.resolve_window(
            {}, *adapter.runtime_identity(substituted["model"], substituted["provider"]), main_route=False
        )
        assert window == expected
    assert _hosts(no_network) <= {"openrouter.ai"}


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


def test_isolated_home_copies_only_the_small_allowlisted_cache_files(make_profile):
    target = make_profile("alpha", "compression: {threshold: 0.6}\n")
    (target / "cache" / "scratch").mkdir(parents=True)
    (target / "cache" / "scratch" / "huge.bin").write_bytes(b"x" * 1024)
    (target / "cache" / "openrouter_model_metadata.json").write_text("{}", encoding="utf-8")
    (target / "context_length_cache.yaml").write_text("{}\n", encoding="utf-8")
    with adapter.isolated_home(target) as home:
        copied = sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file())
    assert copied == ["cache/openrouter_model_metadata.json", "config.yaml", "context_length_cache.yaml"]


def test_isolated_home_skips_oversized_cache_files(make_profile, monkeypatch):
    target = make_profile("alpha", "compression: {threshold: 0.6}\n")
    (target / "context_length_cache.yaml").write_text("x" * 2048, encoding="utf-8")
    monkeypatch.setattr(adapter, "_MAX_COPY_BYTES", 1024)
    with adapter.isolated_home(target) as home:
        assert not (home / "context_length_cache.yaml").exists()
        assert (home / "config.yaml").exists()
