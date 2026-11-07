"""The plugin loads, registers exactly what it declares, and the harness is isolated."""

from __future__ import annotations

from pathlib import Path

import yaml

from conftest import REPO_ROOT, load_plugin_module


def _manifest() -> dict:
    return yaml.safe_load((REPO_ROOT / "plugin.yaml").read_text(encoding="utf-8"))


def test_manifest_has_required_catalogue_fields():
    manifest = _manifest()
    assert manifest["name"] == "hermes-tuneup"
    assert isinstance(manifest["version"], str)
    assert manifest["requires_hermes"].startswith(">=")
    assert manifest["manifest_version"] == 2
    assert manifest["license"] == "MIT"


def test_register_records_exactly_what_the_manifest_declares(recording_ctx):
    plugin = load_plugin_module()
    plugin.register(recording_ctx)
    manifest = _manifest()
    assert sorted(recording_ctx.tools) == sorted(manifest.get("provides_tools") or [])
    assert sorted(recording_ctx.hooks) == sorted(manifest.get("provides_hooks") or [])


def test_fixture_profiles_are_listed_by_hermes(make_profile):
    from hermes_cli.profiles import list_profile_names

    make_profile("default", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    make_profile("alpha", "model: {default: gpt-6.1-sol, provider: openai-codex}\n")
    make_profile("beta", "model: {default: claude-opus-5-5, provider: anthropic}\n")
    assert set(list_profile_names()) == {"default", "alpha", "beta"}


def test_harness_never_points_at_the_real_hermes_home(hermes_home, tmp_path):
    from hermes_constants import get_hermes_home

    resolved = Path(get_hermes_home()).resolve()
    assert resolved == hermes_home.resolve()
    assert tmp_path.resolve() in resolved.parents
    assert resolved != (Path.home() / ".hermes").resolve()
