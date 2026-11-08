"""Real `hermes` runs, so Hermes' own command-line handling is part of the test.

Hermes reads `-p`/`--profile` anywhere on the command line as its own profile switch and
removes it before a plugin's parser runs. These tests launch Hermes itself in a throwaway
home with two profiles and the plugin enabled only in `alpha`, then run the commands
tuneup prints exactly as a person would paste them.
"""

from __future__ import annotations

import json
import os
import pty
import select
import shlex
import subprocess
import sys
import time
import venv

import pytest
import yaml

from conftest import REPO_ROOT
from fleetutil import BUSY

ENABLED = BUSY + "plugins:\n  enabled: [hermes-tuneup]\n"


@pytest.fixture(scope="session")
def hermes_python(tmp_path_factory) -> str:
    """An interpreter Hermes accepts for a throwaway home.

    Hermes will not boot a home of its own from its bare managed interpreter, only from a
    virtual environment (as in a Hermes checkout). A venv over this interpreter keeps the
    same packages, which still arrive through PYTHONPATH.
    """
    if sys.prefix != sys.base_prefix:
        return sys.executable
    target = tmp_path_factory.mktemp("hermes-venv")
    venv.create(target, with_pip=False, symlinks=True)
    return str(target / "bin" / "python")


# Only what Hermes needs to start; nothing else from this shell reaches it or a traceback.
PASSED_THROUGH = ("PATH", "PYTHONPATH", "TMPDIR", "LANG", "LC_ALL")


class Hermes:
    """Runs `hermes` command lines exactly as printed, in the throwaway home."""

    def __init__(self, python: str, env: dict):
        self._python, self._env = python, env

    def __repr__(self) -> str:
        return "Hermes(throwaway home)"

    def argv(self, command: str) -> list[str]:
        words = shlex.split(command)
        assert words[0] == "hermes", command
        return [self._python, "-m", "hermes_cli.main", *words[1:]]

    def run(self, command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            self.argv(command), env=self._env, cwd=self._env["HOME"], capture_output=True, text=True, timeout=180
        )

    def at_terminal(self, command: str, answer: str, prompt: bytes, timeout: float = 180) -> str:
        """Run under a pseudo-terminal, type `answer` once `prompt` shows, and return the screen."""
        master, child = pty.openpty()
        proc = subprocess.Popen(
            self.argv(command), stdin=child, stdout=child, stderr=child, env=self._env, cwd=self._env["HOME"]
        )
        os.close(child)
        shown, answered, deadline = b"", False, time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 1)
                if not ready:
                    if proc.poll() is not None:
                        break
                    continue
                try:
                    chunk = os.read(master, 4096)
                except OSError:  # the child closed its end of the terminal
                    break
                if not chunk:
                    break
                shown += chunk
                if not answered and prompt in shown:
                    os.write(master, answer.encode() + b"\n")
                    answered = True
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
        return shown.decode("utf-8", errors="replace")


@pytest.fixture
def hermes(hermes_python, make_profile, hermes_home, tmp_path) -> Hermes:
    """`default` without the plugin and `alpha` with it enabled."""
    make_profile("default", BUSY)
    alpha = make_profile("alpha", ENABLED)
    (alpha / "plugins").mkdir()
    (alpha / "plugins" / "hermes-tuneup").symlink_to(REPO_ROOT, target_is_directory=True)
    env = {name: os.environ[name] for name in PASSED_THROUGH if name in os.environ}
    env.update(HOME=str(tmp_path), HERMES_HOME=str(hermes_home))
    # A Hermes host would otherwise build a dependency environment for the new home.
    env["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
    return Hermes(hermes_python, env)


def _report(hermes: Hermes) -> dict:
    result = hermes.run("hermes -p alpha tuneup check --json")
    assert result.returncode in (0, 1), result.stdout + result.stderr
    return json.loads(result.stdout)


def _config(path) -> dict:
    return yaml.safe_load((path / "config.yaml").read_text(encoding="utf-8")) or {}


def test_only_limits_check_to_the_named_profile(hermes):
    result = hermes.run("hermes -p alpha tuneup check --only default --json")
    assert result.returncode in (0, 1), result.stdout + result.stderr
    assert [p["name"] for p in json.loads(result.stdout)["profiles"]] == ["default"]


def test_only_limits_report_to_the_named_profile(hermes):
    result = hermes.run("hermes -p alpha tuneup report --only default --json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(json.loads(result.stdout)) == ["default"]


def test_help_says_a_bare_tuneup_runs_a_check(hermes):
    result = hermes.run("hermes -p alpha tuneup --help")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A bare hermes tuneup runs a check" in " ".join(result.stdout.split()), result.stdout


def test_bare_tuneup_runs_a_check_with_terminal_fix_commands(hermes):
    result = hermes.run("hermes -p alpha tuneup")
    assert result.returncode in (0, 1), result.stdout + result.stderr
    assert "tuneup: profile alpha" in result.stdout and "/tuneup fix" not in result.stdout
    assert "fix: hermes -p alpha tuneup fix " in result.stdout


def test_every_printed_terminal_command_reaches_tuneup(hermes):
    rep = _report(hermes)
    printed = sorted({f["fix_command"] for p in rep["profiles"] for f in p["findings"]})
    terminal = [c for c in printed if c.startswith("hermes ")]
    assert terminal, printed
    for command in terminal:
        result = hermes.run(command)
        # With no terminal attached tuneup refuses, which shows its own code got the command.
        assert "needs a person at a real terminal" in result.stdout, command + "\n" + result.stdout + result.stderr


def test_printed_fix_for_another_profile_applies_there_after_yes(hermes, hermes_home):
    alpha = hermes_home / "profiles" / "alpha"
    alpha_before = (alpha / "config.yaml").read_bytes()
    default = next(p for p in _report(hermes)["profiles"] if p["name"] == "default")
    command = next(f["fix_command"] for f in default["findings"] if f["check"] == "prune_cache")
    screen = hermes.at_terminal(command, "yes", b"Type yes to apply:")
    assert "Applied to profile default" in screen, screen
    assert _config(hermes_home)["compression"].get("proactive_prune_tokens", 0) == 0
    assert (alpha / "config.yaml").read_bytes() == alpha_before
