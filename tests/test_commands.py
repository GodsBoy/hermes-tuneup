"""The /tuneup slash command report."""

from fleetutil import busy_fleet
from tuneup import commands


def test_report_on_the_cli(make_profile):
    busy_fleet(make_profile, extra=1)
    out = commands.handle("", platform="cli")
    assert out.startswith("tuneup: profile default")
    assert "Fleet: 2 profiles" in out


def test_report_is_capped_on_telegram(make_profile):
    busy_fleet(make_profile, extra=1)
    assert len(commands.handle("", platform="telegram")) <= commands.MESSAGING_CAP


def test_unknown_subcommand_shows_usage(make_profile):
    busy_fleet(make_profile, extra=0)
    assert "Usage" in commands.handle("frobnicate", platform="cli")
