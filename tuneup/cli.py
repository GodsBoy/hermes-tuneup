"""`hermes tuneup check|report`: the fleet view for the terminal and CI."""

from __future__ import annotations

import json

from . import profiles, render_text, report

EXIT_CLEAN, EXIT_HIGH, EXIT_UNRESOLVED = 0, 1, 2


def setup(parser) -> None:
    subs = parser.add_subparsers(dest="tuneup_command")
    check = subs.add_parser("check", help="Show when compaction fires on every profile and what to fix")
    check.add_argument("--profile", help="Only this profile")
    check.add_argument("--json", action="store_true", help="Machine-readable report")
    parser.set_defaults(func=handle)


def exit_code(rep: dict) -> int:
    unresolved = any(p["status"] != "ok" for p in rep["profiles"]) or any(
        r["status"] == "unresolved" for p in rep["profiles"] for r in p.get("routes", [])
    )
    if unresolved or not rep["profiles"]:
        return EXIT_UNRESOLVED
    if any(f["severity"] == "high" for p in rep["profiles"] for f in p.get("findings", [])):
        return EXIT_HIGH
    return EXIT_CLEAN


def _check(args) -> int:
    name = getattr(args, "profile", None)
    if name and profiles.find_profile(name) is None:
        print(f"tuneup: no profile named {name!r}")
        return EXIT_UNRESOLVED
    rep = report.build_report(only=name)
    print(json.dumps(rep, indent=2) if getattr(args, "json", False) else render_text.render_fleet(rep))
    return exit_code(rep)


def handle(args) -> int:
    sub = getattr(args, "tuneup_command", None) or "check"
    if sub == "check":
        return _check(args)
    print("Usage: hermes tuneup check [--profile NAME] [--json]")
    return EXIT_UNRESOLVED
