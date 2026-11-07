"""The agent's own tools are blocked from running a fix."""

from __future__ import annotations

import argparse

import pytest

from fleetutil import BUSY
from tuneup import cli, guard


def _blocked(result) -> bool:
    return isinstance(result, dict) and result.get("action") == "block" and bool(result.get("message"))


def test_covers_ae10_terminal_fix_is_blocked_with_guidance():
    result = guard.pre_tool_call(tool_name="terminal", args={"command": "hermes tuneup fix ab12cd"})
    assert _blocked(result)
    assert "type" in result["message"]


@pytest.mark.parametrize(
    "command",
    [
        "hermes tuneup  fix ab12cd",
        "hermes 'tuneup' \"fix\" ab12cd",
        "hermes -p alpha tuneup fix ab12cd",
        "HERMES_HOME=/x hermes tuneup fix ab12cd && echo done",
        "python -m tuneup fix ab12cd",
        "echo yes | hermes tuneup fix ab12cd",
    ],
)
def test_terminal_bypass_variants_are_blocked(command):
    assert _blocked(guard.pre_tool_call(tool_name="terminal", args={"command": command}))


def test_code_execution_importing_the_fix_module_is_blocked():
    code = "from tuneup import fixes\nfixes.apply(fixes.prepare('ab12cd', 'default', 'default'))"
    assert _blocked(guard.pre_tool_call(tool_name="execute_code", args={"code": code}))
    assert _blocked(guard.pre_tool_call(tool_name="execute_code", args={"code": "import tuneup.fixes as f"}))


def test_writing_a_script_that_runs_the_fix_is_blocked():
    args = {"path": "/tmp/run.sh", "content": "#!/bin/sh\nhermes tuneup fix ab12cd\n"}
    assert _blocked(guard.pre_tool_call(tool_name="write_file", args=args))


def test_writing_documentation_that_mentions_the_command_is_allowed():
    args = {"path": "README.md", "content": "Run `hermes tuneup fix <code>` or type /tuneup fix <code>."}
    assert guard.pre_tool_call(tool_name="write_file", args=args) is None


def test_checking_is_never_blocked():
    assert guard.pre_tool_call(tool_name="terminal", args={"command": "hermes tuneup check --json"}) is None


def test_unrelated_and_malformed_calls_pass_through():
    assert guard.pre_tool_call(tool_name="web_search", args={"query": "hermes plugins"}) is None
    assert guard.pre_tool_call(tool_name="terminal", args=None) is None
    assert guard.pre_tool_call(tool_name="terminal", args=["not", "a", "dict"]) is None
    assert guard.pre_tool_call(tool_name="terminal", args={"command": {"nested": ["hermes tuneup fix x"]}}) is not None


def test_cli_fix_launched_by_an_agent_tool_refuses_before_prompting(make_profile, monkeypatch, capsys):
    home = make_profile("default", BUSY)
    before = (home / "config.yaml").read_bytes()
    monkeypatch.setenv("HERMES_SESSION_ID", "sess-123")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    prompted = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompted.append(prompt) or "yes")
    parser = argparse.ArgumentParser()
    cli.setup(parser)
    assert cli.handle(parser.parse_args(["fix", "abc123"])) == cli.EXIT_UNRESOLVED
    assert prompted == []
    assert "agent" in capsys.readouterr().out
    assert (home / "config.yaml").read_bytes() == before


def test_register_wires_the_guard(recording_ctx):
    from conftest import load_plugin_module

    load_plugin_module().register(recording_ctx)
    assert "pre_tool_call" in recording_ctx.hooks
