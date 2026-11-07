# Proposal: a public compaction-preview seam for Hermes plugins

## Summary

Add one documented, read-only function to Hermes' plugin API that answers: "for this profile and this model route, what compaction trigger would Hermes install, and why?" Plugins such as hermes-tuneup could then stop importing the resolver internals they need today, and `hermes plugins validate` would no longer warn about them.

## The problem

Catalogue rule 9 asks plugins to use public surfaces only, and invites a seam request when one is missing. A plugin that wants to explain or check compaction behaviour today has two options:

- **Re-implement the maths.** The trigger depends on the window lookup, substring and provider-scoped `model_thresholds` ranking, the small-window floor, the output reservation, the `threshold_tokens` cap, the Codex automatic raise and the summariser ceiling. A copy drifts from Hermes on the next release and gives users wrong numbers.
- **Import the internals.** `agent.agent_init._parse_compression_config`, `agent.context_compressor.ContextCompressor` and its preview, `agent.model_metadata.get_model_context_length`, `hermes_cli.profiles` and `hermes_cli.config_effective`. That is exact, but every import is a rule 9 warning and can break on any release.

Hermes already has the right internal shape: `ContextCompressor.preview_threshold_tokens`, which `hermes_cli/context_switch_guard.py` uses to quote the real trigger before a model switch.

## Proposed API

A module on the public allowlist, for example `hermes_cli.compaction_preview`:

```python
def preview_route(config: dict, *, model: str, provider: str, role: str = "main") -> RoutePreview: ...
def list_profiles() -> list[ProfileRef]: ...            # name and home path, default first
def load_profile_config(home: Path) -> dict: ...         # effective config, no side effects
```

`RoutePreview` would carry the window and where it came from (config pin, custom provider, catalogue, fallback), the trigger in tokens, and the factors: the matched rule, the base and effective percentage, whether the small-window floor applied, the output reservation, the cap, and the summariser ceiling.

Three properties matter:

- **Side-effect free.** No backups, no cache writes into the profile, no network. Today a read through `load_config` writes a `good` backup into the home it reads, so a plugin has to copy files into a temporary home first.
- **Offline.** Window resolution without a base URL or key, with the source reported so callers can mark a fallback as assumed.
- **Versioned.** Covered by the same compatibility promise as the rest of the plugin API, so a plugin's `requires_hermes` floor means something.

## What it would change for users

Plugins could tell users exactly when compaction fires, per route, without a maintenance burden that Nous would otherwise inherit through broken plugins after a release. Hermes' own `/model` switch warning and `hermes config show` could use the same function to print the real trigger instead of the raw percentage.

## Status

Drafted by the hermes-tuneup maintainer. Not yet opened upstream.
