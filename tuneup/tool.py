"""The tuneup_check agent tool: read-only, one call, structured JSON."""

from __future__ import annotations

import json

from . import profiles, report
from .redact import clean

MAX_BYTES = 6000

SCHEMA = {
    "name": "tuneup_check",
    "description": (
        "Read-only Hermes config advisor. Call it when the user asks why quota or tokens are burning, "
        "when this session or a profile will compact, why context fills up, or about cache misses or "
        "subagent cost. Returns each route's real compaction trigger in tokens with the reason, plus "
        "findings with a fix_command. Never offer to apply a fix yourself and never run it: tell the "
        "user to type the exact fix_command."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["active", "all", "profile"],
                "description": "active (default): this profile in full; all: a short digest of every profile; profile: one named profile in full.",
            },
            "profile": {"type": "string", "description": "Profile name, with scope=profile."},
            "include": {
                "type": "array",
                "items": {"type": "string", "enum": ["routes", "findings", "receipts"]},
                "description": "Sections to return (default routes and findings).",
            },
        },
        "required": [],
    },
}


def _full(entry: dict, include: set[str]) -> dict:
    out = {k: entry[k] for k in ("name", "active", "status", "note")}
    if "routes" in include:
        out["routes"] = entry.get("routes", [])
    if "findings" in include:
        out["findings"] = entry.get("findings", [])
    if "receipts" in include and "receipts" in entry:
        out["receipts"] = entry["receipts"]
    return out


def _digest(entry: dict) -> dict:
    findings = entry.get("findings", [])
    main = next((r for r in entry.get("routes", []) if r["role"] == "main"), {})
    top = findings[0] if findings else None
    return {
        "name": entry["name"],
        "active": entry["active"],
        "status": entry["status"],
        "note": entry["note"],
        "main_route": main.get("explain") or main.get("note", ""),
        "finding_counts": {s: sum(1 for f in findings if f["severity"] == s) for s in ("high", "medium", "low")},
        "top_finding": (
            {"severity": top["severity"], "summary": clean(top["summary"], 160), "fix_command": top["fix_command"]}
            if top
            else None
        ),
    }


def _shape(rep: dict, scope: str, include: set[str]) -> dict:
    entries = [_digest(p) if scope == "all" else _full(p, include) for p in rep["profiles"]]
    out = {
        "read_only": True,
        "cannot_apply": rep["cannot_apply"],
        "hermes_version": rep["hermes_version"],
        "generated_at": rep["generated_at"],
        "active_profile": rep["active_profile"],
        "profiles": entries,
        "truncated": False,
    }
    while len(json.dumps(out).encode("utf-8")) > MAX_BYTES and len(out["profiles"]) > 1:
        idx = max(i for i, e in enumerate(out["profiles"]) if not e["active"]) if any(
            not e["active"] for e in out["profiles"]
        ) else len(out["profiles"]) - 1
        out["profiles"].pop(idx)
        out["truncated"] = True
    if out["truncated"]:
        out["next"] = "Call again with scope=profile and a profile name for the rest."
    return out


def handle(args: dict | None = None, **_kwargs) -> str:
    """Always a JSON string, including on failure."""
    args = args or {}
    scope = str(args.get("scope") or "active")
    include = set(args.get("include") or ["routes", "findings"])
    try:
        active = profiles.active_profile()
        if scope == "profile":
            name = str(args.get("profile") or "")
            if profiles.find_profile(name) is None:
                return json.dumps({"error": f"no profile named {name!r}", "read_only": True})
            rep = report.build_report(active=active, only=name)
        elif scope == "all":
            rep = report.build_report(active=active)
        else:
            rep = report.build_report(active=active, only=active)
        return json.dumps(_shape(rep, scope, include))
    except Exception as exc:  # the agent loop must always get JSON back
        return json.dumps({"error": f"tuneup could not build the report: {type(exc).__name__}", "read_only": True})
