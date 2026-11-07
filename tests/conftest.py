"""Shared fixtures: every test runs against a synthetic Hermes home under tmp_path.

The real ~/.hermes is never read or written by the suite. Profile fixtures are
plain config.yaml files; a config.yaml alone makes a named profile listable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from textwrap import dedent

import pytest

# Importing Hermes swaps the interpreter's site-packages for Hermes' own managed
# environment, which need not ship PyYAML. Load the fixtures' YAML reader first.
import yaml  # noqa: F401

# Hermes treats any HERMES_HOME under ~/.hermes as a profile of the real install,
# so a TMPDIR inside it (common on Hermes hosts) would expose the real profiles.
_NATIVE_HOME = (Path.home() / ".hermes").resolve()

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Hermes runs plugins with its source root on sys.path; an editable install may
# lag behind top-level modules added later, so mirror the runtime layout here.
import hermes_constants  # noqa: E402

_HERMES_ROOT = str(Path(hermes_constants.__file__).resolve().parent)
if _HERMES_ROOT not in sys.path:
    sys.path.append(_HERMES_ROOT)

# Import Hermes once, under the environment the run started with. A first import
# after a test has pointed HERMES_HOME at a temp dir makes Hermes treat that dir
# as a new data root and re-provision its dependencies.
import agent.agent_init  # noqa: E402,F401
import agent.context_compressor  # noqa: E402,F401
import agent.model_metadata  # noqa: E402,F401
import hermes_cli.config  # noqa: E402,F401
import hermes_cli.config_effective  # noqa: E402,F401
import hermes_cli.profiles  # noqa: E402,F401
import tools.delegate_tool  # noqa: E402,F401


@pytest.fixture(autouse=True)
def hermes_home(tmp_path, monkeypatch):
    """Point HERMES_HOME at a fresh temp directory for every test."""
    home = tmp_path / ".hermes"
    home.mkdir()
    assert not home.resolve().is_relative_to(_NATIVE_HOME), (
        "pytest's temp dir is inside ~/.hermes; rerun with TMPDIR=/tmp so tests cannot see real profiles"
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    yield home


@pytest.fixture
def make_profile(hermes_home):
    """Write a config.yaml for the default home (name "default") or a named profile."""

    def _make(name: str, config: str) -> Path:
        target = hermes_home if name == "default" else hermes_home / "profiles" / name
        target.mkdir(parents=True, exist_ok=True)
        path = target / "config.yaml"
        path.write_text(dedent(config).lstrip(), encoding="utf-8")
        return target

    return _make


@pytest.fixture
def fixture_config():
    """Read a named synthetic config from tests/fixtures."""

    def _read(name: str) -> str:
        return (FIXTURES / f"{name}.yaml").read_text(encoding="utf-8")

    return _read


def load_plugin_module():
    """Load the plugin's top-level __init__.py as a package, the way Hermes does."""
    name = "hermes_tuneup_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "__init__.py", submodule_search_locations=[str(REPO_ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RecordingContext:
    """Minimal stand-in for Hermes' PluginContext that records registrations."""

    def __init__(self):
        self.tools: dict[str, dict] = {}
        self.hooks: dict[str, list] = {}
        self.commands: dict[str, dict] = {}
        self.cli_commands: dict[str, dict] = {}
        self.state: dict = {}
        self.profile_name = "default"

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, **kwargs}

    def register_hook(self, hook_name, callback, *, hold_stream=False):
        self.hooks.setdefault(hook_name, []).append(callback)

    def register_command(self, name, handler, description="", args_hint="", **kwargs):
        self.commands[name] = {"handler": handler, "description": description, "args_hint": args_hint}

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli_commands[name] = {"help": help, "setup_fn": setup_fn, "handler_fn": handler_fn}

    def get_config(self, key, default=None):
        return default

    def current_cron_execution(self):
        return None

    def ask_choice(self, question, choices):
        return None


@pytest.fixture
def recording_ctx():
    return RecordingContext()
