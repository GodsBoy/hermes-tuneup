"""The hermes tuneup check and report commands."""

import argparse
import json
import re

import pytest

from conftest import REPO_ROOT
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
    from tuneup import report

    busy_fleet(make_profile, extra=1)
    code, out = _run(["check", "--json"], capsys)
    data = json.loads(out)
    core = report.build_report()
    codes = lambda rep: sorted((p["name"], f["code"]) for p in rep["profiles"] for f in p["findings"])  # noqa: E731
    assert data["schema_version"] == core["schema_version"]
    assert codes(data) == codes(core) and codes(data)


def test_check_only_one_profile(make_profile, capsys):
    busy_fleet(make_profile, extra=1)
    code, out = _run(["check", "--only", "spare0", "--json"], capsys)
    assert [p["name"] for p in json.loads(out)["profiles"]] == ["spare0"]


def test_bare_tuneup_runs_check_on_every_profile(make_profile, capsys):
    busy_fleet(make_profile, extra=1)
    code, out = _run([], capsys)
    assert code == 1
    assert "tuneup: profile default" in out and "tuneup: profile spare0" in out


def test_check_prints_the_terminal_fix_command_for_every_profile(make_profile, capsys):
    # A slash command does nothing at a shell prompt, so the terminal never prints /tuneup fix.
    busy_fleet(make_profile, extra=1)
    code, out = _run(["check"], capsys)
    printed = re.findall(r"fix: (.+)", out)
    assert len(printed) == len(re.findall(r"\[(?:HIGH|MEDIUM|LOW)\]", out)) > 0
    assert all(re.fullmatch(r"hermes -p default tuneup fix [0-9a-f]{6}", command) for command in printed), printed
    assert "/tuneup fix" not in out


def test_check_json_carries_the_terminal_fix_command(make_profile, capsys):
    busy_fleet(make_profile, extra=1)
    code, out = _run(["check", "--json"], capsys)
    printed = [f["fix_command"] for p in json.loads(out)["profiles"] for f in p["findings"]]
    assert printed and all(command.startswith("hermes -p default tuneup fix ") for command in printed)


def test_help_says_a_bare_tuneup_runs_a_check():
    parser = argparse.ArgumentParser(prog="hermes tuneup")
    cli.setup(parser)
    assert "A bare hermes tuneup runs a check" in " ".join(parser.format_help().split())


@pytest.mark.parametrize("sub", ["check", "report"])
def test_unknown_only_name_lists_the_profiles(make_profile, capsys, sub):
    busy_fleet(make_profile, extra=1)
    code, out = _run([sub, "--only", "nope"], capsys)
    assert code == 2
    assert out.strip() == "tuneup: no profile named 'nope'. Profiles: default, spare0"


def test_demo_close_line_installs_and_enables():
    close = next(line for line in (REPO_ROOT / "demo/script.md").read_text(encoding="utf-8").splitlines() if "| Close |" in line)
    assert "`hermes plugins install GodsBoy/hermes-tuneup --enable`" in close


def test_report_only_one_profile(make_profile, capsys):
    busy_fleet(make_profile, extra=1)
    code, out = _run(["report", "--only", "spare0", "--json"], capsys)
    assert list(json.loads(out)) == ["spare0"]


@pytest.mark.parametrize(
    "argv",
    [
        ["check", "--profile", "spare0"],
        ["check", "-p", "spare0"],
        ["report", "--profile", "spare0"],
        ["report", "-p", "spare0"],
        ["fix", "abc123", "--profile", "spare0"],
        ["fix", "abc123", "-p", "spare0"],
        ["fix", "abc123", "--only", "spare0"],
        ["models", "add", "anthropic:claude-opus-5-5", "-p", "spare0"],
        ["models", "--profile", "spare0"],
    ],
)
def test_no_option_uses_a_name_hermes_takes_for_itself(argv):
    # Hermes strips -p/--profile from anywhere on the command line before tuneup sees it.
    parser = argparse.ArgumentParser()
    cli.setup(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(argv)


# A tuneup command line followed, anywhere later on that line, by Hermes' own profile switch.
_PROFILE_AFTER_TUNEUP = re.compile(r"\btuneup (?:check|report|fix|models)\b[^\n`]*?[\s\[](?:--profile|-p)\b")


def test_no_doc_or_message_puts_a_profile_switch_after_tuneup():
    files = [
        REPO_ROOT / name for name in ("README.md", "CONTRIBUTING.md", "plugin.yaml", "__init__.py", "demo/script.md")
    ]
    files += sorted((REPO_ROOT / "docs").glob("*.md")) + sorted((REPO_ROOT / "tuneup").rglob("*.py"))
    files += [REPO_ROOT / "demo/seed_home.py", REPO_ROOT / "desktop/plugin.js", REPO_ROOT / "dashboard/plugin_api.py"]
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {match.group(0)}"
        for path in files
        for match in _PROFILE_AFTER_TUNEUP.finditer(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_cli_models_declares_lists_forgets_and_sets_days(make_profile, capsys):
    make_profile("default", "model: {default: gpt-6.1-sol, provider: openai-codex}\n")
    code, out = _run(["models", "add", "anthropic:claude-opus-5-5"], capsys)
    assert code == 0 and out.startswith("Declared anthropic:claude-opus-5-5 for profile default.")
    code, out = _run(["models"], capsys)
    assert code == 0 and "You switch to: anthropic:claude-opus-5-5" in out
    assert "hermes -p default tuneup models add <provider>:<model>" in out and "/tuneup models" not in out
    code, out = _run(["models", "days", "14"], capsys)
    assert code == 0 and "last 14 days" in out
    code, out = _run(["models", "remove", "anthropic:claude-opus-5-5"], capsys)
    assert code == 0 and out.startswith("Forgot")


def test_cli_models_exits_two_on_a_bad_spec_or_unknown_model(make_profile, capsys):
    make_profile("default", "model: {default: gpt-6.1-sol, provider: openai-codex}\n")
    assert _run(["models", "add", "claude-opus-5-5"], capsys)[0] == 2
    assert _run(["models", "remove", "anthropic:never-declared"], capsys)[0] == 2
    assert _run(["models", "days", "-1"], capsys)[0] == 2


def test_terminal_report_labels_switched_and_seen_routes(make_profile, capsys):
    from tuneup import models, receipts

    class _State(dict):
        def set(self, key, value):
            self[key] = value

    class _Ctx:
        state = _State()

    make_profile("default", "model: {default: gpt-6.1-sol, provider: openai-codex}\n")
    models.declare("anthropic", "claude-opus-5-5")
    recorder = receipts.Recorder(_Ctx())
    recorder.set_enabled(True)
    recorder.on_api_request(session_id="s1", model="claude-haiku-4-5", provider="anthropic", usage={"prompt_tokens": 1})
    code, out = _run(["check"], capsys)
    assert "  you switch to: claude-opus-5-5 on anthropic compacts at about" in out
    assert "  seen recently: claude-haiku-4-5 on anthropic compacts at about" in out
    data = json.loads(_run(["check", "--json"], capsys)[1])
    labels = [(r["role"], r["label"]) for r in data["profiles"][0]["routes"]]
    assert ("declared", "you switch to") in labels and ("seen", "seen recently") in labels
