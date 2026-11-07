"""U3: per-profile routes with their real compaction triggers and plain explanations."""

from __future__ import annotations

from textwrap import dedent

import yaml

from tuneup import routes


def _cfg(text: str) -> dict:
    from hermes_cli.config import DEFAULT_CONFIG
    from tuneup.hermes_adapter import _deep_merge

    return _deep_merge(DEFAULT_CONFIG, yaml.safe_load(dedent(text)))


def _by_role(route_list):
    out = {}
    for r in route_list:
        out.setdefault(r.role, []).append(r)
    return out


def test_main_fallbacks_and_inheriting_delegation_are_all_listed():
    cfg = _cfg(
        """
        model: {default: claude-opus-5-5, provider: anthropic}
        fallback_providers:
          - {provider: openai-codex, model: gpt-6.1-sol}
          - {provider: openrouter, model: claude-opus-5-5}
        delegation: {model: "", provider: ""}
        """
    )
    found = _by_role(routes.build_routes(cfg))
    assert [r.model for r in found["main"]] == ["claude-opus-5-5"]
    assert [(r.provider, r.model) for r in found["fallback"]] == [
        ("openai-codex", "gpt-6.1-sol"),
        ("openrouter", "claude-opus-5-5"),
    ]
    assert [(r.provider, r.model) for r in found["delegation"]] == [("anthropic", "claude-opus-5-5")]


def test_main_route_trigger_and_explain_line():
    cfg = _cfg("model: {default: claude-opus-5-5, provider: anthropic}\ncompression: {threshold: 0.5}\n")
    main = _by_role(routes.build_routes(cfg))["main"][0]
    assert main.window == 1_000_000
    assert main.trigger == 500_000
    assert main.status == "resolved"
    assert main.explain == "compacts at about 500K tokens (50% of a 1M window)"


def test_delegation_cap_lowers_the_delegation_trigger_only():
    cfg = _cfg(
        """
        model: {default: claude-opus-5-5, provider: anthropic}
        delegation: {model: "", provider: "", compression_threshold_tokens: 32000}
        """
    )
    found = _by_role(routes.build_routes(cfg))
    assert found["delegation"][0].trigger == 32_000
    assert found["delegation"][0].factors["cap"] == 32_000
    assert found["main"][0].trigger == 500_000


def test_explicit_cap_is_named_in_the_explanation():
    cfg = _cfg(
        "model: {default: claude-opus-5-5, provider: anthropic}\ncompression: {threshold: 0.5, threshold_tokens: 256000}\n"
    )
    main = _by_role(routes.build_routes(cfg))["main"][0]
    assert main.trigger == 256_000
    assert "threshold_tokens" in main.explain
    assert main.factors["ratio_trigger"] == 500_000


def test_smaller_summariser_lowers_the_main_trigger():
    cfg = _cfg(
        """
        model: {default: claude-opus-5-5, provider: anthropic}
        compression: {threshold: 0.5}
        auxiliary: {compression: {provider: openai-codex, model: gpt-6.1-sol}}
        """
    )
    found = _by_role(routes.build_routes(cfg))
    main = found["main"][0]
    assert found["summariser"][0].window == 272_000
    assert main.trigger == 272_000
    assert main.factors["summariser_ceiling"] == 272_000
    assert "summariser" in main.explain


def test_auto_summariser_follows_the_main_route():
    cfg = _cfg("model: {default: claude-opus-5-5, provider: anthropic}\nauxiliary: {compression: {provider: auto, model: ''}}\n")
    found = _by_role(routes.build_routes(cfg))
    assert "summariser" not in found
    assert found["main"][0].factors["summariser_ceiling"] is None


def test_compression_disabled_has_no_trigger():
    cfg = _cfg("model: {default: claude-opus-5-5, provider: anthropic}\ncompression: {enabled: false}\n")
    main = _by_role(routes.build_routes(cfg))["main"][0]
    assert main.status == "off"
    assert main.trigger is None
    assert main.explain == "compaction is off for this profile"


def test_assumed_window_is_flagged_on_the_route():
    cfg = _cfg("model: {default: totally-unknown-model-x, provider: custom}\n")
    main = _by_role(routes.build_routes(cfg))["main"][0]
    assert main.window_assumed is True
    assert "assumed" in main.explain
    assert "model.context_length" in main.explain


def test_format_tokens():
    assert routes.format_tokens(500_000) == "500K"
    assert routes.format_tokens(1_000_000) == "1M"
    assert routes.format_tokens(1_050_000) == "1.05M"
    assert routes.format_tokens(272_000) == "272K"
    assert routes.format_tokens(497_400) == "497K"
