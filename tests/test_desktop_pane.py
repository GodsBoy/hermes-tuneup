"""The Desktop pane renders a real report and explains a failed load (runs desktop/plugin.js in Node)."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from conftest import REPO_ROOT
from fleetutil import busy_fleet
from tuneup import models, report

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
HARNESS = REPO_ROOT / "tests" / "pane_harness.mjs"
PLUGIN = REPO_ROOT / "desktop" / "plugin.js"


def _render(tmp_path, *, profile, data=None, error=None):
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps({"profile": profile, "query": {"data": data, "error": error}}),
        encoding="utf-8",
    )
    result = subprocess.run(
        [NODE, str(HARNESS), str(PLUGIN), str(scenario)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"the pane failed to render: {result.stderr.strip()}"
    return json.loads(result.stdout)


def test_pane_renders_a_real_report(make_profile, tmp_path):
    # The report's generated_at is an ISO string; the SDK's relativeTime takes milliseconds.
    busy_fleet(make_profile, extra=1)
    data = report.build_report()
    assert isinstance(data["generated_at"], str)
    out = _render(tmp_path, profile="spare0", data=data)
    assert "Updated" in out["text"]
    for finding in data["profiles"][0]["findings"]:
        assert finding["fix_command"] in out["text"]


def test_pane_survives_an_unreadable_timestamp(make_profile, tmp_path):
    busy_fleet(make_profile, extra=1)
    data = dict(report.build_report(), generated_at="not a time")
    assert "Updated" in _render(tmp_path, profile="default", data=data)["text"]


def test_report_reloads_when_the_profile_changes(make_profile, tmp_path):
    busy_fleet(make_profile, extra=1)
    data = report.build_report()
    first = _render(tmp_path, profile="default", data=data)["queryKeys"][0]
    second = _render(tmp_path, profile="spare0", data=data)["queryKeys"][0]
    assert first != second


def test_a_404_names_the_profile_without_tuneup(tmp_path):
    # Desktop's REST bridge reports "<status>: <body>" in the message; the status code itself
    # does not always survive the hop from the main process.
    out = _render(
        tmp_path,
        profile="work",
        error={"message": '404: {"detail":"Plugin not found"}'},
    )
    assert 'not enabled for the "work" profile' in out["text"]
    assert "hermes -p work plugins enable hermes-tuneup" in out["text"]
    assert "did not answer" not in out["text"]


def test_other_failures_keep_a_generic_message(tmp_path):
    out = _render(tmp_path, profile="work", error={"message": "socket hang up"})
    assert "could not load the report" in out["text"]
    assert "not enabled" not in out["text"]


def test_pane_labels_the_models_you_switch_to(make_profile, tmp_path):
    make_profile("default", "model: {default: gpt-6.1-sol, provider: openai-codex}\n")
    models.declare("anthropic", "claude-opus-5-5")
    data = report.build_report()
    assert not data["profiles"][0]["findings"], "a clean card still lists the models you switch to"
    out = _render(tmp_path, profile="default", data=data)["text"]
    assert "you switch to: claude-opus-5-5 on anthropic, compacts at about" in out
    busy_fleet(make_profile, extra=0)
    models.declare("openai-codex", "gpt-6.1-sol")
    busy = _render(tmp_path, profile="default", data=report.build_report())["text"]
    assert "you switch to: gpt-6.1-sol on openai-codex, compacts at about" in busy
