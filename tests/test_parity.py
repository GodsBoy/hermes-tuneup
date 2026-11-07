"""Every surface shows the same codes, severities and trigger numbers."""

import argparse
import json
import re

from fleetutil import busy_fleet
from tuneup import cli, commands, report, tool


def test_tool_cli_slash_and_core_agree(make_profile, capsys):
    busy_fleet(make_profile, extra=0)
    core = report.build_report(active="default")
    core_findings = {(f["code"], f["severity"]) for f in core["profiles"][0]["findings"]}
    core_trigger = core["profiles"][0]["routes"][0]["trigger"]

    tool_out = json.loads(tool.handle({}))
    assert {(f["code"], f["severity"]) for f in tool_out["profiles"][0]["findings"]} == core_findings
    assert tool_out["profiles"][0]["routes"][0]["trigger"] == core_trigger

    parser = argparse.ArgumentParser()
    cli.setup(parser)
    cli.handle(parser.parse_args(["check", "--json"]))
    cli_out = json.loads(capsys.readouterr().out)
    assert {(f["code"], f["severity"]) for f in cli_out["profiles"][0]["findings"]} == core_findings

    slash = commands.handle("", platform="cli")
    assert set(re.findall(r"/tuneup fix ([0-9a-f]{6})", slash)) == {c for c, _ in core_findings}
