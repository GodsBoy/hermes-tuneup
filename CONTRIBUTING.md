# Contributing to hermes-tuneup

Thanks for helping. tuneup is a cost and compaction advisor plugin for Hermes Agent: per profile and per model route it shows when compaction really fires, and flags settings that waste quota or break caching before they go live. This guide covers the rules every change follows and how the code is laid out.

## Follow the Hermes docs

Base every rule tuneup checks on Hermes' own documentation and behaviour, not on guesses. In the [Hermes Agent repository](https://github.com/NousResearch/hermes-agent), under `website/docs/`:

- `user-guide/features/plugins.md` and `user-guide/features/plugin-catalog.md`
- `developer-guide/plugins/index.md`, `public-api.md`, `application-declarations.md` and `catalog-submission.md`
- `developer-guide/desktop-plugin-sdk.md` for the Desktop pane
- `user-guide/configuration.md`, including the compression section, for every rule tuneup checks

## Ground rules

- **Public API first.** Use Hermes' documented plugin API. The one exception is `tuneup/hermes_adapter.py`, which holds every import of a Hermes module the public API does not expose, so upstream drift shows up in one place and in `tests/test_adapter_contract.py`. No other module imports Hermes internals.
- **Hermes reads the config.** Read configuration through Hermes' own resolver, never by parsing YAML in tuneup, so a verdict matches what Hermes really does.
- **No secrets in output.** Nothing tuneup prints, logs or stores may contain secrets, API keys or `.env` values.
- **Read-only by default.** Only a fix the user confirms writes to a profile, through Hermes' config writer and after a backup. During development, never write to a real profile's `config.yaml`.

## Making a change

- Write the failing test first, then the change. Keep test profiles synthetic; never commit a real profile's config.
- Before claiming a check works, try it read-only against a real Hermes install.
- Keep commits small and reviewable, with a clear way to roll back.
- Write British English, with no em or en dashes, in prose, docs and UI text.

## Running the checks

```bash
python -m pytest -q
ruff check .
hermes plugins validate . --install-deps
```

Run pytest with the interpreter and dependencies your Hermes install uses, and with `TMPDIR` outside `~/.hermes`; see [Development](README.md#development) in the README for why. CI runs the tests and the plugin validation against a pinned Hermes checkout.

## Layout

- `plugin.yaml` and `__init__.py`: the manifest and the `register(ctx)` entry point
- `tuneup/`: the core report, routes, fixes, agent guard and the Hermes adapter
- `tuneup/checks/`: one module per check
- `dashboard/` and `desktop/`: the read-only Desktop pane (backend API and front end)
- `tests/`: the pytest suite, with synthetic profiles in a temporary Hermes home
- `docs/`: user-facing documentation and images only
- `demo/`: the demo script and the seeder for the synthetic `tuneup-demo` profile
