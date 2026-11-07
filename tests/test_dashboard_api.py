"""The pane's GET-only backend returns the core report and nothing else."""

from __future__ import annotations

import importlib.util
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import REPO_ROOT
from fleetutil import busy_fleet
from tuneup import report


def _client():
    spec = importlib.util.spec_from_file_location("tuneup_plugin_api_under_test", REPO_ROOT / "dashboard" / "plugin_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/hermes-tuneup")
    return TestClient(app), module


def test_manifest_points_at_the_backend():
    manifest = json.loads((REPO_ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "hermes-tuneup"
    assert manifest["api"] == "plugin_api.py"


def test_report_route_matches_the_core_report(make_profile):
    busy_fleet(make_profile, extra=1)
    client, _ = _client()
    response = client.get("/api/plugins/hermes-tuneup/report")
    assert response.status_code == 200
    body = response.json()
    core = report.build_report()
    codes = lambda rep: sorted(f["code"] for p in rep["profiles"] for f in p["findings"])  # noqa: E731
    assert codes(body) == codes(core)


def test_profile_parameter_is_validated(make_profile):
    busy_fleet(make_profile, extra=1)
    client, _ = _client()
    assert client.get("/api/plugins/hermes-tuneup/report", params={"profile": "spare0"}).status_code == 200
    assert client.get("/api/plugins/hermes-tuneup/report", params={"profile": "../spare0"}).status_code == 400
    assert client.get("/api/plugins/hermes-tuneup/report", params={"profile": "missing"}).status_code == 400


def test_router_has_no_write_routes():
    _, module = _client()
    methods = {m for route in module.router.routes for m in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}
