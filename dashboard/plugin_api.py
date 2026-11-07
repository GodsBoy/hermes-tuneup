"""Read-only backend for the tuneup Desktop pane: GET /report, nothing that writes.

The core package is loaded from the plugin folder under a private module name,
so this file works however the gateway imports it.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

_PACKAGE = "hermes_tuneup_backend"
_ROOT = Path(__file__).resolve().parents[1]


def _core(module: str):
    if _PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            _PACKAGE, _ROOT / "__init__.py", submodule_search_locations=[str(_ROOT)]
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[_PACKAGE] = package
        spec.loader.exec_module(package)
    return importlib.import_module(f"{_PACKAGE}.tuneup.{module}")


router = APIRouter()


@router.get("/report")
def report(profile: str | None = None) -> dict:
    """The core report (already redacted), for every profile or one discovered profile."""
    profiles = _core("profiles")
    if profile is not None and profiles.find_profile(profile) is None:
        raise HTTPException(status_code=400, detail="unknown profile")
    return _core("report").build_report(only=profile)
