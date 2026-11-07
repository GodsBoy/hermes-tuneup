"""U5: hermes tuneup check and report."""

import argparse
import json

from fleetutil import CLEAN, busy_fleet
from tuneup import cli


def _run(argv, capsys):
    parser = argparse.ArgumentParser()
    cli.setup(parser)
    args = parser.parse_args(argv)
    code = cli.handle(args)
    return code, capsys.readouterr().out


def test_check_exits_one_on_a_high_finding(make_profile, capsys):
    busy_fleet(make_profile, extra=0)
    code, out = _run(["check"], capsys)
    assert code == 1
    assert "[HIGH]" in out


def test_check_exits_zero_on_a_clean_fleet(make_profile, capsys):
    make_profile("default", CLEAN)
    code, out = _run(["check"], capsys)
    assert code == 0


def test_check_exits_two_when_a_profile_is_unresolved(make_profile, capsys):
    make_profile("default", CLEAN)
    make_profile("broken", "compression: [unclosed\n")
    code, out = _run(["check"], capsys)
    assert code == 2


def test_check_json_matches_the_core_report(make_profile, capsys):
    busy_fleet(make_profile, extra=1)
    code, out = _run(["check", "--json"], capsys)
    data = json.loads(out)
    assert data["schema_version"] == 1
    assert {p["name"] for p in data["profiles"]} == {"default", "spare0"}


def test_check_named_profile(make_profile, capsys):
    busy_fleet(make_profile, extra=1)
    code, out = _run(["check", "--profile", "spare0", "--json"], capsys)
    assert [p["name"] for p in json.loads(out)["profiles"]] == ["spare0"]
